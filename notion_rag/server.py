"""FastAPI server for Notion RAG service.

Provides REST API endpoints for querying indexed Notion databases,
managing stores, and triggering sync operations.
"""

import sys
import time
from typing import Optional

from fastapi import FastAPI, HTTPException
from google.genai import types
from pydantic import BaseModel
from starlette.requests import Request

from notion_rag.billing import get_billing
from notion_rag.config import DATABASES, DEFAULT_QUERY_MODEL, calc_cost, resolve_db
from notion_rag.indexer import get_gemini_client, init_db, sync_db
from notion_rag.logger import log_api, log_query
from notion_rag.store import db_store_name, get_or_create_store, list_documents

app = FastAPI(title="Notion RAG Service", version="0.1.0")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all API requests with timing."""
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    log_api(
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        elapsed=elapsed,
        client_ip=request.client.host if request.client else None,
    )
    return response


class QueryRequest(BaseModel):
    """Request body for RAG query endpoint."""

    name: str | None = None
    query: str
    model: str = DEFAULT_QUERY_MODEL


class QueryResponse(BaseModel):
    """Response body for RAG query endpoint."""

    answer: str
    grounding: Optional[dict] = None
    usage: dict


class SyncRequest(BaseModel):
    """Request body for sync endpoint."""

    name: str | None = None
    force: bool = False


class InitRequest(BaseModel):
    """Request body for init endpoint."""

    name: str | None = None
    db_url: str | None = None


class HealthResponse(BaseModel):
    """Response body for health check endpoint."""

    status: str


class StoreInfo(BaseModel):
    """Store information model."""

    name: str
    display_name: str
    documents: int
    size_bytes: int


class StoresResponse(BaseModel):
    """Response body for stores list endpoint."""

    stores: list[StoreInfo]


class BillingTotal(BaseModel):
    """Billing cost totals."""

    embedding_cost: float
    vision_cost: float
    query_cost: float
    total_cost: float


class BillingEntry(BaseModel):
    """Billing breakdown entry for a specific period."""

    period: str
    embedding_cost: float
    vision_cost: float
    query_cost: float
    total_cost: float


class BillingResponse(BaseModel):
    """Response body for billing endpoint."""

    total: BillingTotal
    breakdown: list[BillingEntry]


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint.

    Returns: dict with status "ok".

    HTTP Method: GET
    """
    return {"status": "ok"}


@app.get("/stores", response_model=StoresResponse)
async def list_stores():
    """List all Notion database stores.

    Returns: dict containing list of stores with metadata.

    HTTP Method: GET
    """
    client = get_gemini_client()
    stores = []

    for store in client.file_search_stores.list():
        if store.display_name and store.display_name in DATABASES:
            docs = list_documents(client, store.name)
            stores.append(
                {
                    "name": store.name,
                    "display_name": store.display_name,
                    "documents": len(docs),
                    "size_bytes": store.size_bytes or 0,
                }
            )

    return {"stores": stores}


@app.get("/billing", response_model=BillingResponse)
async def billing(period: str = "total"):
    """Get Gemini API billing summary from logs.

    Arguments:
    period -- Aggregation period: "total", "daily", or "monthly" (query param). String.

    Returns: dict with total costs and optional period breakdown.

    HTTP Method: GET
    """
    if period not in ("total", "daily", "monthly"):
        raise HTTPException(status_code=400, detail="period must be 'total', 'daily', or 'monthly'")
    result = get_billing(period)
    return result


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """Execute RAG query against a Notion database store.

    Arguments:
    request -- Query request containing name, query text, and model name. QueryRequest.

    Returns: dict with answer, grounding metadata, and usage statistics.

    HTTP Method: POST
    """
    client = get_gemini_client()
    start = time.time()

    # Resolve store name from label
    label, db_url = resolve_db(request.name)
    store_name = db_store_name(label)

    # Get or create store
    store, created = get_or_create_store(client, store_name)

    # Check if store has documents
    docs = list_documents(client, store.name)
    if not docs:
        if created:
            # Clean up empty store
            client.file_search_stores.delete(name=store.name, config={"force": True})
        raise HTTPException(
            status_code=404,
            detail=f"Store '{store_name}' is empty. Run init first to index documents.",
        )

    # Execute query with file_search tool
    response = client.models.generate_content(
        model=request.model,
        contents=request.query,
        config=types.GenerateContentConfig(
            tools=[
                types.Tool(
                    file_search=types.FileSearch(file_search_store_names=[store.name])
                )
            ]
        ),
    )

    # Extract grounding metadata
    grounding = None
    if response.candidates and response.candidates[0].grounding_metadata:
        metadata = response.candidates[0].grounding_metadata
        # Convert to dict for JSON serialization
        grounding = {"metadata": str(metadata)}

    # Calculate usage and cost
    usage = {
        "model": request.model,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost": 0.0,
    }

    if hasattr(response, "usage_metadata") and response.usage_metadata:
        u = response.usage_metadata
        input_tokens = u.prompt_token_count or 0
        output_tokens = u.candidates_token_count or 0
        usage = {
            "model": request.model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": calc_cost(request.model, input_tokens, output_tokens),
        }

    elapsed = time.time() - start
    log_query(
        label=label,
        query=request.query,
        model=request.model,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cost=usage["cost"],
        elapsed=elapsed,
        source="api",
    )

    return {"answer": response.text or "", "grounding": grounding, "usage": usage}


@app.post("/sync")
async def sync(request: SyncRequest):
    """Trigger sync for a Notion database.

    Arguments:
    request -- Sync request containing name and force flag. SyncRequest.

    Returns: dict with sync statistics (pages checked, updated, skipped, costs).

    HTTP Method: POST
    """
    result = sync_db(request.name, force=request.force)
    return result


@app.post("/init")
async def init(request: InitRequest):
    """Initialize and index a new Notion database.

    Arguments:
    request -- Init request containing name and optional db_url. InitRequest.

    Returns: dict with init statistics (pages indexed, costs).

    HTTP Method: POST
    """
    result = init_db(request.name, db_url=request.db_url)
    return result
