# B-052: HDMI dashboard full-canvas redesign

| Field        | Value                  |
|--------------|------------------------|
| Priority     | High (P0 for Sprint 21) |
| Status       | RESOLVED 2026-05-01 by US-257 (Sprint 21) |
| Category     | display / pygame / UX  |
| Size         | M (tentative)          |
| Related PRD  | None (Sprint 21 candidate) |
| Dependencies | None                   |
| Filed By     | Marcus (PM) from CIO observation during 2026-05-01 drain test 5 |
| Created      | 2026-05-01             |
| Resolved     | 2026-05-01 (Rex Session 129, US-257) |

## Description

Current dashboard renders to a pygame surface sized 480x320 (legacy footprint from the Pi-official touchscreen). When mounted on the Eclipse's HDMI display, the rendered area occupies only a small fraction of the screen canvas. CIO observation during 2026-05-01 drain test 5: "the display is way too small for what the HDMI screen is."

Goal: redesign the dashboard layout to use the full HDMI canvas (typical 1920x1080 or 1280x720 depending on screen). Larger fonts, more useful realtime data visible at a glance, post-Sprint-21 power-state indicators (WARNING/IMMINENT/TRIGGER stages — once US-252 lands they have something to display).

## Acceptance Criteria

- [x] Dashboard renders to full HDMI canvas (configurable via `pi.display.displayCanvas` section in config.json; mode='auto' hint for screen dim detection at start time)
- [x] Layout uses larger fonts (proportional to canvas height; e.g., title=72px at 1920x1080) + clearer state indicators visible from a few feet away
- [x] Sprint 16+ state surfaces visible: power-source (EXTERNAL / BATTERY), shutdown-stage (NORMAL / WARNING / IMMINENT / TRIGGER) via `updateShutdownStage()` setter on StatusDisplay, OBD2 drive-state in SW quadrant, alerts in SE
- [x] Render performance acceptable (single render path; pygame.display.flip() called once per frame; refresh cadence preserved at default 2 Hz)
- [x] Synthetic test parameterizes pygame.Surface dimensions over 1920x1080 / 1280x720 / 480x320 and asserts quadrant rect geometry + flip is called without raising
- [x] Backwards compat: 480x320 layout still works (legacy `pi.display.width`/`height` defaults unchanged) for development/testing on small screens

## Open Design Questions

1. **Layout**: rough mockup needed. Spool suggested a 4-quadrant layout (engine telemetry NW, power state NE, drive state SW, alerts SE). PM grooming with Spool input.
2. **Auto-detect vs explicit config**: pygame can read screen dims; but defaulting to "fullscreen" risks production deploys using whatever screen is plugged in (might be larger than expected). Recommend explicit `displayCanvas: {width: 1920, height: 1080}` in config.json with auto-detect fallback.
3. **Touch support**: legacy 480x320 was touch; HDMI screen is not. Drop touch-handler code or keep for hybrid? Recommend keep (button handler in `gpio_button.py` is the production input mechanism anyway).
4. **Color palette**: high-contrast for in-car visibility; especially the shutdown-stage colors (NORMAL=green, WARNING=amber, IMMINENT=orange, TRIGGER=red).

## Validation Script Requirements

- Synthetic: mock pygame.display.set_mode with various sizes; assert layout regions positioned correctly per layout function
- Live: CIO views dashboard on actual HDMI in car post-deploy; reports legibility from driver's seat

## Related

- **Sprint 16 US-219** (touch/display dashboard) — current implementation
- **US-252** (Sprint 21 candidate) — staged shutdown firing, exposes new states the dashboard should surface
- **B-037 phase trail** — dashboard sized for original touch-screen target; HDMI deployment is post-pivot
- **Source**: 2026-05-01 Spool drain-test-5 inbox note Section 7 + CIO live observation

## Notes

- Sprint 21 candidate sized at M tentatively. If pygame layout requires substantial restructuring (e.g., transitioning from one-shot render to dirty-rect updates for performance), bump to L during Rex's grooming.
- Dashboard is currently the only user-facing surface on the Pi. Investment here pays off across all future drives + drain tests.
