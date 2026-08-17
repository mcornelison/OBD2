From: Rex (Ralph, Session 35)
To: Marcus (PM)
Date: 2026-04-17
Story: US-178 — OSOYOO 3.5" HDMI display validation
Status: PARTIAL — marking passed:false

## TL;DR

The pygame-on-HDMI render path that US-178 asks me to validate is
effectively dead code in the current codebase. The in-scope drivers
(`src/pi/display/`) do not use pygame at all — pygame lives in
`src/pi/hardware/status_display.py`, and that module is skipped at runtime
because of an unrelated import bug in `src/pi/obd/orchestrator/lifecycle.py`.

I did what's genuinely in scope (DisplayManager's 3 driver modes work on
ARM, regression gate added, CIO checklist provided). The pygame
visual-render acceptance criteria need either (a) an unblocking fix to
lifecycle.py + touch wiring work, or (b) a story rewrite. Either way,
out of US-178 scope as written.

## What's actually in the codebase

Two distinct "display" systems exist on the Pi today:

1. **DisplayManager** (`src/pi/display/`) — selected via `DISPLAY_MODE` env:
   - `headless` → `HeadlessDisplayDriver` (no output, logs only)
   - `minimal` → `MinimalDisplayDriver` (Adafruit ST7789 1.3" 240x240 **SPI**)
   - `developer` → `DeveloperDisplayDriver` (ANSI-colored stdout)

   **None of these use pygame. None render to the OSOYOO HDMI.**

2. **StatusDisplay** (`src/pi/hardware/status_display.py`) — pygame-based,
   480x320 HDMI, shows battery/power/OBD status. Instantiated by
   `HardwareManager._initializeStatusDisplay()`.

   This IS the pygame+HDMI path US-178 is asking about.

## Why pygame never actually runs today

`src/pi/obd/orchestrator/lifecycle.py:39`:

```python
from src.pi.hardware.hardware_manager import HardwareManager, createHardwareManagerFromConfig
```

`main.py` puts `src/` on `sys.path`, so the correct import is
`from pi.hardware.hardware_manager ...`.  The `src.pi.*` form silently
raises ImportError → `HARDWARE_AVAILABLE=False` → HardwareManager is
always skipped at runtime:

```
DEBUG | pi.obd.orchestrator | _initializeHardwareManager |
       Hardware module not available, skipping HardwareManager
```

Fix is literally one line. But it's in `src/pi/obd/` which US-178's
`doNotTouch` explicitly forbids, and the first-order consequence of
fixing it is that UpsMonitor + I2C probe + GpioButton + pygame all start
trying to initialize — which is exactly US-180's story charter.  So the
right place for this fix is US-180, not US-178.

## What I did in scope

- **Live-verified all 3 display driver modes on the Pi** via SSH with
  `DISPLAY_MODE=<mode>` env var + `main.py --simulate`. All 3 exit 0,
  DisplayManager starts cleanly in each mode, `minimal` falls back to
  NullDisplayAdapter (expected: no Adafruit SPI attached, only OSOYOO
  HDMI). Logs captured in progress.txt.
- **Added `tests/pi/display/test_display_modes_arm.py`** — 8 tests
  (3 mode-selection × 1 + 3 lifecycle × 1 + 1 invalid-mode fallback +
  1 minimal-null-adapter fallback). Runs on both Windows and Pi in
  <0.1s each. Regression-gates the mode-selection logic so a future
  refactor can't break it silently.
- **CIO visual-check checklist** in the US-178 completion note.

## What I explicitly DID NOT do (and why)

- **Did not touch `src/pi/obd/orchestrator/lifecycle.py`** — out of
  `doNotTouch` scope. Strongly recommend folding the one-line import
  fix into US-180 where the consequences (actually booting
  HardwareManager) are the point of the story.
- **Did not wire pygame touch events to `touch_interactions.py`** — no
  such wiring exists today (`pygame.event.get()` is called only in
  status_display.py's refresh thread, and only to handle QUIT). Building
  that plumbing is beyond "validation" and would need a separate story.
- **Did not try to force pygame init via `SDL_VIDEODRIVER=fbcon`/`kmsdrm`
  over SSH** — both fail with "not available" because SSH sessions don't
  own a console seat. Pygame does init with `SDL_VIDEODRIVER=dummy`,
  which confirms the library is installed but does not render to the
  OSOYOO. Real HDMI render needs either a logged-in console session or
  systemd service running with proper seat/group permissions — both of
  which belong in US-179/US-180 follow-ups.

## Recommendations for PM

1. **Scope decision**: either extend US-178 to allow the one-line
   lifecycle.py fix (plus the full consequences — UpsMonitor I2C probe
   etc.), or split off a successor story "US-178b: pygame HDMI render
   validation" that sequences after US-180.
2. **AC wording**: AC #1 references log line `SCREEN_INITIALIZED` which
   does not exist anywhere in src/. Consider rewriting to match real
   log surface (`Display manager initialized in <mode> mode`).
3. **Touch AC**: AC #3 assumes a touch→display_manager wiring that was
   never built. Either defer to a new story or downgrade to "touch input
   detection is unit-tested via mock" (mock-only is already doable in
   US-180's GPIO path for similar reasons).

## Pi live-verification evidence

```
========== MODE: headless ==========
INFO | pi.obd.orchestrator | DisplayManager started successfully | mode=headless
INFO | __main__ | Application completed successfully
========== MODE: minimal ==========
WARNING | pi.display.drivers.minimal | Adafruit display hardware not available - using null adapter.
INFO | pi.display.drivers.minimal | Minimal display driver initialized (240x240, refresh=1000ms)
INFO | pi.obd.orchestrator | DisplayManager started successfully | mode=minimal
INFO | __main__ | Application completed successfully
========== MODE: developer ==========
INFO | pi.display.drivers.developer | Developer display driver initialized - verbose console output enabled
INFO | pi.obd.orchestrator | DisplayManager started successfully | mode=developer
INFO | __main__ | Application completed successfully
```

All 3 modes, exit code 0, clean shutdown.

— Rex
