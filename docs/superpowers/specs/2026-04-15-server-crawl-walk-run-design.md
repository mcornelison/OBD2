# Server-Side Crawl/Walk/Run Architecture Design

| Field | Value |
|---|---|
| **Spec ID** | server-crawl-walk-run |
| **Status** | Approved |
| **Created** | 2026-04-15 |
| **Author** | Ralph (with CIO) |
| **Supersedes** | `prd-infrastructure-pipeline-mvp.md` (DRAFT), reorders and absorbs `prd-companion-service.md` (B-022) |
| **Related Backlog** | B-022 (Companion Service), B-027 (Client Sync), B-035 (Pipeline Scenarios) |

---

## Purpose

Build the Chi-Srv-01 server as the project's analytics brain using a **crawl/walk/run** progression:

- **Crawl**: Server consumes fake (simulator-generated) data and produces real analytics. No Pi involvement.
- **Walk**: Pi sends simulated data through real sync endpoints. Same analytics, different data source.
- **Run**: Pi sends real OBD-II data. Baselines calibrated. AI analytics activated via Spool/Ollama.

This approach lets us prove the analytics are correct before adding network complexity, and prove the network is correct before adding real hardware variability.

### Why Supersede the Existing PRDs

The existing `prd-companion-service.md` (B-022) and `prd-infrastructure-pipeline-mvp.md` focused on plumbing — getting data from Pi to server. They did not address:

- A server-side analytics and reporting layer that can operate independently
- A fake-data-first validation strategy
- Tiered analytics (basic → advanced → AI)
- CLI reporting for SSH-based inspection

This spec restructures all existing B-022 and B-027 stories into the crawl/walk/run framework and adds new stories for analytics, reporting, data loading, and baseline calibration.

---

## Architecture Overview

### Data Flow Across Phases

```
CRAWL:  Simulator → SQLite → load_data.py → MariaDB → Analytics → CLI Reports
WALK:   Simulator → SQLite → SyncClient ──→ MariaDB → Analytics → CLI Reports
RUN:    OBD-II    → SQLite → SyncClient ──→ MariaDB → Analytics + AI → CLI Reports + Recommendations
```

The analytics layer is phase-agnostic. It queries MariaDB tables and produces results regardless of how data arrived. This is a core design constraint — no analytics code may depend on the data source.

### Analytics Tiers

| Tier | Phase Introduced | Description |
|---|---|---|
| **Basic** | Crawl | Per-drive statistics. Profile new data against historical. |
| **Advanced** | Crawl | Multi-drive trends, cross-parameter correlations, anomaly detection. |
| **AI** | Run (stub in Walk) | Ollama/Spool natural-language tuning recommendations. |

### Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| Framework | FastAPI 0.100+ | Async HTTP API |
| Database | MariaDB 10.x | Persistent storage, analytics queries |
| ORM/Driver | SQLAlchemy 2.x + aiomysql | Async MariaDB access |
| AI | Ollama on Chi-Srv-01 (GPU) | LLM inference (run phase) |
| Auth | API key (`X-API-Key` header) | Shared-secret authentication |
| Process | uvicorn | ASGI server |
| Service | systemd | Auto-start, restart on failure |
| Testing | pytest + httpx | Async test client |
| Python | 3.11+ | Match Pi version |

### Server Hardware (Chi-Srv-01)

| Spec | Value |
|---|---|
| IP | 10.27.27.10 |
| OS | Debian 13 |
| CPU | Intel i7-5960X (8 cores / 16 threads) |
| RAM | 128GB DDR4 |
| GPU | 12GB NVIDIA (LLM-capable) |
| Storage | 2TB RAID 5 SSD at `/mnt/raid5` |
| Database | MariaDB (`obd2db`) |
| Ollama | GPU-accelerated at localhost:11434 |

---

## Project Structure

The server lives in `src/server/` within the existing OBD2v2 repo. This keeps shared contracts in `src/common/` accessible without cross-repo dependencies.

```
src/server/
├── __init__.py
├── main.py                  # FastAPI app entry point
├── config.py                # Pydantic Settings from .env
├── database/
│   ├── __init__.py
│   ├── connection.py        # Async SQLAlchemy session factory
│   ├── models.py            # SQLAlchemy models
│   └── migrations/          # Alembic versions
├── analytics/
│   ├── __init__.py
│   ├── types.py             # Dataclasses for analytics results
│   ├── basic.py             # Per-drive statistics, new-vs-existing profiling
│   ├── advanced.py          # Trends, correlations, anomaly detection
│   └── helpers.py           # Shared analytics utilities
├── routers/
│   ├── __init__.py
│   ├── health.py            # GET /health (crawl)
│   ├── sync.py              # POST /sync (walk)
│   ├── analyze.py           # POST /analyze (walk stub, run real)
│   └── backup.py            # POST /backup (run)
├── services/
│   ├── __init__.py
│   ├── sync_service.py      # Delta sync processing (walk)
│   ├── analysis_service.py  # Ollama interaction (run)
│   └── ollama_client.py     # HTTP client for Ollama (run)
├── auth.py                  # API key middleware (walk)
└── reports/
    ├── __init__.py
    ├── drive_report.py      # Single-drive report formatter
    └── trend_report.py      # Multi-drive trend formatter

scripts/
├── load_data.py             # Import simulator SQLite → MariaDB (crawl)
├── report.py                # CLI report entry point (crawl)
├── sync_now.py              # Manual sync trigger (walk)
└── seed_scenarios.py        # Run simulator + export for server import (crawl)

deploy/
├── obd2-server.service      # systemd unit
├── install-service.sh
└── setup-mariadb.sh
```

---

## Phase 1: Crawl — Server Analyzes Fake Data Independently

### Goal

Stand up the server, seed it with simulator-generated data, prove basic + advanced analytics produce correct results via CLI reports. No Pi involvement.

### Done Milestone

CIO can SSH into Chi-Srv-01, run the data loader with simulator exports, run CLI reports, and see meaningful analytics output.

### 1.1 Project Scaffold (absorbed from US-CMP-001)

- FastAPI app skeleton in `src/server/main.py` with lifespan handler
- Pydantic Settings config (`src/server/config.py`) reading from `.env`:
  - Required: `DATABASE_URL`, `API_KEY`
  - Optional with defaults: `OLLAMA_BASE_URL` (http://localhost:11434), `OLLAMA_MODEL` (llama3.1:8b), `BACKUP_DIR` (./data/backups), `PORT` (8000), `LOG_LEVEL` (INFO), `MAX_BACKUP_SIZE_MB` (100), `BACKUP_RETENTION_COUNT` (30), `MAX_SYNC_PAYLOAD_MB` (10), `ANALYSIS_TIMEOUT_SECONDS` (120)
- `.env.example` with all config variables and descriptions
- `requirements.txt`: fastapi, uvicorn, sqlalchemy, aiomysql, pydantic-settings, python-multipart, httpx, alembic, pytest, pytest-asyncio
- App starts with `uvicorn src.server.main:app --host 0.0.0.0 --port 8000`

### 1.2 MariaDB Schema (absorbed from US-CMP-003)

**Synced tables** (mirrored from Pi SQLite with server additions):

| Table | Server Additions |
|---|---|
| `realtime_data` | `source_id`, `source_device`, `synced_at`, `sync_batch_id` |
| `statistics` | `source_id`, `source_device`, `synced_at`, `sync_batch_id` |
| `profiles` | `source_id`, `source_device`, `synced_at` |
| `vehicle_info` | `source_device`, `synced_at` |
| `ai_recommendations` | `source_id`, `source_device`, `synced_at`, `sync_batch_id` |
| `connection_log` | `source_id`, `source_device`, `synced_at`, `sync_batch_id` |
| `alert_log` | `source_id`, `source_device`, `synced_at`, `sync_batch_id` |
| `calibration_sessions` | `source_id`, `source_device`, `synced_at` |

Each synced table has:
- `id` — MariaDB autoincrement PK (server-owned)
- `source_id` — INT NOT NULL (original Pi row ID)
- `source_device` — VARCHAR(64) NOT NULL
- `UNIQUE(source_device, source_id)` constraint for upsert

**Server-only tables** (from B-022):

| Table | Purpose |
|---|---|
| `sync_history` | Log of sync batches: batch_id, device_id, timestamps, row counts, status |
| `analysis_history` | Log of AI analysis runs: analysis_id, profile, drive window, model, timing, status |
| `devices` | Registered devices: device_id, display_name, last_seen, api_key_hash |

**Analytics tables** (new):

| Table | Purpose |
|---|---|
| `drive_summary` | One row per detected drive: start/end time, duration, device, profile, row count |
| `drive_statistics` | Per-drive per-parameter statistics: min, max, avg, std, outlier_min, outlier_max |
| `trend_snapshots` | Rolling trend calculations across last N drives, refreshed after each new drive |
| `anomaly_log` | Flagged anomalies: parameter, drive, deviation magnitude, severity |

**NOT synced** (Pi-only hardware telemetry): `battery_log`, `power_log`

**Schema tooling**:
- `deploy/setup-mariadb.sh` creates `obd2db` (production) and `obd2db_test` (testing), grants privileges to user `obd2`
- `scripts/init_db.py` creates all tables idempotently
- Alembic configured with initial migration

### 1.3 Health Endpoint (absorbed from US-CMP-008)

`GET /api/v1/health` — no auth required.

Response:
```json
{
    "status": "healthy | degraded | unhealthy",
    "version": "1.0.0",
    "components": {
        "api": "up",
        "mysql": "up | down",
        "ollama": "up | down | stub"
    },
    "lastSync": null,
    "lastAnalysis": null,
    "driveCount": 0,
    "uptime": "2d 4h 30m"
}
```

Status logic:
- `healthy`: mysql=up AND ollama=up
- `degraded`: mysql=up, ollama issues
- `unhealthy`: mysql=down

### 1.4 systemd Service (absorbed from US-CMP-009)

- `deploy/obd2-server.service`: Type=simple, ExecStart=uvicorn, Restart=on-failure, RestartSec=10, After=network.target mysql.service
- `deploy/install-service.sh`: copies service file, daemon-reload, enable, start, status check
- `docs/setup-guide.md`: prerequisites, installation, verification, troubleshooting

### 1.5 Data Loader Script (new)

`scripts/load_data.py` — imports simulator-generated SQLite data into MariaDB.

```bash
# Generate simulated data
python scripts/seed_scenarios.py --scenario full_cycle --output data/sim_full_cycle.db

# Load into MariaDB
python scripts/load_data.py --db-file data/sim_full_cycle.db --device-id sim-eclipse-gst
```

Behavior:
- Opens the SQLite file read-only
- Reads all rows from Pi-schema tables (realtime_data, statistics, connection_log, alert_log, profiles, vehicle_info)
- Maps Pi `id` → `source_id`, sets `source_device` to provided device-id
- Bulk inserts into MariaDB using `INSERT ... ON DUPLICATE KEY UPDATE` with upsert key `(source_device, source_id)`
- After loading: detects drives from connection_log (drive_start/drive_end pairs), creates `drive_summary` rows
- Prints summary: rows loaded per table, drives detected, elapsed time
- Idempotent — safe to re-run

### 1.6 Seed Scenarios Script (new)

`scripts/seed_scenarios.py` — runs the existing Pi simulator and exports to a standalone SQLite file.

```bash
# Use existing scenarios
python scripts/seed_scenarios.py --scenario city_driving --output data/sim_city.db
python scripts/seed_scenarios.py --scenario highway_cruise --output data/sim_highway.db
python scripts/seed_scenarios.py --scenario full_cycle --output data/sim_full.db

# Run all scenarios into one database (multiple drives)
python scripts/seed_scenarios.py --all --output data/sim_all_drives.db
```

- Reuses existing `SensorSimulator`, `DriveScenarioRunner`, and `VehicleProfile` from `src/obd/simulator/`
- Writes data to the Pi-schema SQLite tables (realtime_data, connection_log, statistics)
- Time-scaled execution (17-min scenario runs in seconds)
- Output is a portable SQLite file ready for `load_data.py`

### 1.7 Basic Analytics Engine (new)

`src/server/analytics/basic.py`

**Per-drive profiling**:
- Input: drive_summary row (start/end time, device, profile)
- Queries `realtime_data` for all readings in the drive's time window
- Computes per parameter: min, max, avg, std_dev, outlier_min (mean - 2*std), outlier_max (mean + 2*std), sample_count
- Stores results in `drive_statistics` table

**New-vs-existing comparison**:
- Computes aggregate statistics across all prior drives (mean of max, mean of avg, std of max, etc.)
- Compares current drive's statistics against historical aggregates
- Flags parameters where current drive deviates > 2 standard deviations from historical norm
- Returns structured result: parameter name, current value, historical mean, deviation in sigma, status (NORMAL / WATCH / INVESTIGATE)

### 1.8 Advanced Analytics Engine (new)

`src/server/analytics/advanced.py`

**Trend analysis**:
- For each parameter, computes rolling average of key statistics (peak, avg) across last N drives (configurable, default 10)
- Detects direction: rising, falling, stable (based on linear regression slope significance)
- Flags parameters with sustained drift (>5% change over N drives)
- Stores snapshots in `trend_snapshots` table

**Cross-parameter correlation**:
- Computes Pearson correlation coefficient between drive-level aggregates of parameter pairs
- Focuses on known tuning-relevant pairs:
  - IAT ↔ Knock Count (heat-induced knock)
  - IAT ↔ STFT (hot air compensation)
  - RPM ↔ Coolant Temp (load-driven heating)
  - Boost ↔ AFR (boost enrichment)
- Flags correlations with |r| > 0.7 as significant

**Anomaly detection**:
- For each drive, checks whether any parameter's statistics fall outside the historical envelope (mean ± 2*std across drives)
- Writes flagged anomalies to `anomaly_log` with: parameter, drive, observed value, expected range, deviation magnitude, severity (WATCH for 2-3σ, INVESTIGATE for >3σ)

### 1.9 CLI Report Tool (new)

`scripts/report.py` — human-readable analytics output.

**Drive Report**:
```bash
python scripts/report.py --drive latest
python scripts/report.py --drive 2026-04-15
python scripts/report.py --drive all      # Summary table of all drives
```

Output format:
```
═══════════════════════════════════════════════
  Drive Report — 2026-04-15 14:30 (17 min)
  Device: sim-eclipse-gst | Profile: Daily
═══════════════════════════════════════════════

  Parameter       Min     Max     Avg     Std    Status
  ─────────────────────────────────────────────────────
  RPM             850    5200    2340    680.2    NORMAL
  Coolant (°F)    145     198     187      8.1   NORMAL
  IAT (°F)         72     118      94     12.3   ⚠ WATCH
  STFT (%)        -8.2    12.1     1.3     4.2   NORMAL
  Boost (psi)      0.0   12.4     4.2     3.8   NORMAL

  Comparison to Historical (12 prior drives):
  ─────────────────────────────────────────────────────
  IAT peak 118°F is 2.4σ above historical avg peak 98°F
  All other parameters within normal envelope
═══════════════════════════════════════════════
```

**Trend Report**:
```bash
python scripts/report.py --trends
python scripts/report.py --trends --last 20
```

Output format:
```
═══════════════════════════════════════════════
  Trend Report — Last 10 Drives
═══════════════════════════════════════════════

  Parameter        Direction    Δ Over Period     Significance
  ──────────────────────────────────────────────────────────────
  Coolant Peak     ↑ Rising     +6°F               WATCH
  IAT Peak         ↗ Slight     +3°F               OK
  RPM Max          → Stable     -50 RPM            OK
  STFT Avg         ↑ Rising     +2.1%              ⚠ INVESTIGATE
  Knock Count      → Stable     0                  OK

  Correlations Detected:
  ──────────────────────────────────────────────────────────────
  IAT > 110°F correlates with STFT increase (r=0.78)
═══════════════════════════════════════════════
```

---

## Phase 2: Walk — Pi Sends Simulated Data Through Real Pipeline

### Goal

Wire up Pi-to-server sync. Prove the same analytics work on data that arrived via HTTP sync vs bulk import. Iterate on CLI reports.

### Done Milestone

CIO runs simulator on Pi, triggers sync, data lands in MariaDB, CLI reports produce equivalent output to crawl phase.

### 2.1 API Key Auth (absorbed from US-CMP-002)

- `src/server/auth.py`: FastAPI dependency extracting `X-API-Key` header
- Constant-time comparison via `hmac.compare_digest()`
- Missing key → 401 `{"detail": "Missing API key"}`
- Invalid key → 401 `{"detail": "Invalid API key"}`
- `/health` exempt from auth

### 2.2 Delta Sync Endpoint (absorbed from US-CMP-004)

`POST /api/v1/sync`

Request:
```json
{
    "deviceId": "chi-eclipse-tuner",
    "batchId": "sync-2026-04-15T14:30:00",
    "tables": {
        "realtime_data": {
            "lastSyncedId": 3965,
            "rows": [...]
        }
    }
}
```

Behavior:
- Validates request body (Pydantic model)
- Accepted table names: `realtime_data`, `statistics`, `profiles`, `vehicle_info`, `ai_recommendations`, `connection_log`, `alert_log`, `calibration_sessions`
- Upserts rows using `INSERT ... ON DUPLICATE KEY UPDATE` with key `(source_device, source_id)`
- Server sets `synced_at`, `source_device`, `sync_batch_id` on each row
- All upserts in single transaction — rollback on any error
- Creates `sync_history` record
- After successful sync: runs basic analytics on any new drive data detected (same analytics as crawl)
- Max payload: 10MB (configurable)

Response:
```json
{
    "status": "ok",
    "batchId": "sync-2026-04-15T14:30:00",
    "tablesProcessed": {
        "realtime_data": {"inserted": 500, "updated": 0, "errors": 0}
    },
    "syncedAt": "2026-04-15T14:30:05",
    "driveDataReceived": true,
    "autoAnalysisTriggered": false
}
```

### 2.3 Stub AI Endpoint (absorbed from US-147)

`POST /api/v1/analyze`

Returns canned response matching the shape real Ollama will produce in run phase:
```json
{
    "status": "ok",
    "analysisId": "stub-{uuid}",
    "message": "Stub analysis — real implementation in run phase",
    "recommendations": [],
    "model": "stub",
    "processingTimeMs": 0
}
```

Logs request to `analysis_history` table for inspection. API key required.

### 2.4 Pi-Side: Companion Service Config (absorbed from US-151)

New section in `config.json` under `pi:`:
```json
"companionService": {
    "enabled": true,
    "baseUrl": "http://10.27.27.10:8000",
    "apiKeyEnv": "COMPANION_API_KEY",
    "syncTimeoutSeconds": 30,
    "batchSize": 500,
    "retryMaxAttempts": 3,
    "retryBackoffSeconds": [1, 2, 4, 8, 16]
}
```

- `COMPANION_API_KEY` added to `.env.example`
- ConfigValidator updated with new section + defaults
- When `enabled: false`, sync returns early (graceful no-op)

### 2.5 Pi-Side: Sync Log Table (absorbed from US-148)

New `sync_log` table in Pi SQLite:
- `table_name TEXT PRIMARY KEY`
- `last_synced_id INTEGER NOT NULL DEFAULT 0`
- `last_synced_at TEXT`
- `last_batch_id TEXT`
- `status TEXT` (ok, pending, failed)

Added to Pi database initialization. `getDeltaRows(tableName, lastId, limit)` returns rows where `id > lastId`, ascending.

Tables in scope: `realtime_data`, `statistics`, `profiles`, `vehicle_info`, `ai_recommendations`, `connection_log`, `alert_log`, `calibration_sessions`.

Excluded (Pi-only): `battery_log`, `power_log`.

### 2.6 Pi-Side: HTTP Sync Client (absorbed from US-149)

`SyncClient` class:
- `pushDelta(tableName)`: reads sync_log high-water mark → gets delta rows → POSTs to server → updates high-water mark on success only
- `pushAllDeltas()`: iterates all in-scope tables
- API key from `COMPANION_API_KEY` env var via secrets_loader
- Exponential backoff retry: `[1, 2, 4, 8, 16]` seconds, max 3 attempts
- Failed push does NOT advance high-water mark (data loss safety)

### 2.7 Manual Sync CLI (absorbed from US-154)

`scripts/sync_now.py` — one-shot delta push:

```bash
python scripts/sync_now.py
```

Output:
```
Sync started: 2026-04-15 14:32:05
Config: baseUrl=http://10.27.27.10:8000, batchSize=500

realtime_data: 247 new rows → pushed → accepted (batch: abc123)
statistics: 12 new rows → pushed → accepted (batch: abc124)
alert_log: 0 new rows → nothing to sync
...

Total: 259 rows pushed across 2 tables
Elapsed: 1.8s
Status: OK
```

### 2.8 Sync-to-Analytics Parity Validation (new)

Validation story proving analytics are source-agnostic:

1. Run the same simulator scenario twice — export to SQLite files A and B
2. Load file A via `load_data.py` (crawl path) with device-id `crawl-test`
3. Load file B via `sync_now.py` through the sync endpoint (walk path) with device-id `walk-test`
4. Run `report.py --drive latest` for each device
5. Assert: statistics match within floating-point tolerance
6. Automated as an integration test

---

## Phase 3: Run — Real Data, Calibrated Baselines, AI Analytics

### Goal

Real OBD-II data flows through the full pipeline. Baselines calibrated from real drives. Spool/Ollama produces tuning recommendations.

### Done Milestone

Real drive data syncs to server. CLI reports show real trends and baselines. Spool produces actionable tuning recommendations.

### 3.1 Real AI Analysis Endpoint (absorbed from US-CMP-005, replaces stub)

`POST /api/v1/analyze`

- Queries MariaDB for drive data in specified time window
- Builds prompt from `src/server/services/prompts/` templates:
  - System message: vehicle context (Eclipse GST, 4G63 turbo, ECMLink planned), tuning context
  - User message: parameter statistics from basic + advanced analytics, focus areas
- Sends to Ollama via `httpx.AsyncClient` POST to `/api/chat` with `stream: false`
- Timeout: 120 seconds (configurable)
- Parses response into ranked recommendations: rank, category, recommendation text, confidence (0-1)
- Stores in `ai_recommendations` table and `analysis_history`
- Ollama unavailable → 503
- Ollama error → 502
- No drive data for time window → 200 with empty recommendations

### 3.2 Auto-Analysis on Drive Receipt (absorbed from US-CMP-006)

- After `/sync` detects `driveDataReceived=true` (connection_log with drive_end event)
- Enqueues async analysis task via `asyncio.create_task()` — does not block sync response
- Extracts drive boundaries from synced connection_log
- Uses same analysis service as POST /analyze
- Sync response includes `autoAnalysisTriggered: true`
- Ollama unavailable: logs WARNING, sync response still 200, `autoAnalysisTriggered: false`
- Analysis failure: ERROR logged, no effect on sync success

### 3.3 Baseline Calibration Tooling (new)

After N real drives (configurable, default 5), the system can establish real baselines:

```bash
python scripts/report.py --calibrate
```

Output:
```
═══════════════════════════════════════════════
  Baseline Calibration — 8 Real Drives Available
═══════════════════════════════════════════════

  Parameter       Sim Baseline    Real Baseline    Δ         Action
  ────────────────────────────────────────────────────────────────
  RPM idle        900             865              -35       UPDATE
  Coolant norm    185°F           192°F            +7°F      UPDATE
  IAT ambient     85°F            78°F             -7°F      UPDATE
  STFT avg        0.0%            +1.8%            +1.8%     UPDATE
  Boost peak      12.0 psi        10.8 psi         -1.2     UPDATE

  Apply these baselines? (requires CIO approval)
  Run: python scripts/report.py --calibrate --apply
═══════════════════════════════════════════════
```

- `--calibrate` shows proposed changes, does not apply
- `--calibrate --apply` updates baseline values in a `baselines` config table
- Human-in-the-loop: per architectural decision #2, never auto-applied

### 3.4 Backup Receiver (absorbed from US-CMP-007)

`POST /api/v1/backup` — multipart/form-data:
- Fields: `file` (binary), `type` (database|logs|config), `deviceId`
- Allowed extensions: `.db`, `.log`, `.json`, `.gz`
- Max size: `MAX_BACKUP_SIZE_MB` (default 100MB)
- Stores at `{BACKUP_DIR}/{deviceId}/{type}/{stem}-{timestamp}.{ext}`
- Rotation: keeps last `BACKUP_RETENTION_COUNT` (default 30) per type per device
- Never deletes the last remaining file

### 3.5 Pi-Side: Backup Push (absorbed from US-150)

- Pushes SQLite DB + log files to server `/backup` endpoint
- Multipart form upload with SHA256 content hash
- CLI: `python scripts/backup_push.py`
- Non-fatal — backup failure doesn't block sync

### 3.6 AI-Enhanced CLI Reports (new)

Drive report gains AI section when analysis exists:

```
═══════════════════════════════════════════════
  Drive Report — 2026-07-15 14:30 (42 min)
  Device: chi-eclipse-tuner | Profile: Daily
  Data Source: OBD-II (real) | Sync: 2026-07-15 15:02
═══════════════════════════════════════════════

  [Statistics section — same as crawl/walk]

  AI Analysis (llama3.1:8b, 4.2s):
  ─────────────────────────────────────────────────────
  1. [AFR] Wideband AFR trending lean at >4000 RPM
     across last 3 drives. Consider enriching high-load
     fuel map cells by 1-2%.               Confidence: 0.82

  2. [TIMING] Timing advance stable. No knock events
     detected.                              Confidence: 0.95

  Baseline Status:
  ─────────────────────────────────────────────────────
  Calibrated on 8 real drives (established 2026-07-10)
  All parameters within calibrated envelope
═══════════════════════════════════════════════
```

When no AI analysis exists (crawl/walk), the AI section is simply omitted.

---

## Story Map

### Phase 1: Crawl

| # | Story ID | Title | Source | Description |
|---|---|---|---|---|
| 1 | US-CMP-001 | Project scaffold and config | B-022 | FastAPI skeleton, Pydantic settings, .env, requirements |
| 2 | US-CMP-009 | systemd service and deployment | B-022 | Service file, install script, setup-mariadb.sh, setup guide |
| 3 | US-CMP-003 | MariaDB schema and connection | B-022 | SQLAlchemy models, synced + server-only + analytics tables, Alembic |
| 4 | US-CMP-008 | Health endpoint | B-022 | GET /health with component status, no auth |
| 5 | NEW-01 | Seed scenarios script | New | Run simulator, export to portable SQLite files |
| 6 | NEW-02 | Data loader script | New | Import SQLite → MariaDB with upsert, drive detection |
| 7 | NEW-03 | Basic analytics engine | New | Per-drive statistics, new-vs-existing profiling |
| 8 | NEW-04 | Advanced analytics engine | New | Trends, correlations, anomaly detection |
| 9 | NEW-05 | CLI report tool | New | Drive report + trend report, formatted terminal output |

### Phase 2: Walk

| # | Story ID | Title | Source | Description |
|---|---|---|---|---|
| 10 | US-CMP-002 | API key auth middleware | B-022 | X-API-Key header, constant-time compare, /health exempt |
| 11 | US-CMP-004 | Delta sync endpoint | B-022 | POST /sync, upsert, transaction, sync_history |
| 12 | US-147 | Stub AI analysis endpoint | Pipeline MVP | POST /analyze returns canned response |
| 13 | US-148 | Pi sync_log table + delta query | B-027 | High-water mark tracking, getDeltaRows() |
| 14 | US-149 | Pi HTTP sync client | B-027 | SyncClient, pushDelta, retry, high-water safety |
| 15 | US-151 | Pi companion service config | B-027 | Config section, .env, ConfigValidator update |
| 16 | US-154 | Manual sync trigger CLI | Pipeline MVP | scripts/sync_now.py, per-table summary |
| 17 | NEW-06 | Sync-to-analytics parity validation | New | Prove analytics identical regardless of data source |

### Phase 3: Run

| # | Story ID | Title | Source | Description |
|---|---|---|---|---|
| 18 | US-CMP-005 | Real AI analysis endpoint | B-022 | Ollama /api/chat, prompt templates, recommendations |
| 19 | US-CMP-006 | Auto-analysis on drive receipt | B-022 | Async trigger after sync, graceful degradation |
| 20 | US-CMP-007 | Backup receiver endpoint | B-022 | POST /backup, file storage, rotation |
| 21 | US-150 | Pi backup file push | B-027 | Pi-side multipart upload, SHA256 hash |
| 22 | NEW-07 | Baseline calibration tooling | New | Compare sim vs real baselines, CIO-approved updates |
| 23 | NEW-08 | AI-enhanced CLI reports | New | Drive report with AI section, baseline status |

**Total: 23 stories across 3 phases.** 14 absorbed from existing PRDs, 8 new, 1 from pipeline MVP draft.

---

## API Contract Summary (v1)

All endpoints prefixed with `/api/v1/`.

| Method | Endpoint | Auth | Phase | Purpose |
|---|---|---|---|---|
| GET | `/health` | No | Crawl | Component status, sync/analysis state, uptime |
| POST | `/sync` | Yes | Walk | Accept delta data from Pi, upsert into MariaDB |
| POST | `/analyze` | Yes | Walk (stub) / Run (real) | Trigger AI analysis on drive data |
| POST | `/backup` | Yes | Run | Accept file uploads from Pi |

### ID Mapping Strategy

Pi rows have SQLite autoincrement IDs. MariaDB uses its own autoincrement PK:

| MariaDB Column | Purpose |
|---|---|
| `id` (PK) | MariaDB autoincrement, server-owned |
| `source_id` | Original Pi row ID (INT NOT NULL) |
| `source_device` | Device identifier (VARCHAR(64)) |

Upsert key: `UNIQUE(source_device, source_id)` per table. Supports multi-device from day one.

---

## Configuration Variables

All configured via `.env` file on Chi-Srv-01:

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | `mysql+aiomysql://obd2:${DB_PASSWORD}@localhost/obd2db` |
| `API_KEY` | Yes | — | Shared secret for X-API-Key auth |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | No | `llama3.1:8b` | Model for AI analysis |
| `BACKUP_DIR` | No | `./data/backups` | Backup file storage path |
| `PORT` | No | `8000` | HTTP listen port |
| `LOG_LEVEL` | No | `INFO` | Python logging level |
| `MAX_BACKUP_SIZE_MB` | No | `100` | Max upload file size |
| `BACKUP_RETENTION_COUNT` | No | `30` | Max backups per type per device |
| `MAX_SYNC_PAYLOAD_MB` | No | `10` | Max sync request body size |
| `ANALYSIS_TIMEOUT_SECONDS` | No | `120` | Ollama analysis timeout |
| `TREND_WINDOW_DRIVES` | No | `10` | Number of drives for trend analysis |
| `ANOMALY_THRESHOLD_SIGMA` | No | `2.0` | Standard deviations for anomaly flagging |
| `CALIBRATION_MIN_DRIVES` | No | `5` | Minimum real drives before calibration |

---

## Testing Strategy

All tests use **real MariaDB test database** (`obd2db_test`). No SQLite substitutes.

| Category | Approach |
|---|---|
| Analytics unit tests | Seed MariaDB test DB with known data, assert exact statistics |
| CLI report tests | Capture stdout, assert formatting and values |
| Sync endpoint tests | httpx AsyncClient against TestApp, verify MariaDB state |
| Auth tests | Verify 401 on missing/bad key, 200 on valid key |
| Integration tests | Load data → run analytics → verify reports (marked `@pytest.mark.integration`) |
| Parity tests | Same data via loader vs sync → assert identical analytics |
| Pi-side tests | Mock HTTP endpoint, verify sync_log behavior |

---

## Non-Goals

- No web dashboard (future work — CLI reports are sufficient for crawl/walk/run)
- No NAS replication to Chi-NAS-01 (future)
- No HTTPS (home LAN only)
- No user authentication beyond API key
- No auto-discovery of Pi devices
- No ECMLink-specific analytics (blocked until hardware, Summer 2026)
- No auto-apply of baselines or tuning recommendations (human-in-the-loop always)

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Crawl phase too many stories (9) | Medium | Medium | Natural checkpoints: scaffold+deploy first, then schema, then analytics |
| Simulator data doesn't exercise all analytics paths | Medium | Low | Multiple scenarios cover different driving profiles; add more via AI generation if needed |
| MariaDB async driver issues | Low | Medium | aiomysql is mature; fallback to sync pymysql if needed |
| Analytics on fake data misleads baseline tuning | Low | Low | Run phase explicitly re-calibrates from real data; fake baselines are provisional |
| Walk phase reveals sync format issues | Medium | Low | Parity validation test catches mismatches early |
| Ollama model quality insufficient for tuning advice | Medium | Medium | Start with llama3.1:8b; upgrade to 13B+ if quality is lacking; 12GB GPU supports it |

---

## Dependencies

```
Crawl Phase:
  US-CMP-001 (scaffold)
    → US-CMP-009 (deploy)
    → US-CMP-003 (schema)
    → US-CMP-008 (health)
    → NEW-01 (seed scenarios) — independent of above, needs Pi simulator code
    → NEW-02 (data loader) — depends on US-CMP-003
    → NEW-03 (basic analytics) — depends on NEW-02
    → NEW-04 (advanced analytics) — depends on NEW-03
    → NEW-05 (CLI reports) — depends on NEW-03, NEW-04
  CHECKPOINT: SSH to Chi-Srv-01, load data, run reports

Walk Phase:
  US-CMP-002 (auth) — depends on US-CMP-001
    → US-CMP-004 (sync) — depends on US-CMP-002, US-CMP-003
    → US-147 (stub AI) — depends on US-CMP-002
  US-148 (Pi sync_log) — independent of server walk stories
    → US-149 (Pi sync client) — depends on US-148
    → US-151 (Pi config) — independent
    → US-154 (sync CLI) — depends on US-149
  NEW-06 (parity validation) — depends on NEW-05, US-CMP-004
  CHECKPOINT: Simulator on Pi, sync to server, same reports

Run Phase:
  US-CMP-005 (real AI) — depends on US-CMP-004, replaces US-147
    → US-CMP-006 (auto-analysis) — depends on US-CMP-005
  US-CMP-007 (backup receiver) — depends on US-CMP-001
    → US-150 (Pi backup push) — depends on US-CMP-007
  NEW-07 (calibration) — depends on NEW-03, NEW-04
  NEW-08 (AI reports) — depends on US-CMP-005, NEW-05
  CHECKPOINT: Real data flows, Spool produces recommendations
```

---

## Open Questions (Deferred to Implementation)

1. Async MySQL driver choice: `aiomysql` vs `asyncmy` — Ralph to evaluate during US-CMP-001
2. Alembic migrations vs raw SQL — Ralph to decide during US-CMP-003
3. Correlation parameter pairs — Spool may suggest additional pairs beyond the initial set
4. Trend analysis window size — 10 drives is a starting default; may adjust during run phase
5. AI prompt template design — Spool should review/author during US-CMP-005
6. Report format refinements — expected to evolve through all three phases

---

## Success Criteria

| Phase | Success Looks Like |
|---|---|
| **Crawl** | CIO SSHs to Chi-Srv-01, loads simulated data, runs CLI reports, sees correct statistics and trends |
| **Walk** | Simulator runs on Pi, sync pushes to server, CLI reports produce same quality output as crawl |
| **Run** | Real drive data flows end-to-end, baselines calibrated from real data, Spool produces actionable tuning recommendations |

---

## Approval

| Date | Who | What |
|---|---|---|
| 2026-04-15 | CIO | Approved crawl/walk/run approach, Option B (supersede/absorb), tiered analytics, CLI reports, export-import fake data strategy |
| 2026-04-15 | Ralph | Authored spec based on brainstorming session |
