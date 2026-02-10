"""Content extraction from Notion blocks with image description support.

Recursively extract text from Notion pages including image analysis via Gemini vision.
"""

from notion_client import Client as NotionClient
from google import genai

from notion_rag.notion_helpers import extract_rich_text
from notion_rag.image import get_image_url, describe_image


def extract_blocks_with_images(notion: NotionClient, client: genai.Client, block_id: str, depth: int = 0, image_details: list | None = None) -> tuple[str, float]:
    """Recursively extract text from Notion blocks with image description support.

    Arguments:
    notion -- Authenticated Notion API client. NotionClient.
    client -- Authenticated Gemini API client for image description. genai.Client.
    block_id -- The ID of the parent block to extract children from. String.
    depth -- Current nesting depth for indentation (default: 0). Integer.
    image_details -- Optional list to collect per-image analysis details (default: None). List or None.

    Returns: tuple of (extracted text content, total image analysis cost).

    Supported block types:
    - paragraph, heading_1/2/3
    - bulleted_list_item, numbered_list_item, to_do
    - code (preserves language and content)
    - callout, quote, toggle (recursive)
    - table, table_row
    - divider
    - bookmark, link_preview
    - image (downloads and describes via Gemini vision)
    - file, pdf
    - child_page, child_database (title only)
    - column_list, column
    - synced_block

    HTTP Method: GET

    API Reference
    https://developers.notion.com/reference/get-block-children
    """
    texts = []
    indent = "  " * depth
    total_image_cost = 0.0

    # Handle pagination
    cursor = None
    while True:
        response = notion.blocks.children.list(
            block_id=block_id, start_cursor=cursor, page_size=100
        )
        blocks = response.get("results", [])

        for block in blocks:
            btype = block["type"]
            block_data = block.get(btype, {})

            # ── Text blocks ──
            if btype in (
                "paragraph",
                "bulleted_list_item",
                "numbered_list_item",
                "to_do",
                "quote",
                "callout",
                "toggle",
            ):
                text = extract_rich_text(block_data.get("rich_text", []))
                if text:
                    if btype == "bulleted_list_item":
                        texts.append(f"{indent}- {text}")
                    elif btype == "numbered_list_item":
                        texts.append(f"{indent}1. {text}")
                    elif btype == "to_do":
                        checked = "x" if block_data.get("checked") else " "
                        texts.append(f"{indent}- [{checked}] {text}")
                    elif btype == "callout":
                        texts.append(f"{indent}> [!NOTE] {text}")
                    elif btype == "toggle":
                        texts.append(f"{indent}▶ {text}")
                    elif btype == "quote":
                        texts.append(f"{indent}> {text}")
                    else:
                        texts.append(f"{indent}{text}")

            # ── Headings ──
            elif btype in ("heading_1", "heading_2", "heading_3"):
                text = extract_rich_text(block_data.get("rich_text", []))
                level = int(btype[-1])
                if text:
                    texts.append(f"\n{'#' * level} {text}")

            # ── Code block (preserve language) ──
            elif btype == "code":
                text = extract_rich_text(block_data.get("rich_text", []))
                lang = block_data.get("language", "")
                caption = extract_rich_text(block_data.get("caption", []))
                if text:
                    texts.append(f"{indent}```{lang}")
                    texts.append(text)
                    texts.append(f"{indent}```")
                    if caption:
                        texts.append(f"{indent}[Code description: {caption}]")

            # ── Table ──
            elif btype == "table":
                if block.get("has_children"):
                    table_text, table_cost = extract_blocks_with_images(notion, client, block["id"], depth, image_details)
                    total_image_cost += table_cost
                    if table_text:
                        texts.append(table_text)
                continue

            elif btype == "table_row":
                cells = block_data.get("cells", [])
                row_texts = [extract_rich_text(cell) for cell in cells]
                texts.append(f"{indent}| " + " | ".join(row_texts) + " |")

            # ── Divider ──
            elif btype == "divider":
                texts.append(f"{indent}---")

            # ── Image (with description) ──
            elif btype == "image":
                caption = extract_rich_text(block_data.get("caption", []))
                image_url = get_image_url(block_data)

                if image_url:
                    result = describe_image(client, image_url, caption)
                    total_image_cost += result["cost"]
                    if image_details is not None:
                        image_details.append({
                            "url": image_url,
                            "caption": caption,
                            "type": result["type"],
                            "cost": result["cost"],
                            "elapsed": result["elapsed"],
                            "description_preview": result["description"][:100],
                        })

                    if result["type"] == "terminal":
                        # Terminal capture: code block only, no [Image] wrapper
                        if result["description"]:
                            texts.append(f"\n{indent}{result['description']}")
                        if result["code"]:
                            texts.append(f"\n{indent}```\n{result['code']}\n{indent}```\n")
                    else:
                        # Diagram/other: [Image] wrapper with description
                        label = f"Image: {caption}" if caption else "Image"
                        if result["description"]:
                            texts.append(f"\n\n{indent}**[{label}]**\n{indent}{result['description']}\n{indent}**[/{label}]**\n\n")
                        # Code block outside the wrapper if present
                        if result["code"]:
                            texts.append(f"{indent}```\n{result['code']}\n{indent}```\n")
                else:
                    # Fallback if URL extraction fails
                    if caption:
                        texts.append(f"{indent}[IMAGE: {caption}]")
                    else:
                        texts.append(f"{indent}[IMAGE]")

            # ── Bookmark / Link ──
            elif btype == "bookmark":
                url = block_data.get("url", "")
                caption = extract_rich_text(block_data.get("caption", []))
                if caption:
                    texts.append(f"{indent}[REF: {caption} - {url}]")
                elif url:
                    texts.append(f"{indent}[REF: {url}]")

            elif btype == "link_preview":
                url = block_data.get("url", "")
                if url:
                    texts.append(f"{indent}[LINK: {url}]")

            # ── File / PDF ──
            elif btype in ("file", "pdf"):
                caption = extract_rich_text(block_data.get("caption", []))
                name = block_data.get("name", "")
                texts.append(f"{indent}[FILE: {name or caption or 'attachment'}]")

            # ── Child page / Database ──
            elif btype == "child_page":
                title = block_data.get("title", "")
                texts.append(f"{indent}[CHILD PAGE: {title}]")

            elif btype == "child_database":
                title = block_data.get("title", "")
                texts.append(f"{indent}[CHILD DB: {title}]")

            # ── Column ──
            elif btype in ("column_list", "column"):
                if block.get("has_children"):
                    child_text, child_cost = extract_blocks_with_images(notion, client, block["id"], depth, image_details)
                    total_image_cost += child_cost
                    if child_text:
                        texts.append(child_text)
                continue

            # ── synced_block ──
            elif btype == "synced_block":
                if block.get("has_children"):
                    child_text, child_cost = extract_blocks_with_images(notion, client, block["id"], depth, image_details)
                    total_image_cost += child_cost
                    if child_text:
                        texts.append(child_text)
                continue

            # ── Recursively process child blocks (toggle, callout, etc.) ──
            if block.get("has_children") and btype not in (
                "table",
                "column_list",
                "column",
                "synced_block",
            ):
                child_text, child_cost = extract_blocks_with_images(notion, client, block["id"], depth + 1, image_details)
                total_image_cost += child_cost
                if child_text:
                    texts.append(child_text)

        # Pagination
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")

    return "\n".join(texts), total_image_cost
