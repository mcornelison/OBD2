# Pi Touch-UI — Idle-State Card + Full-Bleed Scaling — Design Spec

| | |
|---|---|
| **Author** | Iris (UI/UX) |
| **Date** | 2026-07-21 |
| **Status** | DRAFT — design-before-build (CIO: Iris-designs-then-reviews-before-Ralph) |
| **Companion** | `proposals/2026-07-21-pi-idle-state-and-full-bleed.html` (interactive) |
| **Palette** | `specs/UI/tokens.css` (SSOT) |
| **Consumes** | the shipped `system-status`, `battery-health`, `dtc` state files — **no new hardware polling** |
| **Feeds** | the UI/UX re-groom sprint (`prd-uiline-draft.md`, re-grounded 2026-07-21) |

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

### 1.5 Light-sensor auto-dim (ties to W-11 / TSL2591)
The idle card is the natural first consumer of the light-sensor auto-dim: parked-at-night →
dim the whole surface (a brightness multiplier on the root). The **dim floor must never hide
a real active alarm** — a STOP ribbon keeps its minimum legible brightness. Curve is mine;
lux source is the EDR light sensor (EDR-gated — near-term the idle card just ships a fixed
dim-when-idle default, live lux later).

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

**Recommendation:**
1. **Ship the letterbox transform now** — smallest, safest change; preserves the exact,
   already-gated 480×320 layout; works at any resolution. One wrapper + a resize handler.
2. **IRL-check the real panel's scaler** — if it stretches 1080p onto a 3:2 physical panel,
   switch to **fill** (a one-line change) for edge-to-edge with correct aspect.
3. **Fluid is the long-term ideal** — schedule as a follow-up once the layout is otherwise
   stable, not in the same sprint as the P0 data fix.

Either transform approach also requires changing the viewport meta to
`width=device-width, initial-scale=1` so the stage measures the real output.

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
6. **Full-bleed:** on a 1080p-output Pi the UI fills the panel (no corner-render); typography
   legible + tap targets ≥40px at the physical panel size. ✅/❌

---

## 5. Routing / next steps
- **Atlas (design-gate):** idle-detection SSOT question (§1.4 — emitter flag vs display-derived);
  full-bleed transform is presentation-only (likely no gate) but confirm; token reconciliation (§3).
- **Spool:** none required — idle consumes his battery-health/DTC semantics unchanged; the
  dim-floor-must-not-hide-alarm rule is a UI guard, not a threshold.
- **Ralph:** builds as a new home card + the transform wrapper, **after** CIO/Atlas review
  (design-before-build). Pairs with the P0 data-starvation story (idle is the calm backdrop
  once the emitters write).
- **Marcus:** folds into the re-groomed UI/UX sprint (`prd-uiline-draft.md`).
