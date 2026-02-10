# Notion to VectorDB

Notion 데이터베이스를 VectorDB로 자동 인덱싱하고 Gemini File Search를 이용한 RAG 쿼리를 제공하는 서비스.

## 주요 기능

- **Notion DB 단위 인덱싱** - DB = Store, Page = Document 구조로 관리
- **라벨 기반 멀티 DB 지원** - 여러 Notion 데이터베이스를 라벨로 등록하고 관리
- **이미지 자동 분석** - Gemini Vision으로 이미지 설명 자동 생성 후 인덱싱
- **최근 변경 페이지 자동 동기화** - cronjob 지원으로 정기적 업데이트 가능
- **REST API 서버** - FastAPI 기반, OpenClaw 등 외부 시스템 연동
- **CLI 도구** - init, sync, query, serve, list, remove, cleanup, billing 커맨드 제공

## 환경 설정

### 요구 사항

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) (패키지 매니저)

### 설치

```bash
uv sync
```

### 환경 변수

`.env` 파일을 프로젝트 루트에 생성:

```bash
NOTION_TOKEN=your_notion_api_key
GEMINI_API_KEY=your_gemini_api_key
```

### settings.json

프로젝트 루트에 `settings.json` 파일을 수정하여 서비스 동작에 필요한 요소들을 커스터마이즈할 수 있습니다.

```json
{
  "databases": {
    "label": "notion_db_url"
  },
  "models": {
    "query": "gemini-2.5-flash-lite",
    "embedding": "gemini-embedding-001",
    "image_vision": "gemini-3-flash-preview"
  },
  "sync_days": 2,
  "index_wait_sec": 5,
  "server_host": "127.0.0.1",
  "server_port": 8000
}
```

**설정 항목:**

- `databases` (기본: `{}`) - 등록된 Notion 데이터베이스 매핑 (라벨 → URL). `init` 명령어로 자동 등록됨
- `models` - 사용할 모델 설정 그룹
  - `query` (기본: `"gemini-2.5-flash-lite"`) - RAG 쿼리에 사용할 기본 모델
  - `embedding` (기본: `"gemini-embedding-001"`) - 텍스트 임베딩 모델
  - `image_vision` (기본: `"gemini-3-flash-preview"`) - 이미지 분석에 사용할 Vision 모델
- `sync_days` (기본: `2`) - 동기화 시 검사할 최근 수정 일수
- `index_wait_sec` (기본: `5`) - 인덱싱 후 대기 시간 (초)
- `server_host` (기본: `"127.0.0.1"`) - API 서버 바인딩 호스트
- `server_port` (기본: `8000`) - API 서버 바인딩 포트


## 사용법

### 0. 설치

`notion_rag` 사용을 위해 아래와 같이 설치를 진행합니다.

```
uv sync
uv pip install -e .
```

### 1. 최초 인덱싱

`.env`파일과 `settings.json` 파일에 설정 값을 입력한 후 Notion 데이터베이스를 인덱싱합니다.

```bash
uv run notion-rag init
```

**예시: 수동 인덱싱**

인자를 통해 수동으로 특정 노션 DB에 대해 인덱싱을 진행할 수 있습니다.

```bash
uv run notion-rag init [라벨] [Notion DB URL]
```

**예시: 이미 등록된 DB 재인덱싱**

수동으로 재인덱싱 시에는 라벨만 지정해서 실행하면 됩니다.

```bash
uv run notion-rag init [라벨]
```

### 2. API 서버 실행

FastAPI 기반 REST API 서버를 실행합니다.

```bash
uv run notion-rag serve
```

**옵션:**
```bash
uv run notion-rag serve --host 127.0.0.1 --port 9000
```

서버 주소와 포트는 `settings.json`의 `server_host`, `server_port`로 설정됩니다 (기본: `127.0.0.1:8000`).

**백그라운드 실행 (nohup):**
```bash
nohup uv run notion-rag serve > /dev/null 2>&1 &
echo $!  # PID 확인
```

**백그라운드 서버 종료:**
```bash
kill $(lsof -t -i :8000)
```

**systemd 서비스 등록 (Ubuntu, 운영 권장):**

`/etc/systemd/system/notion-rag.service` 파일을 생성합니다:

```ini
[Unit]
Description=Notion RAG Service
After=network.target

[Service]
WorkingDirectory=/path/to/Notion_To_VectorDB
ExecStart=/usr/bin/env uv run notion-rag serve
Restart=on-failure
EnvironmentFile=/path/to/Notion_To_VectorDB/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable notion-rag   # 부팅 시 자동 시작
sudo systemctl start notion-rag    # 서비스 시작
sudo systemctl status notion-rag   # 상태 확인
sudo systemctl stop notion-rag     # 서비스 종료
```

### 3. 자동 동기화 (Cron Job)

Notion 데이터베이스의 변경사항을 매일 자동으로 벡터 스토어에 동기화합니다.

#### 방법 1: OpenClaw 크론잡 (권장)

OpenClaw 에이전트를 사용 중이라면 다음과 같이 크론잡을 등록할 수 있습니다:

```json
{
  "name": "Notion RAG 일일 동기화",
  "schedule": {
    "kind": "cron",
    "expr": "0 5 * * *",
    "tz": "Asia/Seoul"
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "Notion RAG 동기화를 수행하세요. 명령어: cd /path/to/notion-rag && set -a && source .env && set +a && uv run notion-rag sync"
  },
  "delivery": {
    "mode": "announce",
    "channel": "discord",
    "to": "channel:<CHANNEL_ID>"
  }
}
```

#### 방법 2: crontab

```bash
# 매일 05:00 KST 실행
0 5 * * * cd /path/to/notion-rag && set -a && source .env && set +a && /path/to/uv run notion-rag sync >> /var/log/notion-rag-sync.log 2>&1
```

### 4. CLI 쿼리

커맨드라인에서 직접 RAG 쿼리를 실행합니다.

```bash
notion-rag query [라벨] "질문"
```

**예시:**
```bash
notion-rag query tech-notes "프로젝트의 주요 목표는 무엇인가요?"
notion-rag query "프로젝트의 주요 목표는 무엇인가요?"  # DB가 1개만 등록된 경우 라벨 자동 감지
```

**모델 지정:**
```bash
notion-rag query tech-notes "질문" --model gemini-2.5-pro
notion-rag query "질문" --model gemini-2.5-pro  # 라벨 생략 가능
```

### 5. Store 관리

**모든 Store 목록 조회:**
```bash
notion-rag list
```

**특정 DB의 Document 목록 조회:**
```bash
notion-rag list <라벨>
```

**예시:**
```bash
notion-rag list tech-notes
```

**특정 Document 삭제:**
```bash
notion-rag remove [라벨] <page_id>
```

**예시:**
```bash
notion-rag remove tech-notes b6f58467
notion-rag remove b6f58467  # DB가 1개만 등록된 경우 라벨 자동 감지
```

**Store 전체 삭제 (모든 Document 포함):**
```bash
notion-rag cleanup [라벨]
```

**예시:**
```bash
notion-rag cleanup tech-notes
notion-rag cleanup  # DB가 1개만 등록된 경우 라벨 자동 감지
```

### 6. 비용 조회

Gemini API 사용 비용을 로그 기반으로 조회합니다.

```bash
notion-rag billing
```

**월별 비용 조회:**
```bash
notion-rag billing --monthly
```

**일별 비용 조회:**
```bash
notion-rag billing --daily
```

**출력 예시:**
```
-- Billing Summary --
  Embedding cost:  $0.00125000
  Vision cost:     $0.00030000
  Query cost:      $0.00045000
  Total cost:      $0.00200000

-- Breakdown (monthly) --

  2026-02
    Embedding: $0.00125000
    Vision:    $0.00030000
    Query:     $0.00045000
    Total:     $0.00200000
```

## API 엔드포인트

> 서버 주소는 `settings.json`의 `server_host`:`server_port`를 참조합니다 (기본: `127.0.0.1:8000`).
> 아래 예시에서 `{host}:{port}`는 해당 값으로 대체하세요.

### GET /health

서버 상태 확인.

**요청:**
```bash
curl http://{host}:{port}/health
```

**응답:**
```json
{
  "status": "ok"
}
```

### GET /stores

인덱싱된 모든 Notion 데이터베이스 Store 목록 조회.

**요청:**
```bash
curl http://{host}:{port}/stores
```

**응답:**
```json
{
  "stores": [
    {
      "name": "fileSearchStores/abc123",
      "display_name": "tech-notes",
      "documents": 25,
      "size_bytes": 524288
    }
  ]
}
```

### POST /query

RAG 쿼리 실행.

**요청:**
```bash
curl -X POST http://{host}:{port}/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "이번 스프린트의 우선순위는?",
    "model": "gemini-2.5-flash-lite"
  }'
```

**필수 필드:**
- `query` - 질문 텍스트

**선택 필드:**
- `name` - 데이터베이스 라벨 (DB 1개일 때 자동 감지)
- `model` - 사용할 모델 (기본: `gemini-2.5-flash-lite`)

**응답:**
```json
{
  "answer": "이번 스프린트의 주요 우선순위는 다음과 같습니다:\n1. 사용자 인증 기능 구현\n2. 데이터베이스 마이그레이션 완료\n3. API 성능 최적화",
  "grounding": {
    "metadata": "..."
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

Notion 데이터베이스 동기화 (변경된 페이지만 재인덱싱).

**요청:**
```bash
curl -X POST http://{host}:{port}/sync \
  -H "Content-Type: application/json" \
  -d '{"force": false}'
```

**선택 필드:**
- `name` - 데이터베이스 라벨 (DB 1개일 때 자동 감지)
- `force` - 전체 강제 재인덱싱 여부 (기본: `false`)

**응답:**
```json
{
  "label": "tech-notes",
  "db_id": "title-abc123def456...",
  "pages_checked": 10,
  "pages_updated": 2,
  "pages_skipped": 8,
  "indexing_cost": 0.00001500,
  "image_cost": 0.00000500,
  "total_cost": 0.00002000
}
```

### POST /init

새 Notion 데이터베이스 초기화 (전체 인덱싱).

**요청:**
```bash
curl -X POST http://{host}:{port}/init \
  -H "Content-Type: application/json" \
  -d '{
    "name": "tech-notes",
    "db_url": "https://www.notion.so/title-abc123def456..."
  }'
```

**선택 필드:**
- `name` - 데이터베이스 라벨 (DB 1개일 때 자동 감지)
- `db_url` - Notion 데이터베이스 URL (이미 등록된 경우 생략 가능)

**응답:**
```json
{
  "label": "tech-notes",
  "db_id": "title-abc123def456...",
  "store_name": "tech-notes",
  "pages_total": 25,
  "pages_indexed": 25,
  "indexing_cost": 0.00012500,
  "image_cost": 0.00003000,
  "total_cost": 0.00015500
}
```

### GET /billing

Gemini API 사용 비용 조회.

**요청:**
```bash
curl http://{host}:{port}/billing
curl http://{host}:{port}/billing?period=monthly
curl http://{host}:{port}/billing?period=daily
```

**쿼리 파라미터:**
- `period` - 집계 기간: `"total"` (기본), `"daily"`, `"monthly"`

**응답:**
```json
{
  "total": {
    "embedding_cost": 0.00125000,
    "vision_cost": 0.00030000,
    "query_cost": 0.00045000,
    "total_cost": 0.00200000
  },
  "breakdown": [
    {
      "period": "2026-02",
      "embedding_cost": 0.00125000,
      "vision_cost": 0.00030000,
      "query_cost": 0.00045000,
      "total_cost": 0.00200000
    }
  ]
}
```

## OpenClaw 연동

OpenClaw에서 Notion RAG 스킬을 사용하여 Notion 지식베이스를 쿼리할 수 있습니다.

### 설치

```bash
./openclaw-skills-install.sh
```

스킬이 `~/.openclaw/workspace/skills/notion-rag-query/SKILL.md`에 설치됩니다.

### 사용법

1. **API 서버 실행:**
```bash
notion-rag serve
```

2. **트리거 키워드로 질문:**
"Notion에서 찾아줘" 키워드가 포함된 질문을 하면 자동으로 스킬이 트리거됩니다.

**예시:**
```
사용자: Notion에서 찾아줘 - [질문]
Claude: [API 서버 쿼리 후 답변 제공]
```

## 비용

### 인덱싱 비용

| 항목 | 모델 | 가격 (per 1M tokens) |
|------|------|---------------------|
| 텍스트 인덱싱 | gemini-embedding-001 | $0.15 input |
| 이미지 분석 | gemini-3-flash-preview | $0.15 input / $0.60 output |
| 토큰 카운트 | - | 무료 |
| Store 저장 | - | 무료 (Free tier 1GB) |

### 쿼리 비용

| 모델 | Input (per 1M tokens) | Output (per 1M tokens) |
|------|----------------------|------------------------|
| gemini-2.5-flash-lite | $0.10 | $0.40 |
| gemini-2.5-flash | $0.15 | $0.60 |
| gemini-2.5-pro | $1.25 | $10.00 |
| gemini-3-flash-preview | $0.15 | $0.60 |
| gemini-3-pro-preview | $2.00 | $12.00 |

**참고:**
- 일반적인 페이지 (2,000 토큰)의 인덱싱 비용: ~$0.0003
- 일반적인 쿼리 (3,000 토큰 입력, 500 토큰 출력)의 비용 (flash-lite): ~$0.0005
- 100페이지 DB 인덱싱 비용: ~$0.03
- Store 내 데이터는 수동 삭제 전까지 영구 보존 (추가 저장 비용 없음)

## 로그

운영 로그는 `logs/` 디렉토리에 날짜별로 정리됩니다.

```
logs/
└── 2026-02-11/
    ├── audit/
    │   └── api.jsonl          # API 요청 로그
    └── gemini/
        ├── indexing.jsonl     # 페이지 인덱싱 (임베딩 + 비전 비용)
        ├── query.jsonl        # RAG 쿼리 비용
        ├── sync.jsonl         # 동기화 요약
        └── init.jsonl         # 초기화 요약
```

**로그 형식:** JSONL (JSON Lines) - 각 줄이 하나의 JSON 객체

**예시 (query.jsonl):**
```json
{"label": "tech-notes", "query": "프로젝트 목표는?", "model": "gemini-2.5-flash-lite", "input_tokens": 1234, "output_tokens": 567, "cost": 0.00035, "total_cost": 0.00035, "elapsed": 2.1, "source": "api", "timestamp": "2026-02-11T03:45:00+00:00"}
```

로그 디렉토리는 자동 생성되며, `.gitignore`에 의해 버전 관리에서 제외됩니다.

## 참고 문서

- [Gemini API Documentation](https://ai.google.dev/gemini-api/docs)
- [Gemini File Search Docs](https://ai.google.dev/gemini-api/docs/file-search)
- [Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Notion API Documentation](https://developers.notion.com/)
- [File Search Stores API](https://ai.google.dev/api/file-search/file-search-stores)
- [Documents API](https://ai.google.dev/api/file-search/documents)

## 레거시 테스트 스크립트

`test-scripts/` 디렉토리에는 개발 과정에서 사용된 테스트 스크립트들이 참고용으로 보관되어 있습니다:

- `test.py` - Notion 콘텐츠 추출 및 토큰 카운트 테스트
- `test_embedding.py` - 임베딩 벡터 생성 테스트
- `test_file_search.py` - File Search RAG 프로토타입
- `test_file_search_with_image.py` - 이미지 포함 File Search 테스트

실제 운영에는 `notion_rag` 패키지의 CLI 및 API 서버를 사용하세요.
