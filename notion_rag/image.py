"""Image processing functions for Notion blocks.

Download images from Notion and generate descriptions using Gemini vision model.
"""

import time
import httpx
from google import genai
from google.genai import types

from notion_rag.config import calc_cost, IMAGE_VISION_MODEL


def get_image_url(block_data: dict) -> str:
    """Extract image URL from a Notion image block data.

    Arguments:
    block_data -- The image block data from Notion API. Dictionary.

    Returns: image URL string, or empty string if not found.
    """
    if "file" in block_data:
        return block_data["file"].get("url", "")
    if "external" in block_data:
        return block_data["external"].get("url", "")
    return ""


def describe_image(client: genai.Client, image_url: str, caption: str = "") -> dict:
    """Download an image and describe it using Gemini vision model.

    Arguments:
    client -- Authenticated Gemini API client. genai.Client.
    image_url -- URL of the image to download and describe. String.
    caption -- Optional caption from Notion for context (default: ""). String.

    Returns: dict with keys: type, description, code, cost, elapsed.
             type is "terminal", "diagram", or "other".
    """
    start = time.time()
    error_result = lambda msg: {"type": "error", "description": msg, "code": "", "cost": 0.0, "elapsed": time.time() - start}

    try:
        resp = httpx.get(image_url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        return error_result(f"[Image could not be downloaded: {e}]")

    # Detect mime type from content-type header
    content_type = resp.headers.get("content-type", "image/png")
    mime_type = content_type.split(";")[0].strip()

    # Gemini vision only supports these image types
    supported_types = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}
    if mime_type not in supported_types:
        return error_result(f"[Image skipped: unsupported format ({mime_type})]")

    image_part = types.Part.from_bytes(data=resp.content, mime_type=mime_type)

    prompt = (
        "이 이미지를 분석하고 아래 형식으로 정확히 응답해주세요.\n\n"
        "TYPE: terminal 또는 diagram 또는 other\n"
        "(terminal = 터미널/쉘/명령어 출력/콘솔 캡처, "
        "diagram = 다이어그램/플로우차트/아키텍처도, "
        "other = 그 외 스크린샷/표/차트 등)\n\n"
        "DESCRIPTION: 이미지 핵심 내용 1~2문장 요약 (코드블록 사용 금지)\n\n"
        "CODE:\n코드나 명령어 출력이 있으면 ```로 감싸서 추출. 없으면 빈칸.\n\n"
        "규칙:\n"
        "- DESCRIPTION은 최대 2문장. 장황한 설명 금지\n"
        "- terminal 타입이면 DESCRIPTION은 짧게, CODE에 핵심 명령어/출력 추출\n"
        "- diagram 타입이면 DESCRIPTION에 구성요소와 흐름 요약\n"
        "- CODE가 없으면 CODE: 줄 자체를 생략"
    )
    if caption:
        prompt += f"\n\n참고 캡션: {caption}"

    response = client.models.generate_content(
        model=IMAGE_VISION_MODEL,
        contents=[prompt, image_part],
    )

    raw = response.text or ""

    cost = 0.0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count or 0
        output_tokens = usage.candidates_token_count or 0
        cost = calc_cost(IMAGE_VISION_MODEL, input_tokens, output_tokens)

    return _parse_image_response(raw, cost, time.time() - start)


def _parse_image_response(raw: str, cost: float, elapsed: float) -> dict:
    """Parse structured Gemini vision response into components.

    Arguments:
    raw -- Raw text response from Gemini vision model. String.
    cost -- USD cost of the API call. Float.
    elapsed -- Time elapsed for the API call in seconds. Float.

    Returns: dict with keys: type, description, code, cost, elapsed.
    """
    img_type = "other"
    description = ""
    code = ""

    lines = raw.strip().split("\n")
    section = None
    code_lines = []
    desc_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("TYPE:"):
            val = stripped[5:].strip().lower()
            if "terminal" in val:
                img_type = "terminal"
            elif "diagram" in val:
                img_type = "diagram"
            else:
                img_type = "other"
            section = None
        elif stripped.upper().startswith("DESCRIPTION:"):
            desc_lines.append(stripped[12:].strip())
            section = "desc"
        elif stripped.upper().startswith("CODE:"):
            remainder = stripped[5:].strip()
            if remainder:
                code_lines.append(remainder)
            section = "code"
        elif section == "desc":
            desc_lines.append(line.rstrip())
        elif section == "code":
            code_lines.append(line.rstrip())

    description = "\n".join(desc_lines).strip()
    code = "\n".join(code_lines).strip()

    # Strip wrapping ``` from code block if present
    if code.startswith("```") and code.endswith("```"):
        code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
        # Remove optional language identifier on first line
        first_nl = code.find("\n")
        if first_nl != -1:
            first_line = code[:first_nl].strip()
            if first_line and not first_line.startswith(" ") and len(first_line) < 20:
                code = code[first_nl + 1:]
        code = code.strip()

    # Fallback if parsing failed
    if not description and not code:
        description = raw.strip()

    return {
        "type": img_type,
        "description": description,
        "code": code,
        "cost": cost,
        "elapsed": elapsed,
    }
