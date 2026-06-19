# Pi Touch-Carousel Dashboard — F-092 System Status + F-097 Battery Health — Design Spec v1.2

| Field | Value |
|---|---|
| Feature IDs | **F-092** (System Status tile) · **F-097** (Battery Health, *pivoted* from "drain ladder state UI") |
| Backlog | `offices/pm/backlog/F-092-system-status-tile.md`, `offices/pm/backlog/F-097-drain-ladder-state-ui.md` |
| Author | Iris (UI/UX Designer) |
| Date | 2026-06-05 (v1); 2026-06-05 (v1.1 — folded in the long-press System Setup menu, D-6/D-7); 2026-06-19 (v1.2 — folded Spool's F-097 battery-health semantics + Atlas C-1 sequencing) |
| Status | **GROOM-READY (pending) — Atlas design-gate = CONDITIONAL PASS (2026-06-05 report, no BLOCK); v1.2 folds Spool's F-097 battery-health value semantics (2 render-breaking) + the C-1 sequencing condition. Near-term line (F-103 → this carousel shell → cards) GREEN-LIT by Atlas → Marcus. Argus acceptance advisory-open (non-blocking).** |
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
| D-6 | **System Setup menu** reachable from a **5–6s long-press anywhere** AND the top-bar `⋮` (both open the same menu) | Long-press is a deliberate, accident-proof gesture for consequential actions; `⋮` keeps it discoverable. A filling ring gives hold-feedback; release early cancels. (CIO 2026-06-05.) |
| D-7 | **Service handling: data services stoppable, `eclipse-powerwatch` restart-only** | Stopping the safe-shutdown guard could leave the Pi unprotected on key-off (drain/corruption). Stop + Exit-UI always confirm first. (CIO chose option A.) |

### 0.1 Changelog — v1.2 (Spool F-097 semantics + Atlas C-1, 2026-06-19)

Folds Spool's battery-health value semantics (`inbox/2026-06-18-from-spool-battery-health-f097-semantics.md`, 28 `battery_health_log` rows read off the Pi) + the Atlas gate's C-1 sequencing condition. **Two of Spool's findings are render-breaking** and must shape the card before build:

- **What it is (naming):** `battery_health_log` is the **Pi UPS-HAT LiPo cell (MAX17048 fuel gauge), NOT the car's 12 V lead-acid.** The card must never label it "vehicle battery". (§6 header clarified.)
- **Render-breaking #1 — `start_soc`/`end_soc` hold VOLTAGE, not percent.** Those columns (and `start_vcell_v`/`end_vcell_v`) carry **cell voltage 4.2 → 3.4 V**, not 0–100 % SoC. Rendering `3.44` as "3.44 %" would be badly wrong (it's 3.44 V, a near-empty LiPo). **SoC % must come from the MAX17048's own SoC register** — never from the voltage column, and never linearly interpolated from voltage (the curve is nonlinear: 4.2 V≈100, 3.7 V≈40–50, 3.42 V≈cutoff/near-0 under load). (§6 + schema + S-1.)
- **Render-breaking #2 — stale-green guard.** No drain events since 2026-05-16 → the health data is **month-old**. The card must show **data-age / "last health check"** so a stale GREEN isn't mistaken for a live reading. (§6 + schema `lastHealthCheckTs` + new acceptance test.)
- **Health verdict = GREEN** (Spool-validated): full charge reached every cycle (4.20–4.22 V), sane cutoff floor (~3.42–3.45 V), runtime-to-cutoff **~12 min** (14 clean full-drains, avg 714 s, range 617–831 s), **no degradation** across 2026-05-04..05-16. NORMAL view shows: full-charge-reachable · runtime-to-cutoff ~12 min · last-checked date.
- **Honesty gap — `ambient_temp_c` never logged** → can't show temp-vs-runtime (LiPo runtime is temp-sensitive; cold cuts it). Surface as **"not captured"**, don't fake it.
- **C-1 (sequencing):** unchanged — this carousel shell + cards depend on F-103 (kiosk + `eclipse-states-http`) landing first; nothing in `src/` yet. Already in the header "Depends on" + §7.

(GEAR-derivation note from the same Spool message belongs to the live-instrument surface W-11, not F-097 — tracked there.)

## 1. Executive Summary

A **touch-driven carousel dashboard** for the OSOYOO 3.5″ 480×320 display, replacing the pygame `status_display.py` with an HTML/chromium surface that shares the F-103 splash's kiosk + localhost state-server. It is the **post-boot UI**: when the F-103 boot splash reaches `HEALTHY_YIELD`, it hands off to this dashboard. The driver swipes left/right between cards; a persistent ~42px top bar shows live BT/sync/power status + a system menu. This spec designs the **carousel shell** (minimal, extensible) plus its **first two cards**: **F-092 System Status** (BT link, last sync, power mode, drive state — the honest-instrument fix for the I-033 "did it capture my drive?" gap) and **F-097 Battery Health** (VCELL-authoritative health readout, with the drain ladder demoted to a failsafe that surfaces only during a genuine drain). The dashboard is a **pure consumer** of two new read-only state files served by the (extended) `eclipse-states-http` service; it never owns or decides system state. A **System Setup menu** — reachable by a 5–6s long-press from any screen *or* the top-bar `⋮` — provides the maintenance basics: OBD-II service stop/start/restart (with `eclipse-powerwatch` restart-only for safety) and Exit/Close-UI, both behind confirms. Cards 3–5 (Engine / Drive / Alerts) and the full W-5/W-6 dashboard vision are named but out of scope.

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
- Far right: `⋮` button — opens the **System Setup menu** (§4.6). Also reachable by long-press (D-6).

### Navigation
- **Swipe left/right** moves between cards (CSS scroll-snap, or a minimal JS pager; momentum + snap). **Page dots** show position; current dot is an amber bar.
- **Simple buttons:** on-screen touch buttons within cards (e.g., "tap Battery → Battery Health card"); the `⋮` menu button. No multi-touch gestures beyond horizontal swipe in v1.
- Tap targets ≥ 40×40px (finger-friendly on a 3.5″ panel).

### Motion
Card transitions ≤ 250ms slide; no gratuitous animation (instrument feel). Respects the F-103 honest-instrument principle — motion never implies a state that isn't real.

### 4.6 System Setup menu [D-6, D-7]

A modal overlay over the dimmed dashboard, reachable two ways (both open the same menu):
- **Long-press anywhere ~5s** — press-and-hold with no movement. A radial **progress ring fills** during the hold so the gesture is visibly registering; **releasing early cancels** (no action). At full, the menu opens. This is the deliberate, accident-proof path for consequential actions.
- **Top-bar `⋮`** — a visible shortcut for discoverability.

**Gesture disambiguation:** long-press = touch held > ~600ms with movement < ~10px; a swipe (movement past threshold) is never read as a long-press, and vice-versa. The full open requires the sustained 5–6s hold; the early portion (>600ms) is only what arms the ring.

**Menu contents (v1 "basics"; extensible):**

| Section | Item | Behavior |
|---|---|---|
| OBD-II Services | `eclipse-obd` (data capture) | status dot + **Restart** / **Stop** (Stop confirms) |
| OBD-II Services | `eclipse-sync` (server upload) | status dot + **Restart** / **Stop** (Stop confirms) |
| OBD-II Services | `eclipse-powerwatch` (🛡 safe-shutdown guard) | status dot + **Restart only** — **no Stop** [D-7] |
| Display | **Exit / Close UI** | confirms, then closes the dashboard kiosk → drops to desktop. Confirm dialog states how it returns: next **reboot**, or `systemctl restart eclipse-dashboard` over SSH |
| Footer | version chip `V<x>·<sha>` + uptime | read-only |
| — | "+ more settings in future" | placeholder; future items (brightness, restart-UI, Wi-Fi, etc.) deferred |

**Honest + safe rules:**
- `eclipse-powerwatch` is **restart-only** — its Stop control is rendered disabled. Stopping the safe-shutdown guard could leave the Pi unprotected on key-off (drain/corruption). [D-7]
- **Stop** (any service) and **Exit/Close UI** require a confirm step. No single tap performs a consequential action.
- Service status dots reflect the real `systemctl is-active` state (read via the system-status emitter), not optimistic UI — a Stop that fails shows the service still running.
- A clear **✕ / Back to dashboard** always returns; the menu never traps the user. Auto-dismiss after inactivity is a future nicety, not v1.

**Privilege note (load-bearing → Atlas):** the kiosk runs as an unprivileged user; `systemctl stop/start/restart eclipse-*` and closing the kiosk need a privilege path (a **polkit rule** scoped to the specific units, or a small privileged helper). Precedent: the I-036 polkit poweroff rule. The kiosk must NOT run as root. Exact mechanism + the stoppable-unit allow-list are Atlas's call (A-7) — see §9.

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

> **What this card is about (Spool, render-critical):** the **Pi UPS-HAT LiPo cell** (MAX17048 fuel gauge) — *not* the car's 12 V lead-acid battery. Never label it "vehicle battery". It answers "will the Pi survive a clean shutdown on its own cell?", not anything about the car's charging system.

**Two states** [D-5]. NORMAL is the everyday readout; FAILSAFE renders **only** when `battery-health.draining === true`.

### NORMAL (on car / charging) — primary
```
UPS BATTERY HEALTH             ⚡ CHARGING · EXTERNAL
 4.02 V VCELL          HEALTHY · full charge reached
 SOC 76% (uncalibrated)   Charge +1.8%/h   Weak events 0/30d
 Runtime to cutoff  ~12 min          Temp  not captured
 Rested VCELL · last 8 cycles  ▁▂▁▂▂▁▂▂   no degradation
 Last health check  2026-05-16 (34d ago)
```
- **VCELL** authoritative + largest. **SOC** smallest, always tagged `(uncalibrated)` (US-264 rule). **SOC % is read from the MAX17048 SoC register — never derived from the voltage columns** (see the value-semantics note below); if only voltage is available, the card shows VCELL alone and omits SOC rather than faking a percent.
- **Health verdict = GREEN** (Spool-validated, 28 rows): full charge reached every cycle (4.20–4.22 V); sane cutoff floor (~3.42–3.45 V); **runtime-to-cutoff ~12 min** (14 clean full-drains, avg 714 s); no degradation trend.
- **Runtime-to-cutoff (~12 min)** is a *health stat* (typical full-drain time from Spool's history), distinct from the FAILSAFE's *live* runtime-remaining estimate (S-2, still owed).
- **Temp "not captured"** — `ambient_temp_c` is never logged, so a temp-vs-runtime view would be fabricated. State the gap honestly; LiPo runtime is temp-sensitive (cold shortens it).
- **Stale-green guard:** the health data is only as fresh as the last drain cycle (currently 2026-05-16, month-old). The card shows **"last health check · <date> (<age>)"** so a GREEN verdict is never mistaken for a live reading.
- Charge/discharge state from CRATE sign + power source. Health-over-time = rested-VCELL trend across recent power cycles (from `src/pi/power/battery_health.py` start/end-VCELL event log). "Weak events" = Spool-defined.

> **Value-semantics note (Spool, render-breaking).** The `battery_health_log` columns `start_soc`/`end_soc` (and `start_vcell_v`/`end_vcell_v`) hold **cell voltage in volts (4.2 → 3.4 V), not 0–100 % state-of-charge** — the `_soc` column name is misleading. Rendering `3.44` as "3.44 %" is badly wrong (it's 3.44 V, a near-empty cell). The emitter (§7) must publish `vcellV` from these columns and source `soc` (%) **only** from the MAX17048 SoC register — the voltage→SoC curve is nonlinear (4.2 V≈100, 3.7 V≈40–50, 3.42 V≈cutoff), so **never linearly interpolate** a percent from voltage.

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
| **VCELL** (authoritative) | `battery_health_log.*_vcell_v` / `*_soc` columns (both hold **volts**) + live MAX17048 | exists; **Spool semantics DELIVERED** |
| **SOC %** | **MAX17048 SoC register ONLY** (never from the voltage columns; never lerp from voltage) | **Spool (S-1) — DELIVERED** (render-breaking trap flagged) |
| CRATE | MAX17048 reader / power-watch | exists |
| rested-VCELL history | `battery_health.py` event log | exists |
| **Health verdict = GREEN** (full-charge-reachable, cutoff floor, no-degradation) | Spool analysis of 28 rows | **Spool (S-1) — DELIVERED** |
| **Runtime-to-cutoff ~12 min** (health stat) | Spool history (14 drains, avg 714 s) | **Spool (S-1) — DELIVERED** |
| **`ambient_temp_c`** | never logged → render "not captured" | **DELIVERED** — confirmed gap, don't fake |
| **Data-age / last-health-check** | timestamp of last drain cycle | **DELIVERED** — stale-green guard |
| **Ladder thresholds** (3.70 / 3.55 / 3.45 V — *placeholders*) | power-watch staged-shutdown config | **Spool (S-1)** — confirm exact values (failsafe only) |
| **Live runtime-remaining formula** (from CRATE / drain rate, during a drain) | NEW derivation | **Spool (S-2)** — still owed; flag if not derivable (failsafe only) |
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
| service-control privilege path (polkit rule **or** small privileged helper) | NEW | lets the unprivileged kiosk run `systemctl restart/stop/start` on a fixed allow-list of `eclipse-*` units + close the kiosk. Scoped to specific units; kiosk never runs as root. Mechanism = Atlas A-7. Precedent: I-036 polkit poweroff. |

**System-menu action wiring:** the kiosk issues service actions + exit via the privilege path above (e.g. an authenticated localhost POST to a tiny privileged action endpoint, OR a polkit-authorized `systemctl` invocation). The allow-list is **fixed at install** (not runtime-configurable): `eclipse-obd`, `eclipse-sync` (restart/stop/start); `eclipse-powerwatch` (**restart only**); `eclipse-dashboard` (stop = "Exit UI"). Any unit not on the list is rejected. "Exit UI" stops the kiosk unit; it auto-starts again on next boot (its `WantedBy=graphical.target`).

### State file shapes (proposed; Atlas ratifies paths/schemas/ownership)
```json
// system-status
{ "obdLink": {"state":"reconnecting","retries":3,"lastSeenS":14},
  "sync": {"lastOkTs":"2026-06-05T19:40:00Z","rows":1204,"pending":0,"stale":false},
  "power": {"mode":"car","source":"external"},
  "drive": {"state":"recording","driveId":27},
  "ts": "2026-06-05T19:42:00Z" }

// battery-health  (Pi UPS LiPo cell — MAX17048; NOT the car 12V)
{ "vcellV":4.02,                // authoritative; from battery_health_log *_vcell_v / *_soc (both VOLTS)
  "soc":76, "socCalibrated":false,// % from the MAX17048 SoC REGISTER ONLY — never lerp from vcellV; null if register unavailable
  "crate":1.8, "charging":true, "draining":false,
  "restedVcellV":4.05, "weakEvents30d":0, "restedHistory":[4.05,4.04,...],
  "health":"green",             // Spool verdict: full-charge-reachable + sane cutoff + no degradation
  "fullChargeReached":true,     // 4.20–4.22V every cycle
  "runtimeToCutoffS":714,       // health stat (typical full-drain ~12min); NOT the live failsafe estimate
  "ambientTempC": null,         // never logged → UI renders "not captured", never fabricated
  "lastHealthCheckTs":"2026-05-16T00:00:00Z", // stale-green guard — UI shows date + age
  "ladder": null,               // null unless draining
  "ts": "2026-06-05T19:42:00Z" }
// when draining: "ladder": {"stage":"WARNING","thresholds":{...},"runtimeRemainingS":360}  // runtimeRemainingS = live (S-2, owed)
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
| S-5 | System menu: `eclipse-powerwatch` row has **no enabled Stop control**; data-service rows do | DOM test |
| S-6 | Service-control rejects any unit not on the install-fixed allow-list | unit test of the privilege path |
| S-7 | **SoC never derived from voltage:** fixture `vcellV:3.44` with `soc:null` → card shows `3.44 V` and **omits** the percent (never "3.44 %"); a `soc` value renders only when present + tagged `(uncalibrated)` | fixture test (both branches) |
| S-8 | **Stale-green guard:** fixture `lastHealthCheckTs` 30+ days old → card shows "last health check · <date> (<age>)"; GREEN verdict is never shown without its data-age | DOM test |
| S-9 | **Temp gap honest:** `ambientTempC:null` → card shows "not captured", never a fabricated temperature | fixture test |
| S-10 | Battery card labels the cell as the **UPS/Pi battery**, never "vehicle"/"car battery" | DOM string test |

### IRL
| # | Criterion | Evidence |
|---|---|---|
| I-1 | Boot splash hands off → dashboard visible on OSOYOO within ≤3s of splash yield | photo + journal |
| I-2 | Swipe L/R navigates System Status ↔ Battery Health on the physical touch panel | screen recording |
| I-3 | **I-033 fix:** force BT drop mid-drive → OBD link tile shows `RECONNECTING` + retry within ≤2s; top-bar BT glyph flips amber | recording + `cat system-status` |
| I-4 | Last-sync tile matches actual last successful sync; goes amber when stale-while-driving | screenshot + sync log |
| I-5 | Battery card NORMAL: VCELL matches MAX17048; SOC tagged `(uncalibrated)` and matching the SoC register (not voltage-derived); "last health check" date + age shown | screenshot + reading |
| I-6 | **Failsafe:** pull wall power while parked (no ignition) → card escalates to ladder + runtime within ≤2s; auto-shutdown fires at TRIGGER | recording + power log |
| I-7 | Pygame `status_display` no longer launched (superseded) | `pgrep`/journal |
| I-8 | Long-press ~5s opens System Setup (ring fills during hold); a release < 5s cancels with no menu | screen recording |
| I-9 | Top-bar `⋮` opens the same System Setup menu | recording |
| I-10 | `eclipse-powerwatch` shows Restart but **no working Stop**; tapping its (disabled) stop does nothing | recording |
| I-11 | Stop `eclipse-obd` → confirm → service stops; its status dot reflects stopped within ≤2s; Restart brings it back | recording + `systemctl status` |
| I-12 | Exit/Close UI → confirm → kiosk closes to desktop; returns on next reboot | recording + journal |

### Failure modes (must NOT happen)
| F | Failure | Detection |
|---|---|---|
| F-1 | Tile shows green/healthy when the underlying state is stale or down (green-when-broken) | I-3, I-4 |
| F-2 | Ladder/drain UI shown when not actually draining (dishonest instrument — the D-2 trap) | S-4, I-6 inverse |
| F-3 | Dashboard polls hardware directly instead of reading state files | code review |
| F-4 | Both pygame + HTML dashboards run (double surface) | I-7 |
| F-5 | Touch swipe unreliable / dead zones on the physical panel | I-2 |
| F-6 | A single accidental tap performs a consequential action (must require long-press + confirm) | I-8, I-11, I-12 |
| F-7 | `eclipse-powerwatch` can be stopped from the menu (safe-shutdown guard removed) | S-5, I-10 |
| F-8 | Cell voltage rendered as a percent (e.g. "3.44 %" from the misnamed `*_soc` column) — the render-breaking trap | S-7 |
| F-9 | A stale GREEN health verdict shown as if live (no data-age) | S-8 |
| F-10 | Fabricated ambient temperature shown though `ambient_temp_c` is never logged | S-9 |
| F-11 | UPS LiPo cell mislabeled as the car/vehicle battery | S-10 |
| F-12 | User trapped in the menu with no way back to the dashboard | I-9 (✕/back present) |
| F-13 | Service-control runs the kiosk as root, or accepts an arbitrary unit name | S-6, code review |

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
| A-7 | **System-menu service control privilege path** — polkit rule vs privileged helper; the install-fixed stoppable-unit allow-list (`eclipse-obd`/`eclipse-sync` stop+restart, `eclipse-powerwatch` restart-only, `eclipse-dashboard` stop=Exit). Kiosk stays unprivileged. (I-036 polkit precedent.) | PENDING |
| A-8 | **Exit/Close-UI lifecycle** — stopping the kiosk unit cleanly + auto-relaunch on reboot; confirm-and-return contract | PENDING |

### Spool (semantics)
| # | Item |
|---|---|
| S-1 | ~~"weak event"/"healthy"/charge-rate meanings + battery-health value semantics~~ — **DELIVERED 2026-06-18** (`inbox/2026-06-18-from-spool-battery-health-f097-semantics.md`): health verdict GREEN, VCELL-authoritative, SoC-from-register (not voltage), runtime-to-cutoff ~12 min, temp-not-captured, stale-green guard. Folded §6/§7. **Ladder thresholds (3.70/3.55/3.45 V) still to confirm** (failsafe only). |
| S-2 | Estimated **live** runtime-remaining formula (from CRATE/drain rate, *during* a drain — distinct from the ~12 min health stat); flag if not derivable. **Still owed.** |
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
| M-1 | Proposed split: **US-A** carousel shell (kiosk + swipe + top bar + state-server extension) · **US-B** F-092 System Status card + system-status emitter · **US-C** F-097 Battery Health card + battery-health emitter (+ Spool semantics: SoC-from-register-not-voltage, stale-green data-age, temp-not-captured, UPS-not-vehicle labeling) · **US-D** pygame sunset · **US-E** System Setup menu (long-press + `⋮` + service control + Exit + privilege path [A-7/A-8]) |
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
*End of spec v1.2. Atlas design-gate = CONDITIONAL PASS (no BLOCK); v1.2 folds Spool's F-097 battery-health value semantics (2 render-breaking: voltage-not-percent + stale-green) + C-1 sequencing. Near-term line green-lit by Atlas → groom-ready to Marcus. Spool S-2 (live runtime-remaining formula) + ladder thresholds still owed for the failsafe sub-state only. Argus acceptance advisory-open (non-blocking).*
