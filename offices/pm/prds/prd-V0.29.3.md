---
sprint: 49
version: V0.29.3
status: draft
createdAt: 2026-06-29
createdBy: Marcus (PM)
reviewTier: load-bearing
forksFrom: dev @ (recorded at conversion; AFTER Sprint 48/V0.29.2 lands -- F-103 is the prerequisite runtime)
epic: E-001
feature: F-092, F-097, F-111
theme: Pi touch UI -- carousel dashboard (System Status + Battery Health) + DTC viewer / gated Mode-04 clear
validationMode: BENCH ONLY (CIO waived drive requirements; fixture/DOM tests + boot/touch/UPS-bench drills + a P0443-class DTC read on the bench -- NO drive drills)
designGate: SIGNED OFF -- Atlas A-1..A-8 carousel + DTC rulings (KOEO connection-edge, Mode-04 polkit) 2026-06-30; report offices/architect/reports/2026-06-30-carousel-dtc-design-gate-signoff-sprint49.md
selectedStories: [US-399, US-400, US-401, US-402, US-403, US-404, US-405, US-406, US-407]
---

# PRD — Sprint 49 / V0.29.3 — Pi Touch-Carousel Dashboard (F-092 / F-097)

## Summary

The full Pi touch-UI sprint: the **chromium touch-carousel dashboard** that replaces
the pygame `status_display` — **F-092 System Status** + **F-097 Battery Health** cards
+ a swipe shell + persistent top bar + a long-press **System Setup** menu with gated
service control — **plus the F-111 DTC viewer** (Card 5: check-engine takeover/ribbon,
Alerts card + detail, and the gated **Mode-04 clear** vehicle-write path). It **builds
on F-103** (Sprint 48, shipped): reuses the chromium kiosk + `eclipse-states-http` +
token + states dir, **extends `eclipse-states-http` to full runtime**, and adds three
new emitters (system-status, battery-health, dtc). **9 stories** (CIO-directed single
combined sprint; Atlas concurred ~9).

Spec (GROOM-READY v1.2, Atlas CONDITIONAL-PASS 2026-06-05):
`docs/superpowers/specs/2026-06-05-pi-touch-carousel-dashboard-f092-f097-design.md`.

**Fully BENCH-VALIDATABLE** (CIO waived drive requirements) — almost every gate is a
fixture-based DOM/JSON render test; the rest are boot/touch/UPS-bench drills on the
Pi. No drives. The two acceptance criteria that need real conditions (BT-drop,
UPS-drain) are inducible on the bench/rig.

## ✅ Design gate — Atlas SIGNED OFF 2026-06-30 (load-bearing tier)

Atlas reviewed + **PASSED** both the carousel + DTC design-gates (report
`offices/architect/reports/2026-06-30-carousel-dtc-design-gate-signoff-sprint49.md`,
no BLOCK). His A-1..A-8 carousel rulings stand; the two still-open DTC items he ruled
(below). The A-gate table is the architecture each story builds to:

| Gate | What | Story |
|---|---|---|
| **A-1** | Splash→dashboard hand-off mechanism (F-103 `HEALTHY_YIELD` → dashboard kiosk starts) | US-399 |
| **A-2** | Extend `eclipse-states-http` boot-only → **full runtime** + the two new endpoints | US-399 |
| **A-3** | Two new emitters — ownership, paths, **state-file schemas** (`system-status`, `battery-health`) | US-400, US-401 |
| **A-4** | Pygame sunset path + parity bar (coordinate with Ralph) | US-402 |
| **A-5** | Touch enablement in the chromium kiosk | US-399 |
| **A-6** | `draining` boolean semantics vs ShutdownSequencer (no false failsafe) — joint w/ Spool | US-401 |
| **A-7** | **Service-control privilege path** (polkit rule vs privileged helper; install-fixed allow-list; kiosk never root) | US-403 |
| **A-8** | Exit/Close-UI kiosk lifecycle (clean stop + auto-relaunch on reboot) | US-403 |

**Atlas's 2 DTC rulings (folded into the DTC stories):**
1. **KOEO read (US-404):** fires on the OBD **connection-established edge** (`event_router` `onConnectionRestored`), one-shot Mode 03(+07), **gated on no active RUNNING drive**, owned by the DTC capture path (`dtc_logger` connection-edge entrypoint reusing `dtc_client`) — NOT DriveDetector. **Stamp `drive_id = NULL` EXPLICITLY** (not via `getCurrentDriveId` — a pre-US-388 stale-open leak could pollute it; cross-links A-9 Root 2).
2. **C-5 states-dir carry-forward:** the 3 new state files (`system-status` / `battery-health` / `dtc`) ride the **Sprint-48 F-103 states-dir provisioning** — emitters order *after* it, do NOT re-invent it; extend the Sprint-48 `architecture.md` states-dir lifecycle section to list all 3 writers.

**Standing build conditions (Atlas, re-affirmed):** emitter ownership (no new daemons) · battery-health honesty (SoC-from-register / stale-green / temp-not-captured / UPS-not-vehicle) · A-6 draining-failsafe honesty · **Mode-04 clear via polkit (I-036), gate re-checked at the ACTION path not the UI** · parity-gated pygame sunset · Rule-10 in-sprint `architecture.md` + `specs/UI/` DoD. **C-3 Mode-02 CLOSED** (realtime_data fallback is the default render — Mode 02 confirmed dead on MD326328; the DTC viewer never shows a freeze-frame grid on this ECU). Load-bearing tier: Atlas (done) + Argus acceptance review.

## Two render-breaking UX traps — MUST lock into US-401 before build (Spool, 2026-06-18)

These shape the Battery Health card's data contract; getting them wrong is "badly wrong":
1. **Voltage-is-not-percent (F-8):** `battery_health_log.start_soc/end_soc` hold **VOLTS (4.2→3.4 V), not percent.** Rendering `3.44` as "3.44 %" reads near-empty as near-empty-percent — wrong. **SoC % comes ONLY from the MAX17048 SoC register** (nonlinear curve), never lerped from voltage; `null` → omit the percent, show only volts.
2. **Stale-green (F-9):** health data is only as fresh as the last drain cycle (currently month-old). A GREEN verdict must **always** carry "last health check · <date> (<age>)" so stale isn't mistaken for live.
   (+ F-10 temp = "not captured" never fabricated; F-11 label = the **Pi UPS LiPo cell**, never "vehicle/car battery".)

## Stories (build order follows `deps`)

| Story | Feat | Size | What it does |
|-------|------|------|--------------|
| **US-399** | F-092 | M | **Carousel shell** — chromium dashboard kiosk (sibling to the F-103 splash) + swipe-nav + page dots + persistent top bar (BT/sync/power glyphs, I-033 visibility) + **extend `eclipse-states-http` to full runtime** + touch enablement. Reads only state files. |
| **US-400** | F-092 | M | **System Status card** + **system-status emitter** — OBD-link/sync/power/drive tiles; the **I-033 BT-reconnect-visibility** fix (RECONNECTING + retry ≤2s, top-bar glyph amber); honest-instrument (never green-when-stale/down). |
| **US-401** | F-097 | M | **Battery Health card** + **battery-health emitter** — UPS LiPo health view (the 2 render-breaking traps locked in); ladder only when `draining:true` (failsafe); A-6 draining-semantics. |
| **US-402** | F-092 | S | **Pygame sunset** — retire `status_display.py`/`dashboard_layout.py` once the HTML reaches parity; never both surfaces at once. |
| **US-403** | F-092 | M | **System Setup menu** — long-press (~5s ring) + `⋮` both open it; gated service control on an **install-fixed allow-list** (`eclipse-powerwatch` restart-only, `eclipse-obd`/`eclipse-sync` stop+restart) via the A-7 privilege path; Exit/Close (A-8); confirm-before-consequential; kiosk never root. |
| **US-404** | F-111 | M | **DTC KOEO read + `dtc` emitter** — key-on Mode 03(+07) read on the OBD **connection-edge** (no DriveDetector, `drive_id=NULL` explicit), `dtc` state emitter + states-http endpoint, static P1xxx severity-table loader (Spool SSOT). Closes "blank at key-on" (C-2/DTC-A9). |
| **US-405** | F-111 | S | **DTC takeover + ribbon** — full-screen severity-styled takeover on a NEW code (MIL rising-edge; one at a time) + persistent STOP-red ribbon (`--red-light`, ⚠, subtle pulse) on every card. |
| **US-406** | F-111 | M | **DTC Alerts card (Card 5) + detail** — hero (worst code) + worst-first tappable list; detail = code/desc/severity/freeze-frame-**or-realtime-fallback**/**severity-gated fix** (🔴/🟡 diagnose-don't-swap, 🟢 fix + trust badge)/log-sync; condition-dependent `severityCaveat` + quiet N/A disposition. (Folds US-E: Mode-02-dead → realtime_data fallback render.) |
| **US-407** | F-111 | M | **DTC Clear (Mode-04) path** — NET-NEW vehicle-write: polkit-gated `dtc_client.clear()` + **action-path gate re-check** (all-MINOR + logged + server-acked) + hard confirm modal + immediate re-read + session-lock. Renders against Spool's safety SSOT, never redefines it. |

Build chain: carousel **US-399 → (US-400, US-401) → US-402**; **US-403** deps US-399. DTC **US-404 (KOEO+emitter) → US-405 + US-406 → US-407 (Mode-04 clear, LAST)**; the DTC line deps the carousel shell (US-399) + extends `eclipse-states-http`; US-406 *is* Card 5 of the carousel. **US-407 is the load-bearing vehicle-write — sized + watched hardest.**

## Per-story detail (validation-criteria-upfront; bench-testable)

### US-399 — Carousel shell (F-092)
- **Goal:** As the operator at the dash, I want a swipeable chromium dashboard with a persistent top bar so I can glance at system + battery state on the 3.5" panel after boot.
- **DoD:** dashboard kiosk (Wayland/X11, F-103 launch-flag parity) starts on the splash `HEALTHY_YIELD` hand-off (A-1); `eclipse-states-http` extended to full runtime serving the new state files read-only (A-2); swipe-nav between cards + page dots; persistent top bar with BT/sync/power glyphs (D-3); touch enabled (A-5); reads ONLY state files (never polls hardware). Rule-10 architecture.md updates for the runtime extension + handoff in-sprint.
- **ValidationCriteria (bench):**
  - (load dashboard HTML headless) -> (both cards render, no console errors — S-1)
  - (swipe L/R on the panel / synthetic swipe event) -> (advances card + updates page dot; tap target >=40px — S-2)
  - (boot the Pi: splash reaches HEALTHY_YIELD) -> (dashboard visible on the OSOYOO within <=3s of yield — I-1)
- **ConditionalOutcomes:** if a state file is missing/malformed, the card shows `unavailable`, no crash (honest-instrument).

### US-400 — System Status card + emitter (F-092)
- **Goal:** As the operator, I want OBD-link / sync / power / drive status at a glance, and to SEE when the BT link drops, so I'm not blind to a reconnect (I-033).
- **DoD:** new system-status emitter writes `/run/eclipse-obd/states/system-status` (schema per A-3); card renders it verbatim; malformed JSON -> `unavailable`; **I-033 fix**: BT drop -> tile shows `RECONNECTING` + retries within <=2s + top-bar BT glyph flips amber; last-sync tile goes amber when stale-while-driving; **green-when-broken forbidden** (never healthy when underlying state is stale/down).
- **ValidationCriteria (bench):**
  - (fixture: malformed emitter JSON) -> (card shows `unavailable`, no crash — S-3)
  - (induce a BT drop on the rig / fixture `state:reconnecting`) -> (tile RECONNECTING + retry <=2s; top-bar glyph amber — I-3)
  - (fixture: stale last-sync while driving) -> (last-sync tile amber — I-4)
  - (fixture: any stale/down underlying state) -> (tile never renders green/healthy — F-1)

### US-401 — Battery Health card + emitter (F-097)
- **Goal:** As the operator, I want an HONEST view of the Pi UPS battery's health (not the car battery), so I know it can shut down cleanly — without being lied to by voltage-as-percent or stale-green.
- **DoD:** new battery-health emitter writes `/run/eclipse-obd/states/battery-health` (schema per A-3); the **2 render-breaking traps LOCKED**: (1) SoC % from MAX17048 register only, `null`->omit percent, show volts; (2) GREEN always carries "last health check · <date> (<age>)"; (+ temp "not captured" never faked; cell labeled UPS/Pi battery never vehicle); ladder DOM present ONLY when `draining:true` (failsafe, A-6 semantics joint w/ Spool); VCELL authoritative from `battery_health_log`.
- **ValidationCriteria (bench, fixtures):**
  - (`vcellV:3.44, soc:null`) -> (card shows `3.44 V`, omits percent, never "3.44 %" — S-7/F-8)
  - (`lastHealthCheckTs` 30+ days old) -> (shows "last health check · <date> (<age>)"; GREEN never shown without data-age — S-8/F-9)
  - (`ambientTempC:null`) -> ("not captured", never a number — S-9/F-10)
  - (`draining:false`) -> (NO ladder DOM); (`draining:true`) -> (ladder present — S-4/F-2)
  - (pull wall power on the UPS rig while parked) -> (card escalates to ladder + runtime within <=2s — I-6)
- **ConditionalOutcomes:** Spool S-2 (live runtime-remaining formula) + the ladder thresholds (3.70/3.55/3.45 V) are **failsafe-only + owed by Spool**; if not yet delivered, the failsafe shows VCELL + stage only (no minutes) -- do NOT fabricate a runtime estimate. Route to Spool if blocked.

### US-402 — Pygame sunset (F-092)
- **Goal:** As the Pi, I want exactly one dashboard surface, so retire pygame once the HTML reaches parity.
- **DoD:** `status_display.py`/`dashboard_layout.py` no longer launched (superseded; data republished via the emitters); both surfaces never run simultaneously (A-4 parity-gated).
- **ValidationCriteria (bench):** (systemctl/log check post-deploy) -> (pygame status_display not launched — I-7); (start sequence) -> (pygame + HTML never both active — F-4).

### US-403 — System Setup menu + gated service control (F-092)
- **Goal:** As the operator, I want a deliberate, accident-proof menu to restart/stop services + exit the UI, without the kiosk running as root or letting me brick the safe-shutdown guard.
- **DoD:** long-press ~5s (ring fills; release <5s cancels) AND top-bar `⋮` both open the menu (D-6); service control on an **install-fixed allow-list** via the A-7 privilege path — a **net-new `org.freedesktop.systemd1.manage-units`-scoped polkit rule** (a sibling `51-…` file; **NOT** a privileged helper, **NOT** a widening of the I-036 `50-…poweroff` rule — verified that rule grants only `login1.power-off`; kiosk unprivileged), keyed on **BOTH `action.lookup("unit")` AND `action.lookup("verb")`**; **[ATLAS A-7 defense-in-depth] `eclipse-powerwatch` → `restart` ONLY, `stop`/`kill` DENIED at the polkit rule itself** — not merely a disabled UI button (D-7 safety guard; a kiosk compromise or a direct action-path call must NOT be able to stop the safe-shutdown guard, failure F-7); `eclipse-obd`/`eclipse-sync` → `{start,stop,restart}` with confirm; all other units denied; Exit/Close stops the kiosk + returns on reboot (A-8); confirm-before-consequential; ✕/back always present (never trapped).
- **ValidationCriteria (bench, mock systemctl or rig):**
  - (long-press 5s) -> (menu opens; release <5s -> no menu — I-8); (`⋮` tap) -> (same menu — I-9)
  - (tap `eclipse-powerwatch` Stop) -> (disabled, no-op — I-10/F-7); (Restart) -> (service restarts)
  - (Stop `eclipse-obd` -> confirm) -> (stops; status dot stopped <=2s; Restart brings it back — I-11)
  - (service-control with a unit NOT on the allow-list) -> (rejected — S-6/F-13); (single accidental tap) -> (no consequential action — F-6)
  - **[ATLAS A-7]** (`systemctl stop eclipse-powerwatch` issued at the privileged action path directly, UI bypassed) -> (REJECTED by the polkit rule itself — the verb-deny holds even when the disabled UI button is bypassed; this is the defense-in-depth that mirrors US-407's S-10 action-path re-check, NOT just I-10's UI-button test)
  - (Exit/Close -> confirm) -> (kiosk closes to desktop; returns on next reboot — I-12)

### US-404 — DTC KOEO read + `dtc` emitter (F-111)
- **Goal:** As the operator walking up to a lit MIL at key-on, I want the code(s) on the dashboard at the exact moment I ask "why's my light on?" — a key-on read that doesn't depend on a drive being active.
- **DoD:** a key-on Mode 03(+07) read fires on the **OBD connection-established edge** (`event_router` `onConnectionRestored`), one-shot, **gated on no active RUNNING drive**, owned by the DTC capture path (`dtc_logger` connection-edge entrypoint reusing `dtc_client`) — NOT DriveDetector (Atlas A-9 ruling); `dtc_log` rows written with **`drive_id = NULL` stamped EXPLICITLY** (not via `getCurrentDriveId` — avoids a pre-US-388 stale-open leak); new `dtc` emitter writes `/run/eclipse-obd/states/dtc` (codes + severity + suggested_fix + provenance + freeze-frame/fallback + log/sync), ordered AFTER the F-103 states-dir provisioning (C-5); `eclipse-states-http` extended to serve the `dtc` endpoint read-only; static P1xxx severity-table loader consumes Spool's `dsm-p1xxx-severity-table.md` into the state. Rule-10 architecture.md (the `dtc` writer + KOEO path + 3-writer states-dir list) in-sprint.
- **ValidationCriteria (bench + a real KOEO read):**
  - (DriveDetector inactive/RPM 0, key-on read) -> (captures stored+pending; `dtc_log` rows `drive_id=NULL`; detail shows "key-on read" not "Drive N" -- S-11)
  - (key-on/engine-off with a lit MIL, e.g. the P0443 reference) -> (code on the Alerts card within seconds; `dtc_log` row `drive_id=NULL` -- I-8)
  - (malformed/empty `dtc` JSON) -> (card "unavailable", no crash -- S-9)
- **ConditionalOutcomes:** code with no Spool-table entry -> "No description yet" (never blank).

### US-405 — DTC takeover + ribbon (F-111)
- **Goal:** As the operator, I want a NEW check-engine code to grab my attention, then stay visible — without ever trapping me from seeing the road.
- **DoD:** full-screen takeover per-severity color + directive + dismiss controls (STOP has no plain dismiss; "Acknowledge" drops to ribbon — driver keeps view control); fires ONLY on a NEW code (`newSinceTs` / MIL rising-edge), one at a time, escalation re-fires; persistent STOP-red ribbon (`--red-light #F61D2D`, distinct from brand-red, leading ⚠, subtle pulse) on every carousel card while a code is present.
- **ValidationCriteria (bench, fixtures):**
  - (fixture: new code) -> (takeover renders correct color+directive+dismiss per severity -- S-1)
  - (fixture: known/old code) -> (no takeover; ribbon present -- S-2)
  - (ribbon present) -> (STOP-red distinct from brand-red, ⚠ + pulse -- R-2)
- **ConditionalOutcomes:** STOP code -> "Acknowledge" drops to ribbon (driver can clear the view); never forces full-screen while the road needs watching.

### US-406 — DTC Alerts card (Card 5) + detail (F-111)
- **Goal:** As the operator, I want an honest detail view per code — severity, what to do, the freeze-frame context (or an honest fallback), and a fix ONLY when it's safe — so I'm never misled into clearing a real fault or swapping the wrong part.
- **DoD:** Alerts card = Card 5 of the carousel; hero = highest-severity code + directive; tappable list sorted worst-first; detail = code · description · severity · **freeze-frame OR the realtime_data fallback** ("no freeze frame captured (this ECU) — showing context at fault time"; Mode 02 dead on MD326328 — **folds US-E**) · **severity-gated fix** (🔴/🟡 show the diagnose-don't-swap directive, NO raw fix even if `suggestedFix` non-null; 🟢 show the fix + a 3-state trust badge per `fixProvenance`: ✓ verified / 👥 community / ⏳ offline) · log/sync footer; condition-dependent `severityCaveat` (base chip + caveat line, NOT auto-upgraded) + quiet N/A disposition (auto-trans P1xxx -> "N/A this vehicle", sorts last, no takeover/ribbon). The display maps tier->color/directive ONLY — it never classifies (reads Spool's severity). Rule-10 specs/UI in-sprint.
- **ValidationCriteria (bench, fixtures + a real code):**
  - (fixture: 🔴/🟡 code, `suggestedFix` non-null) -> (detail shows diagnose directive, NO raw fix -- S-4/I-4)
  - (fixture: 🟢 code) -> (fix shown + correct trust badge per `fixProvenance` -- S-4)
  - (fixture: missing freeze-frame) -> ("no freeze frame captured (this ECU)..." fallback, never blank -- S-5)
  - (fixture: auto-trans P1xxx `severity:na`) -> (quiet N/A chip, sorts last, no takeover/ribbon -- S-12)
  - (fixture: P1300 `severityCaveat:"🔴 if knock"`) -> (base 🟡 chip + caveat line, tier NOT auto-upgraded -- S-13)
  - (tap the real P0443 code) -> (detail opens with the fallback context -- I-2)
- **ConditionalOutcomes:** code with no table entry -> "No description yet" (I-3); display never decides severity.

### US-407 — DTC Clear (Mode-04) path (F-111, LOAD-BEARING vehicle-write)
- **Goal:** As the operator, I want to clear a MINOR code safely — but ONLY when it's safe, fully logged, and proven cleared — so I never erase a real fault's evidence or "chase the light."
- **DoD** (renders against `offices/tuner/dtc-display-clear-safety-advisory.md` — Spool SSOT, **non-negotiable; this story does NOT redefine it**): a net-new Mode-04 `dtc_client.clear()` via the **polkit/privileged-action pattern** (same as the F-092 menu; kiosk stays unprivileged); the **clear gate** = ALL stored codes MINOR (🟢) AND logged AND server-sync-acked — **disabled with reason** if any 🟡/🔴 present (`a STOP/WATCH code is present`) or capture/sync incomplete (`waiting for server sync`); a **hard confirm modal** (wipes stored+pending, **erases freeze-frame**, **resets emissions readiness** — full drive cycle before inspection); an **immediate re-read (Mode 03)** proving "0 stored, 0 pending, MIL off" (never "command sent"); a **session-lock** — a cleared code that returns immediately locks Clear for the session ("don't chase the light"). The gate is **RE-CHECKED at the privileged action path** (all-MINOR + logged + server-acked) — a tampered/stale UI MUST NOT force a clear (defense-in-depth). Rule-10 architecture.md (Mode-04 write path + privilege mechanism) in-sprint.
- **ValidationCriteria (bench + a real MINOR clear):**
  - (fixture: `clearGate` stop_present/watch_present) -> (Clear disabled + reason; `sync_pending` -> disabled + reason; `ok` -> enabled -- S-6)
  - (action path: Clear requested with the gate failing server-side, UI tampered) -> (REJECTED at the action path -- S-10)
  - (fixture: 🔴/🟡 code) -> (no Clear button; detail shows diagnose directive, no raw fix -- I-4)
  - (real MINOR, e.g. P0443: log + server-ack -> Clear -> confirm -> Mode 04 -> re-read) -> (capture-before-clear holds; re-read cleared + MIL off; freeze-frame preserved server-side -- I-5/I-6)
  - (cleared code returns immediately) -> (Clear locks for the session -- I-7/S-8)
- **ConditionalOutcomes:** the action-path gate is authoritative (never trust the UI); if the SSOT advisory and the spec ever disagree, the **advisory wins** (engine-protection).

## Validation (Argus) — BENCH ONLY

Almost all acceptance is **fixture-based DOM/JSON render tests** (S-1..S-10 — CI-runnable headless). The rest are **bench drills on the Pi**: boot handoff (I-1), physical/synthetic swipe (I-2), BT-drop on a rig (I-3), UPS-drain on the UPS rig (I-6), long-press (I-8/9), service control via mock/real systemctl (I-10/11/12). **No drive drills** (CIO-waived). Argus advisory Q-1/Q-2/Q-3 (acceptance sign-off + induce-BT-drop/drain methodology + evidence capture) resolve at grooming/review.

## Non-Goals (out of scope)

- **No Mode-02 freeze-frame CAPTURE path** — Mode 02 confirmed dead on MD326328; the DTC detail renders the realtime_data fallback (US-406). A capture path is built only if a future ECU supports Mode 02.
- **No live runtime-remaining formula (Spool S-2) or confirmed ladder thresholds** — failsafe-only, owed by Spool; the Battery Health card (everyday view) ships without them.
- **No drive drills** (CIO-waived); the one real-code acceptance reuses the already-set drive-27 **P0443** (read KOEO, do NOT clear before reading — Argus Q-2).
- **No DTC severity (re)classification in the display** — it reads Spool's SSOT (`dtc-display-clear-safety-advisory.md` + `dsm-p1xxx-severity-table.md`); the display maps tier→color/directive only.
- **No new home/instrument card** (DELTA-2 IMU live-instrument is EDR-epic, A-14).

## Sequencing + sizing + open items
- Forks from `dev` **after Sprint 48/V0.29.2 lands** (F-103 is the prerequisite runtime — Sprint 48 is 4/6 shipped, both bugs remaining). Continues the V0.29 chain as **V0.29.3** (version provisional; confirm at freeze — a case exists for V0.30.0 given the UI scope).
- **Sizing:** **9 stories — near the 10 cap** (CIO-directed single combined sprint; Atlas concurred ~9). I'll size tightly at `/resize-sprint`; **US-407 (Mode-04 clear)** is the load-bearing vehicle-write — watched hardest; if it (or the sprint) reads too heavy, the natural split is **49a carousel (US-399..403) / 49b DTC (US-404..407)**.
- **Atlas design-gate: DONE** (signed off 2026-06-30; rulings folded above). **Spool**: confirm S-2 + ladder thresholds (failsafe-only; non-blocking). **Argus**: acceptance methodology Q-1/2/3 (incl. inducing BT-drop/drain + the drive-27 P0443 read-don't-clear).
- **Bench rigs:** confirm the OSOYOO 3.5" touch panel + the UPS HAT are wired for Argus's I-2/I-3/I-6/I-8/9 + the KOEO DTC read acceptance.

## Next steps (PM)
1. Author US-399..407 into backlog (9 stories) — after Sprint 48 closes (so the chain is clean).
2. Freeze (`prd_to_sprint.py`) + `/resize-sprint` (sizing; consider 49a/49b) + branch `sprint/sprint49-V0.29.3`.
3. Dispatch when F-103 is on `dev` (the runtime the carousel + DTC extend) + Sprint 48 has merged.
