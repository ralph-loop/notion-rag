"""Command-line interface for Notion RAG service.

Provides subcommands for initializing, syncing, querying, and managing
Notion database indexes in Gemini File Search.
"""

import argparse
import sys
import time

import uvicorn
from google.genai import types

from notion_rag.billing import get_billing
from notion_rag.config import DATABASES, DEFAULT_QUERY_MODEL, PRICING, SERVER_HOST, SERVER_PORT, calc_cost, resolve_db
from notion_rag.indexer import get_gemini_client, init_db, sync_db
from notion_rag.logger import log_query
from notion_rag.store import (
    db_store_name,
    delete_store,
    find_document,
    get_document_last_edited,
    get_or_create_store,
    list_documents,
)


def cmd_init(args):
    """Initialize and index a Notion database.

    Arguments:
    args -- Parsed command-line arguments containing optional name and db_url. Namespace.

    Returns: None. Prints summary to stdout.
    """
    if args.name is None:
        label, _ = resolve_db()
        result = init_db(label)
    else:
        result = init_db(args.name, db_url=args.db_url)

    print(f"\n-- Init Summary --")
    print(f"  Label:           {result['label']}")
    print(f"  Database ID:     {result['db_id']}")
    print(f"  Store:           {result['store_name']}")
    print(f"  Pages indexed:   {result['pages_indexed']} / {result['pages_total']}")
    print(f"  Indexing cost:   ${result['indexing_cost']:.8f}")
    print(f"  Image cost:      ${result['image_cost']:.8f}")
    print(f"  Total cost:      ${result['total_cost']:.8f}")
    print(f"\nDone.")


def cmd_sync(args):
    """Sync a Notion database, re-indexing changed pages.

    Arguments:
    args -- Parsed command-line arguments containing name and force flag. Namespace.

    Returns: None. Prints summary to stdout.
    """
    label = args.name if args.name else resolve_db()[0]
    result = sync_db(label, force=args.force)

    print(f"\n-- Sync Summary --")
    print(f"  Database ID:     {result['db_id']}")
    print(f"  Pages checked:   {result['pages_checked']}")
    print(f"  Pages updated:   {result['pages_updated']}")
    print(f"  Pages skipped:   {result['pages_skipped']}")
    print(f"  Indexing cost:   ${result['indexing_cost']:.8f}")
    print(f"  Image cost:      ${result['image_cost']:.8f}")
    print(f"  Total cost:      ${result['total_cost']:.8f}")
    print(f"\nDone.")


def cmd_serve(args):
    """Start the FastAPI server.

    Arguments:
    args -- Parsed command-line arguments containing host and port. Namespace.

    Returns: None. Runs until interrupted.
    """
    uvicorn.run("notion_rag.server:app", host=args.host, port=args.port)


def cmd_query(args):
    """Execute a RAG query against a Notion database.

    Arguments:
    args -- Parsed command-line arguments containing name, query, and model. Namespace.

    Returns: None. Prints response and usage to stdout.
    """
    client = get_gemini_client()

    # Resolve name and query from positional args
    if args.query is not None:
        name, query_text = args.name_or_query, args.query
    else:
        name, query_text = None, args.name_or_query

    label, _ = resolve_db(name)
    store_name = db_store_name(label)

    # Get or create store
    store, created = get_or_create_store(client, store_name)

    # Check if store has documents
    docs = list_documents(client, store.name)
    if not docs:
        print(f"Store '{store_name}' is empty. Run 'init' first to add documents.")
        if created:
            client.file_search_stores.delete(name=store.name, config={"force": True})
        sys.exit(1)

    print(f"-- Querying --")
    print(f"  Store: {store_name} ({len(docs)} documents)")
    print(f"  Model: {args.model}")
    print(f"  Query: {query_text}")

    # Start timing
    start = time.time()

    # Execute query with file_search tool
    response = client.models.generate_content(
        model=args.model,
        contents=query_text,
        config=types.GenerateContentConfig(
            tools=[
                types.Tool(
                    file_search=types.FileSearch(file_search_store_names=[store.name])
                )
            ]
        ),
    )

    print(f"\n-- Response --")
    print(response.text)

    if response.candidates and response.candidates[0].grounding_metadata:
        metadata = response.candidates[0].grounding_metadata
        print(f"\n-- Grounding Metadata --")
        print(f"  {metadata}")

    # Initialize default values for logging
    input_tokens = 0
    output_tokens = 0
    total_cost = 0.0

    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count or 0
        output_tokens = usage.candidates_token_count or 0
        model = args.model
        input_cost = calc_cost(model, input_tokens, 0)
        output_cost = calc_cost(model, 0, output_tokens)
        total_cost = input_cost + output_cost
        rate = PRICING.get(model, (0, 0))

        print(f"\n-- Cost --")
        print(f"  Model:           {model}")
        print(f"  Rate:            ${rate[0]} input / ${rate[1]} output per 1M tokens")
        print(f"  Prompt tokens:   {input_tokens:,}  (${input_cost:.8f})")
        print(f"  Response tokens: {output_tokens:,}  (${output_cost:.8f})")
        print(
            f"  Total:           {input_tokens + output_tokens:,} tokens, ${total_cost:.8f}"
        )

    # Log query
    log_query(
        label=label,
        query=query_text,
        model=args.model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=total_cost,
        elapsed=time.time() - start,
        source="cli",
    )


def cmd_billing(args):
    """Show Gemini API billing summary from logs.

    Arguments:
    args -- Parsed command-line arguments containing period flag. Namespace.

    Returns: None. Prints billing summary to stdout.
    """
    if args.monthly:
        period = "monthly"
    elif args.daily:
        period = "daily"
    else:
        period = "total"

    result = get_billing(period)
    total = result["total"]

    print(f"-- Billing Summary --")
    print(f"  Embedding cost:  ${total['embedding_cost']:.8f}")
    print(f"  Vision cost:     ${total['vision_cost']:.8f}")
    print(f"  Query cost:      ${total['query_cost']:.8f}")
    print(f"  Total cost:      ${total['total_cost']:.8f}")

    if result["breakdown"]:
        print(f"\n-- Breakdown ({period}) --")
        for entry in result["breakdown"]:
            print(f"\n  {entry['period']}")
            print(f"    Embedding: ${entry['embedding_cost']:.8f}")
            print(f"    Vision:    ${entry['vision_cost']:.8f}")
            print(f"    Query:     ${entry['query_cost']:.8f}")
            print(f"    Total:     ${entry['total_cost']:.8f}")


def cmd_list(args):
    """List documents in a store or all Notion stores.

    Arguments:
    args -- Parsed command-line arguments with optional name. Namespace.

    Returns: None. Prints store and document information to stdout.
    """
    client = get_gemini_client()

    if args.name:
        # List documents in specific store
        store_name = db_store_name(args.name)

        store, created = get_or_create_store(client, store_name)
        if created:
            print(f"Store '{store_name}' does not exist.")
            client.file_search_stores.delete(name=store.name, config={"force": True})
            return

        docs = list_documents(client, store.name)

        print(f"-- Store: {store_name} --")
        print(f"  Resource:  {store.name}")
        print(f"  Documents: {len(docs)}")
        print(f"  Size:      {store.size_bytes} bytes")

        if docs:
            print(f"\n-- Documents --")
            for doc in docs:
                print(f"  {doc.display_name}")
                last_edited = get_document_last_edited(doc)
                if last_edited:
                    print(f"    last_edited: {last_edited}")
                print()
    else:
        # List all stores with configured prefix
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

        print(f"-- Notion Stores ({len(stores)}) --")
        for s in stores:
            print(f"  {s['display_name']}")
            print(f"    Resource:  {s['name']}")
            print(f"    Documents: {s['documents']}")
            print(f"    Size:      {s['size_bytes']} bytes")
            print()


def cmd_remove(args):
    """Remove a document from a store.

    Arguments:
    args -- Parsed command-line arguments containing page_id and optional name. Namespace.

    Returns: None. Prints deletion status to stdout.
    """
    client = get_gemini_client()

    # Resolve name and page_id from positional args
    if args.page_id is not None:
        name, page_id = args.name_or_page_id, args.page_id
    else:
        name, page_id = None, args.name_or_page_id

    label, _ = resolve_db(name)
    store_name = db_store_name(label)

    store, created = get_or_create_store(client, store_name)
    if created:
        print(f"Store '{store_name}' does not exist.")
        client.file_search_stores.delete(name=store.name, config={"force": True})
        return

    doc = find_document(client, store.name, page_id)
    if not doc:
        print(f"Document not found for page ID: {page_id}")
        print("Use 'list' to see available documents.")
        return

    print(f"Deleting: {doc.display_name}")
    client.file_search_stores.documents.delete(name=doc.name, config={"force": True})
    print("Done.")


def cmd_cleanup(args):
    """Delete a store and all its documents.

    Arguments:
    args -- Parsed command-line arguments with optional name. Namespace.

    Returns: None. Prints deletion status to stdout.
    """
    client = get_gemini_client()

    label = args.name if args.name else resolve_db()[0]
    store_name = db_store_name(label)

    # Check if store exists
    store_exists = False
    for s in client.file_search_stores.list():
        if s.display_name == store_name:
            store_exists = True
            docs = list_documents(client, s.name)
            print(
                f"Deleting store '{store_name}' ({len(docs)} documents)..."
            )
            break

    if not store_exists:
        print(f"Store '{store_name}' does not exist.")
        return

    # Delete store
    delete_store(client, store_name)
    print("Done.")


def main():
    """Main CLI entry point with argument parsing."""
    parser = argparse.ArgumentParser(
        description="Notion RAG service - Index and query Notion databases with Gemini File Search"
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize and index a Notion database")
    p_init.add_argument("name", nargs="?", help="Database label (auto-detected if omitted)")
    p_init.add_argument("db_url", nargs="?", help="Notion database URL (first-time registration)")

    # sync
    p_sync = sub.add_parser("sync", help="Sync database, re-indexing changed pages")
    p_sync.add_argument("name", nargs="?", help="Database label (auto-detected if omitted)")
    p_sync.add_argument(
        "--force", action="store_true", help="Force re-index all pages"
    )

    # serve
    p_serve = sub.add_parser("serve", help="Start the FastAPI server")
    p_serve.add_argument("--host", default=SERVER_HOST, help=f"Host to bind (default: {SERVER_HOST})")
    p_serve.add_argument("--port", type=int, default=SERVER_PORT, help=f"Port to bind (default: {SERVER_PORT})")

    # query
    p_query = sub.add_parser("query", help="Query a Notion database")
    p_query.add_argument("name_or_query", help="Database label or query text")
    p_query.add_argument("query", nargs="?", help="Query text (if label is provided)")
    p_query.add_argument(
        "--model",
        default=DEFAULT_QUERY_MODEL,
        help=f"Model to use (default: {DEFAULT_QUERY_MODEL})",
    )

    # list
    p_list = sub.add_parser(
        "list", help="List documents in a store or all Notion stores"
    )
    p_list.add_argument(
        "name", nargs="?", help="Database label (optional)"
    )

    # remove
    p_remove = sub.add_parser("remove", help="Remove a document from a store")
    p_remove.add_argument("name_or_page_id", help="Database label or page ID")
    p_remove.add_argument("page_id", nargs="?", help="Page ID (if label is provided)")

    # cleanup
    p_cleanup = sub.add_parser("cleanup", help="Delete a store and all documents")
    p_cleanup.add_argument("name", nargs="?", help="Database label (auto-detected if omitted)")

    # billing
    p_billing = sub.add_parser("billing", help="Show Gemini API billing summary")
    p_billing.add_argument("--monthly", action="store_true", help="Show monthly breakdown")
    p_billing.add_argument("--daily", action="store_true", help="Show daily breakdown")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "sync": cmd_sync,
        "serve": cmd_serve,
        "query": cmd_query,
        "list": cmd_list,
        "remove": cmd_remove,
        "cleanup": cmd_cleanup,
        "billing": cmd_billing,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
