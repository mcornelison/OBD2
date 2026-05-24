# B-071: Drive 11+ end-to-end forensic instrumentation (capture full V0.27 chain IRL validation in one drive)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Medium (P2) -- diagnostic prep; gates the IRL validation cascade |
| Status       | Pending (V0.27.5 candidate) |
| Category     | observability / diagnostics |
| Size         | S                      |
| Related PRD  | None                   |
| Dependencies | None (lands BEFORE B-063 + Drive 11+; observability-only; no behavior change) |
| Created      | 2026-05-10             |

## Description

V0.27 chain has 8 IRL bigDoD clauses pending validation, all gated on Drive 11+ post-B-063 fuse-box wiring. When that drive finally happens, we want to capture EVERY piece of evidence needed to validate the full chain in ONE drive (no "second drive needed for diagnostic re-run" pattern).

This story adds defensive INFO log instrumentation at key state transitions so the journalctl trail from Drive 11+ is sufficient for full chain IRL validation. **Pure observability; no behavior change.**

Same pattern as V0.27.2 US-307 (forensic instrumentation for B-062) -- evidence-gathering at known transition points so the next IRL drill produces a clean discriminator without code surprises.

## Target instrumentation surfaces

### 1. DriveDetector state transitions (for I-019 / US-311 IRL validation)

Add INFO log lines at:
- `_checkDriveStart` entry + exit (logs RPM, SPEED, current DriveState, MIN_INTER_DRIVE_SECONDS check result)
- `_checkDriveEnd` entry + exit (logs the ECU-silence + RPM-debounce timers)
- KEY_OFF -> ACTIVE transitions (warm-restart path Spool's I-019 hypothesizes)
- ApplicationOrchestrator init path on warm-restart (TD-036 territory; one of I-019's 4 candidate hypotheses)

### 2. drive_summary writer call sites (for US-310 + US-317 validation)

Add INFO log lines at:
- `_ensureDriveSummary` entry (logs drive_id + which fields are about to write + pingOllama state)
- Backfill paths A/B/C entry + summary (already mostly logged per Ralph's V0.27.4 work; verify completeness)
- Pi-sync drive_summary INSERT (Pi side) entry

### 3. Sync UPDATE propagation per-table (for US-315 B-065 validation)

Add INFO log lines at:
- sync client `_pushTable` for tables in SUPPORTS_UPDATE_SYNC (battery_health_log, drive_summary, dtc_log, connection_log if applicable)
- last_modified_synced cursor advance event
- Server-side UPSERT acknowledgment

### 4. drive_counter advance + sync push (for V0.27.3 US-314 watch-item resolution)

Add INFO log lines at:
- Pi-side `incrementDriveCounter` (drive_id.py)
- Sync push of drive_counter row
- Server-side drive_counter UPSERT

## Acceptance Criteria

- [ ] Pre-flight audit: rg `logger.info|logger.debug` src/pi/obdii/drive/ src/pi/obdii/drive_summary.py src/pi/sync/ src/pi/obdii/drive_id.py -- map existing instrumentation gaps; document targets in completionNotes
- [ ] INFO log lines added at the 4 target surfaces above; each log includes timestamp + state context + relevant identifiers (drive_id / source_id / row_id / table_name)
- [ ] No behavior change anywhere -- only log emission added; existing tests stay GREEN
- [ ] New test (`tests/pi/diagnostics/test_drive_11_forensic_logging.py`) asserts that a synthetic drive_start -> drive_end sequence emits >= N INFO log lines covering the 4 target surfaces; would FAIL pre-fix because the log lines don't exist

## Validation Script Requirements

- **Input**: any post-V0.27.5-deploy drive (synthetic OR Drive 11+ IRL)
- **Expected Output**: journalctl trail includes INFO log lines for DriveDetector state transitions + drive_summary writes + sync UPDATE propagation + drive_counter advance
- **Database State**: unchanged (this is logging only; no DB writes)
- **Test Program**: synthetic e2e test asserts log line counts + content patterns

## Why this matters for V0.27 chain validation

Without B-071, Drive 11+ IRL data analysis = "look at DB rows + hope the trail tells the story." With B-071, Drive 11+ IRL data analysis = "grep journalctl for known tokens, get exact transition timeline, validate each bigDoD clause from log evidence."

Concretely:
- I-019 / US-311 root cause identification: log lines at DriveDetector transitions discriminate the 4 hypotheses immediately
- US-310 / US-317 drive_summary validation: log lines at writer entry confirm `_ensureDriveSummary` called regardless of Ollama state
- US-315 / B-065 sync validation: log lines confirm modified_at cursor advance + server UPSERT acknowledgment
- US-314 watch-item resolution: log lines confirm drive_counter advance propagates

One Drive 11+ produces evidence for ALL 8 pending V0.27 chain bigDoD clauses. Without B-071, expect 2-3 follow-up drives to chase down what didn't get logged.

## Cross-references

- V0.27.2 US-307 (forensic instrumentation for B-062) -- same pattern; PM standing rule from BL-012 Option A
- B-063 hardware blocker (gates Drive 11+ regardless)
- I-019 + US-311 + US-310 + US-317 + US-315 + US-314 -- all benefit from this instrumentation
- `offices/tuner/drain-test-procedure.md` (Spool's drill protocol -- Drive 11+ checklist will reference these log tokens)

## Source

CIO 2026-05-10 Session 31 directive: "add any non drive required bug fixes or or drive required diagnostics" -- this story is the diagnostics half of that bracket.
