# I-018: src/server/analytics/calibration.py crashes on import (stdlib types.py shadow + missing baselines table)

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | High                      |
| Status       | Open                      |
| Category     | infrastructure / database |
| Found In     | `src/server/analytics/calibration.py` (entry); `src/server/analytics/types.py` (shadow source) |
| Found By     | CIO (Mike), 2026-05-09; reproduced by Marcus (PM) |
| Related B-   | None (V0.27.3 candidate)  |
| Created      | 2026-05-09                |

## Description

`python src/server/analytics/calibration.py --calibrate --apply` crashes before it can even attempt to calibrate. Two stacked failure layers:

1. **Layer 1 (blocking import)**: `src/server/analytics/types.py` shadows the Python stdlib `types` module. When `calibration.py:52` does `import statistics`, Python imports stdlib `statistics` -> stdlib `re` -> stdlib `enum` -> tries to import stdlib `types` -> resolves to the LOCAL `src/server/analytics/types.py` instead -> `ImportError: cannot import name 'GenericAlias' from 'types'`.

2. **Layer 2 (would surface after Layer 1 fix)**: Per Spool's 2026-05-09 housekeeping note Item 1, the `baselines` table that calibration writes to does not exist on the live `obd2db` schema on chi-srv-01. `src/server/db/models.py:703-728` defines the `Baseline` SQLAlchemy model but no migration creates the table. Three possibilities (require triage):
   - (a) Migration drift — migration was written but never deployed to chi-srv-01.
   - (b) Feature spec'd but never shipped — model exists as a stub; migration + CLI never landed.
   - (c) Baselines workflow superseded — analytics moved to a different table; `Baseline` model is dead code.

## Steps to Reproduce

```bash
cd Z:/O/OBD2v2
python src/server/analytics/calibration.py --calibrate --apply
```

Observe the stack trace ending in:
```
ImportError: cannot import name 'GenericAlias' from 'types' (consider renaming
'src/server/analytics/types.py' since it has the same name as the standard
library module named 'types' and prevents importing that standard library module)
```

Python's own error message names the fix.

## Expected Behavior

`calibration.py --calibrate --apply` runs to completion: reads recent realtime_data, computes per-PID baselines from drives 5+6+7 (the pre-mod baseline shelf), and writes rows to the `baselines` table in `obd2db` on chi-srv-01. Spool can then run grading queries that compare future captures against the calibrated baselines.

## Actual Behavior

Crashes at import time before any business logic runs. The `--calibrate --apply` flags are never reached. Even if Layer 1 is patched, Layer 2 (missing `baselines` table) blocks the SQL INSERT.

## Impact

- **Calibration workflow is dead.** Spool cannot establish per-PID baselines from the new pre-mod drive shelf.
- **Future drive grading is gated on this** — without baselines, "Drive 12 vs the baseline" comparisons aren't queryable.
- **Same anti-pattern as I-014 (`obd` package name shadowing)** that triggered the obd -> obdii rename in Sprint 12 (US-187). Standing rule: NEVER name a local module the same as a Python stdlib module. Worth re-auditing the codebase for other shadow risks.

## Resolution

Two-part fix (V0.27.3 candidate sprint):

1. **Rename `src/server/analytics/types.py`** to a non-shadowing name (e.g. `analytics_types.py`, `domain_types.py`, or split contents into the importing modules). Update all imports. Mirror the Sprint 12 US-187 obd -> obdii rename pattern.
2. **Triage + fix the missing `baselines` table** per Spool's three-possibilities triage. Likely outcome: migration was never written (option b); ship a v0008 migration that creates the table, plus a regression test asserting `SHOW TABLES` includes `baselines` post-deploy.

Acceptance: `python src/server/analytics/calibration.py --calibrate --apply` runs to completion against the live `obd2db` and writes rows to `baselines` for drives 5+6+7.

## Cross-references

- Spool's housekeeping note: `offices/pm/inbox/archive/2026-05/2026-05-09-from-spool-post-cleanup-housekeeping-findings.md` Item 1
- Prior shadowing precedent: I-014 (`obd` package name shadowing) + Sprint 12 US-187
- Baseline model: `src/server/db/models.py:703-728`
- Calibration entry: `src/server/analytics/calibration.py:52` (the import that crashes)
- Mike's bug report: 2026-05-09 chat directive to PM
