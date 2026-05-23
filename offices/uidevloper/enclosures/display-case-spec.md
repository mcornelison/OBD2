# OBD2 Display Case — Build Specification

**Status:** SPEC LOCKED, geometry-design phase NOT YET STARTED.
**Last updated:** 2026-05-22 (Iris)
**Owner:** Iris (UI/UX Designer, `offices/uidevloper/`)
**For:** Eclipse OBD-II project — in-car driver-facing display housing.

---

## 0. How to use this document

A future session can pick this up cold and start producing CAD without
asking the CIO any further blocking questions. Open items in §11 are
brainstorming-phase aesthetic choices, not blockers.

**Reading order:**
1. §1 Scope, §2 Hardware — what we're enclosing
2. §3 Dimensions — every number
3. §4 Cable spec — what the case has to feed
4. §5–9 Case design parameters
5. §10 Printing parameters + toolchain
6. §11 Brainstorming-phase decisions (still open)
7. §12 Companion files

---

## 1. Scope

A 3D-printed enclosure for the **OSOYOO 3.5" HDMI Capacitive Touch
Screen v3.0 (Model 2024009100)**, mounted to the dashboard of the CIO's
1998 Mitsubishi Eclipse GST via an existing magnet phone-mount system.

**In scope:**
- Front shell (bezel + glass window)
- Back shell (mount surface + vents + cable exit)
- Internal cable routing geometry
- Brightness button plunger pass-through
- M2.5 mount points for the display PCB
- Cantilever snap clips joining front + back

**Out of scope:**
- Pi 5 and UPS HAT enclosure (separate project; not housed here)
- The car-side magnet mount (CIO supplies; already installed)
- Cable purchase (CIO sources)
- The metal disc itself (CIO sources)

---

## 2. Hardware bill of materials

| # | Item | Qty | Source | Notes |
|---|---|---|---|---|
| 1 | OSOYOO 3.5" HDMI Capacitive Touch Screen v3.0 | 1 | CIO has | Model #2024009100 |
| 2 | Micro-HDMI ↔ Micro-HDMI cable, one end 90° (display end) | 1 | CIO sources | Length TBD (Pi distance unknown) |
| 3 | USB-C → USB-A cable, USB-C end 90° (display end) | 1 | CIO sources | Carries 5 V + capacitive-touch data |
| 4 | Adhesive-backed steel mounting disc | 1 | CIO has (from existing phone-mount kit) | Standard phone-mount magnetic kit component. ~24 mm diameter, ~1–2 mm thick, ferrous steel, 3M VHB (or equivalent) adhesive pre-applied to one face. The case is the "phone" in this analogy. |
| 5 | Magnetic dash mount (car-side) | 1 | CIO has (already installed on dashboard) | The magnet half of the same phone-mount kit. Already adhered to the dashboard — case design doesn't touch this. |
| 6 | M2.5 hardware for PCB mounting | 4 | TBD design phase | Either: brass heat-set inserts + M2.5 screws, OR self-tapping into printed bosses, OR captive nuts. Decide in design phase. |
| 7 | PETG filament | ~50 g | CIO sources | See §10. |

---

## 3. Dimensions — every number (from official datasheet)

### 3.1 Display outer (touch-glass face)

| | Value | Tolerance |
|---|---|---|
| Glass outer X | **93.44 mm** | ±0.3 mm |
| Glass outer Y | **60.00 mm** | ±0.3 mm |
| Glass thickness (incl. touch overlay) | included in Z assembly |  |
| Active LCD area | 73.44 × 48.96 mm | ±0.3 mm |
| Margin glass → active area, long side | 10.00 mm |  |
| Margin glass → active area, short side | 5.52 mm |  |

### 3.2 PCB

| | Value | Tolerance |
|---|---|---|
| PCB outer X | **85.0 mm** | ±0.2 mm |
| PCB outer Y | **49.0 mm** |  |
| Glass overhang past PCB, long axis | (93.44 − 85.0) / 2 = 4.22 mm each side |  |
| Glass overhang past PCB, short axis | (60.0 − 49.0) / 2 = 5.5 mm each side |  |
| Total Z assembly | **7.0 mm** | display side profile from datasheet |

The PCB sits recessed inside the glass envelope. **The front-face
window cuts the GLASS outline (93.44 × 60), not the PCB outline (85 × 49).**

### 3.3 Mounting holes (display PCB)

- **4 holes**, **Φ = 3 mm**, **M2.5 thread**, one near each PCB corner.
- Centers (from datasheet, measured from the PCB edges):
  - ≈ 5.0 mm from short edge (3.5 mm clear + 1.5 mm half-hole)
  - ≈ 4.9 mm from long edge (3.4 mm clear + 1.5 mm half-hole)
- Center-to-center along long edge: **58 mm**.
- Center-to-center along short edge: see datasheet page 1 (15.7 + 25.7 + 14.6 = 56 mm working backward; confirm with calipers when unit is in hand).

### 3.4 Connector positions (display PCB)

| Port | Edge | Body height H (above PCB) | Approx position from corner |
|---|---|---|---|
| **Micro-HDMI** | TOP long edge | 4 mm | ~28.5 mm from one corner |
| **USB-C** | LEFT short edge | 3 mm | TBD by measurement; near top-left area |
| Power slide switch | top-left area | 4 mm | (sealed inside case — no actuator needed) |
| Brightness press button | top-middle | ~3 mm | Plunger pass-through required (§7) |
| 4-pin test header | bottom edge | 2 mm | (sealed inside; not used) |

**Critical:** The two cable ports are on **perpendicular edges**.
Internal routing inside the case will be asymmetric.

### 3.5 Display electrical (from datasheet)

| | Value |
|---|---|
| Resolution | 480 × 320, no scaling at this res |
| Refresh | 60 Hz |
| Touch | 5-point capacitive (via USB-C) |
| Power, normal | 5 V, 200–230 mA (max brightness) |
| Power, standby | 5 V, 70–90 mA |
| Power, suspend (switch off) | 5 V, 20 mA |
| Operating temp | −20 °C to +70 °C |
| Weight (bare) | 55 g |

---

## 4. Cable spec

### 4.1 HDMI

| Field | Value |
|---|---|
| Connector at display | Micro-HDMI (Type D), male |
| Connector at far end | Micro-HDMI (Type D), male |
| Bend | 90° boot on the display end |
| Bend direction | Cable runs **DOWNWARD** along the back of the PCB after the boot |
| Length | TBD by CIO when Pi mount is decided |

Design the boot recess + routing channel around this geometry. Common
90° micro-HDMI boot envelope: estimate **~16 × 10 × 8 mm** (refine
when a specific cable is selected).

### 4.2 USB

| Field | Value |
|---|---|
| Connector at display | USB-C, male |
| Connector at far end | USB-A, male (plugs into Pi 5 USB-A port) |
| Function | 5 V power IN + capacitive touch data OUT, single cable |
| Bend | 90° boot on the display (USB-C) end |
| Bend direction | Cable runs **DOWNWARD** along the back of the PCB after the boot |
| Length | TBD |

Common 90° USB-C boot envelope: **~21.5 × 16.6 × 6.7 mm** (per Mouser
& Amazon listings). Refine with the specific selected cable.

---

## 5. Case form

| Parameter | Value |
|---|---|
| Construction | Two separate pieces — **front shell** + **back shell** — snap together. No hinge, no one-piece collapsing geometry. |
| Snap mechanism | Cantilever clips, perimeter-mounted. Print-direction-friendly. |
| Mount orientation when in car | **Landscape** — 93.44 mm horizontal × 60 mm vertical |
| External dimensions (target) | ~100 × 67 × 14 mm — final dims emerge from §6 |
| Front face | **Recessed bezel** — glass sits flush with the inside of the front shell; bezel frame is proud of the glass on the outside by the front-wall thickness. |
| Bezel frame width (visible) | 3–4 mm recommended (brainstorming-phase choice) |

### 5.1 Case Z budget (build from inside out)

```
Display Z:                          7.0 mm
Cable routing channel behind PCB:   2.0–4.0 mm  (CIO directive)
Front wall thickness:               ~1.2 mm     (3 perimeters)
Back wall thickness:                ~1.2 mm     (3 perimeters)
                                    ----------
External Z total:                   ~12.4–14.4 mm
```

### 5.2 Case X/Y budget

```
Glass:                              93.44 × 60.0 mm
Side clearance + bezel:             ~3 mm each side (front face) — bezel needs material
Wall thickness X:                   ~1.2 mm × 2 = 2.4 mm
                                    ----------
External X:                         93.44 + 2×3 + 2×1.2 ≈ 102 mm
External Y:                         60.0  + 2×3 + 2×1.2 ≈ 69 mm
```

Comfortably inside the 211 × 211 mm print plate.

---

## 6. Internal layout (back shell coordinate space)

Origin: bottom-left INSIDE corner of the back shell, looking AT the
back (from behind the case).

```
+y (top)
 |    ┌─────────────────────────────────────────────────────────┐
 |    │  HDMI boot         brightness                            │
 |    │  position (~28.5)  button (~?)                           │
 |    │     |                  |                                 │
 |    │  ┌──┴──┐            ┌──┴──┐                              │
 |    │  │     │            │     │                              │
 |    │  │     │            │     │                              │
 |    │  │             [display PCB 85 × 49]                     │
 |    │  │     ┌──────────────────────────────────────┐          │
 |    │  │     │                                      │          │
 |    │  │     │       active LCD area                │          │
 |    │ USB-C  │       (73.44 × 48.96)                │          │
 |    │  │     │                                      │          │
 |    │  │     └──────────────────────────────────────┘          │
 |    │  │                                                       │
 |    │  └─ port on                                              │
 |    │     LEFT edge                                            │
 |    │                                                          │
 |    │     ──[cable channel routes both cables down]──          │
 |    │                                                          │
 |    │              ┌─────┐ ┌─────┐                             │
 |    │              │ EXIT│ │ EXIT│  ← cable exits, bottom face │
 |    └──────────────┴─────┴─┴─────┴─────────────────────────────┘
                                                                +x →
```

(Schematic, not to scale — sketch only.)

### 6.1 Mount disc location (back face, outside)

- The disc is the **case side** of a standard phone-mount magnetic kit
  — it has 3M VHB adhesive pre-applied on the case-facing surface.
  The magnet base is already on the dashboard; the disc on the case
  pulls to it.
- Center of the disc = geometric center of the back-face panel
- Coordinates relative to back-face outer rectangle: **(X_external/2, Y_external/2)**
- ~24 mm diameter, ~1–2 mm thick
- Disc adheres to a flat smooth zone on the back outer face — no
  recess unless design phase chooses to add one
- PETG accepts 3M VHB well; wipe surface clean with isopropyl before
  applying. No printed-in surface texture in the disc zone (smooth
  layer top — print orientation already gives this on the outside-back
  face since it prints upward as the bottom of the back-shell mold).

### 6.2 Vent grill location (back face, outside)

- Around the perimeter of the back face, OR on the upper half (with disc on lower half)
- Avoid the central 30 mm-diameter zone where the disc is glued
- Slot widths ≥ 1.5 mm; bridges between slots ≥ 3 mm (FDM-clean without supports at 0.4 mm nozzle)

### 6.3 Cable exit (bottom face)

- Two holes OR one larger oval slot in the bottom edge
- Located along the bottom face of the back shell
- Geometry must allow the cable jacket to exit cleanly without
  pinching; consider chamfered edges or grommet-style relief
- Internal volume between the back of the PCB and the inside of the
  back shell IS the routing channel — no separate ducting needed

### 6.4 PCB mounting

- 4 corner standoffs on the back shell, M2.5-compatible
- Standoff height: ~3 mm to clear bottom-side components (datasheet
  shows H = 2 mm for the GPIO header on the bottom edge of the PCB)
- Method: TBD design phase (heat-set inserts vs printed threads vs
  M2.5 self-tapping). Heat-set inserts give the cleanest result and
  allow re-disassembly without thread degradation.

---

## 7. Brightness button plunger pass-through

The display has a brightness press button on the top edge (~middle).
The case provides a plunger that the user presses externally.

| Parameter | Value |
|---|---|
| Plunger shaft diameter | 3–4 mm |
| Plunger travel | ~1.5 mm |
| Inner end | Rests on the display button cap (no gap when at rest) |
| Outer end | Protrudes ~1.5 mm beyond the case outer surface |
| Return mechanism | Two options — pick in design phase: |
|  | (a) **Molded cantilever spring** — plunger and a thin flexure arm printed as one piece, captured by an interior retaining ring |
|  | (b) **Separate plunger + retaining pin** — plunger slides freely, pin holds it in case, brightness button's own internal spring returns it |
| Location | Directly above the brightness button on the display top-edge — case TOP face (the side that faces UP when in landscape) |
| Material | PETG, same as rest of case |

The power slide switch gets NO pass-through (sealed inside, factory ON).

---

## 8. Mounting tolerances + clearances

| Interface | Recommended tolerance |
|---|---|
| Front-face window cutout (cuts glass outline) | 94.0 × 60.6 mm (datasheet +0.3 mm tolerance baked in) |
| PCB Z resting position | PCB rests on 4 standoffs; PCB sits ~3 mm above back-shell inner face |
| Glass-to-bezel inner step | ~0.2 mm peripheral clearance for glass insertion |
| Cantilever clip engagement | 0.2–0.3 mm interference at the lip; relief notch on the other half |
| Cable bottom-exit hole | Hole diameter = cable jacket diameter + ~1 mm |
| M2.5 standoff hole (if heat-set inserts) | 3.5 mm diameter pre-hole for typical brass insert |

---

## 9. Assembly sequence (target)

1. Set the display's power slide switch to **ON** position.
2. Press M2.5 heat-set inserts into the back shell's 4 corner standoffs (if using insert approach).
3. Plug the 90° connectors of both cables into the display. Route the cables along the back of the PCB toward the bottom.
4. Lay the display PCB into the back shell, aligning the 4 corner mounting holes with the standoffs.
5. Thread 4× M2.5 screws through the PCB into the inserts.
6. Feed the cables through the bottom exit holes/slot.
7. Wipe the back-face disc-zone with isopropyl alcohol. Peel the adhesive liner off the steel mounting disc and press it firmly onto the geometric center of the back outer face. Apply pressure for 30 s; full bond after ~24 hr per typical 3M VHB cure.
8. Lower the front shell onto the back shell, aligning the glass cutout over the display glass. Press to engage the perimeter cantilever clips.
9. Verify brightness plunger has free travel and depresses the underlying button.
10. Plug the cables' far ends into the Pi (Micro-HDMI + USB-A) when ready to deploy.

---

## 10. Printing parameters

| Parameter | Value |
|---|---|
| Printer build volume | 211 × 211 mm (CIO printer) |
| Material | **PETG** (~80 °C glass transition; survives in-car summer) |
| Layer height | 0.2 mm general, **0.1 mm for snap clips + plunger fits + grill slots** |
| Nozzle | 0.4 mm assumed (typical hobbyist FDM) |
| Walls / perimeters | **3** (~1.2 mm wall thickness) |
| Top / bottom solid layers | 4–5 (standard) |
| Infill | 20% cubic |
| Supports | None — design to overhangs ≤ 45° |
| Print orientation | **Both pieces flat-on-bed, inside-face UP.** Front shell: bezel face down, internal glass-window pocket facing up. Back shell: outside-back face down, internal cavity facing up. |
| Bed adhesion | Glue stick or PEI; PETG benefits from a slightly higher bed temp |
| Estimated print time | ~3–5 hours each piece (firm up in slicer) |

### CAD source toolchain (CIO workflow)

| Tool | Use |
|---|---|
| **OpenSCAD** | Parametric source files (.scad). Primary authoring format. Commit .scad to the repo; .stl regenerates from source. |
| **SelfCAD** | CIO's STL viewing + measurement tool (no .scad authoring). |
| Slicer | CIO's standard slicer (PrusaSlicer / Cura / etc.). Slicing settings live in slicer profiles, not in source. |

### .scad file organization (proposed)

```
offices/uidevloper/enclosures/
├── display-case-spec.md             ← this file
├── display-case.scad                ← top-level: includes both shells, parameters at top
├── modules/
│   ├── front_shell.scad
│   ├── back_shell.scad
│   ├── snap_clip.scad
│   ├── plunger.scad
│   └── vent_grill.scad
├── stl/
│   ├── front_shell.stl              ← exported, ready to slice
│   └── back_shell.stl
└── renders/
    └── case_assembly.png            ← OpenSCAD F6 render
```

All key dimensions exposed as parameters at the top of `display-case.scad`
so dimensional updates ripple automatically through both shells.

---

## 11. Resolved design choices (brainstorming complete 2026-05-22)

All ten brainstorming items resolved with CIO. Captured in
`display-case.scad` parameter block.

| # | Choice | Resolved value | Where in .scad |
|---|---|---|---|
| BP-1 | Bezel frame width | **3.5 mm visible** | `bezel_width` |
| BP-2 | Cable exit hole shape | **Single oval slot, 25 × 4 mm**, bottom edge, ~5 mm above cavity floor | `cable_slot_x`, `cable_slot_y`, `cable_slot_z_from_bottom` |
| BP-3 | Snap clip count + position | **6 clips: 2 on each long edge at 30%/70% of width, 1 centered on each short edge** | `clip_positions_long`, `clip_positions_short` |
| BP-4 | Snap clip style | **Cantilever finger on back shell** (6 × 1.5 × 3 mm shaft + 0.6 mm hook), catches in interlock lip of front shell | `snap_clip_finger()` module |
| BP-5 | Grill pattern | **Two groups of 5 horizontal slots**, each slot 50 × 2 mm, 3 mm spacing, above + below the central disc clearance zone (30 mm diameter clear) | vent loop in `back_shell()` |
| BP-6 | Plunger return | **Molded cantilever spring**, single PETG printed piece — plunger shaft Ø3.5 mm + 4 × 12 × 0.8 mm flexure arm + stop collar | `plunger()` module |
| BP-7 | PCB mount method | **M2.5 brass heat-set inserts** in 4 corner bosses (Ø6 mm OD, Ø3.5 mm ID, 3 mm tall) | `boss()` module |
| BP-8 | Front-shell glass retention | **Captive between front-shell inner step + PCB pressing forward** — no separate adhesive | implicit in front_shell geometry |
| BP-9 | Disc recess | **None** — disc glued proud on the outside back face | flat zone, no cutout |
| BP-10 | Corner radius (external) | **2 mm fillet** on all external vertical edges | `corner_r` |

## 11A. v1 STL output (rendered 2026-05-22)

Three printable STL files in `enclosures/stl/`:

| File | Size | Geometry |
|---|---|---|
| `back_shell.stl` | 209 KB | 334 facets, simple manifold. Cavity + bosses + vents + cable exit + snap clips. |
| `front_shell.stl` | 35 KB | 62 facets, simple manifold. Bezel + interlock lip + glass cutout + snap catches. |
| `plunger.stl` | 68 KB | 105 facets, simple manifold. Shaft + flexure + stop collar. |

Assembly preview: `enclosures/renders/assembly.png`.

### Print orientation guidance (v1)

| Part | OpenSCAD default orientation | Slicer action |
|---|---|---|
| `back_shell.stl` | Outside-back face at Z=0 (already bed-down). Cavity opens up. | Slice as-is. |
| `front_shell.stl` | Interlock lip at Z=0, bezel at top. | **Flip 180° around X axis** so bezel face is on the bed (smooth bezel, cleaner snap-catch overhangs). |
| `plunger.stl` | Shaft vertical along Z. | Slice as-is, or rotate to lie on its side if preferred for surface finish. |

### v1 known caveats

- Cable-boot interior clearance is sized for assumed 90° boot envelopes
  (Micro-HDMI ~16 × 10 × 8 mm; USB-C ~21.5 × 16.6 × 6.7 mm). Verify
  against actual purchased cables before final tightening.
- Brightness button plunger X-position assumes brightness button is
  ~50 mm from PCB left edge per datasheet annotation; verify against
  actual unit with calipers if plunger ends up misaligned.
- PCB mounting hole positions assume ~4.9 mm long-edge inset and
  ~5.0 mm short-edge inset. The datasheet's full hole-position
  geometry is partially ambiguous; verify against actual unit.
- Snap clip engagement (0.4 mm interference) is conservative. If
  shells separate too easily after first print, increase
  `clip_hook_proud` in the .scad and re-render.
- This is a **fit-check prototype**. Expect 1–2 iterations before
  production-quality assembly.

---

## 12. Companion files

- `offices/uidevloper/knowledge/reference-osoyoo-v3-display-dimensions.md` — every datasheet number with annotations and the source link
- `offices/uidevloper/knowledge/project-display-case-design-decisions.md` — the decision history with *why* for each locked decision
- `offices/uidevloper/knowledge/feedback-cio-clarifying-questions-always-welcome.md` — CIO interaction norm: ask on load-bearing ambiguity
- OSOYOO datasheet PDF (1.6 MB binary): cached at `C:\Users\mcorn\.claude\projects\Z--o-OBD2v2-offices-uidevloper\b1bd785c-8e41-4c59-9796-fe3980a9b695\tool-results\webfetch-1779497247647-jmet9t.pdf` (re-fetch from https://osoyoo.com/picture/3.5hdmi_screen/2024009100/datasheet.pdf if cache evicted)
- Charter: `offices/uidevloper/claude.md` (Iris office charter; W-2 = this work item)
- Printer-specs source: `Z:\d\DroidForge_DUM-series_PitDroid_1.1\CLAUDE.md`

---

## 13. Session pickup script

A future session opens this file, reads §1–§10, then:

1. Reviews §11 brainstorming choices — adopt defaults OR invoke
   `brainstorming` skill with CIO to refine
2. Authors `display-case.scad` top-level parameter block from §3 +
   §5 + §10 numbers
3. Authors `front_shell.scad` and `back_shell.scad` as separate
   modules
4. F6 render in OpenSCAD; iterate
5. Export STLs to `stl/`; commit `.scad` source (NOT large STL/PDF
   binaries) per repo conventions
6. File an A2AL to PM + Architect when ready for review (Atlas under
   PM Rule 10 if any aspect touches load-bearing surface — unlikely
   for a pure enclosure)

Done — geometry build can start without waiting on CIO.
