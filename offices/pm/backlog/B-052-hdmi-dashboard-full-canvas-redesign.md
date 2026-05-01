# B-052: HDMI dashboard full-canvas redesign

| Field        | Value                  |
|--------------|------------------------|
| Priority     | High (P0 for Sprint 21) |
| Status       | Pending grooming        |
| Category     | display / pygame / UX  |
| Size         | M (tentative)          |
| Related PRD  | None (Sprint 21 candidate) |
| Dependencies | None                   |
| Filed By     | Marcus (PM) from CIO observation during 2026-05-01 drain test 5 |
| Created      | 2026-05-01             |

## Description

Current dashboard renders to a pygame surface sized 480x320 (legacy footprint from the Pi-official touchscreen). When mounted on the Eclipse's HDMI display, the rendered area occupies only a small fraction of the screen canvas. CIO observation during 2026-05-01 drain test 5: "the display is way too small for what the HDMI screen is."

Goal: redesign the dashboard layout to use the full HDMI canvas (typical 1920x1080 or 1280x720 depending on screen). Larger fonts, more useful realtime data visible at a glance, post-Sprint-21 power-state indicators (WARNING/IMMINENT/TRIGGER stages — once US-252 lands they have something to display).

## Acceptance Criteria

- [ ] Dashboard renders to full HDMI canvas (configurable via `display.canvas` section in config.json; auto-detects screen dims)
- [ ] Layout uses larger fonts + clearer state indicators visible from a few feet away
- [ ] All Sprint 16+ state surfaces visible: BT-connection, drive-state, idle/active poll mode, power-source (EXTERNAL / BATTERY), shutdown-stage (NORMAL / WARNING / IMMINENT / TRIGGER) post-US-252
- [ ] Render performance acceptable (no input lag on button presses; refresh cadence preserved)
- [ ] Synthetic test mocks pygame.Surface dimensions + asserts layout positions for known fixed screen sizes
- [ ] Backwards compat: 480x320 layout still works (config-selectable) for development/testing on small screens

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
