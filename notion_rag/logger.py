"""Structured JSONL logging to date-organized directories.

Provides logging functions for indexing, query, sync, init, and API operations.
Logs are written to {project_root}/logs/YYYY-MM-DD/{category}/ with UTC timestamps.

Directory structure:
    logs/YYYY-MM-DD/
    ├── audit/
    │   └── api.jsonl          # HTTP request logs
    └── gemini/
        ├── indexing.jsonl      # Per-page indexing (embedding + vision costs)
        ├── query.jsonl         # RAG query costs
        ├── sync.jsonl          # Sync operation summaries
        └── init.jsonl          # Init operation summaries
"""

import json
from datetime import datetime, timezone
from pathlib import Path

# Base log directory relative to project root
LOG_BASE = Path(__file__).resolve().parent.parent / "logs"


def _get_log_dir(category: str) -> Path:
    """Get today's log directory for a category, creating it if needed.

    Arguments:
    category -- Log category ("audit" or "gemini"). String.

    Returns: Path object for today's categorized log directory (logs/YYYY-MM-DD/{category}/).
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_dir = LOG_BASE / date_str / category
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _append(category: str, filename: str, data: dict) -> None:
    """Append timestamped JSON line to categorized log file.

    Arguments:
    category -- Log category ("audit" or "gemini"). String.
    filename -- Log file name (e.g., "indexing.jsonl"). String.
    data -- Dictionary of log fields to write. Dict.
    """
    data["timestamp"] = datetime.now(timezone.utc).isoformat()
    log_dir = _get_log_dir(category)
    log_file = log_dir / filename
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


def log_indexing(
    *,
    label,
    page_id,
    title,
    embedding_model="",
    embedding_tokens=0,
    embedding_cost=0.0,
    vision_model="",
    vision_cost=0.0,
    status="success",
    error=None,
) -> None:
    """Log a page indexing operation to gemini/indexing.jsonl.

    Arguments:
    label -- Operation label or identifier. String.
    page_id -- Notion page ID. String.
    title -- Page title. String.
    embedding_model -- Model used for embedding (default: ""). String.
    embedding_tokens -- Number of tokens embedded (default: 0). Integer.
    embedding_cost -- Cost of embedding operation in USD (default: 0.0). Float.
    vision_model -- Model used for vision processing (default: ""). String.
    vision_cost -- Cost of vision processing in USD (default: 0.0). Float.
    status -- Operation status (default: "success"). String.
    error -- Error message if status is not success (default: None). String or None.
    """
    data = {
        "label": label,
        "page_id": page_id,
        "title": title,
        "embedding_model": embedding_model,
        "embedding_tokens": embedding_tokens,
        "embedding_cost": embedding_cost,
        "vision_model": vision_model,
        "vision_cost": vision_cost,
        "total_cost": embedding_cost + vision_cost,
        "status": status,
    }
    if error is not None:
        data["error"] = error
    _append("gemini", "indexing.jsonl", data)


def log_query(
    *,
    label,
    query,
    model,
    input_tokens=0,
    output_tokens=0,
    cost=0.0,
    elapsed=0.0,
    source="cli",
) -> None:
    """Log a RAG query operation to gemini/query.jsonl.

    Arguments:
    label -- Operation label or identifier. String.
    query -- The query text. String.
    model -- Model name used for query. String.
    input_tokens -- Number of input tokens (default: 0). Integer.
    output_tokens -- Number of output tokens (default: 0). Integer.
    cost -- Query cost in USD (default: 0.0). Float.
    elapsed -- Query elapsed time in seconds (default: 0.0). Float.
    source -- Query source (default: "cli"). String.
    """
    data = {
        "label": label,
        "query": query,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": cost,
        "total_cost": cost,  # Standardize: all gemini logs have total_cost
        "elapsed": elapsed,
        "source": source,
    }
    _append("gemini", "query.jsonl", data)


def log_sync(
    *,
    label,
    db_id,
    pages_checked=0,
    pages_updated=0,
    pages_skipped=0,
    indexing_cost=0.0,
    image_cost=0.0,
    force=False,
) -> None:
    """Log a sync operation summary to gemini/sync.jsonl.

    Arguments:
    label -- Operation label or identifier. String.
    db_id -- Notion database ID. String.
    pages_checked -- Number of pages checked (default: 0). Integer.
    pages_updated -- Number of pages updated (default: 0). Integer.
    pages_skipped -- Number of pages skipped (default: 0). Integer.
    indexing_cost -- Cost of indexing operations in USD (default: 0.0). Float.
    image_cost -- Cost of image processing in USD (default: 0.0). Float.
    force -- Whether force sync was enabled (default: False). Boolean.
    """
    data = {
        "label": label,
        "db_id": db_id,
        "pages_checked": pages_checked,
        "pages_updated": pages_updated,
        "pages_skipped": pages_skipped,
        "indexing_cost": indexing_cost,
        "image_cost": image_cost,
        "total_cost": indexing_cost + image_cost,
        "force": force,
    }
    _append("gemini", "sync.jsonl", data)


def log_init(
    *,
    label,
    db_id,
    store_name,
    pages_total=0,
    pages_indexed=0,
    indexing_cost=0.0,
    image_cost=0.0,
) -> None:
    """Log an init operation summary to gemini/init.jsonl.

    Arguments:
    label -- Operation label or identifier. String.
    db_id -- Notion database ID. String.
    store_name -- Vector store name. String.
    pages_total -- Total number of pages found (default: 0). Integer.
    pages_indexed -- Number of pages successfully indexed (default: 0). Integer.
    indexing_cost -- Cost of indexing operations in USD (default: 0.0). Float.
    image_cost -- Cost of image processing in USD (default: 0.0). Float.
    """
    data = {
        "label": label,
        "db_id": db_id,
        "store_name": store_name,
        "pages_total": pages_total,
        "pages_indexed": pages_indexed,
        "indexing_cost": indexing_cost,
        "image_cost": image_cost,
        "total_cost": indexing_cost + image_cost,
    }
    _append("gemini", "init.jsonl", data)


def log_api(
    *, method, path, status_code, elapsed=0.0, client_ip=None, detail=None
) -> None:
    """Log an API request to audit/api.jsonl.

    Arguments:
    method -- HTTP method (e.g., "GET", "POST"). String.
    path -- Request path. String.
    status_code -- HTTP status code. Integer.
    elapsed -- Request elapsed time in seconds (default: 0.0). Float.
    client_ip -- Client IP address (default: None). String or None.
    detail -- Additional detail or error message (default: None). String or None.
    """
    data = {
        "method": method,
        "path": path,
        "status_code": status_code,
        "elapsed": elapsed,
    }
    if client_ip is not None:
        data["client_ip"] = client_ip
    if detail is not None:
        data["detail"] = detail
    _append("audit", "api.jsonl", data)
