---
sprint: 71
version: V0.29.26
status: draft
createdAt: 2026-08-03
createdBy: Marcus (PM)
selectedStories: [US-530, US-531, US-532, US-533, US-536, US-537]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion; forks from dev AFTER V0.29.25)
sprintJsonPath: offices/ralph/sprint.json
epics: E-001 (UI/UX Polish)
features: F-126 (Pi settings screen -- config-backed toggles via a Pi-local overlay)
theme: "Pi Settings screen -- Slice 1. First surface that ties the dashboard to config as its data source: 5 user-facing toggles persisted to a Pi-local OVERLAY (config.json stays the read-only shipped default; deploy-preserved so toggles survive deploys). CIO-designed 2026-08-03. DEFERRED (backlog, pending): Battery/Power Test action (Spool), System Settings/Updates (own epic)."
atlasReview: "PASS 2026-08-03 (design gate). Foundation sound; 3 US-530 gaps FOLDED: (1) drop 'applies LIVE' -- auto-rotate needs an eclipse-states-http bounce, labeled honestly (US-533); (2) ONE shared resolveEffectiveConfig SSOT utility both readers call (A-4); (3) use existing autoRotateS not a new bool + default OFF per disposition-B. US-531 token-gate CONFIRMED. Freeze disposition B ruled: keep GPU, revert US-522 --disable-gpu, autoRotateS:0 default (US-536); animation-gating = toggle-safety prereq (US-537)."
irisReview: "DELIVERED 2026-08-03. Option B (CIO-refined): a Settings BAND inside the existing US-403 setup-menu overlay (not a separate carousel card) + honest save flow. Design: offices/uidevloper/proposals/2026-08-03-f126-settings-screen-us532.{md,html}. Folded into US-532."
---

# PRD: V0.29.26 -- Pi Settings screen (Slice 1)

| Field | Value |
|---|---|
| Version | V0.29.26 (patch on dev; forks after V0.29.25) |
| Origin | CIO feature request + brainstorm 2026-08-03: a config/settings screen on the Pi, first setting = carousel auto-rotate on/off, tied to config.json as the data source. Scope grew to a Settings subsystem; sliced. |
| Stories | US-530..533 (Slice 1). US-534 (Battery/Power Test) + US-535 (Updates) filed PENDING/deferred. |
| Deploy | from dev; bench-validated on the Pi (toggles render + persist across a deploy) |

## Goal

Give the operator a **Settings screen** on the Pi dashboard with config-backed toggles, and establish the **persistence pattern** for Pi-side settings: a **Pi-local overlay file** that layers over `config.json`. `config.json` stays the read-only shipped **default**; the overlay holds the operator's runtime choices and is **deploy-preserved** (added to the rsync excludes like `.env`), so a toggle set on the Pi is never wiped by a deploy. This is the first surface tying the dashboard to config as its data source.

## Design (CIO-locked 2026-08-03)

**Persistence -- Pi-local overlay (CIO chose this over writing config.json directly):**
- `config.json` = read-only shipped default; nothing writes it at runtime.
- Read path resolves **effective value = overlay-override ELSE config.json default**.
- The overlay file is gitignored + added to `deploy-pi.sh` rsync excludes, so deploy never clobbers it (proven `.env`-preserve pattern).
- Only an **allow-list** of keys may be overridden (the 5 settings below) -- not arbitrary config.
- **Atlas designs** the overlay file shape, the layering seam, and the allow-list mechanism (load-bearing config/SSOT change = design gate).

**Write path -- token-gated endpoint:**
- The kiosk is chromium JS and cannot write files, so a toggle POSTs to a **write endpoint on `states_http_server`** that writes the overlay.
- The endpoint is **token-gated** with the same US-393 SSOT token as the served pages. Per Atlas's US-525 ruling, `_tokenOk` is never weakened and no un-authenticated write surface is opened (weakening it = Atlas BLOCK / TD-067).

**The 5 Slice-1 settings:**
| Setting | Config key | Default | Type | Consumer / apply |
|---|---|---|---|---|
| Carousel auto-rotate | `pi.display.carousel.autoRotate` *(new bool)* | on | toggle | carousel JS, applies LIVE |
| Power mode | `pi.power.mode` | unknown | car / wall / unknown | PowerModeProvider re-emits (fixes bench "unknown") |
| Audio alerts | `pi.alerts.audioAlerts` | off | toggle | alerts subsystem |
| Calibration mode | `pi.calibration.mode` | off | toggle | calibration subsystem |
| Auto-analyze after drive | `pi.analysis.triggerAfterDrive` | on | toggle | analysis trigger |

**Honest-instrument rules (throughout):** controls show the REAL effective value (never a hardcoded default); a write failure reflects the real stored value, never an optimistic success; a setting that needs a service restart to take effect says so plainly -- never a silent no-op that looks applied; a malformed/absent overlay resolves to the config default.

## Stories (full DoD/validationCriteria in backlog.json)

| Story | Size | Summary | Gate |
|---|---|---|---|
| US-530 | M | Overlay persistence + layered read (config default <- overlay override) + allow-list + `autoRotate` key | **Atlas design-gate** |
| US-531 | M | Token-gated settings write endpoint on states_http_server | **Atlas seam** (token-gate) |
| US-532 | M | Settings carousel card UI + effective-value render | **Iris UX** (+ US-403 reconcile) |
| US-533 | M | Wire the 5 settings end-to-end (read effective + write overlay + apply semantics) | none |

## Sequencing / gates

- **US-530 first** -- the overlay contract is the foundation everything else reads/writes. Atlas rules it before build.
- **US-531** depends on US-530's overlay + allow-list; reuses the existing token gate.
- **US-532** (Iris) + **US-533** wire the UI to the read/write path; land after 530/531.
- **Open gates for review:** Atlas (US-530 overlay contract + US-531 token-gate seam), Iris (US-532 screen shape + US-403 reconciliation).

## Validation (bench-gated; no car needed)

- Set an overlay override on the Pi, run a deploy, confirm the override **survives** (persistence proof).
- Swipe to / open the Settings screen: all 5 controls show their real effective values.
- Toggle auto-rotate off -> carousel stops rotating **live**; set power mode = wall -> System-Status power tile reads **WALL** (not unknown); both survive a reboot via the overlay.
- Token-gated write: authenticated allow-listed write persists; un-authenticated or out-of-allow-list write rejected with no change.

## Deferred (filed PENDING in backlog, not in this sprint)

- **US-534 -- Battery / Power Test action** (Slice 2): an action that runs a drain/UPS test. A drain test deliberately runs the pack toward cutoff to measure runtime-to-cutoff -- semantics + safety are **Spool's** domain; Atlas gates the shutdown/power-path touch. Ties to US-526 drain writer + US-527 verdict.
- **US-535 -- System Settings > Updates** (Slice 3): OS / library / OBD2-project updates. Own epic building on the existing `pi.update.*` config; only a placeholder screen is near-term.

## Notes

- The UPS (MAX17048) data surface is documented for reference: real registers = VCELL (trust), SOC (show but flag uncalibrated), CRATE (dead on this variant), VERSION/MODE/CONFIG (diagnostic). No current/source/temperature register; power source is VCELL-slope-derived. (Relevant to the deferred Battery/Power Test.)
- This PRD is the design artifact for F-126 Slice 1 (per PM Rule 4, no separate spec doc -- the design is captured here).
