# Enclosures — 3D-printable cases for the Eclipse OBD-II hardware

Design artifacts for the three printed enclosures. Owner: **Iris (UI/UX)**; the CIO prints
and fit-checks them. Landed here 2026-09-18 at the CIO's direction — before that they lived
only on the fleet share, which has **no git, no snapshots and no undo**.

| Case | Houses | Current | State |
|---|---|---|---|
| [`case-display-osoyoo-3.5in/`](case-display-osoyoo-3.5in/) | OSOYOO 3.5″ 480×320 display | **v2.8** | printed; fit-check open |
| [`case-light-sensor-tsl2591/`](case-light-sensor-tsl2591/) | Adafruit TSL2591 lux breakout #1980 | **v6.3** | printed; fit-check open |
| [`case-imu-icm20948/`](case-imu-icm20948/) | Adafruit TDK ICM-20948 9-DoF IMU | **v5** | v4 printed OK; v5 awaiting print |

⚠️ These were `enclosure1/`, `enclosure2/` and `enclosure3/` until 2026-09-18. Older notes
use the numbered names; the table above is the mapping. A search for the old names returns
nothing, which reads like the work is missing — it is not.

## Layout — the same in every case folder

| Folder | What | Regenerable? |
|---|---|---|
| `src/` | **`.scad` parametric source — the only authored geometry** | **no, this is the original** |
| `specs/` | design spec, changelog, verification logs | no |
| `datasheets/` | vendor PDF + extracted-facts notes | no |
| `photos/` | CIO fit-check photographs | **no — irreplaceable evidence** |
| `stl/` | printable geometry | yes, from `src/` |
| `print/` | `.3mf` model files | yes, from `stl/` |
| `renders/` | `.png` | yes, from `src/` |
| `tests/` | verification harnesses + slice scripts | no |

**Everything derives from `src/`.** A 14 KB `.scad` generates ~5 MB of STL. If you change
geometry, change the `.scad` and regenerate — never hand-edit an STL.

## What is deliberately NOT here

- **`.gcode`** — sliced for the **retired MK3S+/PrusaSlicer**. The CIO prints on a **Bambu
  Lab P2S** (arrived ~2026-08-10). It regenerates from the STL, and a stale sliced file is
  exactly what cost six failed prints on the light-sensor case: the `.gcode` had been cut
  from an obsolete STL carrying a 0.5 mm recess, so only the perimeter touched the bed.
  Keeping it would import that trap.
- **`*-shell.stl`** — `part=6/7` debug intermediates, never printable (3.6 MB).
- `.obj` duplicates of kept STLs, the retired MK3S+ slicer profile, build noise.

## Regenerating

```bash
SCAD="/c/Program Files/OpenSCAD/openscad.exe"
"$SCAD" -o stl/v5-base.stl      -D part=1 src/imu-case-v5.scad
"$SCAD" -o stl/v5-lid-print.stl -D part=4 src/imu-case-v5.scad
python tests/verify_v5_deltas.py
```

⚠️ Paths in the `.scad` headers and the test harnesses assume the **flat working layout on
the share** (`stl/`, `specs/` beside the `.scad`), not the `src/` split used here. Run them
from a share working copy, or adjust the paths. **The organisation here is for finding
things; the share is where they are built.**

## Slicing

The **Bambu Studio CLI does not work on the CIO's PC** — exit `-3` with the profile chain,
`0xC0000005` without. Slice in the GUI. Four settings the CLI could never have set anyway:

1. **bed plate** — the profile defaults to Cool Plate 35 °C; pick the one installed.
2. **base: no supports, Arachne walls** — the IMU case's spring fingers are thinner than two
   0.42 mm extrusion lines.
3. **lid: tree supports, support BLOCKERS painted on the sockets, brim.** Support left in a
   socket stops the lid seating.
4. `print/*.3mf` here are **model** 3MFs (geometry + mm units), **not sliced projects** —
   no profile, no layer count, no print time.
