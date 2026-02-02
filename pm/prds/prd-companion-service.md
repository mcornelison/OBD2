# PRD: Chi-Srv-01 Companion Service (eclipse-ai-server)

**Parent Backlog Item**: B-022
**Status**: Active
**Target Repo**: `eclipse-ai-server` (separate GitHub repo)

## Introduction

The Eclipse AI Server is a FastAPI companion service running on Chi-Srv-01 (10.27.27.100, Debian/Ubuntu Server) that provides three core capabilities for the EclipseTuner Pi 5:

1. **AI Analysis** -- Host Ollama with GPU acceleration, expose analysis endpoints, auto-analyze incoming drive data
2. **Delta Sync Receiver** -- Accept push-based delta data from EclipseTuner, store in MySQL with server-side metadata
3. **Backup Receiver** -- Accept database and log file uploads, store with timestamps and rotation

The service runs as a systemd unit, auto-starts on boot, and communicates with EclipseTuner via HTTP with API key authentication.

**Key constraint**: This PRD covers the **server-side** only. Client-side sync changes to the EclipseTuner repo are tracked in B-027.

## Architecture

```
EclipseTuner (10.27.27.28)            Chi-Srv-01 (10.27.27.100)
┌────────────────────────┐              ┌─────────────────────────────────┐
│  Eclipse OBD-II App    │  WiFi/LAN   │  eclipse-ai-server              │
│                        │ ──────────> │                                  │
│  Post-drive triggers:  │  HTTP POST  │  FastAPI (async)                │
│  1. Delta sync         │  + API key  │  ├── POST /api/v1/sync          │
│  2. Request AI         │             │  ├── POST /api/v1/analyze       │
│  3. Push backup        │ <────────── │  ├── POST /api/v1/backup        │
│                        │  JSON resp  │  ├── GET  /api/v1/health        │
│                        │             │  │                               │
│  Trigger: connect to   │             │  Dependencies:                   │
│  DeathStarWiFi         │             │  ├── MySQL 8.x (mirrored schema)│
│  (B-023 handles)       │             │  ├── Ollama (GPU-accelerated)   │
└────────────────────────┘              │  └── systemd (auto-start)       │
                                        └─────────────────────────────────┘
                                                    │
                                          Chi-NAS-01 (10.27.27.121)
                                          (future: NAS replication)
```

## Goals

- Stand up a production-ready FastAPI service on Chi-Srv-01
- Accept delta-synced OBD-II data from EclipseTuner and store in MySQL
- Provide on-demand and auto-triggered AI analysis via local Ollama
- Accept and store backup files with rotation
- Expose health endpoint for monitoring
- Document setup for CIO to deploy on Chi-Srv-01

## Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Framework | FastAPI 0.100+ | Async HTTP API with auto OpenAPI docs |
| Database | MySQL 8.x | Persistent storage, mirrored Pi schema |
| ORM/Driver | SQLAlchemy 2.x + aiomysql | Async MySQL access |
| AI | Ollama (local on Chi-Srv-01) | GPU-accelerated LLM inference |
| Auth | API key (header) | Simple shared-secret authentication |
| Process | uvicorn | ASGI server |
| Service | systemd | Auto-start, restart on failure |
| Testing | pytest + httpx | Async test client for FastAPI |
| Python | 3.11+ | Match EclipseTuner version |

## API Contract (v1)

All endpoints prefixed with `/api/v1/`. API key sent as `X-API-Key` header.

### POST /api/v1/sync

Accept delta data from EclipseTuner. Upserts into MySQL.

**Request:**
```json
{
    "deviceId": "chi-eclipse-tuner",
    "batchId": "sync-2026-02-01T14:30:00",
    "tables": {
        "realtime_data": {
            "lastSyncedId": 3965,
            "rows": [
                {
                    "id": 3966,
                    "timestamp": "2026-02-01T14:25:00",
                    "parameter_name": "RPM",
                    "value": 2500.0,
                    "unit": "rpm",
                    "profile_id": 1
                }
            ]
        },
        "statistics": {
            "lastSyncedId": 78,
            "rows": []
        }
    }
}
```

**Response (200):**
```json
{
    "status": "ok",
    "batchId": "sync-2026-02-01T14:30:00",
    "tablesProcessed": {
        "realtime_data": {"inserted": 500, "updated": 0, "errors": 0},
        "statistics": {"inserted": 0, "updated": 0, "errors": 0}
    },
    "syncedAt": "2026-02-01T14:30:05",
    "driveDataReceived": true
}
```

**Error (401):** Invalid or missing API key
**Error (422):** Validation error (missing fields, bad types)
**Error (500):** Server error (MySQL down, etc.)

### POST /api/v1/analyze

Trigger AI analysis on drive data. Can be called explicitly or auto-triggered by /sync when new drive data arrives.

**Request:**
```json
{
    "profileId": 1,
    "driveStartTime": "2026-02-01T14:00:00",
    "driveEndTime": "2026-02-01T14:25:00",
    "parameters": ["RPM", "COOLANT_TEMP", "THROTTLE_POS", "INTAKE_TEMP", "SPEED"],
    "focusAreas": ["air_fuel_ratio", "timing", "throttle_response"]
}
```

**Response (200):**
```json
{
    "status": "ok",
    "analysisId": "analysis-2026-02-01T14:30:10",
    "recommendations": [
        {
            "rank": 1,
            "category": "air_fuel_ratio",
            "recommendation": "Air-fuel ratio trending lean at high RPM...",
            "confidence": 0.85
        }
    ],
    "model": "gemma2:2b",
    "processingTimeMs": 4500
}
```

**Error (503):** Ollama unavailable or model not loaded

### POST /api/v1/backup

Accept file uploads (SQLite DB, log files).

**Request:** `multipart/form-data`
- `file`: The file to upload
- `type`: One of `database`, `logs`, `config`
- `deviceId`: Source device identifier

**Response (200):**
```json
{
    "status": "ok",
    "filename": "obd-2026-02-01T14-30-00.db",
    "storedAt": "/data/backups/chi-eclipse-tuner/database/obd-2026-02-01T14-30-00.db",
    "sizeBytes": 524288
}
```

### GET /api/v1/health

No auth required. Returns service status.

**Response (200):**
```json
{
    "status": "healthy",
    "version": "1.0.0",
    "components": {
        "api": "up",
        "mysql": "up",
        "ollama": "up",
        "ollamaModel": "gemma2:2b"
    },
    "lastSync": {
        "deviceId": "chi-eclipse-tuner",
        "syncedAt": "2026-02-01T14:30:05",
        "batchId": "sync-2026-02-01T14:30:00"
    },
    "uptime": "2d 4h 30m"
}
```

## MySQL Schema

Mirror Pi SQLite tables with server-only additions. Same table names, column names, and types where possible.

### Synced Tables

| Table | Pi Source | Server Additions |
|-------|-----------|-----------------|
| `realtime_data` | Full mirror | `synced_at`, `source_device`, `sync_batch_id` |
| `statistics` | Full mirror | `synced_at`, `source_device`, `sync_batch_id` |
| `profiles` | Full mirror | `synced_at`, `source_device` |
| `vehicle_info` | Full mirror | `synced_at`, `source_device` |
| `ai_recommendations` | Full mirror | `synced_at`, `source_device`, `sync_batch_id` |
| `connection_log` | Full mirror | `synced_at`, `source_device`, `sync_batch_id` |
| `alert_log` | Full mirror | `synced_at`, `source_device`, `sync_batch_id` |
| `calibration_sessions` | Full mirror | `synced_at`, `source_device` |

### Server-Only Tables

| Table | Purpose |
|-------|---------|
| `sync_history` | Log of all sync batches (batch_id, device_id, started_at, completed_at, tables_synced, rows_total, status) |
| `analysis_history` | Log of all AI analysis runs (analysis_id, profile_id, drive_start, drive_end, model, processing_time_ms, status) |
| `devices` | Registered devices (device_id, display_name, last_seen, api_key_hash) |

### NOT Synced (Pi-only)

- `battery_log` -- UPS hardware telemetry
- `power_log` -- AC/battery power transitions

## Project Structure (eclipse-ai-server repo)

```
eclipse-ai-server/
├── README.md
├── pyproject.toml
├── requirements.txt
├── .env.example
├── .gitignore
├── alembic.ini                 # DB migrations
├── alembic/
│   └── versions/               # Migration scripts
├── src/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Settings (pydantic-settings)
│   ├── auth.py                 # API key middleware
│   ├── models/                 # SQLAlchemy models
│   │   ├── __init__.py
│   │   ├── realtime_data.py
│   │   ├── statistics.py
│   │   ├── profiles.py
│   │   ├── vehicle_info.py
│   │   ├── sync_history.py
│   │   └── ...
│   ├── routers/                # FastAPI route handlers
│   │   ├── __init__.py
│   │   ├── sync.py             # POST /sync
│   │   ├── analyze.py          # POST /analyze
│   │   ├── backup.py           # POST /backup
│   │   └── health.py           # GET /health
│   ├── services/               # Business logic
│   │   ├── __init__.py
│   │   ├── sync_service.py     # Delta sync processing
│   │   ├── analysis_service.py # Ollama interaction
│   │   ├── backup_service.py   # File storage
│   │   └── ollama_client.py    # Ollama HTTP client
│   └── database/               # DB connection, session
│       ├── __init__.py
│       ├── connection.py
│       └── migrations.py
├── tests/
│   ├── conftest.py
│   ├── test_sync.py
│   ├── test_analyze.py
│   ├── test_backup.py
│   ├── test_health.py
│   └── test_auth.py
├── deploy/
│   ├── eclipse-ai-server.service   # systemd unit
│   ├── install-service.sh
│   └── setup-mysql.sh              # MySQL DB creation script
├── docs/
│   ├── setup-guide.md              # Full setup instructions
│   └── api-reference.md            # Auto-generated from OpenAPI
└── scripts/
    ├── init_db.py                  # Create MySQL schema
    └── seed_db.py                  # Optional test data
```

## Testing Strategy

All tests use a **real MySQL test database** (`eclipse_ai_test`). No SQLite substitutes. This ensures MySQL-specific behavior (upsert syntax, FK enforcement, type handling) is validated.

**Test database setup**: `deploy/setup-mysql.sh` creates both `eclipse_ai` (production) and `eclipse_ai_test` (testing) databases. Tests use the test database via `DATABASE_URL` override in `conftest.py`.

**Test fixtures** (`tests/conftest.py`):
- `db_session`: Async SQLAlchemy session connected to test MySQL, with table truncation between tests
- `client`: httpx `AsyncClient` with TestApp, API key pre-configured
- `sample_sync_payload`: Valid sync request body with realistic OBD-II data
- `sample_realtime_rows`: 13 parameter readings matching Pi's simulated output
- `mock_ollama`: httpx mock for Ollama `/api/chat` endpoint returning canned recommendations

## ID Mapping Strategy

Pi rows have SQLite autoincrement IDs. MySQL uses its own autoincrement PK. Mapping:

| MySQL Column | Purpose |
|-------------|---------|
| `id` (PK) | MySQL autoincrement, server-owned |
| `source_id` | Original Pi row ID (INTEGER, NOT NULL) |
| `source_device` | Device identifier (VARCHAR, e.g., "chi-eclipse-tuner") |

**Upsert key**: `UNIQUE(source_device, source_id)` per table. This supports multi-device sync from day one and prevents ID collisions.

## User Stories

### US-CMP-001: Project Scaffolding and Configuration

**Description:** As a developer, I need the eclipse-ai-server project scaffolded with FastAPI, configuration, and dependency management so all subsequent stories have a foundation to build on.

**Acceptance Criteria:**

Implementation:
- [ ] GitHub repo `eclipse-ai-server` created with README, .gitignore, pyproject.toml
- [ ] FastAPI app skeleton in `src/main.py` with lifespan handler (startup: verify MySQL connection, log config; shutdown: close DB pool)
- [ ] Pydantic Settings config (`src/config.py`) reading from `.env`: DATABASE_URL, OLLAMA_BASE_URL, OLLAMA_MODEL, API_KEY, BACKUP_DIR, PORT, LOG_LEVEL, MAX_BACKUP_SIZE_MB, BACKUP_RETENTION_COUNT
- [ ] `.env.example` with all config variables and descriptions
- [ ] `requirements.txt` with: fastapi, uvicorn, sqlalchemy, aiomysql, pydantic-settings, python-multipart, httpx, alembic, pytest, pytest-asyncio
- [ ] `GET /api/v1/health` returns `{"status": "healthy", "version": "1.0.0"}`
- [ ] App starts with `uvicorn src.main:app --host 0.0.0.0 --port 8000`
- [ ] Tests run with `pytest tests/` against MySQL test database

Tests (all automated):
- [ ] Test: health endpoint returns 200 with `status: "healthy"` and `version: "1.0.0"`
- [ ] Test: config loads all expected variables from `.env`
- [ ] Test: config raises error on startup if DATABASE_URL is missing (fail fast)
- [ ] Test: config raises error on startup if API_KEY is missing (fail fast)
- [ ] Test: config uses defaults for optional variables (PORT=8000, LOG_LEVEL=INFO, MAX_BACKUP_SIZE_MB=100, BACKUP_RETENTION_COUNT=30)

### US-CMP-002: API Key Authentication Middleware

**Description:** As a developer, I need API key authentication on all endpoints (except /health) so only authorized devices can push data.

**Acceptance Criteria:**

Implementation:
- [ ] `src/auth.py` implements FastAPI dependency that extracts `X-API-Key` header
- [ ] API key compared against `API_KEY` from config using `hmac.compare_digest()` (constant-time comparison, prevents timing attacks)
- [ ] Missing key returns 401 with `{"detail": "Missing API key"}`
- [ ] Invalid key returns 401 with `{"detail": "Invalid API key"}`
- [ ] `/api/v1/health` is exempt from auth (no dependency)
- [ ] All other endpoints (`/sync`, `/analyze`, `/backup`) require auth dependency

Tests (all automated):
- [ ] Test: POST /sync without `X-API-Key` header returns 401 with body `{"detail": "Missing API key"}`
- [ ] Test: POST /sync with wrong key `"bad-key-123"` returns 401 with body `{"detail": "Invalid API key"}`
- [ ] Test: POST /sync with correct key returns non-401 (200 or 422 depending on body)
- [ ] Test: GET /health without any key returns 200
- [ ] Test: POST /analyze without key returns 401
- [ ] Test: POST /backup without key returns 401

### US-CMP-003: MySQL Database Schema and Connection

**Description:** As a developer, I need the MySQL database schema mirroring the Pi's SQLite tables plus server-only columns and tables.

**Acceptance Criteria:**

Implementation:
- [ ] SQLAlchemy models for all 8 synced tables: `realtime_data`, `statistics`, `profiles`, `vehicle_info`, `ai_recommendations`, `connection_log`, `alert_log`, `calibration_sessions`
- [ ] Each synced table has: `id` (MySQL autoincrement PK), `source_id` (INT NOT NULL, original Pi row ID), `source_device` (VARCHAR(64) NOT NULL), `synced_at` (DATETIME NOT NULL, server-set), `sync_batch_id` (VARCHAR(64), nullable)
- [ ] Each synced table has `UNIQUE(source_device, source_id)` constraint for upsert key
- [ ] Synced table columns mirror Pi SQLite columns exactly (same names, compatible types): see `specs/architecture.md` Section 5 for full column list per table
- [ ] FK constraints on MySQL mirror Pi schema: `realtime_data.profile_id` → `profiles`, `statistics.profile_id` → `profiles`, etc. FK references use MySQL `id` column (not `source_id`)
- [ ] Server-only tables: `sync_history` (batch_id VARCHAR PK, device_id, started_at, completed_at, tables_synced JSON, rows_inserted INT, rows_updated INT, status ENUM('success','failed','partial')), `analysis_history` (analysis_id VARCHAR PK, profile_source_id, drive_start, drive_end, model, processing_time_ms, status, created_at), `devices` (device_id VARCHAR PK, display_name, last_seen, api_key_hash, created_at)
- [ ] `deploy/setup-mysql.sh` creates `eclipse_ai` database, `eclipse_ai_test` database, and service user with grants
- [ ] `scripts/init_db.py` creates all tables idempotent (safe to run repeatedly)
- [ ] Alembic configured with initial migration matching the schema above
- [ ] Async database session factory via SQLAlchemy 2.x + aiomysql

Tests (all automated, against real MySQL test database):
- [ ] Test: `init_db.py` creates all 11 tables (8 synced + 3 server-only). **DB validation**: query `SHOW TABLES` and assert all 11 table names present.
- [ ] Test: `realtime_data` table has columns: id, source_id, source_device, synced_at, sync_batch_id, timestamp, parameter_name, value, unit, profile_id. **DB validation**: query `DESCRIBE realtime_data` and assert column names and types.
- [ ] Test: `UNIQUE(source_device, source_id)` constraint on realtime_data. **DB validation**: insert row with (source_device='test', source_id=1), insert duplicate → expect IntegrityError.
- [ ] Test: FK constraint on realtime_data.profile_id. **DB validation**: insert realtime_data row referencing non-existent profile_id → expect IntegrityError.
- [ ] Test: `sync_history` accepts insert with all fields. **DB validation**: insert row, SELECT it back, verify all fields match.
- [ ] Test: `init_db.py` is idempotent -- run twice, second run does not error and tables still have correct structure.

### US-CMP-004: Delta Sync Endpoint

**Description:** As a developer, I need the POST /sync endpoint that accepts delta data from EclipseTuner and upserts into MySQL.

**Accepted table names**: `realtime_data`, `statistics`, `profiles`, `vehicle_info`, `ai_recommendations`, `connection_log`, `alert_log`, `calibration_sessions`. Any other table name is rejected with 422.

**Acceptance Criteria:**

Implementation:
- [ ] `POST /api/v1/sync` accepts JSON body: `{deviceId: str, batchId: str, tables: {tableName: {lastSyncedId: int, rows: [...]}}}`
- [ ] Pydantic request model validates: deviceId required (non-empty string), batchId required (non-empty string), tables required (dict), each table name must be in the allowed list, rows must be a list of dicts
- [ ] Invalid request body returns 422 with Pydantic validation details
- [ ] For each table: upserts rows using `INSERT ... ON DUPLICATE KEY UPDATE` with upsert key `(source_device, source_id)`. Pi's `id` field maps to `source_id`. MySQL generates its own `id`.
- [ ] Server sets `synced_at=NOW()`, `source_device=request.deviceId`, `sync_batch_id=request.batchId` on each row
- [ ] All table upserts run in a single MySQL transaction. On any error: entire batch rolls back, nothing persisted.
- [ ] Creates `sync_history` record: batch_id, device_id, started_at, completed_at, tables_synced (JSON list), rows_inserted, rows_updated, status
- [ ] Returns sync receipt: `{status, batchId, tablesProcessed: {table: {inserted, updated, errors}}, syncedAt, driveDataReceived}`
- [ ] `driveDataReceived` is `true` if `connection_log` rows in this batch contain `event_type='drive_end'`
- [ ] Max payload size: 10MB (configurable via `MAX_SYNC_PAYLOAD_MB`). Returns 413 if exceeded.
- [ ] On MySQL error: returns 500 with `{"detail": "Sync failed", "batchId": "..."}`, sync_history status='failed'

Tests (all automated, against real MySQL test database):

Input/output tests:
- [ ] Test: sync 5 realtime_data rows → response 200, `tablesProcessed.realtime_data.inserted=5`. **DB validation**: `SELECT COUNT(*) FROM realtime_data WHERE sync_batch_id='test-batch'` returns 5. `SELECT source_id, parameter_name, value FROM realtime_data WHERE sync_batch_id='test-batch'` matches input rows.
- [ ] Test: sync empty tables `{tables: {realtime_data: {lastSyncedId: 0, rows: []}}}` → response 200, `inserted=0, updated=0`.
- [ ] Test: sync with table name `"fake_table"` → response 422 with validation error mentioning allowed tables.
- [ ] Test: sync same batchId twice with same rows → second call returns 200, `updated=5, inserted=0` (idempotent). **DB validation**: row count unchanged.
- [ ] Test: sync with missing `deviceId` field → response 422.
- [ ] Test: sync with missing `batchId` field → response 422.
- [ ] Test: sync with `connection_log` containing `event_type='drive_end'` → response has `driveDataReceived: true`.
- [ ] Test: sync with `connection_log` containing only `event_type='drive_start'` → response has `driveDataReceived: false`.
- [ ] Test: sync_history record created. **DB validation**: `SELECT * FROM sync_history WHERE batch_id='test-batch'` returns 1 row with correct device_id, status='success', rows_inserted matching.

Transaction safety:
- [ ] Test: sync with one valid table and one table containing a row that violates a constraint → entire batch rolled back, no rows persisted in any table. **DB validation**: `SELECT COUNT(*) FROM realtime_data WHERE sync_batch_id='bad-batch'` returns 0. sync_history status='failed'.

### US-CMP-005: AI Analysis Endpoint

**Description:** As a developer, I need the POST /analyze endpoint that triggers Ollama AI analysis on drive data stored in MySQL.

**Ollama integration**: Uses `/api/chat` endpoint (conversational). Server owns prompt templates in `src/services/prompts/`. Format: system message with vehicle context + user message with drive data summary.

**Acceptance Criteria:**

Implementation:
- [ ] `POST /api/v1/analyze` accepts JSON body: `{profileId: int, driveStartTime: ISO8601, driveEndTime: ISO8601, parameters: [str], focusAreas: [str]}`
- [ ] Queries MySQL: `SELECT parameter_name, timestamp, value, unit FROM realtime_data WHERE source_id IN (SELECT source_id FROM connection_log WHERE ...) AND timestamp BETWEEN driveStartTime AND driveEndTime AND parameter_name IN (parameters)`
- [ ] If zero rows returned: returns 200 with `{status: "ok", recommendations: [], message: "No drive data found for the specified time window"}`
- [ ] Prompt template in `src/services/prompts/drive_analysis.py`: system message describes the vehicle and tuning context; user message contains parameter statistics (min, max, avg, count per parameter) and focus areas
- [ ] Sends to Ollama via `httpx.AsyncClient` POST to `{OLLAMA_BASE_URL}/api/chat` with `{model: OLLAMA_MODEL, messages: [...], stream: false}`
- [ ] Analysis timeout: 120 seconds (configurable via `ANALYSIS_TIMEOUT_SECONDS`). Returns 504 if exceeded.
- [ ] Parses Ollama response `message.content` into ranked recommendations. Each recommendation has: rank (int), category (str), recommendation (str), confidence (float 0-1)
- [ ] Stores each recommendation in `ai_recommendations` table with: source_device, analysis metadata, synced_at=NOW()
- [ ] Creates `analysis_history` record with: analysis_id, profile_source_id, drive_start, drive_end, model, processing_time_ms, status='success'
- [ ] Returns: `{status, analysisId, recommendations: [...], model, processingTimeMs}`
- [ ] If Ollama unreachable (connection refused / timeout on health check): returns 503 with `{"detail": "Ollama unavailable", "ollamaUrl": "...", "model": "..."}`
- [ ] If Ollama returns error (model not found, generation error): returns 502 with `{"detail": "Ollama error", "ollamaError": "..."}`

Tests (all automated, against real MySQL test database):

Input/output tests:
- [ ] Test: seed MySQL with 50 realtime_data rows for RPM, SPEED, COOLANT_TEMP across a 10-minute window. Call /analyze with matching time window and mocked Ollama returning 3 recommendations. **Response validation**: status=200, 3 recommendations returned with rank, category, recommendation, confidence fields. **DB validation**: `SELECT COUNT(*) FROM ai_recommendations WHERE sync_batch_id LIKE 'analysis-%'` returns 3. `SELECT * FROM analysis_history WHERE analysis_id=response.analysisId` returns 1 row with status='success' and processing_time_ms > 0.
- [ ] Test: call /analyze with time window that has no data → response 200, `recommendations: []`, `message: "No drive data found..."`. **DB validation**: no new rows in ai_recommendations.
- [ ] Test: call /analyze with mocked Ollama returning connection error → response 503 with detail containing "unavailable".
- [ ] Test: call /analyze with mocked Ollama returning HTTP 500 → response 502 with detail containing "Ollama error".
- [ ] Test: call /analyze with mocked Ollama that takes >120s → response 504 (timeout). **DB validation**: analysis_history status='failed'.

### US-CMP-006: Auto-Analysis on Drive Data Receipt

**Description:** As a developer, I need the sync endpoint to automatically trigger AI analysis when it detects that a completed drive's data was synced.

**Acceptance Criteria:**

Implementation:
- [ ] After /sync inserts data and detects `driveDataReceived=true`, enqueues an async analysis task via `asyncio.create_task()` (does not block sync response)
- [ ] Auto-analysis extracts drive boundaries from the synced `connection_log` rows: finds the most recent `drive_start` and `drive_end` event pair for this batch
- [ ] If `connection_log` was not included in the sync batch but `driveDataReceived` was inferred from other signals: skip auto-analysis, log warning "Cannot determine drive boundaries without connection_log"
- [ ] Async task calls the same analysis logic as /analyze endpoint (shared service function)
- [ ] Sync response includes `"autoAnalysisTriggered": true` when task was enqueued
- [ ] If Ollama is unavailable: auto-analysis logs WARNING "Auto-analysis skipped: Ollama unavailable", sync response still 200 with `autoAnalysisTriggered: false`
- [ ] If auto-analysis fails for any reason: error logged at ERROR level, no effect on sync success

Tests (all automated, against real MySQL test database):
- [ ] Test: sync payload includes `connection_log` with `drive_start` and `drive_end` events + `realtime_data` rows → response has `autoAnalysisTriggered: true`. **DB validation** (after brief async wait): `analysis_history` has a new row for this drive window. `ai_recommendations` has new rows (with mocked Ollama).
- [ ] Test: sync payload with only `realtime_data` (no `connection_log`) → response has `autoAnalysisTriggered: false`. **DB validation**: no new `analysis_history` rows.
- [ ] Test: sync payload with `connection_log` containing only `drive_start` (no `drive_end`) → response has `driveDataReceived: false`, `autoAnalysisTriggered: false`.
- [ ] Test: sync with drive_end but Ollama mocked as unavailable → response 200 (sync succeeds), `autoAnalysisTriggered: false`. **DB validation**: sync_history status='success', no analysis_history row.
- [ ] Test: sync with drive_end, Ollama mocked to raise exception during generation → sync response still 200. **DB validation**: analysis_history row with status='failed'.

### US-CMP-007: Backup Receiver Endpoint

**Description:** As a developer, I need the POST /backup endpoint that accepts file uploads from EclipseTuner and stores them with timestamps.

**Allowed file extensions**: `.db`, `.log`, `.json`, `.gz`

**Acceptance Criteria:**

Implementation:
- [ ] `POST /api/v1/backup` accepts `multipart/form-data` with fields: `file` (binary), `type` (string: `database`|`logs`|`config`), `deviceId` (string)
- [ ] Validates: `type` must be one of the 3 allowed values (else 422), file extension must be `.db`, `.log`, `.json`, or `.gz` (else 422 with `"detail": "File extension not allowed. Allowed: .db, .log, .json, .gz"`), `deviceId` must be non-empty (else 422)
- [ ] Max file size: `MAX_BACKUP_SIZE_MB` from config (default 100MB). Returns 413 with `{"detail": "File too large. Max: 100MB"}` if exceeded.
- [ ] Stores file at `{BACKUP_DIR}/{deviceId}/{type}/{original_stem}-{YYYY-MM-DDTHH-MM-SS}.{ext}`
- [ ] Creates directory structure if it doesn't exist (`os.makedirs(..., exist_ok=True)`)
- [ ] Returns: `{status: "ok", filename: "...", storedAt: "/full/path/...", sizeBytes: 12345}`
- [ ] Rotation: after storing, counts files in `{BACKUP_DIR}/{deviceId}/{type}/`. If count > `BACKUP_RETENTION_COUNT` (default 30), deletes oldest files until count = retention limit. Never deletes the file just uploaded.
- [ ] Rotation safety: never deletes the last remaining file (minimum 1 file always kept)

Tests (all automated, using `tmp_path` for BACKUP_DIR):
- [ ] Test: upload a 1KB `.db` file with type=`database`, deviceId=`test-pi` → response 200. **Filesystem validation**: file exists at `{tmp}/test-pi/database/testfile-{timestamp}.db`, file size matches uploaded content. Response `sizeBytes` matches.
- [ ] Test: upload file with extension `.exe` → response 422 with detail mentioning allowed extensions.
- [ ] Test: upload with type=`invalid` → response 422.
- [ ] Test: upload with empty deviceId → response 422.
- [ ] Test: upload file exceeding MAX_BACKUP_SIZE_MB → response 413.
- [ ] Test: upload 32 files (retention=30) → oldest 2 files deleted, 30 remain. **Filesystem validation**: list files in directory, assert count=30, assert newest file still exists.
- [ ] Test: upload to non-existent directory → directory created automatically, file stored. **Filesystem validation**: directory exists.
- [ ] Test: single file in directory, rotation does NOT delete it (minimum 1 kept). **Filesystem validation**: 1 file remains.

### US-CMP-008: Health Endpoint with Component Status

**Description:** As a developer, I need the GET /health endpoint to return detailed status of all service components.

**Acceptance Criteria:**

Implementation:
- [ ] `GET /api/v1/health` returns: `{status, version, components: {api, mysql, ollama, ollamaModel}, lastSync: {deviceId, syncedAt, batchId} | null, uptime}`
- [ ] `components.mysql`: "up" if `SELECT 1` succeeds within 3 seconds, "down" otherwise
- [ ] `components.ollama`: "up" if `GET {OLLAMA_BASE_URL}/` returns 200 within 5 seconds, "down" otherwise
- [ ] `components.ollamaModel`: model name if `GET {OLLAMA_BASE_URL}/api/tags` lists the configured model, "not_loaded" otherwise, "unknown" if Ollama is down
- [ ] `status`: "healthy" if mysql=up AND ollama=up AND model loaded; "degraded" if mysql=up but ollama/model issues; "unhealthy" if mysql=down
- [ ] `lastSync`: query `SELECT device_id, completed_at, batch_id FROM sync_history WHERE status='success' ORDER BY completed_at DESC LIMIT 1`. If no rows: `lastSync: null`
- [ ] `uptime`: calculated from app startup time (stored in lifespan handler), formatted as `"Xd Yh Zm"`
- [ ] No authentication required
- [ ] Must respond within 5 seconds total (timeouts on component checks ensure this)

Tests (all automated):
- [ ] Test: all components mocked as healthy → response 200, `status: "healthy"`, `components.mysql: "up"`, `components.ollama: "up"`, `components.ollamaModel: "<model_name>"`.
- [ ] Test: Ollama mocked as unreachable → response 200, `status: "degraded"`, `components.ollama: "down"`, `components.ollamaModel: "unknown"`.
- [ ] Test: MySQL mocked as unreachable → response 200, `status: "unhealthy"`, `components.mysql: "down"`.
- [ ] Test: no sync_history rows → `lastSync: null`.
- [ ] Test: insert sync_history row, call /health → `lastSync.syncedAt` matches inserted row timestamp, `lastSync.batchId` matches.
- [ ] Test: `uptime` field is a non-empty string matching pattern `\d+d \d+h \d+m`.

### US-CMP-009: systemd Service and Deployment

**Description:** As a developer, I need the companion service to run as a systemd unit on Chi-Srv-01 with auto-start and restart-on-failure.

**Acceptance Criteria:**

Implementation:
- [ ] `deploy/eclipse-ai-server.service` systemd unit file: Type=simple, ExecStart runs uvicorn with `--host 0.0.0.0 --port $PORT`, `Restart=on-failure`, `RestartSec=10`, `After=network.target mysql.service`, `EnvironmentFile=/path/to/.env`, `WorkingDirectory=/path/to/project`
- [ ] `deploy/install-service.sh`: copies .service file to `/etc/systemd/system/`, runs `systemctl daemon-reload`, `systemctl enable`, `systemctl start`, checks status
- [ ] `deploy/setup-mysql.sh`: creates `eclipse_ai` and `eclipse_ai_test` databases, creates service user with password from env, grants privileges
- [ ] `docs/setup-guide.md` with sections: Prerequisites (Python 3.11+, MySQL 8.x, Ollama), OS package installation, Python venv creation, pip install, MySQL database setup, Ollama install and model pull, `.env` configuration, service installation, firewall rules (allow port 8000 from LAN), verification steps (curl /health), troubleshooting (service logs, MySQL connection, Ollama status)

Tests:
- [ ] Automated: `deploy/eclipse-ai-server.service` file exists and contains expected directives (ExecStart, Restart, After). Parse with regex or systemd-analyze.
- [ ] Automated: `deploy/install-service.sh` file exists and is executable
- [ ] Automated: `deploy/setup-mysql.sh` file exists and is executable
- [ ] Automated: `docs/setup-guide.md` file exists and contains sections: Prerequisites, MySQL, Ollama, .env, Installation, Verification, Troubleshooting
- [ ] Manual (CIO verification): service starts on Chi-Srv-01, `curl http://localhost:8000/api/v1/health` returns healthy
- [ ] Manual (CIO verification): `sudo systemctl stop eclipse-ai-server && sleep 15 && systemctl is-active eclipse-ai-server` returns "active" (restart-on-failure)

## Functional Requirements

- FR-1: All data accepted via /sync must be persisted in MySQL or rejected with clear error
- FR-2: Partial sync failures must not leave MySQL in an inconsistent state (use transactions)
- FR-3: Auto-analysis must not block the sync response
- FR-4: Backup rotation must never delete the only remaining backup
- FR-5: Health endpoint must respond within 5 seconds even if components are degraded
- FR-6: API key must be compared in constant time (prevent timing attacks)

## Non-Goals

- No data dashboard (deferred to future sprint)
- No NAS replication to Chi-NAS-01 (deferred to future B- item)
- No client-side sync code (B-027, EclipseTuner repo)
- No auto-discovery of Pi devices (explicit device registration)
- No user authentication beyond API key (no login, no sessions)
- No HTTPS (home LAN only; add later if needed)

## Configuration Variables

All configured via `.env` file:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | -- | MySQL connection string: `mysql+aiomysql://user:pass@localhost/eclipse_ai` |
| `API_KEY` | Yes | -- | Shared secret for X-API-Key auth |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | No | `gemma2:2b` | Model name for AI analysis |
| `BACKUP_DIR` | No | `./data/backups` | Filesystem path for backup storage |
| `PORT` | No | `8000` | HTTP listen port |
| `LOG_LEVEL` | No | `INFO` | Python logging level |
| `MAX_BACKUP_SIZE_MB` | No | `100` | Max upload file size in MB |
| `BACKUP_RETENTION_COUNT` | No | `30` | Max backup files kept per type per device |
| `MAX_SYNC_PAYLOAD_MB` | No | `10` | Max sync request body size in MB |
| `ANALYSIS_TIMEOUT_SECONDS` | No | `120` | Timeout for Ollama analysis requests |

## Design Considerations

- **MySQL over PostgreSQL**: CIO preference. MySQL 8.x supports JSON columns, window functions, and CTEs if needed later for dashboard queries.
- **SQLAlchemy 2.x async**: Matches FastAPI's async nature. Use `async_session` for all DB operations.
- **Alembic from day one**: Even though schema starts simple, migrations will be needed as the dashboard and NAS features are added.
- **Ollama /api/chat endpoint**: Conversational API with system/user/assistant roles. More structured than /api/generate. Server owns prompt templates.
- **ID mapping**: Pi's autoincrement IDs stored as `source_id`. MySQL has its own `id` PK. Upsert key is `(source_device, source_id)` supporting multi-device from day one.
- **Real MySQL for all tests**: No SQLite substitutes. Tests validate actual MySQL behavior (upsert syntax, FK enforcement, type handling).
- **Ollama client is simple HTTP**: No SDK needed. `httpx.AsyncClient` to call Ollama's REST API directly.
- **Backup storage is filesystem**: No need for S3/object storage on a home server. Simple directory structure with rotation.
- **API versioning via URL prefix**: `/api/v1/` allows future breaking changes without disrupting existing clients.
- **Constant-time API key comparison**: `hmac.compare_digest()` prevents timing attacks.

## Open Questions

- Exact GPU model on Chi-Srv-01 (determines Ollama model selection)
- Exact RAM on Chi-Srv-01 (determines MySQL buffer pool sizing)
- MySQL root password / user creation (CIO to set during OS install)

## Success Metrics

- EclipseTuner pushes drive data to companion service and receives AI recommendations
- Data visible in MySQL after sync (queryable for future dashboard)
- Service runs unattended for days without intervention
- Backup files accumulate with proper rotation
