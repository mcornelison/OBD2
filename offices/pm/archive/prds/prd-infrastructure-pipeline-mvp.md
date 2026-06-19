# PRD: Infrastructure Pipeline MVP + Simulated Drive Scenarios

> **STATUS: SUPERSEDED (2026-04-15)**
>
> This PRD has been fully absorbed and restructured into two CIO-approved architecture specs:
> - **Server**: `docs/superpowers/specs/2026-04-15-server-crawl-walk-run-design.md` (B-036)
> - **Pi**: `docs/superpowers/specs/2026-04-15-pi-crawl-walk-run-sprint-design.md` (B-037)
>
> Stories US-147–154 from this draft were absorbed into the new specs. US-152, US-153, US-155 were retired (scope covered by new stories). This file is retained for historical reference only.
>
> ---
>
> ~~**STATUS: DRAFT — PENDING RALPH'S ARCH REORG COMPLETION**~~
>
> ~~This PRD was drafted during a PM brainstorming session on 2026-04-13. At the time of writing, Ralph was mid-flight on an architectural reorganization that will move files and module structure. File paths and module references in this doc are marked `TBD after arch reorg` wherever they would be reorg-sensitive.~~
>
> ~~**Before promoting to active**: walk the "Finalization Checklist" at the bottom, fill in all TBDs, re-review, create backlog items, update `backlog.json` and `story_counter.json` in a single clean commit.~~

| Field | Value |
|---|---|
| **PRD ID** | prd-infrastructure-pipeline-mvp |
| **Parent Backlog Items** | B-022 (Companion Service), B-027 (Client Sync), B-035 (new, Pipeline Scenarios) |
| **Priority** | High |
| **Status** | Draft |
| **Target Sprints** | Sprint 7, 8, 9 (post arch-reorg) |
| **Owner** | Marcus (PM) |
| **Created** | 2026-04-13 |
| **Source** | CIO brainstorming session 2026-04-13 |
| **Story Range** | US-147 through US-155 |

---

## Purpose

Build the minimum viable software pipeline that lets us **end-to-end debug Pi → Server → AI analysis → Pi** with realistic simulated drive data while the CIO works on real Bluetooth/dongle integration in parallel. When the real dongle lands, the pipeline is already debugged — we swap `--simulate` for the real connection and the downstream code path is unchanged.

This PRD does **not** build the full production companion service in one shot. Instead, it reorders the existing B-022 PRD so the full loop lights up after ~4-5 stories (instead of 9), then circles back in a later sprint to complete the deferred stories. Nothing from B-022 is lost — every story is tracked.

---

## The CIO's Original 4-Step Plan

From brainstorming session 2026-04-13:

1. **Deployment process**: Deploy code to Pi and to Chi-Srv-01 server
2. **Both running + SSH debuggable**: Verify both services are up, accessible via SSH, diagnosable via logs + health endpoints
3. **End-to-end communications**: Pi↔Server communication (delta sync + AI analysis) working
4. **Simulated data sets**: Two realistic drive scenarios (town + highway) for exercising the pipeline

**Parallel track (CIO-owned, outside this PRD)**: Real Bluetooth pairing, OBDLink LX verification, first real datalogs. Swap-in happens post-sprint 9.

---

## Design Decisions (Resolved in Brainstorm)

| Decision | Resolution |
|---|---|
| B-022 scope strategy | **Option C**: Reorder B-022 stories so "loop live" hits early. All 9 stories tracked. Sprint 7 gets 6 originals + 1 stub AI. Sprint 9 finishes the remaining 3. |
| Simulated data approach | **Approach A**: Scenario JSON files running through existing physics-based `SensorSimulator`. Same format as existing `city_driving.json` etc. No pre-recorded fixtures. |
| SSH debugging scope | **Option B**: Logs + `/health` endpoints. Health endpoint is `curl`able from any SSH session. Matches existing US-CMP-008 scope. |
| Sync trigger mechanism | **Manual CLI script** for sprint 7/8. Auto-trigger (B-023 WiFi detection) deferred — manual is enough for debugging. |
| Scrum-style iteration | **Build-test-adjust per sprint**. Stories kept small and reversible. Follow-up stories created when a sprint changes direction mid-flight (not edits to existing stories). |

---

## The Phased Plan

### Sprint 7 — Server MVP + Deploy + Loop Live (10 stories)

**Goal**: Deploy an OBD2-Server skeleton to Chi-Srv-01, get both services healthy, and close the Pi→Server→stub AI→Pi round trip.

**Deliverable**: CIO can run `python src/main.py --simulate --scenario <existing scenario>` on the Pi, then run `python scripts/sync_now.py` (new), and watch data land in Chi-Srv-01 MariaDB. `curl http://10.27.27.10:8000/health | jq` returns green. `curl http://10.27.27.10:8000/api/analyze` returns a stub response.

**Stories** (all from existing B-022 or new):

1. **US-CMP-001** — Project Scaffolding and Configuration (B-022)
2. **US-CMP-009** — systemd Service and Deployment (B-022) — **moved up from original position 9**
3. **US-CMP-003** — MariaDB Database Schema and Connection (B-022)
4. **US-CMP-002** — API Key Authentication Middleware (B-022)
5. **US-CMP-004** — Delta Sync Endpoint (B-022)
6. **US-CMP-008** — Health Endpoint with Component Status (B-022) — **moved up from original position 8**
7. **US-147** — Stub AI Analysis Endpoint (new, B-022) — returns canned response, no real Ollama
8. **US-148** — sync_log Table + Delta Query Client (B-027, Pi-side)
9. **US-149** — HTTP Sync Push with Auth + High-Water Mark (B-027, Pi-side)
10. **US-151** — Companion Service Config (B-027, Pi-side)

**Rationale for ordering**: Scaffolding + systemd deployment comes before schema/auth because getting `curl /health` to return 200 on a deployed empty skeleton is a huge unlock — even before any real endpoints exist. Then layer in schema → auth → sync → stub AI.

---

### Sprint 8 — Scenarios + Integration (4 stories)

**Goal**: Create two realistic drive scenarios and run them through the deployed pipeline end-to-end.

**Deliverable**: CIO can run either `town_local_drive.json` or `highway_drive.json` on the Pi, observe the simulated drive hitting realistic coolant/RPM/IAT values, watch sync push to server, verify stub AI response comes back, and debug any step via SSH + `/health`.

**Stories** (all new, in new backlog item B-035):

1. **US-152** — Town Local Drive Scenario (JSON file + simulator validation)
2. **US-153** — Highway Drive Scenario (JSON file + simulator validation)
3. **US-154** — Manual Sync Trigger CLI (`scripts/sync_now.py` — TBD final path after reorg)
4. **US-155** — End-to-End Integration Test (runs scenario → Pi pipeline → mocked server → stub AI)

---

### Sprint 9 — B-022/B-027 Deepening (4 stories)

**Goal**: Finish the deferred B-022 and B-027 work. Replace stub AI with real Ollama integration using Spool's tuning prompts.

**Deliverable**: B-022 fully complete. B-027 fully complete. B-031 (Spool's Server Analysis Pipeline, 7 stories) unblocks — its stories depend on US-CMP-005 being real.

**Stories**:

1. **US-CMP-005** — Real AI Analysis Endpoint (B-022) — supersedes US-147 stub. Real Ollama `/api/chat` integration with Spool-spec prompt templates.
2. **US-CMP-006** — Auto-Analysis on Drive Data Receipt (B-022) — trigger analysis after sync completes, push results back to Pi on next sync.
3. **US-CMP-007** — Backup Receiver Endpoint (B-022) — `.db`/`.log`/`.json`/`.gz` file receiver. Server-side.
4. **US-150** — Backup File Push (B-027) — Pi-side counterpart. Pushes SQLite DB + logs on schedule or on-demand.

---

## New Story Details (US-147 through US-155)

### US-147: Stub AI Analysis Endpoint (B-022, sprint 7)

**As a** developer debugging the Pi→Server→AI→Pi loop, **I want** a minimal stub AI endpoint **so that** the full round-trip can be verified without needing real Ollama integration yet.

**Acceptance Criteria:**
- [ ] `POST /api/analyze` endpoint accepts JSON body: `{drive_id: string, parameters: [...]}`
- [ ] Returns 200 with JSON: `{status: "ok", analysis_id: "stub-{uuid}", message: "Stub analysis — real implementation pending US-CMP-005", recommendations: []}`
- [ ] Response contract matches expected shape from Spool's tuning spec (so US-CMP-005 can slot in without Pi-side changes)
- [ ] Writes request to a log table (`analysis_requests`) for later inspection — fields: id, drive_id, requested_at, response_status
- [ ] API key authentication required (uses US-CMP-002 middleware)
- [ ] Tests validate: success case, missing auth returns 401, malformed body returns 400, log row written on success
- [ ] TBD after arch reorg: module path for analyze endpoint handler

**Why stub first**: Real Ollama integration is substantial (prompt templates, response parsing, error handling for model downtime). Stubbing lets sprint 7 close the loop without blocking on US-CMP-005's complexity. US-CMP-005 in sprint 9 replaces the stub with real logic — same endpoint shape, same response contract, no Pi-side changes needed.

---

### US-148: sync_log Table + Delta Query Client (B-027, sprint 7)

**As a** developer, **I want** the Pi to track which rows have been synced to the server **so that** delta sync only pushes new data without duplicates or data loss.

**Acceptance Criteria:**
- [ ] New `sync_log` table added to Pi SQLite schema:
  - `table_name TEXT NOT NULL`
  - `last_synced_id INTEGER NOT NULL DEFAULT 0`
  - `last_synced_at TEXT`
  - `last_batch_id TEXT`
  - `status TEXT` (values: `ok`, `pending`, `failed`)
  - Primary key on `table_name`
- [ ] Table added to `ALL_SCHEMAS` in Pi database module — **TBD exact path after arch reorg**
- [ ] `ObdDatabase.initialize()` creates the table idempotently
- [ ] New module (TBD path) exposes `getDeltaRows(tableName, lastId, limit)` returning rows where `id > lastId` sorted ascending
- [ ] Tables in scope for delta sync: `realtime_data`, `statistics`, `profiles`, `vehicle_info`, `ai_recommendations`, `connection_log`, `alert_log`, `calibration_sessions`
- [ ] Tables explicitly excluded (Pi-only hardware telemetry): `battery_log`, `power_log`
- [ ] Tests:
  - [ ] Empty sync_log returns all rows as delta
  - [ ] Populated sync_log returns only rows above high-water mark
  - [ ] Batch size limit respected
  - [ ] Excluded tables not queryable via delta client

---

### US-149: HTTP Sync Push with Auth + High-Water Mark (B-027, sprint 7)

**As a** developer, **I want** the Pi to push delta rows to the companion service with authentication and safe high-water mark tracking **so that** data syncs reliably and sync failures don't lose data.

**Acceptance Criteria:**
- [ ] New `SyncClient` class — **TBD module path after arch reorg**
- [ ] `pushDelta(tableName)` method:
  - Reads sync_log for the table's current high-water mark
  - Calls `getDeltaRows()` to get new rows
  - Serializes rows to JSON with source_device identifier
  - POSTs to `{baseUrl}/sync` with `X-API-Key` header
  - On HTTP 200 with valid receipt: updates sync_log `last_synced_id` to highest id in the pushed batch, status `ok`, `last_synced_at` current timestamp
  - On HTTP error or network failure: leaves sync_log unchanged, status `failed`, logs error via existing error_handler
- [ ] API key read from `COMPANION_API_KEY` env var via existing secrets_loader
- [ ] Exponential backoff retry on transient failures: `[1, 2, 4, 8, 16]` seconds, max 3 attempts (matches existing error_handler pattern)
- [ ] Multi-table sync: `pushAllDeltas()` iterates all in-scope tables
- [ ] Tests use mocked HTTP endpoint:
  - [ ] Successful push advances high-water mark
  - [ ] Failed push does NOT advance high-water mark (data loss safety)
  - [ ] Retry logic on transient failures
  - [ ] Missing API key raises configuration error
  - [ ] Auth failure (401 from server) raises authentication error

---

### US-150: Backup File Push (B-027, sprint 9)

**As a** driver, **I want** the Pi to periodically push its SQLite DB and logs to the companion service **so that** a full snapshot backup exists in case of Pi storage failure.

**Acceptance Criteria:**
- [ ] Pushes `eclipse.db` SQLite file to server `/backup` endpoint (depends on US-CMP-007)
- [ ] Pushes rotating log files (`*.log`) to server `/backup` endpoint
- [ ] Multipart form upload with filename + SHA256 content hash
- [ ] Allowed extensions: `.db`, `.log`, `.json`, `.gz` (matches server-side restriction)
- [ ] Runs via CLI on-demand: `python scripts/backup_push.py` — **TBD final path after reorg**
- [ ] Future enhancement: scheduled run (every 24h) — not in this story
- [ ] Tests use mocked endpoint
- [ ] Does NOT block delta sync — backup failure is non-fatal

---

### US-151: Companion Service Config (B-027, sprint 7)

**As a** developer, **I want** companion service configuration in the existing config system **so that** sync behavior can be tuned without code changes.

**Acceptance Criteria:**
- [ ] New `companionService` section added to `src/obd_config.json`:
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
- [ ] `COMPANION_API_KEY=` entry added to `.env.example` with comment
- [ ] ConfigValidator schema updated with new section + defaults (matches existing 3-layer config pattern)
- [ ] When `companionService.enabled: false`, sync attempts return early without error (graceful no-op)
- [ ] Tests validate config loading, defaults, enabled/disabled toggle

---

### US-152: Town Local Drive Scenario (B-035, sprint 8)

**As a** developer, **I want** a scenario JSON file that simulates a typical town drive **so that** the pipeline can be exercised with realistic low-speed data.

**Acceptance Criteria:**
- [ ] New file `src/obd/simulator/scenarios/town_local_drive.json` — **TBD exact path after arch reorg**
- [ ] Matches existing scenario JSON schema (phases array with name, durationSeconds, targetRpm, targetThrottle, targetGear, description)
- [ ] Phase breakdown (total ~17 minutes):
  | Phase | Duration | RPM | Throttle | Gear | Notes |
  |---|---|---|---|---|---|
  | `cold_start` | 10s | 1200 | 0 | 0 | Cold start, high idle |
  | `warmup_idle` | 120s | 900 | 0 | 0 | Idle while warming up |
  | `depart` | 8s | 2500 | 35 | 1 | Pull out of driveway |
  | `stop_go_1` | 45s | 1800-2200 | 15-30 | 2 | Stop sign, accelerate, brake |
  | `cruise_35mph` | 300s | 2200 | 22 | 3 | Main residential cruise (5 min) |
  | `stop_light_1` | 30s | 800 | 0 | 0 | Red light |
  | `cruise_40mph` | 240s | 2400 | 25 | 3 | Faster residential (4 min) |
  | `stop_go_2` | 60s | 1800-2300 | 15-30 | 2 | More stops |
  | `cruise_35mph_back` | 240s | 2200 | 22 | 3 | Return leg (4 min) |
  | `arrive_home` | 15s | 1500 | 5 | 2 | Decel into driveway |
  | `park_idle` | 30s | 850 | 0 | 0 | Idle briefly at rest |
- [ ] Total drive time ~17 minutes, matches CIO spec "15 min of 35-40 mph with stops"
- [ ] Tests validate scenario loads, simulator runs through all phases without errors, coolant reaches normal operating range (~185-200F), no alert triggers (normal drive)
- [ ] CIO can run: `python src/main.py --simulate --scenario town_local_drive` — **TBD final CLI syntax after reorg**

---

### US-153: Highway Drive Scenario (B-035, sprint 8)

**As a** developer, **I want** a scenario JSON file that simulates highway driving **so that** the pipeline can be exercised with sustained higher speed and load.

**Acceptance Criteria:**
- [ ] New file `src/obd/simulator/scenarios/highway_drive.json` — **TBD exact path after arch reorg**
- [ ] Phase breakdown (total ~40 minutes):
  | Phase | Duration | RPM | Throttle | Gear | Notes |
  |---|---|---|---|---|---|
  | `cold_start` | 10s | 1200 | 0 | 0 | Cold start |
  | `warmup_idle` | 120s | 900 | 0 | 0 | Warmup |
  | `local_leg` | 240s | 2000-2400 | 20-28 | 3 | 4 min local to on-ramp |
  | `on_ramp` | 15s | 4000 | 60 | 3 | Merge acceleration |
  | `highway_cruise_65` | 900s | 2800 | 30 | 5 | 15 min at 65 mph |
  | `highway_cruise_75` | 900s | 3200 | 35 | 5 | 15 min at 75 mph |
  | `off_ramp` | 20s | 2200 | 10 | 5 | Decel |
  | `local_return` | 180s | 2000-2400 | 20-28 | 3 | 3 min local back |
  | `arrive_home` | 15s | 1500 | 5 | 2 | Arrive |
  | `park_idle` | 30s | 850 | 0 | 0 | Idle |
- [ ] Total drive time ~40 minutes, matches CIO spec "warmup → 2-5 min local → 30 min highway 65-75 mph → back local → home"
- [ ] Tests validate higher RPM sustained, IAT climbs (heat soak simulation), boost (if enabled in simulator) reaches realistic values, coolant stays below caution threshold (<210F)
- [ ] CIO can run: `python src/main.py --simulate --scenario highway_drive` — **TBD final CLI syntax after reorg**

---

### US-154: Manual Sync Trigger CLI (B-035, sprint 8)

**As a** developer debugging the sync pipeline, **I want** a CLI script that triggers a one-shot delta sync **so that** I can manually push data to the server and observe the result without waiting for auto-trigger logic.

**Acceptance Criteria:**
- [ ] New script `scripts/sync_now.py` — **TBD final path after arch reorg**
- [ ] Loads `obd_config.json` via existing config system
- [ ] Instantiates `SyncClient` (from US-149)
- [ ] Calls `pushAllDeltas()` for all in-scope tables
- [ ] Prints summary:
  ```
  Sync started: 2026-04-13 14:32:05
  Config: baseUrl=http://10.27.27.10:8000, batchSize=500
  
  realtime_data: 247 new rows → pushed → server accepted (batch_id: abc123)
  statistics: 12 new rows → pushed → server accepted (batch_id: abc124)
  alert_log: 0 new rows → nothing to sync
  ...
  
  Total: 259 rows pushed across 2 tables
  Elapsed: 1.8s
  Status: OK
  ```
- [ ] Exit code 0 on success, 1 on any sync failure (with error summary printed)
- [ ] Works against empty DB (prints "Nothing to sync")
- [ ] Works when server is unreachable (prints timeout/connection error, exits 1, does NOT advance sync_log)
- [ ] Tests use mocked SyncClient

---

### US-155: End-to-End Integration Test (B-035, sprint 8)

**As a** developer, **I want** an integration test that runs a full scenario → Pi pipeline → mocked server loop **so that** regressions in the pipeline are caught before deployment.

**Acceptance Criteria:**
- [ ] New test file `tests/test_e2e_pipeline.py` — **TBD final path after arch reorg**
- [ ] Marked `@pytest.mark.slow` and `@pytest.mark.integration`
- [ ] Test 1 — town scenario:
  - Fresh Pi SQLite DB in `tmp_path`
  - Run `town_local_drive.json` through simulator with `time_scale=10.0` (17-min drive → 1.7 min test)
  - Verify `realtime_data` row count in expected range (e.g., ~4000 rows for 17 min at 5Hz polling average)
  - Verify drive_detector triggered start and end events
  - Verify statistics calculated for the drive
  - Mock companion service HTTP endpoint, run SyncClient, assert correct delta rows sent
- [ ] Test 2 — highway scenario: same pattern with `highway_drive.json`
- [ ] Tests use existing test fixtures where possible
- [ ] TBD after reorg: exact import paths, may need adjustment

**Not in scope**: Actual deployed-pipeline test (that's manual verification per CIO directive). This is code-path-only integration.

---

## Backlog Structure Summary

| Action | Item | Changes |
|---|---|---|
| **Update** | B-022 | Add US-147 story. Add notes marking US-CMP-001/002/003/004/008/009 + US-147 as "sprint 7 batch" and US-CMP-005/006/007 as "sprint 9 batch". Status stays `groomed` until sprint 7 loads. |
| **Update** | B-027 | Write the PRD section with 4 stories (US-148 through US-151). Status → `groomed`. |
| **Create** | B-035 | New backlog item "Infrastructure Pipeline Scenarios + Integration". Contains US-152, US-153, US-154, US-155. Status → `groomed`. |
| **Update** | `backlog.json` | Add US-147 to B-022, create B-027 stories array, create B-035 entry. Update stats. |
| **Update** | `story_counter.json` | nextId: 146 → 156 |

---

## Dependencies and Risks

### Dependency Chain

```
Sprint 7 (Server MVP + Pi Client MVP)
  ├── US-CMP-001 → US-CMP-009 → US-CMP-003 → US-CMP-002 → US-CMP-004 (server)
  ├── US-CMP-008 (health — independent, can run parallel)
  ├── US-147 (stub AI — depends on US-CMP-002)
  ├── US-148 → US-149 → US-151 (Pi client — independent of server until US-149)
  └── CHECKPOINT: curl /health green from Pi, sync_now.py pushes data successfully
  
Sprint 8 (Scenarios + Integration)
  ├── US-152, US-153 (data files — no deps)
  ├── US-154 (depends on sprint 7 being live)
  ├── US-155 (depends on US-152, US-153)
  └── CHECKPOINT: both scenarios run end-to-end against deployed pipeline

Sprint 9 (Deepening)
  ├── US-CMP-005 (real AI — supersedes US-147)
  ├── US-CMP-006 (auto-trigger — depends on US-CMP-005)
  ├── US-CMP-007 + US-150 (backup send/receive — paired)
  └── CHECKPOINT: B-022 fully complete, B-031 unblocks
```

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Sprint 7 is too big (10 stories) | Medium | Medium | Ralph can split mid-sprint. US-CMP-001+009 is a natural first checkpoint (deployed empty scaffold). |
| MariaDB schema wrong in sprint 7 | Medium | Medium | US-CMP-003 ACs include concrete table shape. Easy fix in follow-up story. |
| Stub AI response shape doesn't match real Ollama output | Low | Low | Define contract in US-147 to match Spool's expected structure. Real Ollama slots in unchanged. |
| Physics sim produces unrealistic values for new scenarios | Medium | Low | Sprint 8 integration test catches it. Tuning phase parameters is a quick follow-up. |
| Chi-Srv-01 firewall blocks port 8000 | Low | Medium | Pre-verify connectivity in first sprint 7 checkpoint. SSH already works. |
| Real Bluetooth work invalidates pipeline assumptions | Low | Medium | Pipeline is agnostic to data source. Physics sim vs real OBD both produce the same DB rows. |

### Open Questions (Defer to Ralph During Implementation)

1. Async MySQL driver choice: `aiomysql` vs `asyncmy` vs sync `pymysql`
2. Alembic migrations or raw SQL schema files?
3. How to seed MariaDB test data for CI/local testing?
4. Sync endpoint: batched multi-table deltas or one table per request?
5. AI analysis response JSON shape (defer to sprint 9, use reasonable stub in sprint 7)

---

## Finalization Checklist — Before Promoting to Active

When Ralph completes his architectural reorg, walk this checklist:

- [ ] Re-read `src/` tree post-reorg — identify new module paths
- [ ] Update all `TBD after arch reorg` markers in this PRD with real paths:
  - [ ] US-147: analyze endpoint handler module path
  - [ ] US-148: `ObdDatabase` path, new sync module location
  - [ ] US-149: `SyncClient` module path
  - [ ] US-150: backup push script path
  - [ ] US-152, US-153: simulator scenarios directory path
  - [ ] US-154: `sync_now.py` script path
  - [ ] US-155: e2e test file path
- [ ] Verify existing scenario format (`city_driving.json`) still matches after reorg
- [ ] Verify `ALL_SCHEMAS` constant location for adding `sync_log`
- [ ] Verify secrets_loader and ConfigValidator patterns are unchanged
- [ ] Verify test fixture patterns (`tmp_path`, etc.) still work
- [ ] Spell-check and self-review the PRD
- [ ] Change status banner from `DRAFT` to `ACTIVE — promoted YYYY-MM-DD`
- [ ] Remove finalization checklist (or archive it in an "Implementation Notes" appendix)
- [ ] Create/update backlog items:
  - [ ] Update `B-022.md` with US-147 story + sprint split notes
  - [ ] Update `B-027.md` with 4-story PRD section
  - [ ] Create `B-035.md` with 4-story PRD section
  - [ ] Update `backlog.json` with new items + stats
  - [ ] Update `story_counter.json` nextId to 156
- [ ] Commit all changes as single clean commit
- [ ] Update `projectManager.md` session handoff to reflect promotion
- [ ] Coordinate with CIO on sprint 7 launch timing

**Only after every box above is checked does this PRD become active.**

---

## Approval Trail

| Date | Who | What |
|---|---|---|
| 2026-04-13 | CIO | Confirmed Option C scope, Approach A simulation, Option B debugging, scrum-style iteration |
| 2026-04-13 | Marcus (PM) | Drafted PRD based on brainstorm |
| TBD | CIO | Review promoted version before sprint 7 launch |

---

## Related Files (Current — Update After Reorg)

| File | Purpose | Reorg-Sensitive? |
|---|---|---|
| `offices/pm/backlog/B-022.md` | Companion Service parent | No |
| `offices/pm/backlog/B-027.md` | Client Sync parent | No |
| `offices/pm/prds/prd-companion-service.md` | B-022 existing PRD | No |
| `offices/pm/inbox/2026-04-10-from-spool-system-tuning-specifications.md` | Spool's original spec (informs US-CMP-005 sprint 9) | No |
| `offices/ralph/inbox/2026-04-12-from-marcus-architectural-decisions-brief.md` | Architectural context for Ralph | No |
| `src/obd/simulator/scenarios/` | Where new scenarios live | **YES — may move** |
| `src/obd/database.py` or equivalent | Where `sync_log` table gets added | **YES — may move** |
| `src/alert/` module | Alert threshold integration context | **YES — may move** |
| `scripts/` directory | Where sync_now.py and backup_push.py live | **YES — may move** |
| `tests/` directory | Where test_e2e_pipeline.py lives | **YES — may move** |

---

*"Build the minimum pipeline that lets us debug end-to-end. Real hardware slots in when ready. Don't over-engineer before we have real data to learn from."*

— Marcus, 2026-04-13
