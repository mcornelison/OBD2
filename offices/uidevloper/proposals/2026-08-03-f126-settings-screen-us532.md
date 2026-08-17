# F-126 Settings Screen (US-532) — UX Design Spec

| | |
|---|---|
| **Author** | Iris (UI/UX) |
| **Date** | 2026-08-03 · **rev 2026-08-17** |
| **Status** | **CIO CHOSE B (2026-08-03): settings live INSIDE the US-403 ⋮ setup-menu overlay** (a Settings section above the service controls), NOT a separate card. Redesigned accordingly. |
| **Rev 2026-08-17** | **(a) Slice 1 is 4 settings, not 5 — `audioAlerts` DROPPED** (CIO; deferred to **US-538**, not cancelled). **(b) Auto-rotate corrected to Atlas's F-126 design-gate ruling:** one key **`autoRotateS`** (no parallel bool), on/off derived from `> 0`, **default OFF**, and apply-state is **RESTART, not live**. |
| **Story** | US-532 (F-126 / V0.29.26 / Sprint 71) — PRD `offices/pm/prds/prd-V0.29.26-settings-screen.md` |
| **Companion** | `proposals/2026-08-03-f126-settings-screen-us532.html` + hosted artifact |
| **Design system** | F-124 carousel (tokens, Oswald `--font-display`) |

## 1. Shape — DECISION: B (CIO 2026-08-03) — settings INSIDE the ⋮ setup-menu overlay

**CIO chose B.** No separate carousel card. The existing US-403 setup-menu overlay (opened by the 5 s
long-press / `⋮`, parked-only) gains a **Settings section** at the top — the 4 config toggles (Slice 1) — **above**
its existing **Service control** section (OBD stop/restart, powerwatch restart-only, Exit-UI). One overlay,
two clearly-separated bands: **Settings (safe, persistent prefs)** on top, **Service & Exit (destructive,
confirm-gated)** below. The controls, honest save flow, apply-state, and effective-value rules in §2–§3
are unchanged — only the container is the menu, not a card. Consequences: no 5th carousel card; the menu
scrolls (settings + services exceed one screen); the destructive service rows keep their confirms + the
powerwatch-no-stop rule. *(The A/B/C analysis below is kept as the record of the decision.)*

### (Superseded) recommendation — Settings = a carousel card; setup menu stays separate

Marcus asked me to reconcile with the existing **US-403 setup menu** (kebab/long-press overlay). They're
**different concerns**, so keep them distinct — no competing surfaces:

| | US-403 Setup menu (exists) | **F-126 Settings (new)** |
|---|---|---|
| Purpose | **service control + destructive** — OBD stop/restart, Exit-UI | **non-destructive persistent preferences** |
| Access | deliberate **5 s long-press / `⋮`** (parked-only) | a **swipe-to card** in the carousel |
| Risk | dangerous → behind a gesture + confirms | safe → discoverable |

**Recommendation (Option A):** Settings is a **carousel card** (the CIO called it a "screen"; a card is the
swipe-to screen, like System Status). The setup menu **stays the overlay** for service/Exit (destructive
stuff belongs behind the deliberate gesture, not one swipe away). **Cross-link both ways:** a `Service & Exit ›`
row at the bottom of the Settings card opens the setup menu; the setup menu gets a `⚙ Settings` row that jumps
to the card. One home for preferences, one for dangerous actions.

**Alternatives (for the CIO):** (B) settings toggles *inside* the setup-menu overlay — rejected: overloads a
destructive menu with frequently-toggled prefs, and buries auto-rotate behind a 5 s long-press. (C) one unified
card holding prefs *and* service-stop — rejected: puts a destructive "stop OBD" one accidental swipe-tap away.
**Confirm A vs B vs C with CIO.**

## 2. Slice 1 — 4 controls (each shows its REAL effective value)

Layout: a `SETTINGS` band, one row per setting = **label · effective value · control · apply-state tag**.

| Setting | Control | Apply-state (honest) |
|---|---|---|
| **Carousel auto-rotate** (`pi.display.carousel.`**`autoRotateS`**) | toggle, **derived from `autoRotateS > 0`** — OFF writes `0`, ON writes the shipped default seconds. **Default OFF.** | **RESTART NEEDED** — *not* live (see below) |
| **Power mode** (`pi.power.mode`) | **3-state segmented** CAR · WALL · UNKNOWN | **live** (PowerModeProvider re-emits → power tile updates; this is the fix for the bench "unknown") |
| **Calibration mode** (`pi.calibration.mode`) | toggle | apply-timing TBD → shows whatever the wiring reports (`live` / `restart`) — **not** a silent no-op |
| **Auto-analyze after drive** (`pi.analysis.triggerAfterDrive`) | toggle | **next drive** (deferred effect — say so, don't imply instant) |

**DROPPED from Slice 1 — Audio alerts** (`pi.alerts.audioAlerts`). CIO removed it 2026-08-02; **deferred to
US-538, not cancelled.** The band is designed to take a 5th row without re-layout when it returns.

### Auto-rotate: one key, and it is NOT live (Atlas F-126 design-gate, folded 2026-08-17)

Two corrections from his ruling, both load-bearing for this surface:

- **GAP 3 — one key, one truth.** Do **not** mint a parallel `autoRotate` bool alongside the existing
  `autoRotateS` (seconds; `0` = off). `autoRotate=true` + `autoRotateS=0` is ambiguous. The overlay stores
  **`autoRotateS`** and the toggle derives its on/off state from `> 0`. **Shipped default is OFF (`0`)** per
  the CIO's disposition-B freeze fix — so the toggle renders OFF by default, not on.
- **GAP 1 — "applies LIVE" is false.** `states_http_server` reads `pi.display.carousel` **once at startup**
  and serves it cached; a change needs an `eclipse-states-http` restart + page reload. So this row is tagged
  **RESTART NEEDED**. Slice 1 may keep that (his option *a*) **only because it is honestly labelled**; his
  recommended long-term shape (*b*) is to publish effective settings as a polled state topic the carousel
  reads each tick, like `dtc`/`imu` already do. **A silent no-op that looks applied is the one outcome this
  screen must never produce** — which makes this the most important tag on the surface, not a detail.

### The rest
- **Power mode is a 3-state selector, not a toggle** (car/wall/unknown). `unknown` = no override (system
  decides); car/wall = a deliberate override. The segmented control shows the effective one highlighted.
  **Overlay values must validate to `{car, wall, unknown}` — anything else resolves to `unknown`**, never a
  confident wrong mode (the existing honest-unknown contract; Atlas's allow-list note).
- Effective value = **overlay-override ELSE config default** (US-530 read via the state server). Never a hardcoded
  default. A subtle marker distinguishes an operator-**set** value from the shipped **default** (small dot/label).

## 3. Honest-instrument rules (the whole point of this surface)
- **Real value, always.** Controls render the effective value the state server reports, not an optimistic assumption.
- **No optimistic success.** On tap → the control shows a brief **`saving…`**, then confirms from the **re-read**
  (`saved`), or snaps **back to the real stored value + `couldn't save`** on a write failure/401. The token-gated
  write (US-531) can reject — the UI must reflect the *actual* stored state, never a fake "on".
- **Apply-state is explicit.** Each row carries a tag: **live** / **next drive** / **restart needed** — a setting
  that needs a restart says so plainly; a deferred one says "next drive". Never a silent no-op that looks applied.
- **Malformed/absent overlay → config default** (US-530); the card still renders every control at its default.
- **Persistence is stated:** a small footer — "saved on the Pi · survives deploys & reboots" (the overlay is
  deploy-preserved) — so the operator trusts a toggle sticks.

## 4. Placement (B) — one setup-menu overlay, two bands
- **No new carousel card.** The `⋮`/long-press opens the setup-menu overlay, which now reads top-to-bottom:
  **① Settings** (the 4 config controls) → **② OBD-II Services** (eclipse-obd/-sync Restart·Stop,
  eclipse-powerwatch Restart-only) → **③ Display** (Exit / Close UI). The overlay scrolls.
- **Safety unchanged:** the service + Exit rows keep their confirm modals (F-6) and the powerwatch-no-Stop
  rule (F-7); the new Settings toggles are non-destructive and don't confirm. Visual separation (a divider +
  section labels) keeps "flip a preference" clearly distinct from "stop a service".

## 5. Acceptance criteria (Argus-style)
1. Every control renders its **real effective value** (overlay-override else config default), never a hardcoded default. ✅/❌
2. Toggling shows `saving…` then confirms from a **re-read** (`saved`); a rejected/failed write snaps back to the real value with `couldn't save` — never an optimistic on. ✅/❌
3. Power mode is a **3-state** CAR/WALL/UNKNOWN selector; setting WALL makes the System-Status power tile read WALL. ✅/❌
4. Each row shows an honest **apply-state** (live / next drive / restart); a restart-needed setting says so. ✅/❌
6. **Auto-rotate binds to `autoRotateS` ONLY** — no parallel `autoRotate` bool exists anywhere; OFF writes `0`, ON writes the shipped default seconds; the toggle derives its state from `autoRotateS > 0`. ✅/❌
7. **Auto-rotate renders OFF by default** (disposition-B shipped default) and is tagged **RESTART NEEDED**, not live. ✅/❌
8. **Slice 1 shows exactly 4 settings** — no Audio-alerts row (deferred US-538). ✅/❌
9. A `pi.power.mode` overlay value outside `{car, wall, unknown}` resolves to **unknown**, never a confident wrong mode. ✅/❌
5. Settings is a **section at the top of the setup-menu overlay**, above the service controls (one overlay, visually separated bands); the destructive service/Exit rows keep their confirms + powerwatch-no-Stop. ✅/❌

## 6. Routing
- **CIO:** shape **CONFIRMED = B** (2026-08-03) — settings inside the setup-menu overlay. Slice 1 trimmed to **4 settings** (audio → US-538) on his 08-02 call. Nothing further owed.
- **Atlas:** owns US-530 overlay contract + US-531 token-gate (not my build); I consume the effective-value read +
  POST the token-gated write. Confirm the read exposes each key's **apply-state** so the tag isn't guessed.
- **Ralph:** builds US-532 card + US-533 wiring after the CIO shape + Atlas seams; GPU-frugality (no always-on anims — this card is static, good).
- **Marcus:** US-532 routes back on the CIO shape confirm.
