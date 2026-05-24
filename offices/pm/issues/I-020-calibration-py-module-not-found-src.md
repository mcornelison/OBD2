# I-020: calibration.py crashes with ModuleNotFoundError: No module named 'src' on local invocation

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium                    |
| Status       | Open (V0.27.4 candidate)  |
| Category     | infrastructure / dev-ergonomics |
| Found In     | `src/server/analytics/calibration.py` line 58 (`from src.server.db.models import ...`) |
| Found By     | CIO (Mike), 2026-05-10 (running locally on Windows) |
| Related I-   | I-018 (closed in V0.27.3 US-312) -- this is a follow-on third layer |
| Created      | 2026-05-10                |

## Description

After V0.27.3 US-312 fixed I-018's two layers (stdlib `types.py` shadow rename + missing `baselines` table migration), a THIRD layer surfaced when CIO ran calibration.py locally on Windows:

```
$ python src/server/analytics/calibration.py --calibrate --apply
Traceback (most recent call last):
  File "Z:\O\OBD2v2\src\server\analytics\calibration.py", line 58, in <module>
    from src.server.db.models import Baseline, DriveStatistic, DriveSummary
ModuleNotFoundError: No module named 'src'
```

The script imports from `src.server.db.models` which requires `src` to be on Python's import path as a top-level package. Without `PYTHONPATH=<repo-root>` set explicitly, the `src` package can't be resolved.

## Steps to Reproduce

1. From repo root, run: `python src/server/analytics/calibration.py --calibrate --apply`
2. Observe: `ModuleNotFoundError: No module named 'src'` at line 58

## Expected Behavior

CLI runs to completion regardless of how the user invokes it (from repo root, with or without PYTHONPATH set). Script should self-bootstrap its sys.path OR be invoked via a wrapper that handles the path setup.

## Actual Behavior

Crashes at import time before any business logic runs. The script CANNOT self-import `src.server.db.models` without the repo root on sys.path.

## Impact

- CIO cannot run calibration.py locally to review baseline proposals (the script's stated purpose per its docstring at line 4 -- "review and propose baseline updates against sim baselines for CIO review")
- Server-side invocation works (PM validated 2026-05-10 on chi-srv-01 with `PYTHONPATH=/mnt/projects/O/OBD2v2 ...`) but that requires SSH + a non-trivial command line; not the intended user experience
- I-018 was filed as a single bug; we shipped 2 of 3 fix layers in V0.27.3. Layer 3 is this PYTHONPATH issue. Should have been caught by V0.27.3 US-312's IRL validation gate, but PM only validated server-side; never tested local invocation. **PM testing-discipline gap**: when validating CLI fixes, run from CIO's actual usage context (Windows shell, no env vars set), not just the path that's known to work.

## Resolution (V0.27.4 candidate)

Two-part fix scope, ranked by simplicity:

1. **Add sys.path bootstrap at top of calibration.py** (cheapest):
   ```python
   import sys
   from pathlib import Path
   sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
   ```
   This ensures the repo root is on sys.path regardless of how the script is invoked. Standard pattern for Python CLI scripts in src/-layout repos.

2. **OR provide a wrapper script** (`scripts/calibrate.sh` or `scripts/calibrate.py`) that sets PYTHONPATH + invokes the underlying script. More indirect; adds a file.

Recommend Option 1 (cheaper, single-file change, standard idiom).

## Acceptance

- `python src/server/analytics/calibration.py --calibrate --apply` runs from any working directory on a fresh shell with no env vars set
- Test added that exercises the entry point (subprocess invocation; would FAIL pre-fix on the import error)

## Cross-references

- I-018 (closed in V0.27.3 US-312) -- the original calibration.py crash bug; this is layer 3
- V0.27.3 US-312 acceptance criteria included "post-deploy + python src/server/analytics/calibration.py --calibrate --apply runs to completion against chi-srv-01" -- which was PM-validated server-side BUT not validated against CIO's local Windows environment. Standing rule: validate CLI fixes in the user's actual usage context, not just the path that's known to work.
- PM lesson saved: when validating CLI fixes, the IRL gate must include running from CIO's actual shell (Windows, no env vars). Recurrence prevention.
