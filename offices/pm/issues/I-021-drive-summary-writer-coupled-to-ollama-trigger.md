# I-021: drive_summary writer is short-circuited when Ollama unreachable + backfill script gap

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | High                      |
| Status       | Open (V0.27.4 candidate)  |
| Category     | infrastructure / data integrity |
| Found In     | `src/server/services/analysis.py:1025-1069` (`enqueueAutoAnalysisForSync`) + `scripts/backfill_drive_summary_analytics_fields.py` |
| Found By     | Spool 2026-05-10 audit (V0.27.4 grooming pass) |
| Related      | V0.27.3 US-310 (function correctly implemented but caller short-circuits); B-059 (Spec 3 contract) |
| Created      | 2026-05-10                |

## Description

V0.27.3 US-310 satisfies Spool's Spec 3 12-field contract correctly in `_ensureDriveSummary()` at `src/server/services/analysis.py:879`. **HOWEVER** -- `_ensureDriveSummary` is called from `enqueueAutoAnalysisForSync` (line 1025-1069) which short-circuits if Ollama is unreachable:

```python
if not await pingOllama(ollamaBaseUrl):
    logger.warning("Auto-analysis skipped: Ollama unreachable...")
    return False  # <-- _ensureDriveSummary never called
```

**If Ollama is down at sync time, drive_summary rows are never created or updated** -- regardless of US-310's correctness. The two responsibilities (populate drive_summary metadata vs. run AI analysis) are bundled when they should be independent.

## Empirical evidence

Server-side `obd2db.drive_summary` post-V0.27.3 deploy (2026-05-10):

```sql
SELECT id, source_id, drive_id, start_time, end_time FROM drive_summary ORDER BY id DESC LIMIT 5;
-- Returns ONLY 3 rows for drives 3, 4, 5 (legacy NULL drive_id)
-- Drives 6, 7, 8, 9, 10 have NO drive_summary row at all
```

Drives 6-10 should have populated rows post-V0.27.3 -- they don't. Either Ollama was down during one or more sync cycles, OR the trigger logic isn't firing. **Either way the design is fragile** -- US-310's writer correctness is gated on a separate service (Ollama) being up.

## Bonus finding (related; same fix story)

`scripts/backfill_drive_summary_analytics_fields.py` (V0.27.3-shipped backfill tool) **filters on `drive_id IS NOT NULL`**, which:
- **Excludes drives 3-5** (legacy rows have NULL drive_id on server)
- **Won't INSERT new rows for drives 6-10** (no row to update because Ollama short-circuited the writer)

Backfill script can't recover the historical state. Worth extending the script to handle both cases (NULL drive_id + missing row) in the same fix.

## Steps to Reproduce

1. Stop Ollama on chi-srv-01: `sudo systemctl stop ollama`
2. Trigger sync from Pi: `sync_now.py` or normal sync cadence
3. Observe: server-side drive_summary rows NOT created for drives that synced during Ollama-down window
4. Restart Ollama: `sudo systemctl start ollama`
5. Trigger sync again: drive_summary rows STILL NOT created (no retry mechanism for the Ollama-skipped path)

## Expected Behavior

`_ensureDriveSummary` runs UNCONDITIONALLY on every sync that includes drive_end events. Ollama auto-analysis is a SEPARATE step that runs only when Ollama is up.

```python
# Proposed fix shape:
await _ensureDriveSummary(...)  # always runs -- writes 12-field row
if not await pingOllama(ollamaBaseUrl):
    logger.warning("Auto-analysis skipped: Ollama unreachable; drive_summary still written")
    return True  # drive_summary written, just no AI analysis
# ... continue with AI analysis path
```

## Actual Behavior

Drive_summary rows for drives 6-10 are missing on server. Spool's tuning analysis is blocked because the rows that should reflect Drives 6-10 don't exist; backfill script can't help because it filters on NULL drive_id.

## Impact

- **V0.27.3 US-310 fix is effectively inert in production** -- correctly-implemented writer never gets called when Ollama is unreachable
- Spool's tuning analysis blocked; per-drive grading + analysis_history + drive_statistics all downstream-blocked because drive_summary rows don't exist
- Manual data recovery requires SSH + sqlite query + manual UPSERTs for drives 6-10 -- not scalable
- **All future drives are at risk** of being silently skipped if Ollama has any downtime during sync windows

## Resolution (V0.27.4 candidate -- US-317)

Two-part fix:

1. **Decouple `_ensureDriveSummary` from Ollama trigger** in `enqueueAutoAnalysisForSync`:
   - Call `_ensureDriveSummary` FIRST (always runs)
   - Then `pingOllama` for the analysis-only path
   - Two-line code change

2. **Extend backfill script** to handle both cases:
   - Rows with NULL drive_id (drives 3-5) -- UPDATE the existing rows with computed analytics fields
   - Drives without rows entirely (drives 6-10+) -- INSERT new rows from realtime_data + connection_log evidence
   - Preserve idempotency + --dry-run support

## Acceptance Criteria

- [ ] Pre-flight audit: rg `_ensureDriveSummary|enqueueAutoAnalysisForSync|pingOllama` src/server/ -- map ALL call sites; confirm only `enqueueAutoAnalysisForSync` couples writer to ping
- [ ] `enqueueAutoAnalysisForSync` calls `_ensureDriveSummary` UNCONDITIONALLY; pingOllama gates only the analysis step
- [ ] `scripts/backfill_drive_summary_analytics_fields.py` extended to (a) UPDATE existing NULL-drive_id rows + (b) INSERT new rows for drives without entries
- [ ] Integration test asserts: Ollama-down + sync arrives -> drive_summary row WRITTEN; Ollama-up + sync arrives -> drive_summary row written + AI analysis enqueued; would FAIL pre-fix on the Ollama-down case
- [ ] Backfill script tested against a synthetic DB with drives 3-5 NULL + drives 6-10 missing rows; both paths handled correctly + idempotent

## Cross-references

- V0.27.3 US-310 (closes B-059) -- `_ensureDriveSummary` correctly implemented; this story fixes the COUPLING that prevents it from running
- Spool 2026-05-10 V0.27.4 audit note (`offices/pm/inbox/archive/2026-05/2026-05-10-from-spool-v0274-bug-fix-candidates-from-spool-audit.md`) Item 2
- Server-side analysis pipeline downstream: analysis_history (0 rows) + drive_statistics (0 rows) -- these will start producing rows once drive_summary is reliably populated post-fix
