# Pi Touch-Carousel Dashboard — F-092 System Status + F-097 Battery Health — Design Spec v1

| Field | Value |
|---|---|
| Feature IDs | **F-092** (System Status tile) · **F-097** (Battery Health, *pivoted* from "drain ladder state UI") |
| Backlog | `offices/pm/backlog/F-092-system-status-tile.md`, `offices/pm/backlog/F-097-drain-ladder-state-ui.md` |
| Author | Iris (UI/UX Designer) |
| Date | 2026-06-05 |
| Status | **DRAFT — design brainstormed + CIO-approved; pending Atlas design-gate (Rule 10) + Spool semantics + Argus acceptance** |
| Target sprint | V0.28+ |
| Depends on | **F-103 splash** (shares the chromium kiosk + `eclipse-states-http` localhost state-server) — see `docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md` |
| Supersedes | `src/pi/hardware/status_display.py` + `dashboard_layout.py` (pygame 4-quadrant dashboard, US-257/B-052) — coordinated sunset, not a hard cut |

## 0. Provenance & Decisions (CIO brainstorm 2026-06-05)

Designed with the CIO via live HTML mockups. Decisions ratified this session:

| # | Decision | Rationale |
|---|---|---|
| D-1 | **Display stack = HTML/chromium** (not the existing pygame dashboard) | CIO wants touch: swipe-L/R carousel navigation + simple on-screen buttons. HTML does touch/gesture/animation natively; pygame would hand-roll a UI framework. Also unifies the human surface with the F-103 splash (one visual SSOT). |
| D-2 | **F-097 pivots: "drain ladder state UI" → "Battery Health"** | The new key-off **ShutdownSequencer** (F-7) shuts the Pi down promptly on ignition-off (~10–12s); it no longer sits draining the UPS down a ladder (the old US-216 staged-shutdown-at-30%-SOC model). A live drain-ladder readout would be a *dishonest instrument* — implying a draining process the sequencer specifically prevents. Battery **health** is the meaningful everyday view; the ladder is demoted to a **failsafe** that appears only during a genuine drain. |
| D-3 | **Persistent thin top bar** (W-5 option) for system-menu access | Instrument honesty: BT/sync/power status must be glanceable on *every* card (directly serves the I-033 BT-reconnect visibility gap). Chosen over full-bleed + hidden swipe-down menu. |
| D-4 | **F-092 layout = 2×2 status tiles + drive banner** | Bigger state words readable from the driver's seat at arm's length; color-coded. |
| D-5 | **F-097 layout = two-state card** (NORMAL health view + FAILSAFE ladder escalation) | Health primary; ladder/runtime/thresholds render only when a real drain is underway. |

## 1. Executive Summary

A **touch-driven carousel dashboard** for the OSOYOO 3.5″ 480×320 display, replacing the pygame `status_display.py` with an HTML/chromium surface that shares the F-103 splash's kiosk + localhost state-server. It is the **post-boot UI**: when the F-103 boot splash reaches `HEALTHY_YIELD`, it hands off to this dashboard. The driver swipes left/right between cards; a persistent ~42px top bar shows live BT/sync/power status + a system menu. This spec designs the **carousel shell** (minimal, extensible) plus its **first two cards**: **F-092 System Status** (BT link, last sync, power mode, drive state — the honest-instrument fix for the I-033 "did it capture my drive?" gap) and **F-097 Battery Health** (VCELL-authoritative health readout, with the drain ladder demoted to a failsafe that surfaces only during a genuine drain). The dashboard is a **pure consumer** of two new read-only state files served by the (extended) `eclipse-states-http` service; it never owns or decides system state. Cards 3–5 (Engine / Drive / Alerts) and the full W-5/W-6 dashboard vision are named but out of scope.

## 2. Context & Motivation

### What exists today
- **Pygame dashboard** (`src/pi/hardware/status_display.py` + `dashboard_layout.py`, US-257/B-052, May 2026) — canvas-aware 4-quadrant layout (NW engine / NE power+shutdown-stage / SW drive+OBD2 / SE alerts) + footer (uptime · IP · DTC), wired via `hardware_manager.py`. It already renders much of F-092/F-097's data and encodes a hard-won honest-instrument rule (`PowerCardFields`, US-264): **VCELL is the authoritative battery readout; SOC is shown smallest + tagged `(uncalibrated)`** because Drain Test 6 misled the operator (SOC 96% while VCELL near WARNING).
- **F-103 splash** — HTML/chromium boot/shutdown splash + the `eclipse-states-http` localhost state-server pattern (127.0.0.1:9899, read-only, stdlib).

### Why change
- The CIO wants **touch interaction** (swipe carousel + buttons) the pygame surface can't deliver without re-inventing a UI toolkit.
- Two human-surface stacks (pygame dashboard + chromium splash) means visual drift + two codebases. HTML unifies them under one visual SSOT (the F-103 tokens) — avoids the multi-generation drift Atlas catalogued (A-2).
- The **shutdown model changed**: F-097's original "drain ladder" framing describes a scenario the new sequencer prevents (see D-2). The card must pivot to stay honest.

### What this spec adds
- A minimal **carousel shell**: chromium kiosk post-boot UI, swipe nav, persistent top bar, page dots, button affordances.
- **F-092 System Status card** — honest-instrument status with freshness on every field (the I-033 fix).
- **F-097 Battery Health card** — two-state: health normally, failsafe ladder only during a real drain.
- Two new **state emitters** + endpoints on the extended state-server.

### Out of scope (named, deferred)
| Item | Why deferred |
|---|---|
| Cards 3–5 (Engine / Drive / Alerts+DTC) | Graft on later from the pygame dashboard's existing data; shell is extensible |
| Full W-5 dashboard vision (enlarged canvas variants, minimize behaviors beyond the top bar) | Bigger surface; design when V0.28+ grooming opens it |
| W-6 GEM-1 warnings-first quiet carousel | Separate backlog item; the carousel shell here is the substrate it will use |
| 1080p HDMI variant | OSOYOO 480×320 is the target (shell is responsive but only 480×320 is specced/tested in v1) |
| On-screen keyboard / text entry | No text-entry use case in v1 |
| Tuning gauges (coolant/knock/AFR) | V0.28+ B-076 downstream; will inherit the F-103 `--amber-warn` token + Spool's future palette |

## 3. System Overview & Data Flow

The dashboard is a **consumer** of two SSOTs, mirroring the F-103 splash pattern.

```
F-103 boot splash  ──HEALTHY_YIELD──►  dashboard kiosk (this spec)
                                            │  swipe nav between cards
                                            │  fetch @ ~1s via localhost HTTP
                                            ▼
   ┌─────────────────────────┐     ┌──────────────────────────────┐
   │ eclipse-states-http      │◄────│ /var/run/eclipse-obd/states/ │
   │ (F-103; EXTENDED to      │     │   system-status   (NEW)      │
   │  full runtime, read-only)│     │   battery-health  (NEW)      │
   └─────────────────────────┘     └──────────────┬───────────────┘
                                                   │ written by
                          ┌────────────────────────┴───────────────────────┐
                          │ system-status emitter (NEW): BT link / sync /   │
                          │   power mode / drive state                      │
                          │ battery-health emitter (NEW): VCELL / CRATE /   │
                          │   SOC / health-over-time / ladder (drain-only)  │
                          └─────────────────────────────────────────────────┘
```

### Key contracts (carry from F-103)
1. Dashboard **never polls hardware** (GPIO6, MAX17048, OBDLink) directly. It reads only the state files those services author. One direction of data flow.
2. Dashboard **never decides system state**. It renders what the emitters report. If `system-status` says the BT link is `reconnecting`, it paints amber. If `battery-health` reports `draining:false`, the ladder does not render.
3. The dashboard **supersedes** the pygame `status_display.py`. The data that module reads in-process gets republished via the two emitters so the HTML surface can read it over HTTP.

### Lifecycle
- Launched after the F-103 boot splash yields (splash JS `window.close()` on `HEALTHY_YIELD` → dashboard kiosk starts). **[Atlas: hand-off mechanism — A-1.]**
- `eclipse-states-http` lifetime extends from boot-only to full runtime. **[Atlas: A-2.]**

## 4. Carousel Shell — Visual Spec

### Canvas & stack
480×320 native, chromium kiosk (`--ozone-platform=wayland`, same flags as F-103 `splash-boot.service`). Visual SSOT = the F-103 tokens (mono type, `--text-secondary #888`, `--text-tertiary #666`, `--amber-warn #FFC400`, brand reds). No web fonts.

### Layout
```
┌──────────────────────────────────────────────┐ y=0
│ ECLIPSE OBD-II        ✦BT  ⟳2m  ⏻CAR   ⋮     │ y=0..42  persistent top bar
├──────────────────────────────────────────────┤ y=42
│                                              │
│              [ active card ]                 │ card viewport (y=42..290)
│                                              │
├──────────────────────────────────────────────┤ y=290
│               ▬ ○ ○ ○ ○                      │ y=290..320  page dots
└──────────────────────────────────────────────┘ y=320
```

### Top bar (persistent, ~42px) [D-3]
- Left: `ECLIPSE OBD-II` wordmark (mono, `#888`, 10–13px, 0.14em tracking).
- Right: live status glyphs — **BT** (✦), **sync** (⟳ + age), **power** (⏻ CAR/WALL/BATT) — each colored by state (green ok / amber attention / red fault). These are the *at-a-glance* mirror of the System Status card's detail.
- Far right: `⋮` system-menu button (opens a system overlay — power off, brightness, restart kiosk, version chip `V<x>·<sha>`). System-menu contents are minimal in v1; full menu = future.

### Navigation
- **Swipe left/right** moves between cards (CSS scroll-snap, or a minimal JS pager; momentum + snap). **Page dots** show position; current dot is an amber bar.
- **Simple buttons:** on-screen touch buttons within cards (e.g., "tap Battery → Battery Health card"); the `⋮` menu button. No multi-touch gestures beyond horizontal swipe in v1.
- Tap targets ≥ 40×40px (finger-friendly on a 3.5″ panel).

### Motion
Card transitions ≤ 250ms slide; no gratuitous animation (instrument feel). Respects the F-103 honest-instrument principle — motion never implies a state that isn't real.

## 5. F-092 — System Status Card

Layout = **2×2 status tiles + a drive banner** [D-4]. Every tile carries **freshness** — the core honest-instrument behavior and the I-033 fix.

```
SYSTEM STATUS
┌───────────────────┬───────────────────┐
│ OBD LINK          │ LAST SYNC         │
│ RECONNECTING ⚠    │ 2 min ago         │
│ last seen 14s·r3  │ 1,204 rows·0 pend │
├───────────────────┼───────────────────┤
│ POWER             │ BATTERY           │
│ CAR · ext         │ 4.02 V  ✓         │
│ engine running    │ healthy · tap ›   │
└───────────────────┴───────────────────┘
  Drive   ● recording · Drive 27
```

### Fields & data sources
| Tile | Shows | State enum | Source (verify at build) | Gap? |
|---|---|---|---|---|
| **OBD link** | BT/OBDLink link state + freshness | `linked` / `reconnecting` (retry n, last-seen) / `down` | rfcomm0 / OBD stream service; the I-033 reconnect path | partial — reconnect detail must be exposed |
| **Last sync** | time since last successful Pi→server sync + rows synced + pending count | fresh / **stale** (amber) | `src/pi/data/sync_log.py`, `src/pi/sync/client.py` | **NEW** — "last successful sync" timestamp must be surfaced to the emitter |
| **Power** | in-car vs wall mode + external/battery source | `car·ext` / `car·batt` / `wall·debug` | `power_log` / power-watch; the in-car-vs-wall guardrail (Spool) | exists; semantics → Spool |
| **Battery** | VCELL + one-word health; tap → Battery Health card | `healthy` / `attn` / `low` | battery-health emitter (§6) | reuse |
| **Drive** (banner) | recording state | `● recording · Drive N` / `idle` | DriveDetector / obd database | exists |

### Honest-instrument rules
- Each tile shows **how fresh** its value is; staleness → amber, not silent green. (V0.27.x false-pass lessons applied at the pixel layer.)
- **OBD link** is the I-033 fix: surfacing `reconnecting` + retry-count + last-seen means "did it capture my drive?" is never a mystery again.
- **Last sync stale** while a drive is recording → amber (threshold = Spool, S-3).

### Acceptance-relevant behaviors
- Tile reflects the emitter's value within ≤ 2s of a real state change.
- Tapping the Battery tile navigates to the Battery Health card.

## 6. F-097 — Battery Health Card (pivoted)

**Two states** [D-5]. NORMAL is the everyday readout; FAILSAFE renders **only** when `battery-health.draining === true`.

### NORMAL (on car / charging) — primary
```
BATTERY HEALTH                 ⚡ CHARGING · EXTERNAL
 4.02 V VCELL          HEALTHY · rested 4.05 V
 SOC 76% (uncalibrated)   Charge +1.8%/h   Weak events 0/30d
 Rested VCELL · last 8 cycles  ▁▂▁▂▂▁▂▂
 Holds voltage normally · no degradation trend
```
- **VCELL** authoritative + largest. **SOC** smallest, always tagged `(uncalibrated)` (US-264 rule).
- Charge/discharge state from CRATE sign + power source. Health-over-time = rested-VCELL trend across recent power cycles (from `src/pi/power/battery_health.py` start/end-VCELL event log). "Weak events" = Spool-defined.

### FAILSAFE (wall power lost + actually draining) — conditional
```
BATTERY HEALTH                 ⚠ ON UPS BATTERY · DRAINING
 3.58 V VCELL          WARNING · wall power lost
 [NORMAL ≥3.70][WARNING 3.55–3.70•][IMMINENT 3.45–3.55][TRIGGER ≤3.45]
 Est. runtime remaining          ~6 min
 Auto safe-shutdown at TRIGGER (3.45 V) — pack protected
```
- Ladder stage + VCELL thresholds + **estimated runtime remaining** (the original F-097 ask, correctly placed: it only matters during a drain).
- Amber escalation; honest about the auto-shutdown promise.

### Data sources & Spool ownership
| Element | Source | Owner |
|---|---|---|
| VCELL, SOC, CRATE | MAX17048 reader / power-watch | exists |
| rested-VCELL history | `battery_health.py` event log | exists |
| **Ladder thresholds** (3.70 / 3.55 / 3.45 V — *placeholders*) | power-watch staged-shutdown config | **Spool (S-1)** — confirm exact values |
| **Runtime-remaining formula** (from CRATE / drain rate) | NEW derivation | **Spool (S-2)** — define formula; flag if not derivable |
| "weak event" / "healthy" / charge-rate semantics | — | **Spool (S-1)** |
| `draining` boolean (when does failsafe render) | power-watch (wall-power-lost + sustained) | **Spool/Atlas** — must be honest re sequencer interplay |

## 7. Integration / Architecture

### New + changed units
| Unit / file | Status | Purpose |
|---|---|---|
| dashboard kiosk (`splash`-sibling chromium service) | NEW | renders the HTML carousel post-boot; Wayland/X11 variants like F-103 |
| `eclipse-states-http.service` | **EXTEND** (F-103) | lifetime boot-only → full runtime; serves the two new state files read-only |
| system-status emitter | NEW | writes `/var/run/eclipse-obd/states/system-status` |
| battery-health emitter | NEW | writes `/var/run/eclipse-obd/states/battery-health` |
| `src/pi/hardware/status_display.py` + `dashboard_layout.py` | **SUPERSEDE** | pygame dashboard retired once HTML surface reaches parity; data republished via emitters |

### State file shapes (proposed; Atlas ratifies paths/schemas/ownership)
```json
// system-status
{ "obdLink": {"state":"reconnecting","retries":3,"lastSeenS":14},
  "sync": {"lastOkTs":"2026-06-05T19:40:00Z","rows":1204,"pending":0,"stale":false},
  "power": {"mode":"car","source":"external"},
  "drive": {"state":"recording","driveId":27},
  "ts": "2026-06-05T19:42:00Z" }

// battery-health
{ "vcellV":4.02, "soc":76, "socCalibrated":false, "crate":1.8,
  "charging":true, "draining":false,
  "restedVcellV":4.05, "weakEvents30d":0, "restedHistory":[4.05,4.04,...],
  "ladder": null,        // null unless draining
  "ts": "2026-06-05T19:42:00Z" }
// when draining: "ladder": {"stage":"WARNING","thresholds":{...},"runtimeRemainingS":360}
```

### Touch
OSOYOO capacitive touch over USB-C reaches chromium natively; no extra driver work expected (verify at build). Kiosk launched with touch enabled (no `--touch-events=disabled`).

## 8. Acceptance Criteria (Argus patterns: single-boolean, evidence-survival, failure-mode enumeration)

### Synthetic (CI-runnable)
| # | Criterion | Evidence |
|---|---|---|
| S-1 | Dashboard HTML renders both cards headless with no console errors | headless chrome log |
| S-2 | Carousel swipe advances card + updates page-dot; tap-target ≥40px | DOM/geometry test |
| S-3 | Card renders emitter JSON verbatim; malformed JSON → card shows `unavailable`, no crash | fixture test |
| S-4 | Battery card: `draining:false` → NO ladder DOM; `draining:true` → ladder present | fixture test (both) |

### IRL
| # | Criterion | Evidence |
|---|---|---|
| I-1 | Boot splash hands off → dashboard visible on OSOYOO within ≤3s of splash yield | photo + journal |
| I-2 | Swipe L/R navigates System Status ↔ Battery Health on the physical touch panel | screen recording |
| I-3 | **I-033 fix:** force BT drop mid-drive → OBD link tile shows `RECONNECTING` + retry within ≤2s; top-bar BT glyph flips amber | recording + `cat system-status` |
| I-4 | Last-sync tile matches actual last successful sync; goes amber when stale-while-driving | screenshot + sync log |
| I-5 | Battery card NORMAL: VCELL matches MAX17048; SOC tagged `(uncalibrated)` | screenshot + reading |
| I-6 | **Failsafe:** pull wall power while parked (no ignition) → card escalates to ladder + runtime within ≤2s; auto-shutdown fires at TRIGGER | recording + power log |
| I-7 | Pygame `status_display` no longer launched (superseded) | `pgrep`/journal |

### Failure modes (must NOT happen)
| F | Failure | Detection |
|---|---|---|
| F-1 | Tile shows green/healthy when the underlying state is stale or down (green-when-broken) | I-3, I-4 |
| F-2 | Ladder/drain UI shown when not actually draining (dishonest instrument — the D-2 trap) | S-4, I-6 inverse |
| F-3 | Dashboard polls hardware directly instead of reading state files | code review |
| F-4 | Both pygame + HTML dashboards run (double surface) | I-7 |
| F-5 | Touch swipe unreliable / dead zones on the physical panel | I-2 |

## 9. Routing Surface

### Atlas (design-gate, Rule 10) — load-bearing
| # | Item | Verdict |
|---|---|---|
| A-1 | Splash→dashboard hand-off mechanism (lifecycle) | PENDING |
| A-2 | Extend `eclipse-states-http` to full runtime; new endpoints | PENDING |
| A-3 | Two new emitters: ownership, paths, schemas (`/var/run/eclipse-obd/states/{system-status,battery-health}`) | PENDING |
| A-4 | Superseding pygame `status_display.py` — sunset path + parity bar (coordinate w/ Ralph) | PENDING |
| A-5 | Touch enablement in chromium kiosk | PENDING |
| A-6 | `draining` boolean semantics vs ShutdownSequencer (no false failsafe) | PENDING (jointly w/ Spool) |

### Spool (semantics)
| # | Item |
|---|---|
| S-1 | Ladder thresholds (3.70/3.55/3.45 V — confirm), "weak event"/"healthy"/charge-rate meanings |
| S-2 | Estimated-runtime-remaining formula (from CRATE/drain rate); flag if not derivable |
| S-3 | "Last sync stale" threshold (when stale-while-driving becomes amber); power-mode (in-car vs wall) semantics |

### Argus (advisory)
| # | Item |
|---|---|
| Q-1 | §8 acceptance criteria sign-off |
| Q-2 | IRL drill methodology — inducing BT-drop (I-3) + a controlled drain (I-6) safely |
| Q-3 | Evidence capture for touch + visual criteria |

### Marcus (PM — sprint scoping)
| # | Item |
|---|---|
| M-1 | Proposed split: **US-A** carousel shell (kiosk + swipe + top bar + state-server extension) · **US-B** F-092 System Status card + system-status emitter · **US-C** F-097 Battery Health card + battery-health emitter (+ Spool semantics) · **US-D** pygame sunset |
| M-2 | **Depends on F-103** (shared kiosk + `eclipse-states-http`) — sequence F-103 first or together |
| M-3 | Rule-10 DoD: the state-server extension + emitters land matching `specs/architecture.md` updates in-sprint (per A-2/A-3) |

## 10. Open Questions
- **Pygame sunset timing** — supersede in the same sprint as US-A, or run both briefly until HTML reaches parity? (Atlas A-4.)
- **Runtime-remaining derivability** — is CRATE stable enough on the UPS to estimate minutes, or is it best-effort/±? (Spool S-2.) If not derivable, the failsafe shows VCELL + stage only, no minutes.
- **System-menu scope in v1** — power-off / brightness / restart-kiosk / version only, or more? (CIO at grooming.)

## 11. Routing Plan
```
Iris (this spec) → CIO review
   → A2AL Atlas (design-gate A-1..A-6, load-bearing)
   → A2AL Spool (semantics S-1..S-3)
   → A2AL Argus (advisory Q-1..Q-3)
   → on Atlas sign-off: A2AL Marcus (groom-ready, story split M-1)
```

---
*End of spec v1. Held for CIO review before routing.*
