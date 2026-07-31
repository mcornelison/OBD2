# UI Feedback Round 2 — CIO bench review 2026-07-31 (triage + routing SSOT)

CIO gave 15 UI-feedback items on the shipped V0.29.21 Pi touch-carousel. Grounded via a read-only
code investigation (emitters, orchestrator, carousel.js, Iris specs — all file-cited). This doc is the
single source of truth for the round; stories/inbox-notes reference it, they don't re-state it.

**Carousel order (1-based, as CIO numbers screens):** 1 idle-home · 2 System Status · 3 Battery Health ·
4 Light · 5 Motion/IMU · 6 Alerts · 7 LTFT Trend (vehicle-gated, ships hidden).

**CIO decisions (AskUserQuestion 2026-07-31):**
1. #13 → **Add auto-rotation + swipe-to-pause** (net-new; needs a slow-vs-fast swipe distinction that doesn't exist today).
2. #4/#5 → **Build both new producers** (last-drive-summary + battery-health-check history).
3. Approach → **Iris design pass + parallel dev wiring sprint** (two tracks).

This round runs in PARALLEL to BL-025 (the capture P0) — it does not touch that critical path.

---

## Per-item triage

| # | Item | Grounded finding (file-cited in investigation) | Verdict | Owner | Story/Route |
|---|------|--------|---------|-------|-------|
| 1 | Version "V?.?.?" | Hardcoded literal `dashboard.html:37`; `.deploy-version`=V0.29.21 exists but never injected/read (`states_http_server.py:317-323`). | **Bug (stub)** | Dev | US-501 |
| 2 | Header bolt grayed | `powerGlyphState` reads `source` from `PowerMonitor.readPowerStatus()` which returns None (no reader wired). **Same root as #6.** NOT a bench-power honest-gray — a defect. | **Bug** | Dev | US-502 |
| 3 | 24h clock | `fmtClock` uses `getHours()` (`carousel.js:1929`). One-function change. | Format pref | Dev | US-503 |
| 4 | "No recent drive" | No last-drive-summary producer exists (`carousel.js:881-898` comment). Honest today; CIO wants it real → **build a producer**. | Build new source | Dev (+source confirm) | US-505 |
| 5 | Health check "never" | `lastHealthCheckTs` hardcoded None (`card_state_emitter.py:402`); no `battery_health_log` history reader. | Build/wire source | Dev (+Spool/source) | US-504 |
| 6 | Power "unavailable" | Same root as #2 — tile reads the reader-less `readPowerStatus()`; real `PowerSourceProvider`/GPIO6 only feeds `power_log`. | **Bug (=#2)** | Dev | US-502 |
| 7 | "System · 1 issue" not clickable | Display-only by design (P-1 was presentation-only, no drill-down). CIO wants a detail view = new design+build. | Design change | Iris → Dev | F-124 |
| 8 | Battery health / temp "no source" | CELL(volts)+CHARGE(%) = real MAX17048. HEALTH verdict hardcoded "unknown" (no producer). **TEMP: MAX17048 has NO temp register — genuinely no source → remove it.** | Bug + remove | Dev (+Spool verdict) | US-504 |
| 9 | Motion screen — move + match Iris | Built card DIVERGES from Iris's CIO-locked live-card design: standalone (not home-slot swap), needle-dial (not compass tape), **no GEAR readout**, **no 0.6 g amber**. | Design regression | Iris → Dev | F-124 |
| 10 | Alerts "not read yet" | Correctly wired to the real DTC source; a read only happens key-on with the car. Honest on the bench, **not a bug**. | Honest-correct | (explain) | — |
| 11 | LTFT (screen 7) | US-420 Long-Term Fuel-Trim Trend — tracks fuel-mixture drift across drives. Vehicle-gated + normally hidden on bench (CIO seeing it on bench = verify the gate). | Explain + verify gate | Dev (verify) | F-124 (gate check) |
| 12 | Carousel should wrap | Currently intentionally clamped, "no wrap" by design (`carousel.js:44-45`). CIO wants 7↔1 wrap = deliberate reversal. | Behavior change | Iris ratify → Dev | F-124 |
| 13 | Stop auto-rotate on swipe | **No auto-rotation exists today.** CIO chose: ADD auto-rotate + swipe-to-pause + hard-swipe-advance (needs new slow/fast swipe distinction; swipe is distance-only today). | New behavior | Iris design → Dev | F-124 |
| 14 | Look & feel drift | Residual untokenized color literals (TD-065), idle wordmark "ECLIPSE" vs spec "ECLIPSE OBD-II", footer copy drift, generic monospace (no brand face). | Design fidelity | Iris → Dev | F-124 |
| 15 | "⋮" inconsistent | Shows only when `system-status.idle===true`; `idle` flips with OBD availability (not a stable "parked" concept) → toggles on OBD blips. Needs a steadier parked definition. | Design refinement | Iris (+Atlas?) → Dev | F-124 |

---

## Routing

**Track A — Dev wiring sprint (F-123, groom now, design-independent):**
- US-501 version inject (#1) · US-502 power-reader → fixes #2+#6 · US-503 clock 12h (#3) · US-504 battery-health truthfulness (#8: remove TEMP + wire HEALTH verdict + lastHealthCheck; source-confirm gated) · US-505 last-drive producer (#4; source-confirm gated).
- Source-confirms owed before US-504/505 are dev-ready: **Spool** = battery-health verdict semantics/source (US-504 HEALTH); **last-drive source-of-truth** = what the Pi can authoritatively read for "last drive" (US-505) — confirm in grooming.

**Track B — Iris design-fidelity + interaction pass (F-124, design-before-build):**
- #14 look/feel fidelity · #9 IMU card redesign + placement · #12 wrap · #13 auto-rotate + swipe-to-pause · #7 system-status drill-down · #15 stable "parked" kebab trigger. Iris designs → CIO reviews mockup → PM grooms dev stories. #11 LTFT bench-visibility gate check folds in.

**Not a bug (explain, no work):** #10 Alerts "not read yet" is correct on the bench.
