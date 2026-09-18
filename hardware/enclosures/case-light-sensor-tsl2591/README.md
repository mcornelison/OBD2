# Light-sensor case - Adafruit TSL2591 lux breakout #1980

One-piece shell with a gravity-slide diffuser. Feeds the display's auto-dim. Was
`enclosure2/`.

**Current: v6.3** (`src/light-sensor-case.scad`). Printed by the CIO; **fit-check open.**

| Print this | |
|---|---|
| `stl/shell.stl` | one-piece shell, **flat bottom**, 5 mm brim, bed 60 C, fan off 3 layers |
| `stl/diffuser-template.stl` | diffuser cutting template |

Spec: [`specs/light-sensor-case-design.md`](specs/light-sensor-case-design.md).

## 🔴 The bed-adhesion saga - the reason this repo carries no .gcode

The CIO's print released ~15 minutes in, on his **sixth attempt**. It was read as a recipe
problem for weeks. It was not.

Diagnosed by parsing STL vertices: `shell.stl` carried a **0.5 mm VHB recess**, so its lowest
Z was `[0.0, 0.5, 2.0...]` - **only the perimeter lip ever touched the bed.** The floor sat
0.5 mm above it.

**The trap was a FILE, not a setting.** A friendlier-named `light_sensor_enclosure.gcode` had
been sliced from that recessed STL, and it was what kept getting printed. The fix removed the
recess, regenerated the STL flat (verified `[0.0, 2.0...]`), re-sliced **one** gcode, and
**deleted the recessed twin** so it could not be picked up again.

⇒ **Rule: delete the trap file.** Leave exactly one printable per part. It is also why no
`.gcode` was carried into this repo at all - every file here was sliced for the retired
MK3S+, and the CIO now prints on a Bambu Lab P2S.

## Design facts

Board tilted **15 degrees internally**; 2x M2.5 standoffs plus a header ledge; diffuser
gravity-slides into a **3-sided interior U-channel** with a world-aligned front groove (a
tilted groove shears); passenger-side wire exit; vents 3 tall plus 2 angled.
Datasheet-grounded at 19.05 x 16.51 mm.
