# 3D Printer & Slicer Reference — Iris enclosure work

Reference for printing the enclosure parts. Captured 2026-06-17 from the
light-sensor-case prototype session. Reusable for any Iris enclosure.

## Printer — Prusa i3 MK3S+

| Spec | Value |
|---|---|
| Type | FDM, direct-drive (Bondtech) extruder |
| Build volume | 250 × 210 × 210 mm |
| Nozzle | 0.4 mm (E3D V6 brass) |
| Filament | 1.75 mm |
| Bed | Heated, removable spring-steel PEI sheet |
| Max temps | nozzle ~300 °C, bed ~120 °C |

## Slicer — PrusaSlicer 2.9.5

Set the **mode to Expert** (top-right) to expose every field below. The
**Plater right sidebar** has the quick knobs (Supports dropdown, Infill, Brim
checkbox, filament); the **Print Settings tab** has the detailed sections.

## Materials

| Use | Material | Why |
|---|---|---|
| **Prototype / fit-check** | **PLA** | Cheap, crisp dimensions, easy. **NOT for in-car** — softens at Tg ~55–60 °C; a sun-loaded dash exceeds that. |
| **Final in-car part** | **PETG** (or **ASA**) | PETG: in-car thermal margin, proven on enclosure #1. ASA: best UV+heat but warp-prone, needs an enclosure. Geometry is identical across materials. |

## Validated profile — black PLA prototype (light-sensor case)

| Setting | Value | PrusaSlicer location |
|---|---|---|
| Layer height | **0.15 mm** (first layer 0.2 mm) | Print Settings → Layers and perimeters |
| Perimeters | **3** | Print Settings → Layers and perimeters |
| Top / bottom solid layers | **5 / 4** | Print Settings → Layers and perimeters |
| Seam position | **Rear** | Print Settings → Layers and perimeters → Seam position |
| Infill | **15–20 %**, grid or gyroid | Print Settings → Infill |
| Brim | **Outer brim only, 4 mm**, gap 0.1 mm | Print Settings → Skirt and brim |
| Supports | **On build plate only** | Plater sidebar **Supports** dropdown |
| Support top contact Z | **0.10 mm** | Print Settings → Support material |
| Support top interface layers | **2** | Print Settings → Support material |
| Support style | Snug (or Grid) | Print Settings → Support material |
| Nozzle / bed | **215 → 210 °C / 60 °C** | Filament Settings → Filament / temperatures |
| Cooling fan | **100 % after layer 1** | Filament Settings → Cooling |

PLA tolerances print true on a calibrated MK3S+ — the 1.0 mm board drop-in
clearance, 1.8 mm diffuser groove (1.5 + 0.3), and M2.5 self-tap into Ø2.1
pilots all work as-modelled. PETG tends to swell slightly more; if a PETG
final part is tight, nudge `lid_clear` / `clr` up ~0.1 mm.

## Print orientation & support strategy (this part)

- **Orientation:** flat **bottom (VHB face) on the bed, open top up.** Prints
  support-free except for the bottom recess.
- **Why "On build plate only":** the VHB recess pocket (a ~19.5 mm flat ceiling
  0.5 mm above the bed) needs support or it sags. "Build plate only" supports it
  from the bed while leaving the cavity, diffuser grooves, and vents
  **support-free** — protecting the slide + drop-in fits. The back-mouth lip
  (~21 mm) just bridges (minor cosmetic sag, acceptable).
- **Don't use "Everywhere":** it crams removable supports into the diffuser
  grooves / cavity → fouls the slide fit and is fiddly to clean out of 1.3 mm
  vents.
- **Surgical alternative:** "For support enforcers only" + Support-painting tool
  (shortcut **L**) → paint enforcers on the recess floor and the back-mouth-lip
  underside only.
- **No-support option:** `stl/shell-proto-flatbottom.stl` (VHB recess disabled,
  flat bottom) prints with zero supports — good for a quick fit-check; lose the
  recess (re-add for the final by printing `stl/shell.stl`).

## Quick reference — where settings live in PrusaSlicer 2.9.5

- **Supports placement:** Plater right sidebar → **Supports** dropdown
  (`None` / `Support on build plate only` / `For support enforcers only` /
  `Everywhere`).
- **Brim width / type:** Print Settings → **Skirt and brim**.
- **Seam:** Print Settings → **Layers and perimeters → Seam position**.
- **Support contact Z / interface layers:** Print Settings → **Support material**
  (Advanced/Expert mode).
- **Temps:** Filament Settings → **Filament**. **Cooling:** Filament Settings →
  **Cooling**.
