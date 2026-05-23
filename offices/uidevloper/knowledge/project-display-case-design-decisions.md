---
name: project-display-case-design-decisions
description: Locked-in CIO design decisions for the OSOYOO 3.5" display-only 3D-printed case (started 2026-05-22). Foundational facts the case geometry has to honor.
metadata:
  type: project
---

# 3D-Printed Display Case — Locked Decisions

Project started 2026-05-22 (CIO direction). Display unit: OSOYOO 3.5" HDMI
Capacitive Touch Screen v3.0, Model 2024009100 — see [[reference-osoyoo-v3-display-dimensions]]
for all dimensions.

## Scope

**Display only.** Pi 5 + UPS HAT live in a separate (TBD) location and
connect to the display by external cables.

**Why:** CIO directive 2026-05-22 — Pi is NOT part of this case. Earlier
charter §8 W-2 wording (Pi + UPS HAT + display single enclosure) is
SUPERSEDED. Update charter at next closeout.

**How to apply:** Case houses ONLY the display PCB + glass overlay.
Two external cables (HDMI + USB) leave the case and travel to whatever
distant location the Pi gets mounted at.

## Cable specs locked

| Cable | Spec | Bent end | Straight end |
|---|---|---|---|
| HDMI | **Micro-HDMI ↔ Micro-HDMI, one end 90°** | Display (Micro-HDMI port) | Pi 5 (Micro-HDMI port) |
| USB | **USB-C ↔ USB-A, USB-C end 90°** | Display (USB-C port) — carries 5V power + capacitive touch data | Pi 5 (USB-A port) |

**Why:** CIO answered AskUserQuestion 2026-05-22.
- HDMI: matched-connector-both-ends is the cleanest (Pi 5 and display
  are both native Micro-HDMI — no adapters).
- USB: Pi 5 has no USB-C data input, so USB-A is the data-side terminus.
  Single cable carries both power and touch.

**How to apply:** Internal routing channels and bottom-exit holes must
accommodate the 90° connector body on the display end and a flexible
cable continuing from there. 90° body dims to design around:
- Micro-HDMI 90° boot: estimate ~15 × 10 × 6 mm (refine when specific
  cable picked).
- USB-C 90° boot: ~21.5 × 16.6 × 6.7 mm per common adapter dims.

## Mounting orientation locked

**Landscape.** Display is 93.44 mm wide × 60 mm tall when mounted.

**Why:** CIO directive 2026-05-22. Matches gauge/OBD natural reading
orientation.

**How to apply:**
- 93.44 mm axis = horizontal (the long edge)
- 60 mm axis = vertical
- "Bottom of case" (where cables exit) = the bottom horizontal 93.44 mm
  edge
- PCB silkscreen "3.5 Inch LCD Display" reads correctly in this
  orientation per datasheet page 2 photo → Micro-HDMI port is on TOP
  long edge, USB-C is on LEFT short edge
- Both cables route DOWN inside the case from their port positions to
  the bottom exit (HDMI travels the longer internal path)

## Mount system (locked 2026-05-22, refined later same session)

**Standard phone-mount magnetic kit, already partially installed.** The
magnet base is glued to the dashboard. The kit's steel mounting disc
— ~quarter-sized, with 3M VHB adhesive pre-applied — gets stuck to the
center of the back of the case (case = "phone" in this analogy).

**Why:** CIO direction 2026-05-22. CIO is reusing a phone-mount kit he
already has installed on the dash. No new hardware needed beyond what's
in the kit. "Quarter" was a size reference, not a US currency quarter
— the disc is proper ferrous steel from the kit.

**How to apply:**
- Disc dims: ~24 mm diameter × ~1–2 mm thick (typical phone-mount kit
  spec; confirm against CIO's specific kit).
- Back shell needs a flat smooth zone ≥ 25 mm diameter at geometric
  center (in landscape: at 93.44/2 = ~47 mm from one side, 60/2 = 30 mm
  from one end — adjusted for chosen external case dims).
- Adhesive is BUILT INTO the disc (3M VHB or equivalent). No separate
  glue/CA/epoxy needed. Wipe surface with isopropyl, peel liner, press
  on, hold 30 s, full bond ~24 hr.
- Disc sits proud ~1–2 mm above the back surface (no recess unless
  design phase chooses to add one).
- Magnetic flux path stays car-side → through air gap + disc → back
  to magnet. Does NOT pass through the display PCB. No interference
  risk to the LCD or capacitive touch expected.
- Print orientation already gives a smooth flat outer-back face (back
  shell prints inside-face-up so outside-back is on the build plate
  — flattest possible PETG surface, ideal for VHB bond).

## Pi distance — DEFERRED

Pi-to-display distance is TBD. **Case design is cable-length-agnostic.**

**Why:** CIO answered "Don't know yet — TBD" 2026-05-22.

**How to apply:** Pick cable length downstream when Pi mount location
is decided. Case geometry only needs to honor the cable's 90° connector
body + bottom exit geometry — the dangling length outside the case is
not the case's problem.

## Construction style (from charter §8 W-2, reconfirmed 2026-05-22)

**Front and back are SEPARATE PIECES that snap together** — print as two
distinct parts (not a hinged or one-piece collapsing assembly), join via
a snap mechanism at the perimeter.

**Why:** CIO direction at onboarding + reconfirmed mid-research-session
2026-05-22. Print-economic on hobbyist FDM, no screws needed at the seam,
both pieces print flat-on-bed with their inside face up.

**How to apply:** Front shell is the glass-window bezel. Back shell is
the magnet-mount surface + cable exit + ventilation. Snap mechanism:
**cantilever clips** (locked 2026-05-22) — small flexure fingers
moulded into the perimeter of one half, mating to undercut catches on
the other. FDM-friendly, no supports needed if clips face the build-plate
direction. Both pieces designed for unsupported overhang printability.

## Ventilation (added 2026-05-22)

**Vents on the back shell** are required.

**Why:** CIO direction 2026-05-22. Display draws up to 230 mA @ 5 V ≈ 1.15 W
peak; LCD driver IC + USB-C touch controller dissipate inside the case.
In-car summer ambient + sealed plastic enclosure = real risk of exceeding
the display's 70 °C operating ceiling.

**How to apply:**
- Vent pattern on back-shell face (slots, holes, or grille).
- Pattern must not compromise magnet-mount flat zone — vents around the
  perimeter region OR a vent area that the magnet system can sit clear of.
- Cable exit channel at the bottom edge also contributes airflow path
  (convective flow up the back of the PCB, out the vents).
- Style: **grill** (locked 2026-05-22). Parallel slots or crosshatch
  pattern in the back-shell face. Slot widths sized to FDM-print
  cleanly without supports (≥ 1.5 mm wide, ≥ 3 mm bridges between
  slots at 0.4 mm nozzle).
- Grill must AVOID the central ~30 mm diameter zone where the
  quarter-sized metal disc gets glued. Two acceptable layouts: (a)
  grill around the perimeter region in a frame pattern; (b) grill on
  the upper half of the back, disc on the lower half (or vice versa)
  — final layout is a brainstorming-phase pick.

## Interior depth allowance (added 2026-05-22)

**Reserve an extra 2–4 mm of interior depth beyond the 7 mm display
thickness** for cable routing.

**Why:** CIO direction 2026-05-22. The 90° cable boots exit the port
parallel to the PCB face (not perpendicular), so the cable jacket runs
along the back of the PCB toward the bottom exit. That run needs clearance
between the back of the PCB and the inside of the back shell.

**How to apply:**
- Total interior cavity depth ≈ 7 mm (display) + 2–4 mm (routing channel) =
  **9–11 mm inside dimension**.
- Plus front + back wall thickness of ~1.5–2.5 mm each (FDM-friendly) =
  ~12–16 mm total external Z.
- The routing channel is a continuous open volume behind the PCB — not
  separate channels per cable — so each cable can find its own path
  without designed-in ribs. Strain relief is enforced at the bottom exit
  hole geometry, not by internal channels.
- 90° boot bodies sit in this same volume: the boots fold the cable
  parallel to the PCB face, so a USB-C 90° boot (~21.5 × 16.6 × 6.7 mm)
  fits in the 2–4 mm channel as long as it's oriented "thin axis
  perpendicular to PCB."

## Front face — recessed bezel (locked 2026-05-22)

**Recessed bezel frame** around the glass.

**Why:** CIO direction 2026-05-22. Visual: case material frames the
glass and the glass sits below the case-front plane (the bezel is
"raised" above the glass surface). Protects glass edges + gives a
finished look.

**How to apply:**
- Front-face cutout: 93.44 × 60 mm (glass outline, +0.3 mm tolerance
  each side → cut to ~94 × 60.5 mm).
- The cutout exposes the touch glass. Capacitive touch works through
  the open window.
- Bezel frame width around the window: design-choice. Recommend 3–4 mm
  visible bezel (keeps overall case width to ~100 × 68 mm).
- Recess depth: glass sits flush with the inside of the front shell,
  so the front face is "proud" of the glass by the front-shell wall
  thickness — typically 1.5–2 mm. That's the recess depth as seen from
  outside.

## Pass-through actuators for display controls (locked 2026-05-22)

**Approach:** Remote pass-through buttons in the case wall that
mechanically depress the underlying display buttons when pushed.

**Why:** CIO direction 2026-05-22. Keeps the display controls accessible
without exposing the PCB directly.

**The display has TWO user controls per datasheet, but only ONE gets a
pass-through:**
1. **Power slide switch** (top-left area, H=4 mm) — **SEALED inside the
   case, factory ON** (CIO 2026-05-22). Set to ON before final
   assembly. Display will power on whenever USB-A delivers 5 V from the
   Pi. No case slot, no external control. Cleaner print, no ingress.
2. **Brightness button** (top-middle area, H≈3 mm) — *press* button.
   Standard plunger pass-through pattern works:
   - Plunger pin slides through a snug hole in the case wall
   - Inner end rests against the display button cap
   - Outer end protrudes for finger access
   - A flexure / O-ring / molded-in cantilever returns it to "out"
     position
   - All-PLA flexure version: plunger + thin cantilever spring printed
     as a single part (FDM-friendly), captured by a retaining ring on
     the case interior side

**Plunger geometry preview (brightness button):**
- Plunger shaft ~3–4 mm diameter
- Travel ~1.5 mm (depress button on display by ~1 mm)
- Located directly above the brightness button position on top edge of
  PCB — pass-through hole is in the case TOP face or top-front face

## Printer specs (from PitDroid project Z:\d\DroidForge_DUM-series_PitDroid_1.1\CLAUDE.md)

| Spec | Value (this case) | Source |
|---|---|---|
| Build volume (X × Y) | **211 × 211 mm** | Plenty of room — case is ~95×70 mm |
| Layer height | **0.2 mm** standard, **0.1 mm** for small/detail parts | Use 0.1 mm for snap clip flexures + plunger fits |
| Walls / perimeters | **3 perimeters / ~1.2 mm walls** (locked 2026-05-22) | Thin-case-appropriate. PitDroid's 8–10 was overkill for low-stress housing. |
| Infill | **20% cubic** | Display case can use 20% |
| Supports | Everywhere at **45°** overhang | Design overhangs ≤ 45° to avoid supports |
| Material | **PETG** (locked 2026-05-22) | ~80 °C glass transition gives margin over PLA for in-car summer dash temps. |

**CAD source toolchain (CIO's workflow):**
- **OpenSCAD** for parametric source files (.scad → .stl) — preferred
  format for custom adapter parts
- **SelfCAD** for STL viewing and measurement (CIO's primary tool)
- Python + numpy-stl for batch operations (scale_stl.py)

→ **Implication:** I produce design source as OpenSCAD .scad files
committed into `offices/uidevloper/enclosures/`. STLs render from those.

## Concerns resolved 2026-05-22

All three flagged concerns answered by CIO this session:

| # | Concern | Resolution |
|---|---|---|
| C-1 | Power slide switch — pass-through hard | **Sealed inside, factory ON.** No case slot. Brightness button is the only pass-through. |
| C-2 | PLA thermal margin thin for in-car | **PETG locked** (~80 °C GT, in-car safe). |
| C-3 | 8–10 walls overkill for thin case | **3 perimeters / ~1.2 mm walls locked.** |

## Open items remaining

All major geometry-blocking items now resolved. Remaining items are
brainstorming-phase choices:
- Exact bezel width (3 mm vs 4 mm)
- Cable exit hole pattern at the bottom — single oval slot vs two
  round holes, strain relief style
- Snap clip count + position around perimeter
- Grill pattern geometry (slot count, spacing, orientation)
- Plunger return mechanism (molded cantilever vs separate retaining
  ring)
