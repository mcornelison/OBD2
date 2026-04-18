# TD-015: HARDWARE_AVAILABLE false-negative when lifecycle.py loaded via main.py

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Medium                    |
| Status       | Open                      |
| Category     | code                      |
| Affected     | `src/pi/obd/orchestrator/lifecycle.py` (import try/except at lines 37-53) |
| Introduced   | Pre-dates this session; likely from the orchestrator split (Sweep 5 Task 2, 2026-04-14) or the TD-014 fix (2026-04-17) |
| Created      | 2026-04-17                |

## Description

In `src/pi/obd/orchestrator/lifecycle.py`:

```python
try:
    from pi.hardware.hardware_manager import HardwareManager, createHardwareManagerFromConfig
    from pi.hardware.platform_utils import isRaspberryPi
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False
    ...
```

When the module is imported directly on chi-eclipse-01:

```bash
cd /home/mcornelison/Projects/Eclipse-01/src
~/obd2-venv/bin/python -c "from pi.obd.orchestrator.lifecycle import HARDWARE_AVAILABLE; print(HARDWARE_AVAILABLE)"
# → True
```

But when loaded through the main.py startup chain:

```bash
cd /home/mcornelison/Projects/Eclipse-01
~/obd2-venv/bin/python src/pi/main.py --simulate --verbose
# → ... pi.obd.orchestrator | _initializeHardwareManager |
#       Hardware module not available, skipping HardwareManager
```

The try/except catches the import silently and `HARDWARE_AVAILABLE` stays
False. The HardwareManager initialization is then skipped with a `debug`
log message (invisible at normal INFO level). In isolation,
`pi.hardware.hardware_manager`, `pi.hardware.platform_utils`, `smbus2`,
and `gpiozero` all import cleanly.

Reproduced cleanly after `find src -name __pycache__ -type d -exec rm -rf {} +`
on the Pi, so not a stale-pyc issue.

## Why It Was Accepted

Hasn't been caught until now because:

1. US-181's shutdown lifecycle validation still works perfectly — components
   that *do* initialize (Database, ProfileManager, Connection, VinDecoder,
   DisplayManager, StatisticsEngine, DriveDetector, AlertManager, DataLogger,
   ProfileSwitcher) shut down in correct reverse order. Graceful teardown
   invariants are all met.
2. The Pi's X1209 UPS HAT was the focus of recent hardware-subsystem
   concerns (US-180), not the orchestrator-level init detection.
3. DEBUG-level logging hides the early-return message at normal INFO
   verbosity.

## Risk If Not Addressed

**High** once the Pi enters walk/run phases:

- UpsMonitor will never initialize under the running service, so the AC-loss
  → scheduled-shutdown path (deferred US-181 AC) stays dead code in production.
- GpioButton (physical long-press shutdown) will never wire up under the
  running service, even once the button is physically wired in Sprint 11.
- TelemetryLogger won't run, so battery/power telemetry lines never land in
  rotating log files.
- Graceful degradation paths from US-180's tests pass in pytest but never
  exercise the real code path on the real Pi.

All of these are Sprint 10+ invariants that'll silently fail until someone
runs with `--verbose` and grep-spots the debug log. Medium priority because
Sprint 10 crawl is functionally fine without them; High priority for
Sprint 11 when the button and UPS path go hot.

## Remediation Plan

Short investigation to pinpoint the root cause — it's NOT one of:
- Missing third-party deps (verified all import in isolation)
- Stale `__pycache__` (tested after full clear)
- `sys.path` missing `src/` (main.py inserts `srcDir` at position 0
  before any imports)
- Circular import (no circular-import error is raised — the
  `try/except ImportError` catches the failure silently)

Candidate root causes to investigate:

1. **Import ordering.** When `main.py` runs `from common.*` imports first,
   maybe `common.logging.setup` or `common.config.validator` indirectly
   imports something in `pi.*` that partially initializes the `pi.hardware`
   package (leaving it in a broken state for lifecycle.py's subsequent
   import).
2. **`from pi.hardware.hardware_manager` triggers a sub-import that
   fails.** `hardware_manager.py` imports from `pi.hardware.i2c_client`,
   `pi.hardware.ups_monitor`, etc. One of those sub-imports might depend
   on something that's clean in isolation but dirty after `common.*` has
   been imported.
3. **The exception being caught isn't an ImportError** but is being
   swallowed because `except ImportError:` doesn't cover it. Possibilities:
   `ModuleNotFoundError` (which IS an ImportError subclass, so it WOULD be
   caught); `AttributeError` from a `from ... import <name>` where the name
   doesn't exist (the bare `except ImportError` wouldn't catch that — but
   then the orchestrator wouldn't finish loading, which it does).

Recommended fix (once root cause is pinpointed):

- Widen the `except` clause to catch and LOG the exception at `warning`
  level so this class of bug surfaces at INFO verbosity:
  ```python
  except ImportError as e:
      HARDWARE_AVAILABLE = False
      logger.warning(f"Hardware module detection skipped: {type(e).__name__}: {e}")
  ```
- Or promote the skip message in `_initializeHardwareManager` from
  `logger.debug` to `logger.info` so operators see it in normal journal
  output.

Backlog: no B- item yet. Candidate for rollup into B-042 (obd package rename)
since both are systemd/sys.path-shadowing-flavored bugs.
