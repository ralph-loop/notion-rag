---
description: "Notion RAG 검색. 'Notion에서 찾아줘' 키워드가 포함된 질문에 사용."
alwaysApply: false
---

# Notion RAG Query

Query a Notion database knowledge base using Retrieval Augmented Generation (RAG). This skill connects to a local FastAPI service that indexes Notion pages and provides semantic search with LLM-powered answers.

## Service Overview

The Notion RAG service host and port are configured in `settings.json` (`server_host`, `server_port`). Default: `http://127.0.0.1:8000`. Always read `settings.json` first to determine the correct base URL before making API calls.

**Note**: The knowledge base content is primarily in Korean. Responses will be in Korean when querying Korean content.

## Quick Start

1. **Read settings.json** to get the server address:
```bash
cat settings.json | jq '{server_host, server_port}'
```
The base URL is `http://{server_host}:{server_port}`.

2. **Check if the service is running**:
```bash
curl http://{host}:{port}/health
```
Expected response: `{"status":"ok"}`

3. **List available knowledge bases**:
```bash
curl http://{host}:{port}/stores
```

4. **Query the knowledge base**:
```bash
curl -X POST http://{host}:{port}/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "프로젝트의 주요 목표는 무엇인가요?",
    "model": "gemini-2.5-flash-lite"
  }'
```

## Available Endpoints

### GET /health
Health check to verify the service is running.

**Example**:
```bash
curl http://{host}:{port}/health
```

**Response**:
```json
{"status": "ok"}
```

### GET /stores
List all indexed Notion databases with their metadata.

**Example**:
```bash
curl http://{host}:{port}/stores
```

**Response**:
```json
{
  "stores": [
    {
      "name": "fileSearchStores/xxx",
      "display_name": "tech-notes",
      "documents": 5,
      "size_bytes": 12345
    }
  ]
}
```

The `display_name` is the registered database label. Use it as the `name` parameter in queries.

### POST /query
Perform a RAG query against a Notion database.

**Required fields**:
- `query` -- The question to ask. String.

**Optional fields**:
- `name` -- The registered database label. Auto-detected when only one database is registered. String.
- `model` -- Gemini model to use (default: "gemini-2.5-flash-lite"). String.

**Available models**:
- `gemini-2.5-flash-lite` -- Fastest and cheapest (recommended for most queries)
- `gemini-2.5-flash` -- Better quality, slightly slower
- `gemini-2.5-pro` -- Highest quality, slowest
- `gemini-3-flash-preview` -- Next-gen flash model (preview)
- `gemini-3-pro-preview` -- Next-gen pro model (preview)

**Example**:
```bash
curl -X POST http://{host}:{port}/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "이번 스프린트의 우선순위는?",
    "model": "gemini-2.5-flash-lite"
  }'
```

**Response**:
```json
{
  "answer": "이번 스프린트의 주요 우선순위는 다음과 같습니다:\n1. 사용자 인증 기능 구현\n2. 데이터베이스 마이그레이션 완료\n3. API 성능 최적화",
  "label": "tech-notes",
  "grounding": {
    "chunks": [
      {
        "chunk_index": 0,
        "score": 0.85,
        "content": "Sprint Planning 2024-Q1..."
      }
    ]
  },
  "usage": {
    "model": "gemini-2.5-flash-lite",
    "input_tokens": 1234,
    "output_tokens": 567,
    "cost": 0.00012345
  }
}
```

### POST /sync
Synchronize changes from Notion (incremental update).

Checks for updated pages and re-indexes only what changed. Use this for regular updates.

**Optional fields**:
- `name` -- The registered database label. Auto-detected when only one database is registered. String.
- `force` -- Force re-index all pages even if not modified (default: false). Boolean.

**Example**:
```bash
curl -X POST http://{host}:{port}/sync \
  -H "Content-Type: application/json" \
  -d '{"force": false}'
```

**Response**:
```json
{
  "db_id": "your_database_id_here",
  "pages_checked": 10,
  "pages_updated": 2,
  "pages_skipped": 8,
  "total_cost": 0.001
}
```

### POST /init
Initialize a new Notion database (full indexing).

Indexes all pages from a Notion database. Use this for the first-time setup or complete re-indexing.

**Optional fields**:
- `name` -- The database label. Auto-detected when only one database is registered. Required when providing `db_url`. String.
- `db_url` -- The full Notion database URL. String. Only needed for first-time registration.

**Example**:
```bash
curl -X POST http://{host}:{port}/init \
  -H "Content-Type: application/json" \
  -d '{
    "name": "tech-notes",
    "db_url": "https://www.notion.so/your_database_id_here?v=your_view_id_here"
  }'
```

**Response**:
```json
{
  "db_id": "your_database_id_here",
  "pages_total": 25,
  "pages_indexed": 25,
  "total_cost": 0.005
}
```

### GET /billing
Get Gemini API billing summary from logs.

**Query parameters**:
- `period` -- Aggregation period: `"total"` (default), `"daily"`, or `"monthly"`. String.

**Example**:
```bash
curl http://{host}:{port}/billing
curl http://{host}:{port}/billing?period=monthly
curl http://{host}:{port}/billing?period=daily
```

**Response**:
```json
{
  "total": {
    "embedding_cost": 0.00125,
    "vision_cost": 0.0003,
    "query_cost": 0.00045,
    "total_cost": 0.002
  },
  "breakdown": [
    {
      "period": "2026-02",
      "embedding_cost": 0.00125,
      "vision_cost": 0.0003,
      "query_cost": 0.00045,
      "total_cost": 0.002
    }
  ]
}
```

When `period` is `"total"`, the `breakdown` array is empty. Use `"daily"` or `"monthly"` for detailed breakdowns.

## Workflow Examples

### First-time setup for a new Notion database:
```bash
# 1. Check service is running
curl http://{host}:{port}/health

# 2. Initialize with label + URL
curl -X POST http://{host}:{port}/init \
  -H "Content-Type: application/json" \
  -d '{"name": "my-notes", "db_url": "https://www.notion.so/your-db-url"}'

# 3. Query using label
curl -X POST http://{host}:{port}/query \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-notes",
    "query": "프로젝트 개요를 알려주세요",
    "model": "gemini-2.5-flash-lite"
  }'
```

### Regular usage (after setup):
```bash
# 1. Check for updates (run periodically)
curl -X POST http://{host}:{port}/sync \
  -H "Content-Type: application/json" \
  -d '{"name": "my-notes"}'

# 2. Query whenever needed
curl -X POST http://{host}:{port}/query \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-notes",
    "query": "최신 회의록 요약해줘"
  }'
```

### When user doesn't know the label:
```bash
# List all indexed databases
curl http://{host}:{port}/stores

# The display_name IS the label — use it directly in queries
# If only one database is registered, the name parameter can be omitted
```

## Tips for Effective Queries

1. **Model selection**:
   - Default to `gemini-2.5-flash-lite` for speed and cost efficiency
   - Use `gemini-2.5-flash` for complex queries requiring better reasoning
   - Use `gemini-2.5-pro` only for critical queries needing highest accuracy

2. **Query formulation**:
   - Be specific: "3월 스프린트의 완료된 태스크는?" instead of "태스크 알려줘"
   - Ask for summaries when needed: "프로젝트 마일스톤을 요약해줘"
   - Use natural language - the model handles Korean well

3. **Performance**:
   - `/query` response time: 2-5 seconds (depends on model and result size)
   - `/sync` is incremental - much faster than `/init`
   - Run `/sync` before important queries if content was recently updated

## Error Handling

**Service not running**:
```bash
curl: (7) Failed to connect to {host} port {port}: Connection refused
```
→ Start the API server: `cd /path/to/Notion_To_VectorDB && uv run notion-rag serve`

**Invalid label**:
```json
{"detail": "Unknown database label 'xxx'. Available labels: tech-notes, ..."}
```
→ Run GET /stores to see available labels, or register a new database with POST /init

**Database not initialized**:
```json
{"detail": "Database not indexed. Run /init first"}
```
→ Run POST /init with the db_url before querying

**Rate limit or API error**:
```json
{"detail": "Gemini API error: ..."}
```
→ Check API quotas and retry after a short delay

## Implementation Notes for Claude Code

When a user asks to query their Notion knowledge base:

1. **Read settings.json first**: Read `settings.json` to get `server_host` and `server_port`. Construct the base URL as `http://{server_host}:{server_port}`
2. **Always check health first**: Run `GET /health` to ensure the service is available
3. **Auto-detect label**: If only one database is registered, the `name` parameter can be omitted. Otherwise call `GET /stores` to list available labels
4. **Use Bash tool with curl**: All API calls should use curl via the Bash tool
5. **Parse JSON responses**: Extract the `answer` field and display it clearly
6. **Show grounding when relevant**: For fact-checking or source verification, show the `grounding.chunks`
7. **Handle errors gracefully**: If the service is down, provide clear instructions on how to start it
8. **Cost awareness**: The `usage` field shows the cost - mention it if the user asks about costs
9. **Billing queries**: Use `GET /billing?period=monthly` to check cumulative API costs. Show the total and breakdown when users ask about spending

## Example Korean Queries

- "프로젝트의 현재 상태는?"
- "이번 주 완료된 작업을 요약해줘"
- "데이터베이스 스키마에 대해 알려줘"
- "버그 수정 관련 문서를 찾아줘"
- "API 인증 방법은 무엇인가요?"
- "팀 미팅 노트에서 액션 아이템 추출해줘"
