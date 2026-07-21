# Pi Touch-UI — Idle-State Card + Full-Bleed Scaling — Design Spec

| | |
|---|---|
| **Author** | Iris (UI/UX) |
| **Date** | 2026-07-21 |
| **Status** | REVIEWED — CIO decisions locked 2026-07-21 (see §0.1); build-ready pending Atlas data-contract nod |
| **Companion** | `proposals/2026-07-21-pi-idle-state-and-full-bleed.html` (interactive) |
| **Palette** | `specs/UI/tokens.css` (SSOT) |
| **Consumes** | the shipped `system-status`, `battery-health`, `dtc` state files — **no new hardware polling** |
| **Feeds** | the UI/UX re-groom sprint (`prd-uiline-draft.md`, re-grounded 2026-07-21) |

## 0.1 CIO decisions — locked 2026-07-21 (live artifact review)
1. **Full-bleed = FLUID** (§2). Not letterbox, not fill — the layout reflows to fill the
   viewport with relative units. Truest resolution-independence; accept the CSS churn.
2. **Light sensor = a real DATA FEED into the display** (§1.5). Auto-dim consumes a live lux
   reading (pure consumer of a state file), **not** a fixed schedule. The brightness curve is
   mine; the lux source is the EDR light sensor (TSL2591, W-9). Live feed is EDR-gated → the
   display ships a documented fallback until the lux state file exists.

## 0. Why these two, why now

The touch carousel (F-092/097/111) is **built and deployed**, but two gaps make it
read wrong on the real Pi (CIO-flagged, current state pointer):

1. **No idle state.** When the car is parked (engine off → OBD asleep), the carousel's
   default card (System Status) shows a column of `NA / — / unavailable` tiles. That
   **reads as broken**, and it's the backdrop the "phantom Check Engine" appears against.
2. **No full-bleed scaling.** The kiosk hard-codes `<meta viewport width=480,height=320>`.
   When the Pi outputs 1080p, Chromium doesn't honour that mobile viewport meta, so the
   480×320 layout renders in a corner instead of filling the panel.

Neither is a redraw — both are additive layers over the shipped, honest render logic.

> **Scope note.** The "phantom Check Engine" itself is a **runtime/state bug**, not a design
> bug: the shipped `takeoverView()` already returns `null` for a missing/unavailable `dtc`
> file (verified in `carousel.js`). It's the P0 data-starvation story (Ralph's lane). The
> idle card *reduces the blast radius* (a calm parked home instead of a broken-looking one)
> but does not replace that fix.

---

## 1. Idle-state card

### 1.1 What it is
A calm, honest **home card** shown when the vehicle is parked. It is the **parked twin of
the (EDR-gated, W-11) live-instrument home card** — same carousel home slot: parked → idle
card; driving → live card. No separate drive-mode (CIO decision, W-11).

### 1.2 Contents (all honest, no fabricated live values)
- **Header:** `ECLIPSE OBD-II` wordmark (dim) + live clock + date.
- **Hero:** a soft brand mark + `STANDBY` (neutral grey) + substate `engine off · OBD asleep`.
- **Summary strip (3 real facts):**
  | Line | Source | Honest rule |
  |---|---|---|
  | **Last drive** | drive state / last drive record | `no drive recorded` if unknown — never a guess |
  | **Battery** | `battery-health` emitter | reuses the F-9 stale-green guard: green verdict **always** carries `checked Nd ago` |
  | **Faults** | `dtc` state | `No stored codes (key-on read Nm ago)` **only** if a genuine clean key-on read exists; otherwise `DTC not read since key-off` |
- **Footer:** `swipe for details · hold or ⋮ for setup`.

### 1.3 Honest-instrument rules (load-bearing)
- **Never green "OK" at idle** — nothing was measured. STANDBY is neutral grey. Green appears
  *only* on the battery line (a real recent reading, with its age).
- **Never amber/red at idle** unless a **real stored STOP/WATCH code** exists — in which case
  the existing ribbon/takeover surfaces it on every card (unchanged). Idle itself stays calm.
  (This is the F-103 alarm-fatigue guard I-10b/F-7 applied to the dashboard.)
- **Absence ≠ clean, absence ≠ fault.** `DTC not read since key-off` is neither "No codes"
  (false all-clear) nor "Check Engine" (the phantom).

### 1.4 Idle detection (SSOT — flag to Atlas)
Idle is **derived from existing SSOT facts the emitters already write**, not invented by the
display:

```
idle  ⟺  system-status.source.obd.available === false   (OBD asleep / engine off)
         AND system-status.drive.state === "idle"        (not recording)
```

The carousel makes **Idle the home card** while `idle` holds, and **auto-advances off idle**
to the live/System-Status view the moment OBD wakes or a drive starts recording. This is
display *policy over facts* (allowed), not data acquisition.

> **Design-gate question for Atlas (DELTA-3-ish):** should `idle` instead be an explicit
> boolean the `system-status` emitter writes (cleaner one-fact-one-owner SSOT), rather than
> the display AND-ing two fields? My lean: **emitter-provided** long-term, display-derived
> acceptable near-term (no new source needed). Routing to Atlas.

### 1.5 Light-sensor auto-dim — a DATA FEED (CIO-confirmed 2026-07-21)
Display brightness is **driven by a live lux reading**, not a clock schedule. The whole surface
is a pure consumer (SSOT): the EDR light sensor (TSL2591, W-9) → the canonical light reader →
a `light` state file → the display applies a brightness multiplier on the root. The display
**never reads the sensor itself**.

- **Contract (proposed; routes to Atlas):** the display reads `light.lux` (+ its freshness) from
  a state file the light reader owns — same pattern as every other card. Brightness =
  `clamp(MIN, curve(lux), 1.0)`. The **curve is mine** (UI); the **lux value is the EDR reader's**
  (owner = the single dedicated reader, per Atlas's DELTA-2 pure-consumer ruling).
- **Alarm floor (load-bearing):** `MIN` never drops the screen below a legible threshold while a
  **real active alarm** (STOP ribbon/takeover) is present — you can dim a calm idle screen, never
  a damage-in-progress warning. This floor is a UI guard, independent of the lux value.
- **Honest fallback (near-term, EDR-gated):** the live lux feed lands with the EDR sensor build
  (W-9, ~mid-July+). Until the `light` state file exists / is fresh, the display uses a fixed
  default brightness and **shows no fabricated "auto" behavior** — it does not pretend to be
  reacting to light it can't read (honest instrument). The dim seen in the mockup is that curve
  previewed.

---

## 2. Full-bleed scaling

**Problem:** `<meta name="viewport" content="width=480, height=320, ...">` → the 480×320
layout does not fill a 1080p output.

**Three candidate mechanisms** (all in the companion HTML, side by side):

| Mode | Mechanism | Pro | Con |
|---|---|---|---|
| **Letterbox** (uniform) | `transform: scale(min(100vw/480, 100vh/320))` on a 480×320 stage | zero layout risk; exact current design; fills most of the screen | thin bars on the aspect-mismatched axis (16:9 output vs 3:2 design) |
| **Fill** (non-uniform) | `scaleX(100vw/480) scaleY(100vh/320)` | fills 100% | only correct **if the panel scaler squishes 1080p back to 3:2** (cancels the stretch) — **must be IRL-confirmed** |
| **Fluid** (reflow) | drop the fixed box; relative units + `clamp()` typography fill the viewport | truest resolution-independence | most CSS churn |

**DECISION (CIO 2026-07-21): FLUID.** The layout reflows to fill the viewport — not a scaled
480×320 box. Letterbox/fill are retired as candidates (kept above only to document the reasoning).

**Build strategy for Ralph (fluid):**
1. Change the viewport meta to `width=device-width, initial-scale=1` (drop the hard 480×320).
2. Make the root a viewport-proportional type/space base so everything scales *and* reflows:
   `:root{ font-size: clamp(14px, 2.6vmin, 30px); }` — then re-express `dashboard.css`'s fixed
   `px` (topbar 28px, paddings, tile/font sizes) in **rem/em** off that root.
3. Structure fills with `%`/`vh`/flex-grow (already mostly true: `#carousel top:28px bottom:24px`,
   `.card flex:0 0 100%`). Convert the fixed chrome heights (topbar/dots/ribbon) to rem.
4. **Preserve physical minimums:** tap targets `min-height: max(40px, 6vmin)` so a large viewport
   never shrinks a target below the S-2 40px floor, and a small one never blows it up.
5. `text-wrap: balance` on card headlines; keep the mono face.

**Cost note (grooming):** this is the largest lift of the two — it touches most of
`dashboard.css`. It does *not* depend on the P0 data fix, but it should be its **own story** so
the data-starvation P0 isn't blocked behind a CSS refactor. Validate on the real 1080p-output Pi
(a fluid layout is only truly confirmed on-hardware).

---

## 3. Token reconciliation (W-3 — surfaced, route via Atlas)
The shipped `dashboard.css` `:root` **drifts from the `specs/UI/tokens.css` SSOT**:
- `--ok-green: #2ECC71` (dist) vs `--green-ok: #35C46A` (SSOT).
- `--text-primary: #DDDDDD` defined in dist but marked "not yet tokenized" in the SSOT.

This design uses the **SSOT values**. Reconciling `dashboard.css` → tokens is a Rule-10 item
(route the token additions through Atlas). Flagging, not fixing (not my file to edit).

---

## 4. Acceptance criteria (Argus-style, single boolean each)
1. **Idle appears when parked:** with `source.obd.available=false` + `drive.state=idle`, the
   carousel home card is the idle card (not the System-Status NA wall). ✅/❌
2. **No false green:** idle STANDBY renders neutral grey; no tile/glyph is green except a
   battery line that carries a `checked Nd ago` age. ✅/❌
3. **Honest faults line:** with no key-on DTC read, the Faults line reads `DTC not read since
   key-off` — never "No codes", never "Check Engine". ✅/❌
4. **Auto-advance:** when OBD wakes (`source.obd.available=true`) or a drive starts, the home
   card leaves idle without a manual swipe. ✅/❌
5. **Real alarm still wins:** a genuine stored STOP code shows the ribbon/takeover while idle
   is displayed (idle never suppresses a real fault). ✅/❌
6. **Full-bleed (fluid):** on a 1080p-output Pi the UI fills the panel edge-to-edge with no
   corner-render and no letterbox bars; text stays legible and every tap target is ≥40px
   physical at the panel size. Confirmed on the real Pi, not just a desktop browser. ✅/❌
7. **Light feed + alarm floor:** brightness tracks a live `light.lux` reading when the state
   file is fresh; when it's absent/stale the screen holds a fixed default (no fake "auto"); and
   dimming never takes a STOP alarm below its legible floor. ✅/❌

---

## 5. Routing / next steps
- **Atlas (design-gate):** (a) idle-detection SSOT (§1.4 — emitter `idle` flag vs display-derived);
  (b) **NEW — the `light` lux state-file contract** (§1.5): the display consumes `light.lux` from
  the EDR light reader (owner = the single dedicated reader, per his DELTA-2 ruling) — bless the
  state-file seam + fallback-when-absent; (c) token reconciliation (§3). **Full-bleed is now fluid
  = presentation-only, no data contract → no gate** (confirming only).
- **Spool:** none required — idle consumes his battery-health/DTC semantics unchanged; the
  dim-floor-must-not-hide-alarm rule is a UI guard, not a threshold.
- **Ralph:** builds (after Atlas nod) as: (1) fluid conversion of `dashboard.css` (§2 strategy);
  (2) the idle home card; (3) the brightness consumer of the `light` state file (+ fixed fallback).
  Idle pairs with the P0 data-starvation story (calm backdrop once the emitters write); fluid is
  its own story (a CSS refactor, not blocked behind P0).
- **Marcus:** folds into the re-groomed UI/UX sprint (`prd-uiline-draft.md`) — 3 stories above +
  the P0 data fix + the Rule-10 token reconciliation.
