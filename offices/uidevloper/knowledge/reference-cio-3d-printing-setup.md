---
name: reference-cio-3d-printing-setup
description: CIO's 3D printing setup, materials, toolchain, and known-good print parameters — extracted from PitDroid project (Z:\d\DroidForge_DUM-series_PitDroid_1.1\) which is Mike's parallel hobby project and the only source of his printer-side conventions
metadata:
  type: reference
---

# Reference — CIO's 3D printing setup

**Source:** `Z:\d\DroidForge_DUM-series_PitDroid_1.1\` (CIO's Pit Droid build —
his parallel hobby; only documented source of his print toolchain).
**Captured:** 2026-05-25 (Iris).
**Status:** Partially confirmed — **printer access itself is an open item**
in the PitDroid project as of last update. Verify with CIO before assuming.

---

## 1. Printer hardware — CONFIRMED 2026-05-25

| Item | Value | Source / Confidence |
|---|---|---|
| **CIO's printer** | **Prusa i3 MK3S+** | CIO direct confirmation 2026-05-25 |
| **Build volume** | 250 × 210 × 210 mm | Prusa published spec |
| **Nozzle (stock)** | 0.4 mm E3D V6 brass | Prusa stock config |
| **Bed leveling** | SuperPINDA probe — automatic mesh bed leveling | MK3S+ improvement over base MK3S |
| **Bed surfaces** | Magnetic; swappable steel sheets — typically smooth PEI + textured powder-coated | Prusa standard |
| **File transfer** | **Full-size SD card** (primary), USB-B from PC (secondary) | MK3S+ standard |
| **Filament sensor** | Yes — auto-pause on runout | MK3S+ standard |

**PitDroid history (now obsolete):** PitDroid CLAUDE.md from 2026-02 said
"printer TBD; library Prusa i3 MK3S = one-file-at-a-time, not viable for
160+ parts." That gap is closed — CIO has their own MK3S+ now. Library
MK3S notes preserved here only as historical context.

**Implication for OBD2 display case:** own printer means no library
queue, full retry latitude, can iterate the same evening. 3-piece print
still runs sequentially (per first-print-discipline + plate orientation
differences), but transfer happens via SD card not library scheduling.

## 2. Build plate dimensions

| Parameter | Value | Source |
|---|---|---|
| **Target build plate** | **211 × 211 mm minimum** | PitDroid spec |
| **Build height** | TBD; "most printers fine" for ≤ 125 mm tall | PitDroid spec |
| **Display case fits** | Yes — back shell external is ~102 × 69 mm | display-case-spec.md §5.2 |

Prusa i3 MK3S confirmed build volume: **250 × 210 × 210 mm** (industry-known;
not in PitDroid file but is the standard MK3S spec).

## 3. Material + nozzle

| Parameter | PitDroid Value | Display Case Value | Note |
|---|---|---|---|
| **Filament** | **PLA, 1.75 mm** (CONFIRMED) | **PETG, 1.75 mm** (display-case-spec §10) | **Different materials.** PETG chosen for display because in-car summer dash temps exceed PLA's ~60°C softening; PLA is fine for the indoor Pit Droid. CIO must source PETG separately. |
| **Nozzle** | **0.4 mm brass** (CONFIRMED) | 0.4 mm assumed | Standard hobbyist size; same nozzle works for both materials. |

## 4. Print parameters (PitDroid defaults — adopt as starting point for display case)

| Parameter | PitDroid | Display Case | Diff reason |
|---|---|---|---|
| Layer height (general) | 0.2 mm | 0.2 mm | Same |
| Layer height (detail) | 0.1 mm for small parts | 0.1 mm for snap clips + plunger flexure + grill slots | Same principle |
| **Walls / perimeters** | **8–10** (heavy — droid is structural) | **3** (~1.2 mm) | Display case is non-structural enclosure; 3 perimeters give clean snap-clip mechanical action without over-building |
| **Infill** | 20% cubic (15% for head — weight) | 20% cubic | Same |
| **Supports** | "Everywhere 45°" | **None** — designed to overhangs ≤ 45° | Display case is intentionally support-free; PitDroid parts vary |

**For PETG vs PLA temps** (not in PitDroid file — standard reference):
- PLA: bed 50–60 °C, nozzle 200–220 °C, no enclosure needed
- PETG: **bed 70–85 °C, nozzle 230–250 °C**, partial enclosure helpful, no
  fan on first layer + reduced fan on subsequent
- PETG strings more than PLA — retraction tuning needed
- PETG bonds aggressively to bare PEI — **use glue stick as release layer**
  or textured PEI plate

## 5. CAD + slicing toolchain

| Tool | Use | Status |
|---|---|---|
| **SelfCAD** | STL viewing + measurement | **CONFIRMED — CIO's primary tool** |
| **3D Viewer** (Windows) | Quick STL preview | Mentioned |
| **OpenSCAD** | Parametric source authoring (.scad → .stl) | Iris uses for display case (per pattern-openscad-cli-numeric-part-selector.md) |
| **Slicer** | Print prep (STL → G-code) | **NOT YET INSTALLED 2026-05-25.** Recommendation: **PrusaSlicer** (free, Prusa-made, MK3S+ profiles pre-loaded, Prusament PETG profile pre-tuned for the exact printer). Install from `prusa3d.com/prusaslicer`. |

## 6. File transfer to printer

Not documented in PitDroid file. Standard options for the library MK3S:
- **SD card** (MK3S has full-size SD slot — most common library workflow)
- **USB thumb drive** (newer Prusa-Connect-enabled units; verify with library)
- **Direct USB cable from laptop** to printer (slicer-dependent; ties up the laptop)
- **OctoPrint / Prusa Connect** (network upload) — unlikely on library hardware

The library probably has a posted workflow — confirm before showing up.

## 7. Knowledge gaps to fill on next CIO interaction

1. ~~Did the CIO acquire a personal printer?~~ **CLOSED 2026-05-25 — MK3S+ confirmed.**
2. ~~Which slicer is on his machine?~~ **CLOSED 2026-05-25 — none yet; PrusaSlicer recommended.**
3. **Which bed sheet?** Smooth PEI vs textured powder-coated. Drives PETG
   release advice (smooth = need glue stick; textured = release naturally,
   preferred for PETG).
4. **PETG spool sourced?** Brand + color. Different PETG brands have
   slightly different optimal temps; the Prusament PETG profile is tuned
   for Prusament; generic PETG may need ±5 °C nozzle adjustment.

---

## Companion references

- Display case spec — `enclosures/display-case-spec.md`
- PitDroid source — `Z:\d\DroidForge_DUM-series_PitDroid_1.1\CLAUDE.md`
  + `planning/pit_droid_master.md` §"Printing Specifications"
- OpenSCAD CLI workflow note — `knowledge/pattern-openscad-cli-numeric-part-selector.md`
- CIO clarifying-question norm — `knowledge/feedback-cio-clarifying-questions-always-welcome.md`
