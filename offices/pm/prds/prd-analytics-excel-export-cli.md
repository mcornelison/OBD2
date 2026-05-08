# PRD: Analytics Excel Export CLI

| Field        | Value                                            |
|--------------|--------------------------------------------------|
| Backlog Item | B-041                                            |
| Status       | **GROOMED 2026-05-05** -- ready for sprint inclusion |
| Priority     | Medium                                           |
| Size         | M                                                |
| Owner        | Marcus (PM)                                      |
| Created      | 2026-04-16 (B-041) -> Groomed 2026-05-05         |
| Sprint       | Sprint 27+ candidate (Sprint 26 already loaded with B-047 + B-053 candidates) |

## Background

Windows-friendly Python CLI that pulls analytics + raw telemetry from chi-srv-01 and writes a single multi-sheet `.xlsx` workbook for offline analysis. CIO uses Excel for pivots / charts / drive comparisons. The server's `scripts/report.py` renders fixed-layout text reports; this CLI exposes the underlying data for exploration.

Tool is HTTP-only -- authenticates via existing `X-API-Key` middleware (US-CMP-002). No direct SQL access -> portable, safe to share, future-proof for laptop-in-garage use.

## Resolved design decisions (CIO 2026-05-05)

### D1 -- Default `--params` PID set: Phase 1 Core 5
**Resolution**: `SHORT_FUEL_TRIM_1, COOLANT_TEMP, RPM, TIMING_ADVANCE, ENGINE_LOAD`

**Rationale**: tuning-data focus matches the project's stated workflow (collect OBD-II -> AI analyze -> inform ECMLink V3 tuning). STFT/timing/load are the X/Y axes of fuel + timing maps; they're the lookup-table values CIO will be staring at when prepping the ECMLink install. The Spool Gate 1 primary-screen list (RPM/COOLANT/INTAKE_PRESSURE/O2_B1S1/SPEED/CONTROL_MODULE_VOLTAGE) is the "driver's-eye view" alternative -- exposed via `--params` flag for users who want it.

### D2 -- API key provisioning: shared `.env` value
**Resolution**: Single `X-API-Key` from `.env`. Same key used by the Pi sync path (US-201 / US-CMP-002). No multi-client gating today.

**Future flag**: if multi-client provisioning ever ships, expand to per-client API keys. Out of scope for B-041.

### D3 -- Excel engine: `openpyxl`
**Resolution**: Pure Python; ubiquitous in venvs; ~50k cells/drive (8k rows x 6 params on a full day) is well within `openpyxl`'s capacity per the file-size estimate in B-041. No xlsxwriter dependency added.

**Stop condition**: if a future use case requires >500k cells/sheet (a multi-month aggregate?), revisit and consider `xlsxwriter` for streaming write performance. Not blocking today.

### D4 -- API shape: BATCHED with PAGINATED options for big data sets
**Resolution**: Single batched endpoint `GET /api/v1/export?...` returns all 3 payloads (drives + statistics + realtime) as JSON. Client assembles workbook.

**Pagination addition** (CIO 2026-05-05): when result set exceeds a configured threshold (proposed default: **5000 realtime_data rows** -- subject to load testing), server paginates via `?cursor=<last-id>&limit=<n>` URL params. Client follows pagination links and concatenates results before workbook write.

**Rationale**:
- Single endpoint = simpler to build, simpler to version, single auth round-trip (vs 3 separate GETs with their own auth + retry handling)
- Pagination protects against multi-day or all-vehicle exports overwhelming server memory + breaking the chi-srv-01 -> CLI HTTP timeout
- Drives + statistics payloads are bounded (1 row per drive, ~10s of drives total in a typical query window) and never need pagination -- only realtime_data accumulates rows
- Client-side concatenation is mechanical (extend a list across page fetches) -- no architectural complexity

**Pagination contract** (PRD detail):
- Response includes `pagination: {hasMore: bool, nextCursor: <id> | null, pageSize: int, totalEstimate: int | null}`
- Client follows `nextCursor` until `hasMore=false`
- Per-page row cap configured server-side (default 5000); client respects whatever the server returns
- If a cursor becomes invalid mid-walk (server restart / data gap), error response shape: `{error: "cursor_invalid", restartFromCursor: null}` -> client retries from page 1 with a warning
- Empty result set still returns one page with `hasMore: false` + empty arrays -- client writes empty-sheet workbook with warning

## Scope (final)

**In scope:**
- CLI runs from any Windows / Linux / Mac with project venv
- Single `.xlsx` output per invocation; 3 sheets
  - **Drives** -- `drive_summary` rows in filter window (summary)
  - **Statistics** -- per-drive, per-parameter aggregates (summary)
  - **Realtime** -- raw `realtime_data` rows for filtered drives + selected PIDs (detail; pagination-driven)
- Filters:
  - `--start-date YYYY-MM-DD` / `--end-date YYYY-MM-DD` (inclusive on `start_time`)
  - `--drive-id N` (repeatable; overrides date filter when both given)
  - `--device-id STR` (default: all)
  - `--params RPM,SPEED,COOLANT_TEMP` (default: D1 Phase 1 Core 5)
  - `--output path.xlsx`
- Pagination handling per D4 (transparent to user; CLI shows progress when `--verbose`)
- Graceful error handling: 401 (bad API key), 404 (unknown drive id), empty result (warn + write empty-sheet workbook)

**Out of scope (B-041 / future):**
- Embedded charts (Excel handles charting)
- AI analysis / recommendations sheet (US-CMP-005 server side owns)
- ECMLink CSV-format parity
- Scheduled/automated runs

## Acceptance Criteria

- [ ] `python scripts/export_analytics.py --help` prints usage + all flags
- [ ] Tool runs successfully on Windows against `chi-srv-01:8000` using `X-API-Key` from env or `--api-key`
- [ ] No filter -> workbook contains all drives in server; row counts match direct MariaDB query
- [ ] `--start-date YYYY-MM-DD --end-date YYYY-MM-DD` returns only drives whose `start_time` falls in that range (inclusive)
- [ ] `--drive-id 7 --drive-id 8` returns exactly those drives; ignores any date filter also given
- [ ] Realtime sheet contains ONLY the PIDs named in `--params`, in given order, with `timestamp + parameter_value` rows per drive
- [ ] **Default `--params` is the D1 Phase 1 Core 5** (verifiable via `--help` output + behavior with no `--params` flag)
- [ ] Workbook opens cleanly in Excel with no repair warning
- [ ] Bad/missing API key returns clean error message; no stack trace
- [ ] HTTP API expectations documented (single client module, one function per endpoint surface) so server-side endpoint evolution has obvious coupling point
- [ ] **Pagination correctness** (D4): synthetic test simulates server response with `hasMore: true` -> client follows `nextCursor` -> assembles full result set -> workbook row count matches `SUM(filtered drives.row_count)` for selected PIDs

## Validation Script Requirements

**Input**: tool invoked with known filter against deployed server.

**Expected output**:
- `.xlsx` at `--output` path
- Drives sheet row count = `SELECT COUNT(*) FROM drive_summary WHERE <filter>`
- Statistics sheet row count = `SELECT COUNT(*) FROM statistics` scoped to filtered drives
- Realtime sheet row count = `SUM(filtered drives.row_count)` for selected PIDs

**Database state**: read-only.

**Test program**: use `data/regression/inputs/day1.db` + Session 17 fixtures as deterministic dataset. Snapshot expected workbooks in `data/regression/expected/excel/` once format stabilizes.

## Sprint sizing (to fold into sprint-grooming time)

Estimated 3-4 stories:

| # | Title | Size | Notes |
|---|---|---|---|
| 1 | Server `GET /api/v1/export` batched endpoint with pagination | M | Server-side; new endpoint reading drive_summary + statistics + realtime_data with cursor pagination |
| 2 | Client CLI scaffold + auth + flags | S | Argument parsing + X-API-Key header + error handling; openpyxl workbook scaffolding |
| 3 | Pagination walking + workbook assembly | M | Client reads pages; assembles realtime sheet correctly; runtime test against staged paginated server |
| 4 | Regression fixture + snapshot tests | S | data/regression/expected/excel/ snapshot baseline |

Total ~7 size points; single-sprint fit. Could go in Sprint 27 or later (Sprint 26 already loaded with B-047 + B-053 candidates).

## Operator-action gates (action items, NOT sprint stories per Sprint 19+ rule)

- CIO runs the CLI against deployed server post-ship; confirms Excel opens cleanly + row counts match expectations
- CIO chooses pagination threshold default (proposed 5000 realtime_data rows; tunable in server config)

## Related

- **B-036 Server Companion Service** -- complete; provides the HTTP infrastructure + auth pattern this CLI consumes
- **US-CMP-002 X-API-Key middleware** -- complete; this CLI's auth pattern
- **scripts/report.py** -- existing text report; this CLI is a complementary "raw data for offline analysis" tool, not a replacement
- **B-053 sync cadence (Option 2 approved)** -- orthogonal; B-053 is about Pi -> server write cadence; B-041 is about server -> Excel read pattern. Pagination here parallels B-053's "ACTIVE cadence vs IDLE heartbeat" pattern -- both are about not overwhelming the network with bulk transfers.
