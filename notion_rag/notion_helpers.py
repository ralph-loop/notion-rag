"""Notion API helper functions for page and database operations.

Extract IDs from URLs, retrieve page properties, and query database pages.
"""

import re
from datetime import datetime, timedelta, timezone
from notion_client import Client as NotionClient


def extract_page_id(url_or_id: str) -> str:
    """Extract page ID from a Notion URL or raw ID string.

    Arguments:
    url_or_id -- A Notion page URL or raw page ID. String.

    Returns: 32-character hex page ID string.

    Raises:
    ValueError -- If the input is not a valid Notion URL or ID.

    Supported formats:
    - https://www.notion.so/title-abc123def456...
    - https://www.notion.so/title-abc123def456...?source=copy_link
    - abc123def456 (32-char hex)
    - abc123de-f456-... (UUID with dashes)
    """
    # Handle URL format
    if "notion.so" in url_or_id:
        # Strip query parameters
        url_clean = url_or_id.split("?")[0]
        # Extract 32-char hex ID from the last path segment
        match = re.search(r"([a-f0-9]{32})$", url_clean.replace("-", ""))
        if match:
            return match.group(1)
        # UUID format with dashes
        match = re.search(
            r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})",
            url_clean,
        )
        if match:
            return match.group(1).replace("-", "")

    # Handle raw ID format
    clean = url_or_id.replace("-", "")
    if re.match(r"^[a-f0-9]{32}$", clean):
        return clean

    raise ValueError(f"Invalid Notion URL or ID: {url_or_id}")


def extract_db_id(url_or_id: str) -> str:
    """Extract database ID from a Notion database URL or raw ID string.

    Arguments:
    url_or_id -- A Notion database URL or raw database ID. String.

    Returns: 32-character hex database ID string.

    Raises:
    ValueError -- If the input is not a valid Notion database URL or ID.

    Supported formats:
    - https://www.notion.so/286c479a8fc21c807d134a19e9ae7065?v=...
    - 286c479a8fc21c807d134a19e9ae7065 (32-char hex)
    - 286c479a-8fc2-1c80-7d13-4a19e9ae7065 (UUID with dashes)
    """
    # Handle URL format
    if "notion.so" in url_or_id:
        # Strip query parameters (remove ?v=... part)
        url_clean = url_or_id.split("?")[0]
        # Extract 32-char hex ID from the last path segment
        match = re.search(r"([a-f0-9]{32})$", url_clean.replace("-", ""))
        if match:
            return match.group(1)
        # UUID format with dashes
        match = re.search(
            r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})",
            url_clean,
        )
        if match:
            return match.group(1).replace("-", "")

    # Handle raw ID format
    clean = url_or_id.replace("-", "")
    if re.match(r"^[a-f0-9]{32}$", clean):
        return clean

    raise ValueError(f"Invalid Notion database URL or ID: {url_or_id}")


def extract_rich_text(rich_text_list: list) -> str:
    """Extract plain text from a Notion rich_text array.

    Arguments:
    rich_text_list -- List of Notion rich_text objects. List.

    Returns: concatenated plain text string.
    """
    return "".join(rt.get("plain_text", "") for rt in rich_text_list)


def get_page_properties(notion: NotionClient, page_id: str) -> dict:
    """Extract metadata properties from a Notion page.

    Arguments:
    notion -- Authenticated Notion API client. NotionClient.
    page_id -- The Notion page ID. String.

    Returns: dict containing page_id, last_edited, title, and other properties.

    HTTP Method: POST

    API Reference
    https://developers.notion.com/reference/retrieve-a-page
    """
    page = notion.pages.retrieve(page_id=page_id)
    props = page.get("properties", {})

    result = {
        "page_id": page["id"],
        "last_edited": page.get("last_edited_time", ""),
    }

    for name, prop in props.items():
        ptype = prop["type"]
        if ptype == "title":
            result["title"] = extract_rich_text(prop["title"])
        elif ptype == "select" and prop.get("select"):
            result[name] = prop["select"]["name"]
        elif ptype == "multi_select":
            result[name] = [o["name"] for o in prop["multi_select"]]
        elif ptype == "url":
            result[name] = prop.get("url", "")
        elif ptype == "rich_text":
            result[name] = extract_rich_text(prop["rich_text"])

    return result


def query_database_pages(notion: NotionClient, db_id: str, last_days: int | None = None) -> list[str]:
    """Query a Notion database and retrieve page IDs.

    Arguments:
    notion -- Authenticated Notion API client. NotionClient.
    db_id -- The Notion database ID. String.
    last_days -- Filter pages edited within the last N days (optional). Integer or None.

    Returns: list of page IDs as strings.

    HTTP Method: POST

    API Reference
    https://developers.notion.com/reference/post-database-query
    """
    page_ids = []

    # Build filter for last_edited_time if last_days is specified
    filter_params = {}
    if last_days is not None:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=last_days)
        iso_date_str = cutoff_date.isoformat()
        filter_params = {
            "filter": {
                "timestamp": "last_edited_time",
                "last_edited_time": {
                    "on_or_after": iso_date_str
                }
            }
        }

    # Retrieve the database to get its data source ID (notion-client 2.7+ / API 2025-09-03)
    db = notion.databases.retrieve(database_id=db_id)
    ds_id = db["data_sources"][0]["id"]

    # Handle pagination
    cursor = None
    while True:
        query_params = {"data_source_id": ds_id, **filter_params}
        if cursor:
            query_params["start_cursor"] = cursor

        response = notion.data_sources.query(**query_params)

        for page in response.get("results", []):
            page_ids.append(page["id"])

        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return page_ids
