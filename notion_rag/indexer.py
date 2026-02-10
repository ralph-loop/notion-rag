"""High-level indexing operations for Notion RAG system.

Manages database initialization, synchronization, and page indexing
using Gemini Document custom_metadata for change tracking.
"""

import os
import sys
import tempfile
import time

from google import genai
from google.genai import types
from notion_client import Client as NotionClient

from .config import EMBEDDING_MODEL, GEMINI_API_KEY, IMAGE_VISION_MODEL, INDEX_WAIT_SEC, calc_cost, resolve_db, save_database
from .notion_helpers import (
    extract_db_id,
    get_page_properties,
    query_database_pages,
)
from .extractor import extract_blocks_with_images
from .logger import log_indexing, log_init, log_sync
from .store import (
    db_store_name,
    find_document,
    get_document_last_edited,
    get_or_create_store,
    list_documents_map,
)


def get_gemini_client() -> genai.Client:
    """Create authenticated Gemini API client.

    Returns: authenticated genai.Client instance.

    Raises:
    SystemExit -- if GEMINI_API_KEY is not set.
    """
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY environment variable is not set")
        sys.exit(1)
    return genai.Client(api_key=GEMINI_API_KEY)


def index_page(
    client: genai.Client,
    store,
    notion: NotionClient,
    page_id: str,
    db_id: str,
    label: str = "",
    reindex: bool = False,
    quiet: bool = False,
) -> tuple[float, float]:
    """Index a single Notion page into the store with image analysis.

    Arguments:
    client -- Authenticated Gemini API client. genai.Client.
    store -- The file search store object. Store.
    notion -- Authenticated Notion API client. NotionClient.
    page_id -- The Notion page ID to index. String.
    db_id -- The Notion database ID this page belongs to. String.
    label -- The database label for logging (default: ""). String.
    reindex -- Force reindexing even if unchanged (default: False). Boolean.
    quiet -- Suppress log output (default: False). Boolean.

    Returns: tuple of (indexing cost, image analysis cost) in USD.

    Auto-detects changes via custom_metadata comparison. Use reindex=True to force.
    """
    log = (lambda *a, **kw: None) if quiet else print

    existing_doc = find_document(client, store.name, page_id)

    if existing_doc and not reindex:
        # Compare Notion's last_edited_time with stored custom_metadata
        page = notion.pages.retrieve(page_id=page_id)
        current_edited = page.get("last_edited_time", "")
        old_edited = get_document_last_edited(existing_doc)

        if current_edited == old_edited:
            log(f"  Already up to date: {existing_doc.display_name}")
            return 0.0, 0.0
        else:
            log(f"  Change detected ({old_edited} -> {current_edited})")
            reindex = True

    # Extract content
    props = get_page_properties(notion, page_id)
    title = props.get("title", "Untitled")
    last_edited = props.get("last_edited", "")

    log(f"  Title: {title}")
    content, image_cost = extract_blocks_with_images(notion, client, page_id)
    log(f"  Image analysis cost: ${image_cost:.8f}")

    doc_type = props.get("Type", "")
    tags = props.get("Tags", [])
    ref_url = props.get("URL", "")

    header = f"[Title: {title}]"
    if doc_type:
        header += f"\n[Type: {doc_type}]"
    if tags:
        header += f"\n[Tags: {', '.join(tags) if isinstance(tags, list) else tags}]"
    if ref_url:
        header += f"\n[Reference: {ref_url}]"

    full_text = f"{header}\n---\n{content}"

    # Write to temp file for upload
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(full_text)
        text_file = f.name

    try:
        # Token count
        token_response = client.models.count_tokens(
            model=EMBEDDING_MODEL,
            contents=full_text,
        )
        token_count = token_response.total_tokens
        indexing_cost = calc_cost(EMBEDDING_MODEL, token_count)
        log(f"  Tokens: {token_count:,}, cost: ${indexing_cost:.8f}")

        # Delete old document if reindexing
        if existing_doc and reindex:
            log(f"  Deleting old document...")
            client.file_search_stores.documents.delete(
                name=existing_doc.name, config={"force": True}
            )

        # Upload with custom_metadata
        doc_display = f"[{page_id}] {title[:50]}"
        log(f"  Uploading: {doc_display}")

        operation = client.file_search_stores.upload_to_file_search_store(
            file=text_file,
            file_search_store_name=store.name,
            config=types.UploadToFileSearchStoreConfig(
                display_name=doc_display,
                custom_metadata=[
                    types.CustomMetadata(key="last_edited", string_value=last_edited),
                    types.CustomMetadata(key="page_id", string_value=page_id),
                ],
            ),
        )

        poll_count = 0
        while not operation.done:
            poll_count += 1
            time.sleep(2)
            operation = client.operations.get(operation)

        log(f"  Indexed in ~{poll_count * 2}s")

        log_indexing(
            label=label,
            page_id=page_id,
            title=title,
            embedding_model=EMBEDDING_MODEL,
            embedding_tokens=token_count,
            embedding_cost=indexing_cost,
            vision_model=IMAGE_VISION_MODEL,
            vision_cost=image_cost,
        )
    finally:
        os.unlink(text_file)

    return indexing_cost, image_cost


def init_db(label: str | None = None, db_url: str | None = None) -> dict:
    """Initialize a Notion database for RAG by indexing all pages.

    Arguments:
    label -- The database label for store naming and registry lookup (optional).
             Auto-detected when omitted and exactly one database is registered.
             String or None.
    db_url -- Notion database URL (optional). If provided, saves to settings registry.
              If None, resolves from existing registry. String or None.

    Returns: summary dictionary with keys:
             {label, db_id, store_name, pages_total, pages_indexed, total_cost,
              indexing_cost, image_cost}.
    """
    from .config import NOTION_TOKEN

    if not NOTION_TOKEN:
        print("NOTION_TOKEN environment variable is not set")
        sys.exit(1)

    # Resolve or register database URL
    if db_url is not None:
        if label is None:
            print("Label is required when providing a database URL")
            sys.exit(1)
        save_database(label, db_url)
    else:
        label, db_url = resolve_db(label)

    # Parse database ID
    db_id = extract_db_id(db_url)
    print(f"Database ID: {db_id}")

    # Create clients
    client = get_gemini_client()
    notion = NotionClient(auth=NOTION_TOKEN)

    # Get or create store
    store_display_name = db_store_name(label)
    store, created = get_or_create_store(client, store_display_name)
    if created:
        print(f"Created store: {store_display_name}")
    else:
        print(f"Using store: {store_display_name}")

    # Query ALL pages from database
    print(f"\n-- Querying all pages from database --")
    page_ids = query_database_pages(notion, db_id, last_days=None)
    pages_total = len(page_ids)
    print(f"Found {pages_total} pages")

    # Index each page
    print(f"\n-- Indexing pages --")
    pages_indexed = 0
    total_indexing_cost = 0.0
    total_image_cost = 0.0

    for i, page_id in enumerate(page_ids, 1):
        print(f"\n[{i}/{pages_total}] Page {page_id[:8]}")
        try:
            indexing_cost, image_cost = index_page(
                client, store, notion, page_id, db_id, label=label, reindex=False, quiet=False
            )
            total_indexing_cost += indexing_cost
            total_image_cost += image_cost
            pages_indexed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            log_indexing(label=label, page_id=page_id, title="", embedding_model=EMBEDDING_MODEL, status="error", error=str(e))
            continue

    # Wait for index to settle
    print(f"\n  Waiting {INDEX_WAIT_SEC}s for index to be ready...")
    time.sleep(INDEX_WAIT_SEC)

    total_cost = total_indexing_cost + total_image_cost

    print(f"\n-- Summary --")
    print(f"  Label:         {label}")
    print(f"  Database:      {db_id[:8]}")
    print(f"  Store:         {store_display_name}")
    print(f"  Pages total:   {pages_total}")
    print(f"  Pages indexed: {pages_indexed}")
    print(f"  Indexing cost:       ${total_indexing_cost:.8f}")
    print(f"  Image analysis cost: ${total_image_cost:.8f}")
    print(f"  Total cost:          ${total_cost:.8f}")

    log_init(
        label=label,
        db_id=db_id,
        store_name=store_display_name,
        pages_total=pages_total,
        pages_indexed=pages_indexed,
        indexing_cost=total_indexing_cost,
        image_cost=total_image_cost,
    )

    return {
        "label": label,
        "db_id": db_id,
        "store_name": store_display_name,
        "pages_total": pages_total,
        "pages_indexed": pages_indexed,
        "total_cost": total_cost,
        "indexing_cost": total_indexing_cost,
        "image_cost": total_image_cost,
    }


def sync_db(label: str | None = None, force: bool = False) -> dict:
    """Sync a Notion database by re-indexing changed pages.

    Arguments:
    label -- The registered database label (optional).
             Auto-detected when omitted and exactly one database is registered.
             String or None.
    force -- Force reindex all pages regardless of changes (default: False). Boolean.

    Returns: summary dictionary with keys:
             {label, db_id, pages_checked, pages_updated, pages_skipped, total_cost,
              indexing_cost, image_cost}.
    """
    from .config import NOTION_TOKEN, SYNC_DAYS

    if not NOTION_TOKEN:
        print("NOTION_TOKEN environment variable is not set")
        sys.exit(1)

    # Resolve database URL from registry
    label, db_url = resolve_db(label)
    db_id = extract_db_id(db_url)
    print(f"Database ID: {db_id}")

    # Create clients
    client = get_gemini_client()
    notion = NotionClient(auth=NOTION_TOKEN)

    # Get or create store
    store_display_name = db_store_name(label)
    store, created = get_or_create_store(client, store_display_name)
    if created:
        print(f"Created store: {store_display_name}")
    else:
        print(f"Using store: {store_display_name}")

    # Query pages updated in last SYNC_DAYS
    print(f"\n-- Querying pages updated in last {SYNC_DAYS} days --")
    page_ids = query_database_pages(notion, db_id, last_days=SYNC_DAYS)
    pages_checked = len(page_ids)
    print(f"Found {pages_checked} pages")

    # Build document map from Store for change detection
    doc_map = list_documents_map(client, store.name)

    # Check and reindex changed pages
    print(f"\n-- Checking for changes --")
    pages_updated = 0
    pages_skipped = 0
    total_indexing_cost = 0.0
    total_image_cost = 0.0

    for i, page_id in enumerate(page_ids, 1):
        print(f"\n[{i}/{pages_checked}] Page {page_id[:8]}")

        try:
            props = get_page_properties(notion, page_id)
            title = props.get("title", "Untitled")
            current_edited = props.get("last_edited", "")

            # Compare with Store document metadata
            existing_doc = doc_map.get(page_id)
            old_edited = get_document_last_edited(existing_doc) if existing_doc else ""

            if current_edited == old_edited and not force:
                print(f"  {title} - up to date")
                pages_skipped += 1
            else:
                if force:
                    print(f"  {title} - FORCE reindex")
                else:
                    print(f"  {title} - CHANGED ({old_edited} -> {current_edited})")

                indexing_cost, image_cost = index_page(
                    client, store, notion, page_id, db_id, label=label, reindex=True, quiet=True
                )
                total_indexing_cost += indexing_cost
                total_image_cost += image_cost
                pages_updated += 1
                print(f"  re-indexed (indexing: ${indexing_cost:.8f}, images: ${image_cost:.8f})")

        except Exception as e:
            print(f"  ERROR: {e}")
            log_indexing(label=label, page_id=page_id, title=title, embedding_model=EMBEDDING_MODEL, status="error", error=str(e))
            continue

    # Wait for index to settle if any updates
    if pages_updated > 0:
        print(f"\n  Waiting {INDEX_WAIT_SEC}s for index to be ready...")
        time.sleep(INDEX_WAIT_SEC)

    total_cost = total_indexing_cost + total_image_cost

    print(f"\n-- Sync Summary --")
    print(f"  Checked:  {pages_checked}")
    print(f"  Updated:  {pages_updated}")
    print(f"  Skipped:  {pages_skipped}")
    if total_cost > 0:
        print(f"  Indexing cost:       ${total_indexing_cost:.8f}")
        print(f"  Image analysis cost: ${total_image_cost:.8f}")
        print(f"  Total cost:          ${total_cost:.8f}")

    log_sync(
        label=label,
        db_id=db_id,
        pages_checked=pages_checked,
        pages_updated=pages_updated,
        pages_skipped=pages_skipped,
        indexing_cost=total_indexing_cost,
        image_cost=total_image_cost,
        force=force,
    )

    return {
        "label": label,
        "db_id": db_id,
        "pages_checked": pages_checked,
        "pages_updated": pages_updated,
        "pages_skipped": pages_skipped,
        "total_cost": total_cost,
        "indexing_cost": total_indexing_cost,
        "image_cost": total_image_cost,
    }
