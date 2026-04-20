# TD-024: `pi.hardware.status_display` crashes with GL BadAccess under X11

| Field        | Value                                                |
|--------------|------------------------------------------------------|
| Severity     | High (blocks US-170 + any production main.py with HDMI render) |
| Status       | **Closed — fixed in US-198 on 2026-04-19 (Session 68)** |
| Filed By     | Marcus (PM), Session 23, 2026-04-19                  |
| Surfaced In  | Sprint 13 PM+CIO live drill (US-170)                 |
| Blocking     | US-170 (HDMI display) — deferred to Sprint 14 (US-192 retry) |
| Closed By    | Ralph (Rex), Session 68 -- chose Option (a): force SDL software renderer via env hints before pygame.init, plus Option (d) config flag `pi.hardware.statusDisplay.enabled` as operator escape hatch |

## Fix Summary (US-198, 2026-04-19)

Chose **Option (a): force software renderer** as primary fix, with **Option (d):
config-flag disable** as operator escape hatch. Rejected Option (c) surface-
sharing refactor because `pi.display.manager` drivers don't call
`pygame.display.set_mode` -- there is no shared surface to share. Rejected
Option (b) catch-and-fall-back because Xlib's `XIOError` handler calls `exit()`
on `BadAccess` before Python's `try/except` can intercept -- the fix MUST
prevent the GL context request, not catch it after.

**Implementation** (`src/pi/hardware/status_display.py`):

- New constructor arg `forceSoftwareRenderer: bool = True`.
- Before `pygame.init()`, set SDL env hints (only if not already in env, so
  operator overrides via `.service` files are preserved):
  - `SDL_RENDER_DRIVER=software`
  - `SDL_VIDEO_X11_FORCE_EGL=0`
  - `SDL_FRAMEBUFFER_ACCELERATION=0`
- `_initializePygame` already returned False on exception -- added regression
  tests for the failure path to lock that behavior in.

**Config** (`config.json`):

```json
"pi": {
  "hardware": {
    "statusDisplay": {
      "enabled": true,
      "forceSoftwareRenderer": true
    }
  }
}
```

Both default to `true` and are backwards-compatible: existing configs without
the block continue to work. `hardware.statusDisplay.enabled` takes precedence
over legacy `hardware.display.enabled` for the overlay.

**Tests**: 18 new tests across two files
(`tests/pi/hardware/test_status_display.py` 11 + `test_manager_status_display_disable.py` 7)
cover: default flag value, env hints set before pygame.init, operator override
preservation, init-failure graceful path, start() never raising, refresh-loop
crash containment (existing behavior regression-guard), factory-to-manager-to-
display threading, and `enabled=False` skipping construction entirely.

**Verification on Pi**: owed by CIO in next garage drill via the Sprint 14
US-192 retry story (the one that originally blocked on this TD). Until then the
fix is provable only at unit-test level -- stopCondition #2 in US-198 (software
renderer visibly broken) can't be checked from Windows dev box.

## Problem

When `src/pi/main.py` runs under the X11 environment per Session 22 finding
(`DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority SDL_VIDEODRIVER=x11`), the
`pi.hardware.status_display` component crashes immediately on its first
refresh tick:

```
2026-04-19 07:18:51 | INFO  | pi.hardware.status_display | start | Status display started with refresh rate 2.0s
2026-04-19 07:18:51 | ERROR | pi.hardware.status_display | _refreshLoop |
    Error in display refresh loop: Could not make GL context current:
    BadAccess (attempt to access private resource denied)
```

The crash propagates to the orchestrator runLoop and kills it at
`uptime=0.6s` — before any sustained data capture or display rendering
can happen.

## Confirmed Workaround

Setting `SDL_VIDEODRIVER=dummy` (headless) avoids the crash entirely.
Session 23 drill ran 60s headless and persisted 149 rows successfully.
But headless = no HDMI render, which is exactly what US-170 requires.

## Important Distinction

`pi.hardware.status_display` is **NOT** the primary OSOYOO display.
It's a separate hardware-monitor overlay component. The actual
production display is `pi.display.manager` + `pi.display.screens.*`
which was proven working under X11 in Session 22 via
`scripts/render_primary_screen_live.py`.

So the bug is scoped to the `pi.hardware.status_display` overlay alone,
not the entire pygame stack on the Pi.

## Likely Causes (for Ralph triage)

1. `pi.hardware.status_display` is calling `pygame.display.set_mode()` with a flag like `pygame.OPENGL` that requests GL acceleration. Pygame's wheel-bundled SDL2 (per Session 22 finding) supports software rendering but the X11 server may not grant a GL context to a non-priviledged session.
2. Some SDL2 versions auto-attempt GL on X11 even without explicit OPENGL flags. Force `SDL_RENDER_DRIVER=software` or `SDL_VIDEO_GL_DRIVER=swrast` env at component startup.
3. The two display surfaces (`pi.hardware.status_display` overlay + `pi.display.manager` primary) may be conflicting on framebuffer resources — the second pygame display init in the same process tries to grab a context the first already holds.

## Acceptance for Fix

- `python src/pi/main.py` with `DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority SDL_VIDEODRIVER=x11` runs sustained (>60s) without GL context errors
- HDMI render of the primary screen displays live data from real OBD reads
- Either status_display overlay renders correctly OR has a config flag to disable when the primary pygame display is already attached
- Add a regression test if feasible (likely a manual / scripted live-on-Pi check, not a unit test)

## Path to Unblock US-170

1. Triage status_display GL usage (does it need GL accel? force software renderer?)
2. OR add config flag to disable status_display when an external display surface is owned by the primary display manager
3. Re-run main.py with X11 + verify primary display shows live numbers
4. File US-192 in Sprint 14 as the US-170 retry (once TD-024 fix lands)

## Related

- Sprint 13 closeout: `offices/pm/blockers/BL-006.md`
- US-170 blockedReason: `offices/ralph/sprint.json`
- Session 22 X11 baseline finding: `offices/pm/projectManager.md` (Session 22 summary, HDMI render via X11)
- TD-023 (sibling Sprint 13 finding): OBD connection layer MAC vs serial path
- Carryforward note to Ralph: `offices/ralph/inbox/2026-04-19-from-marcus-sprint13-carryforward.md`
