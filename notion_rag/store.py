"""Gemini FileSearch store management for Notion RAG system.

Provides functions to create, query, and manage FileSearch stores
that hold indexed Notion documents.
"""

from google import genai


def db_store_name(label: str) -> str:
    """Generate store display name from database label.

    Arguments:
    label -- The registered database label. String.

    Returns: the label itself as the store display name.
    """
    return label


def get_or_create_store(client: genai.Client, store_name: str) -> tuple:
    """Get existing store by display_name or create new one.

    Arguments:
    client -- Authenticated Gemini API client. genai.Client.
    store_name -- Display name to search for or assign to new store. String.

    Returns: tuple of (store object, created boolean).
             created=True if a new store was created, False if existing store was found.
    """
    for store in client.file_search_stores.list():
        if store.display_name == store_name:
            return store, False

    store = client.file_search_stores.create(
        config={"display_name": store_name}
    )
    return store, True


def find_document(client: genai.Client, store_name: str, page_id: str):
    """Find an existing document in the store by page_id in custom_metadata.

    Arguments:
    client -- Authenticated Gemini API client. genai.Client.
    store_name -- The resource name of the store (e.g., "fileSearchStores/xxx"). String.
    page_id -- The Notion page ID to search for. String.

    Returns: document object if found, None otherwise.
    """
    for doc in client.file_search_stores.documents.list(parent=store_name):
        if doc.custom_metadata:
            for meta in doc.custom_metadata:
                if meta.key == "page_id" and meta.string_value == page_id:
                    return doc
    return None


def list_documents(client: genai.Client, store_name: str) -> list:
    """List all documents in a store.

    Arguments:
    client -- Authenticated Gemini API client. genai.Client.
    store_name -- The resource name of the store (e.g., "fileSearchStores/xxx"). String.

    Returns: list of document objects.
    """
    return list(client.file_search_stores.documents.list(parent=store_name))


def get_document_last_edited(doc) -> str:
    """Extract last_edited value from a document's custom_metadata.

    Arguments:
    doc -- Gemini FileSearch document object. Document.

    Returns: last_edited timestamp string, or empty string if not found.
    """
    if doc and doc.custom_metadata:
        for meta in doc.custom_metadata:
            if meta.key == "last_edited":
                return meta.string_value or ""
    return ""


def list_documents_map(client: genai.Client, store_name: str) -> dict:
    """Build a mapping of full page_id to document object.

    Arguments:
    client -- Authenticated Gemini API client. genai.Client.
    store_name -- The resource name of the store (e.g., "fileSearchStores/xxx"). String.

    Returns: dictionary with full page_id as key and document object as value.
    """
    result = {}
    for doc in client.file_search_stores.documents.list(parent=store_name):
        if doc.custom_metadata:
            for meta in doc.custom_metadata:
                if meta.key == "page_id" and meta.string_value:
                    result[meta.string_value] = doc
                    break
    return result


def delete_store(client: genai.Client, store_name: str) -> bool:
    """Delete a store by display_name.

    Arguments:
    client -- Authenticated Gemini API client. genai.Client.
    store_name -- Display name of the store to delete. String.

    Returns: True if store was found and deleted, False if not found.
    """
    store = None
    for s in client.file_search_stores.list():
        if s.display_name == store_name:
            store = s
            break

    if not store:
        return False

    client.file_search_stores.delete(name=store.name, config={"force": True})
    return True
