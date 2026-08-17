# 3.5″ Legibility + Layout Pass — Design Spec

| | |
|---|---|
| **Author** | Iris (UI/UX) |
| **Date** | 2026-08-07 |
| **Status** | **DRAFT — for CIO review.** Structural parts (screen count, stage/scale changes) route to Atlas for design-gate per his 08-07 note. |
| **Trigger** | CIO reviewed the live UI on the 3.5″ panel: fonts too small to read at arm's length in the car — compass heading, %-values, g-force, the P0443 CHECK ENGINE line all illegible. |
| **Bundle** | Atlas 2026-08-07 (legibility) + Atlas 2026-08-03 (3 UI change requests: IMU-always-on · Alerts-to-2nd · auto-rotate-off) = **one coherent pass**. |
| **Companion** | `proposals/2026-08-07-pi-3p5in-legibility-and-layout.html` |

---

## 1. The measurement, before the design

The panel is **3.5″ diagonal at 480×320** → `√(480²+320²) / 3.5` = **~165 PPI**, so **one design pixel ≈ 0.154 mm**. In-car glance distance to a dash-mounted panel is ~**650 mm**.

Legibility for glanceable in-vehicle text is an *angular* requirement, not a pixel one: comfortable glance reading wants a cap height of about **20 arcminutes**, with roughly **16′** as the practical floor. At 650 mm:

| | cap height | design px (cap ≈ 0.72 em) | font-size |
|---|---|---|---|
| Comfort target (20′) | 3.8 mm | ~24.5 px | **~34 px** |
| Practical floor (16′) | 3.0 mm | ~20 px | **~28 px** |

### What is shipped today

`dashboard.css` carries **83 hardcoded `px` font sizes**:

- **Primary values: 13–15 px.** Tile labels: **8–11 px.**
- The **only** two elements in the legible band are `.imu-gear` (40 px) and `.idle-hero` (34 px).

### The CIO's report independently confirms the math

He flagged compass heading, %-values, g-force and the CHECK ENGINE line — **all ≤22 px**. He did **not** flag the gear or the standby hero — **the only two elements ≥34 px**. His eyes and the arcmin arithmetic agree, from different directions. That makes **34 px the empirically-validated floor for anything he must read**, not a theoretical one.

> **This is the honest-instrument principle applied to type.** A value rendered too small to read is not a degraded instrument — it is a *silent* one. It occupies the space of a working readout while conveying nothing, which is worse than an explicit "no source", because it doesn't announce its own failure.

---

## 2. The type scale (the deliverable that makes the rest possible)

Atlas's note assumes the lever is "larger font tokens — one scaling change." **That lever does not exist yet:** `specs/UI/tokens.css` defines font *families* and colours but **no type scale**, and the 83 sizes are hardcoded literals. Today this is 83 per-element edits, and it will drift back — the exact multi-generation drift the token SSOT exists to prevent (my W-3, open since 2026-05-26).

**So story 1 is "extract the type scale into tokens." Story 2 is "set its values." Not the reverse.**

```css
/* specs/UI/tokens.css — type scale for the 3.5" 480x320 stage @ ~165 PPI.
   Values are ANGULAR requirements at ~650 mm, not taste. Do not shrink to fit
   content; cut content instead. */
--fs-hero:      44px;  /* 25.8' — the one number that owns the card        */
--fs-primary:   34px;  /* 20.0' — MUST-READ-WHILE-DRIVING floor            */
--fs-secondary: 26px;  /* 15.3' — parked reading only                      */
--fs-label:     20px;  /* 11.7' — recognition, not reading                 */
--fs-meta:      15px;  /*  8.8' — provenance/age; never action-critical    */
```

### The floor rule (the part that must survive review)

> **Anything the driver must read to act is `--fs-primary` (34 px) or larger. Anything smaller than 26 px must be non-critical — a recognition label, a timestamp, a provenance note. Nothing goes below `--fs-meta` (15 px), ever.**

Labels survive at 20 px because a label is *recognised*, not read — you learn "COOLANT" once and thereafter identify it by position and shape. Values are read fresh every time. That asymmetry is what buys the layout its room.

**When content doesn't fit, the answer is fewer facts per card — never a smaller size.** Shrinking to fit is how we got here.

---

## 3. What the scale costs: capacity, and therefore screens

Stage is 480×320. Top bar ~30 px + page dots ~16 px → **~258 px of usable card body**.

One label+value row = 20 + 4 + 34 = **58 px**, plus ~14 px row gap = **72 px**.

- **Single column: 3 facts per card.**
- **2×2 grid: 4 facts per card.**
- **4 facts is the ceiling. 3 is comfortable.**

Today's four cards carry far more than that — Health alone stacks Battery + Light + Fuel Trim. **So the 6→4 consolidation has to partly reverse.** I designed that consolidation (F-124/W-14) at the CIO's request, and it was right for what he asked then — too many screens to page through. It packed the density that now costs legibility. **On a 3.5″ panel legibility outranks screen count**, so the number goes back up.

Auto-rotate being **off** (CIO disposition-B) materially lowers the cost of more screens: cards no longer advance under you, so paging is deliberate and a longer set is cheap.

### Proposed card set — 6 now, 7 with the Engine card

Order per Atlas #2 (**Alerts to 2nd**):

| # | Card | Facts | Note |
|---|---|---|---|
| 1 | **Home — Live instrument** | compass · g-force · gear · grade | always-on (§4); graphical, not tiles |
| 2 | **Alerts** | hero + DTC state | + the DTC-freshness line inherited from idle (§4) |
| 3 | **System Status** | 4 tiles (2×2) | at the ceiling; no more tiles here |
| 4 | **Battery** | verdict · cell V · runtime | was a Health section |
| 5 | **Fuel Trim** | STFT · LTFT · loop state | was a Health section; bands applied **straight** (Spool withdrew the idle-offset 08-07) |
| 6 | **Light / Ambient** | lux · auto-dim state | was a Health section |
| (7) | **Engine** | MAF · coolant · intake air · throttle | W-16 P2, when groomed — the slot exists |

**"Health" retires as a card.** It was a container of three unrelated facts, and a container is exactly what the new scale cannot afford.

---

## 4. Atlas's design question — what remains of the idle/standby face?

> *"If the live instrument is always the Home face, what (if anything) remains of the idle/standby face?"*

**Answer: the idle face retires. It does not survive as a face — it survives as a *state* of the live card. Its one load-bearing element relocates to where that fact actually lives.**

Reasoning:

1. **Parked, the IMU is not unavailable — it is correct.** The compass reads a true heading and the g-meter reads a true 0.0 g when stationary. Showing them parked is not fabrication; it is the instrument working. There was never a reason to hide them behind "standby."
2. **What is genuinely absent when parked is the OBD-dependent content** — gear, and the speed-gated altitude integration. Those get **typed-NA / greyed**, which is the honest-availability pattern Atlas cites and that Battery + Light already use.
3. **The idle face's unique content was three things:** the STANDBY hero, a clock, and the honesty line *"DTC not read since key-off."*
   - The **STANDBY hero** is replaced by the live instrument showing a true parked reading. Strictly better: a real heading beats the word "standby."
   - The **clock** moves to the top bar (it is chrome, not a card fact).
   - The **DTC-freshness line is real, load-bearing content and must not be lost.** It moves to the **Alerts card** — which is where that fact belongs by SSOT, and which is now adjacent at position 2.

   The idle card was *borrowing* Alerts' fact. Retiring the face returns it to its owner.

**Net: no honest content is lost, one SSOT borrow is repaired, and the CIO gets his compass on the bench.**

---

## 5. The other two change requests

- **#2 Reorder → Home · Alerts · System Status · Health→(split).** Markup order only; carousel finds the DTC index dynamically. Adopted in §3's ordering.
- **#3 Auto-rotate off.** `autoRotateS: 0`. Already CIO disposition-B. See §6 — it constrains the Settings screen.

---

## 6. Knock-on to F-126 Settings (US-532) — from Atlas's design-gate ruling

Two of his US-530 gaps land directly on my Settings design:

- **GAP 3 — one key, not two.** Do **not** render a toggle bound to a new `autoRotate` bool: the overlay stores the existing **`autoRotateS`**, and the UI derives on/off from `autoRotateS > 0` (off writes `0`, on writes the shipped default). Two keys for one fact is an SSOT conflict. **The toggle's default is now OFF** per disposition-B.
- **GAP 1 — auto-rotate does NOT apply live.** `states_http_server` reads `pi.display.carousel` once at startup and serves it cached, so a change needs an `eclipse-states-http` restart + page reload. Slice 1 is acceptable **only if honestly labelled**. My Settings design therefore shows **"applies on restart"** against that control, and the save flow must not present a silent no-op as applied — which was already the brief's honest-apply-state requirement; this just pins which control needs it.
- **Power mode** validates to `{car, wall, unknown}`; anything else resolves to **unknown**, never a confident wrong mode.

The type scale also reaches the Settings surface — its labels and values obey §2 like everything else.

---

## 7. Validate on the panel, not the bench

The scale values are derived, so they must be confirmed against the real display at real distance before they lock. Two specific things to check:

1. **Read the card set at arm's length in the car**, seated normally — not leaning in at a desk. This is Atlas's own A-16 lesson (renders-on-desktop ≠ survives-the-Pi) applied to type.
2. **Verify whether small text is also being resampled.** The stage is authored at 480×320 and scaled up (US-482), with the Pi outputting 1080p into a 480×320 native panel. If the panel downsamples, small glyphs may be blurred as well as small — which would make 8–11 px worse than the arithmetic alone predicts, and would further justify the floor. **I have not confirmed this; it needs a look at the real panel.**

---

## 8. Routing

- **CIO:** review the scale + the card count (6, or 7 with Engine). The count is yours and mine; the values are mine.
- **Atlas:** design-gate the **structural** pieces — screen-count change + the US-482 stage/scale interaction + the idle-face retirement (§4 answers his question).
- **Marcus:** groom as a bundle — (a) tokenize the type scale, (b) set values + re-lay cards, (c) reorder + auto-rotate-off, (d) idle-face retirement.
- **Spool:** no new value semantics requested. NOTE his **08-07 CORRECTION** — the LTFT idle-offset rule is **withdrawn** (the −6.25 % figure was old-ECU); the Fuel Trim card bands STFT/LTFT **straight**, no idle special-case.
