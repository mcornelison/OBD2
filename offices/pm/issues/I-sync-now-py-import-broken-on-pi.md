---
id: I-sync-now-import-broken
type: issue
severity: medium
parent: E-OPS
status: pending
found: 2026-06-29 (Session 50, V0.29.1 deploy)
foundBy: Marcus (PM) -- running the US-367 dtc_freeze_frame re-drain
---

# `scripts/sync_now.py` import-broken on the Pi (`pi.` vs `src.pi.` convention collision)

## Symptom
On the Pi, `python scripts/sync_now.py` throws:
```
ModuleNotFoundError: No module named 'pi'
  .../scripts/sync_now.py:91   from src.pi.sync import PushResult, PushStatus, SyncClient
  .../src/pi/sync/__init__.py:16   from src.pi.sync.client import ...
  .../src/pi/sync/client.py:132    from src.pi.obdii.drive_id import DRIVE_COUNTER_TABLE
  .../src/pi/obdii/__init__.py:26  from pi.display import (...)   <-- fails
```

## Root cause
A sys.path / import-convention collision between two halves of the import chain:
- `scripts/sync_now.py` inserts the **repo ROOT** on `sys.path` (line ~78) and imports `from src.pi.sync import ...` (the `src.pi.*` convention).
- `src/pi/obdii/__init__.py:26` uses the bare **`from pi.display import (...)`** convention (the `pi.*` convention the running services use, which requires **`src/` on `sys.path`**).

No single `sys.path` satisfies both: ROOT-on-path resolves `src.pi.*` but not `pi.*`; `src`-on-path resolves `pi.*` but not `src.pi.*`. The chain reaches the `pi.display` import with only ROOT on the path -> fails.

## Impact
- **Operator-facing**: the manual Pi->server sync trigger (`sync_now.py`) is broken. The CIO can't run a manual sync the documented way.
- **Services UNAFFECTED**: `eclipse-obd` + `eclipse-powerwatch` run under the `pi.*`-on-`src/`-path convention consistently, so they import + sync fine (verified active + healthy on V0.29.1; the dtc_freeze_frame re-drain self-healed via the service sync). This is a script-only break, NOT a service regression.

## Workaround (used 2026-06-29)
`PYTHONPATH=<repo>/src python scripts/sync_now.py` -- adds `src/` so `pi.display` resolves; `sync_now.py`'s own ROOT-insert keeps `src.pi.*` resolving. (Mild double-import of `display` under both namespaces, but the sync path itself is `src.pi.*`-consistent, so the sync is unaffected.)

## Fix direction (for grooming -> a Ralph Story under E-OPS)
Per the project convention [[feedback-path-convention-no-src-prefix]] (`from pi.X`, not `from src.pi.X`, on the Pi tier), **`sync_now.py` is the outlier** -- it should put `src/` on `sys.path` and import `pi.sync` / `pi.data` (the `pi.*` convention the services + the rest of `src/pi` use), not insert ROOT + import `src.pi.*`. Audit other `scripts/*.py` Pi-side entry points for the same ROOT-insert + `src.pi.*` pattern (likely a cluster).

## Notes
- Discovered while running the deploy-time US-367 dtc_freeze_frame re-drain; the re-drain itself succeeded (self-healed via the running service), so this did not block V0.29.1.
- Sibling capture: `I-simulate-duplicate-timestamp-parameter-rows.md` (Ralph, same session).
