# B-041: Analytics Excel Export CLI

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Medium                 |
| Status       | Pending                |
| Category     | infrastructure         |
| Size         | M                      |
| Related PRD  | None (not yet groomed) |
| Dependencies | B-036 (Server) — needs read-only GET endpoints for drives, statistics, realtime_data. Most do not exist yet. |
| Created      | 2026-04-16             |

## Description

A Windows-friendly Python CLI that pulls analytics and raw telemetry from the
companion server and writes them to a single multi-sheet Excel workbook so the
CIO can view and do his own slicing/analysis outside the server's built-in
reports.

The motivation is that the server's `scripts/report.py` renders fixed-layout
text reports. Those are good for at-a-glance checks, but the CIO wants to pull
the underlying data into Excel to explore — pivot, chart, compare drives
side-by-side, build his own dashboards, and learn what the analytics pipeline
is actually producing.

The tool is **HTTP-only** — it authenticates to the server via the existing
`X-API-Key` middleware (US-CMP-002) and assumes no direct SQL access. That
keeps the tool portable, safe to share, and future-proofs it for running off a
laptop in the garage.

## Scope

**In scope:**
- CLI runs from any Windows (or Linux/Mac) machine with the project venv.
- Single `.xlsx` output per invocation with multiple sheets.
- Three logical payloads per run, each a sheet:
  - **Drives** — drive_summary rows in the filter window (summary).
  - **Statistics** — per-drive, per-parameter aggregates (summary).
  - **Realtime** — raw realtime_data rows for the filtered drives and
    selected PIDs (detail).
- Filter parameters:
  - `--start-date YYYY-MM-DD` / `--end-date YYYY-MM-DD` (inclusive, on drive
    `start_time`).
  - `--drive-id N` (repeatable) — explicit drive IDs; overrides the date
    filter when both are given.
  - `--device-id STR` — restrict to one vehicle (default: all).
  - `--params RPM,SPEED,COOLANT_TEMP` — subset the realtime sheet; default
    is the "basic PID set" (see Grooming Questions).
  - `--output path.xlsx` — output file path.
- Graceful error handling for the common cases: bad API key (401), unknown
  drive id (404), empty result (writes a workbook with empty sheets and
  warns).

**Out of scope (can follow in a future backlog item):**
- Charts embedded in the workbook (Excel handles that).
- AI analysis / recommendations sheet (US-CMP-005 Server Run phase owns that).
- Parity with ECMLink CSV format.
- Scheduled/automated runs (manual CLI only).

## Acceptance Criteria

- [ ] `python scripts/export_analytics.py --help` prints usage and all flags.
- [ ] Tool runs successfully on Windows against `chi-srv-01:8000` using
      `X-API-Key` from env var or `--api-key` flag.
- [ ] Running with no filter produces a workbook containing all drives in the
      server, with row counts matching a direct MariaDB query.
- [ ] `--start-date 2026-04-16 --end-date 2026-04-16` returns only drives
      whose `start_time` falls in that range (inclusive).
- [ ] `--drive-id 7 --drive-id 8` returns exactly those drives and ignores
      any date filter that was also given.
- [ ] Realtime sheet contains only the PIDs named in `--params`, in the
      given order as columns, with timestamp + parameter_value rows per
      drive.
- [ ] Workbook opens cleanly in Excel with no repair warning.
- [ ] A wrong/missing API key returns a clean error message, not a stack
      trace.
- [ ] Tool documents its HTTP API expectations so when server endpoints
      evolve, the coupling point is obvious (single client module with
      one function per endpoint).

## Validation Script Requirements

**Input:** Tool invoked with a known filter against the deployed server.

**Expected Output:**
- An `.xlsx` file at the path passed to `--output`.
- Drives sheet row count matches `SELECT COUNT(*) FROM drive_summary WHERE ...`
- Statistics sheet row count matches `SELECT COUNT(*) FROM statistics` scoped
  to the filtered drives.
- Realtime sheet row count = sum of filtered drives' `row_count` values for
  the selected PIDs.

**Database State:** Read-only — the tool writes nothing back to the server.

**Test Program:** Use `data/regression/inputs/day1.db` plus the existing
Session 17 fixtures as the deterministic dataset. Expected Excel outputs
should be snapshotted in `data/regression/expected/excel/` once the format
stabilizes.

## Grooming Questions (must answer before PRD)

1. **Default "basic PID" set.** Two candidate lists exist:
   - Spool Gate 1 primary-screen params: `RPM, COOLANT_TEMP, INTAKE_PRESSURE
     (boost proxy), O2_B1S1 (AFR proxy pre-ECMLink), SPEED,
     CONTROL_MODULE_VOLTAGE`.
   - Phase 1 Core 5 (health focus): `SHORT_FUEL_TRIM_1, COOLANT_TEMP, RPM,
     TIMING_ADVANCE, ENGINE_LOAD`.
   - Pick one as the default, expose the other via `--params`.
2. **API-key provisioning for the Windows user.** Today the server's
   `X-API-Key` is a single shared value from `.env`. Fine for now. Flag for
   later if we add multiple clients.
3. **Excel engine.** `openpyxl` (pure Python, in most environments) or
   `xlsxwriter` (faster for large sheets, streaming). Realtime detail sheet
   on a full day ≈ 8k rows × 6 params = ~50k cells per drive — openpyxl is
   fine. Decide in the PRD.

## Notes

- Server work that must precede the CLI:
  - `GET /api/v1/drives?start_date=&end_date=&device_id=` — list drive_summary
  - `GET /api/v1/drives/{id}/statistics` — stats for one drive
  - `GET /api/v1/drives/{id}/realtime?params=` — raw telemetry
  - Or a single batched `GET /api/v1/export?...` that returns all three as
    JSON and lets the client assemble the workbook. Simpler to build, simpler
    to version. Leaning toward batched.
- Windows compatibility:
  - Excel CSV/xlsx files opened in Windows Excel should use `newline=''` when
    written from Python (already a project convention per CLAUDE.md).
  - No path separator assumptions — use `pathlib.Path`.
- Related reports already in the server:
  - `scripts/report.py` renders text reports that cover the same underlying
    data. The CLI doesn't replace it — it exposes the raw data for offline
    analysis.
- This tool is the CIO's primary "understand what the system is producing"
  interface until a real GUI exists. Keep it boring, reliable, and easy to
  run.
