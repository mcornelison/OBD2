---
name: reference-mk3s-plus-first-print-guide
description: Distilled MK3S+ first-print procedure from the official Prusa user manual (specs/vendor/prusa3d_manual_mk3s_en.pdf). Captures bed-sheet behavior, PETG settings, calibration sequence, and live-Z tuning — the pieces a first-time operator needs without reading 100+ pages.
metadata:
  type: reference
---

# Reference — MK3S+ first-print procedure (from official manual)

**Source:** `specs/vendor/prusa3d_manual_mk3s_en.pdf` (Prusa handbook
v3.18, 2023-01-26). Section/page numbers below cite the manual directly.
**Captured:** 2026-05-25 (Iris).
**Use case:** First-time print on the OBD2 display case. Companion to
`reference-cio-3d-printing-setup.md`.

---

## 1. Quick-guide to first print (manual cover, paraphrased)

1. Safety instructions — page 7
2. Place printer on flat, stable surface — page 10
3. Download + install drivers (PrusaSlicer) — page 47
4. **Calibration flow / wizard** — page 12 (§6.3.1)
5. Insert SD card and print first model — page 29 (§7)

Steps 1–3 are setup. Steps 4–5 are the actual first-print work.

## 2. Bed sheet types — which one matters for PETG (§6.3.2)

The MK3S+ ships with one of three swappable spring steel sheets. **The
sheet type drives whether you need glue stick for PETG.** Each sheet
needs its own First Layer Calibration (save up to 8 profiles in
Settings → Steel sheets, §8.1).

| Sheet | PETG compatibility | Glue stick needed? | Visual ID |
|---|---|---|---|
| **Smooth PEI** (double-sided) | "Do not clean with IPA before PETG. **Release agent might be necessary.**" | **YES** — needed to prevent over-adhesion + bed damage | Glossy orange/black surface |
| **Satin powder-coated** | "Suitable for both PLA and PETG. No need for glue stick with FlexFill98A." | **NO** | Matte, lightly textured |
| **Textured PEI powder-coated** | Works, prints auto-detach when cool | **NO** | Visibly granular/bumpy |

**Key rule for Smooth PEI + PETG (§6.3.2.2):** Don't wipe with isopropyl
before PETG — it makes PETG stick *more* aggressively, and removing the
print can rip flakes off the PEI surface (permanent bed damage).

**Never clean Satin or Textured powder-coated sheets with acetone** —
creates microfractures.

## 3. PETG specifics (§12.2)

| Parameter | Manual value |
|---|---|
| Nozzle temperature | **240 °C** |
| Bed temperature | **80–100 °C** |
| Typical use cited | "mechanical components, holders and cases, watertight prints" |

Tips from manual:
- PETG oozes / strings more than PLA. PrusaSlicer's PETG presets already
  tune retraction; small residual stringing peels off easily.
- Heat gun blast removes finishing strings.
- PETG holds heatbed very well — low warping risk.
- **Strong bed adhesion = the main risk** with PETG (esp. on Smooth PEI).

## 4. Calibration sequence (one-time, before first print)

### 4.1 First Layer Calibration (§6.3.9) — the critical step

LCD Menu → **Calibration → First layer cal.**

What it does:
1. Probes the bed (auto via SuperPINDA).
2. Starts printing a zigzag pattern.
3. Live menu appears — turn the control knob to **adjust nozzle height
   in real time**. This is the **Live Adjust Z** value.
4. Goal: "extruded plastic sticks nicely to the bed and you can see it
   is being slightly squished."
5. Value should not exceed **−2.000 mm**. If you need more, the
   SuperPINDA probe physically needs to be repositioned (loosen M3
   screw on probe holder, adjust, re-run Calibrate Z + First layer cal).

**The Live Adjust Z value is stored per steel sheet.** Switching sheets =
re-calibrate or load the saved profile (§8.1).

### 4.2 Fine tuning (§6.3.10)

After the zigzag, manual recommends printing the **Prusa logo from the
included SD card** as a final fine-tune. Live Adjust Z works during *any*
print — you can keep nudging while the logo's first layer goes down until
it looks like Pict. 12 in the manual ("perfectly tuned first layer").

**Visual cue for properly tuned first layer:** even, glossy, slightly
squished lines with no gaps between adjacent passes. Too high = gaps +
stringy lines you can lift off. Too low = transparent / scraped lines +
PETG smears into the nozzle.

## 5. Loading filament (§6.3.8)

LCD Menu → **Load Filament**

1. Auto-prompts for filament type → select **PETG**.
2. Printer preheats nozzle to 240 °C.
3. **Cut filament tip at an angle** (sharp diagonal, makes a "pointy tip"
   — manual emphasis).
4. Insert into extruder when prompted.
5. Auto-loads via stepper motor.

If filament sensor + autoloading enabled (default on MK3S+), just
preheat and insert — extruder grabs automatically.

## 6. Starting the print (§7)

1. Slice STL in PrusaSlicer → export `.gcode` to SD card.
2. Insert SD card into front of MK3S+.
3. LCD → **Print from SD** → select file.
4. Auto-homes XYZ → runs mesh bed level (SuperPINDA ticks around the bed) →
   starts print.
5. **Live Adjust Z is active during the whole print** — if first layer
   looks off, knob to adjust in real time.

## 7. Removing the print (§7.1)

- Wait for bed to cool to ~50 °C (or fully ambient for PETG —
  auto-detach on textured/satin sheets).
- Remove magnetic steel sheet from heatbed.
- **Flex the sheet gently** — prints pop off cleanly when sheet is bent.
- On Smooth PEI + PETG: if it doesn't release, do NOT pry with a metal
  tool (damages PEI). Wait for full cool + flex again.

## 8. Maintenance items relevant to first-time use (§13)

- Wipe extruder drive gear free of filament dust every few prints.
- Don't touch sheets with bare fingers — skin oils kill adhesion. Wipe
  with isopropyl (smooth PEI only, *not before PETG*) or soapy water
  (textured/satin).
- **Smooth PEI rejuvenation** (§13.1.5): hard side of dry kitchen sponge,
  circular motion. Acetone OK for Smooth PEI only.

## 9. Manual cross-reference index

| Topic | Manual section | Manual page |
|---|---|---|
| Safety | §- | 7 |
| Calibration wizard (full flow) | §6.3.1 | 12 |
| Steel sheets — preparation + types | §6.3.2 | 13–18 |
| Increasing adhesion (glue/separator) | §6.3.3 | 18 |
| Calibrate Z | §6.3.6 | 22 |
| Mesh bed leveling | §6.3.7 | 23 |
| Loading filament | §6.3.8 | 24 |
| **First Layer Calibration** | **§6.3.9** | **25** |
| Fine tuning first layer | §6.3.10 | 28 |
| Printer control / LCD | §7.2 | 30 |
| Print statistics | §7.2.3 | 31 |
| Power panic recovery | §7.2.12 | 38 |
| Steel sheet profiles (save up to 8) | §8.1 | 44 |
| PrusaSlicer overview | §11.1 | 53 |
| **PETG (PET) detailed** | **§12.2** | **59–60** |
| Smooth PEI rejuvenation | §13.1.5 | 69 |
| Print surface preparation | §13.2 | 69 |
| Firmware update | §13.9 | (see chapter) |

## 10. Confirmed sheet — CIO 2026-05-25

**Sheet on MK3S+: Textured PEI powder-coated.**

Implications:
- **No glue stick needed** for PETG. PETG releases naturally when sheet
  cools.
- "More forgiving Live Adjust Z setting" than smooth sheets
  (§6.3.2.1) — easier first-print calibration.
- Texture transfers to print's bottom face — fine for this case
  (back face hidden against dashboard mount; not a cosmetic issue).
- **NEVER clean with acetone** — creates microfractures in PEI.
  Clean with isopropyl alcohol or soapy water only.
- Auto-detaches when cool — bend sheet gently, print pops off.
- Hard to damage by nozzle crash (powder coat on metal dissipates heat).
