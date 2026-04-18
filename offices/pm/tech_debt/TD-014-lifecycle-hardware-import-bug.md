# TD-014 — lifecycle.py hardware import uses stale `src.pi.*` path

## Status
Open — discovered Session 35 (Rex, US-178)

## Summary

`src/pi/obd/orchestrator/lifecycle.py:39` has a pre-reorg import path:

```python
from src.pi.hardware.hardware_manager import HardwareManager, createHardwareManagerFromConfig
from src.pi.hardware.platform_utils import isRaspberryPi
```

`main.py` puts `src/` on `sys.path`, so all other modules in
`src/pi/obd/orchestrator/lifecycle.py` correctly import as
`from pi.display import …`, `from pi.hardware.hardware_manager import …`,
etc. (see line 360 same file).

The `src.pi.*` form raises ImportError silently → `HARDWARE_AVAILABLE=False`
→ HardwareManager is permanently skipped → UpsMonitor, StatusDisplay
(pygame+HDMI), GpioButton, and TelemetryLogger never get instantiated at
runtime, even on the real Pi.

## Symptom

On the Pi at 10.27.27.28 (chi-eclipse-01, aarch64), running
`main.py --simulate --verbose` produces:

```
DEBUG | pi.obd.orchestrator | _initializeHardwareManager |
       Hardware module not available, skipping HardwareManager
```

…instead of the "Starting hardwareManager..." / "HardwareManager started"
messages the code is supposed to emit on Pi.

## Fix

One-line change:

```python
from pi.hardware.hardware_manager import HardwareManager, createHardwareManagerFromConfig
from pi.hardware.platform_utils import isRaspberryPi
```

## Why not fixed in US-178

US-178's `doNotTouch` includes `src/pi/obd/`. Also, unblocking the import
has cascading consequences (I2C probe on boot, pygame trying to acquire
HDMI, GPIO pins claimed) that are explicitly US-180's territory
("Hardware subsystem validation — I2C UPS + GPIO path").

## Recommendation

Fold into US-180 first step: fix the import, then run the story's
i2cdetect / UpsMonitor verification on live Pi. US-180 needs this fix
to exercise its AC anyway.

## Evidence

- `src/pi/obd/orchestrator/lifecycle.py:39-40` — the stale imports
- `src/pi/obd/orchestrator/lifecycle.py:360` — adjacent code using the
  correct `from pi.display import …` form
- Session 35 Pi transcripts in `offices/pm/inbox/2026-04-17-from-rex-us178-pygame-path-scope-disconnect.md`
