# Light Sensor Enclosure — Design Record v1

**Author:** Iris (UI/UX) · **Date:** 2026-06-16 · **Status:** DESIGN APPROVED (CIO interview) → building v1 STL

Houses the **Adafruit TSL2591 lux-sensor breakout (#1980)** as a dash-mounted
ambient-light sensor feeding the Pi display **auto-dim** (day/night + tunnel/garage
transitions). Part of the black-box / EDR build. Spool owns the sensor-side reality
(`inbox/2026-06-16-from-spool-edr-display-data-palette.md`): TSL2591 gives lux at
~1–2 Hz — plenty for dimming; optics + brightness curve are Iris's call.

## Authoritative board facts (Adafruit #1980 datasheet, last-page mech drawing)

Source: `datasheets/datasheet-1516629-adafruit-1980-1-pcs.pdf` p.22 (dims in INCHES → mm).

| Dim | inches | mm |
|---|---|---|
| Board overall W × H | 0.75 × 0.65 | **19.05 × 16.51** |
| Mounting-hole spacing (horiz c-c) | 0.55 | **13.97** |
| Mounting-hole Ø | 0.10 | **2.54** (≈ M2.5) |
| Hole inset from each side edge | 0.10 | **2.54** |
| Hole inset from top (mount) edge | ~0.10 | ~**2.54** |

6-pin 0.1″ header along one long edge: `Vin · 3vo · GND · SDA · SCL · Int`.
The TSL2591 chip (the light aperture) is surface-mounted on the top face.

## Design decisions (CIO interview 2026-06-16)

1. **Optics / cover** — a flat square of semi-hard plastic the CIO cuts himself
   (clear hard plastic OR translucent **milk-jug HDPE = built-in diffuser**),
   slides into **side grooves**. Swappable / consumable. Diffuser kills direct-sun
   hot-spots; auto-dim only needs *relative* brightness so a cheap diffuser is free.
2. **Slide cover (v4 U-channel — CIO fit-check 2026-06-16)** — the diffuser plate
   inserts through a **single mouth in the TALL/BACK wall** (high/mount edge) and
   rides a **3-sided U-channel of blind interior grooves on the LEFT, RIGHT and
   FRONT walls**; it **slides downhill and seats its front edge into the front
   groove** (the down-slope stop), held by **gravity + friction**. Only the back
   wall shows a slot; left, right and front outer faces stay clean. The tilt rises
   toward the back/mouth wall, so mounting that wall toward the glass gives both the
   windshield aim and gravity retention. (v2 had side grooves only + a butt stop;
   v4 adds the front groove so the channel actually captures the plate.) Groove
   sized by `lid_thickness` (default 1.5 mm + 0.3 clearance) — one number to retune
   to the chosen sheet.
3. **Form** — **one-piece shell**: closed flat bottom (VHB face, 0.5 mm recessed lip
   to hide tape edges), four walls, open top. Board drops in from the top, screws
   down, diffuser slides in to close.
4. **15° tilt — internal** — case bottom stays flat (full VHB contact; wedges peel
   in heat). Board is tilted 15° *inside*: two **printed screw standoffs** at the
   mounting-hole edge (the HIGH side) lift it; a **ledge** under the header edge (LOW
   side) supports it. Two screws + one support line = no rattle, no 4th fastener.
   Top wall rim cut at 15° so the diffuser sits parallel to the board → reads as an
   intentional wedge, professional look.
5. **Fastening** — M2.5 self-tapping into printed posts (Ø2.1 pilot). Heat-set inserts
   optional (CIO has the kit from enclosure #1) — swap `pilot_r`/post if desired.
6. **Cable** — 4-wire I2C (Vin, GND, SDA, SCL; skip Int + 3vo), soldered flat to the
   pads (low profile). Exits the **low/header-edge wall toward the passenger side**,
   rounded slot sized for **4–5 small wires** (~7 × 3.5 mm).
7. **Interior** — recommend matte black (black filament or paint) to kill stray
   internal reflections. Optical, not geometry.

## Print

| Param | Value | Note |
|---|---|---|
| Material | **PETG** (default) | proven on enclosure #1; in-car thermal margin. ASA better for UV/heat (CIO spec) but warp-prone — geometry identical, only tolerances differ. |
| Board clearance | **1.0 mm/side** | easy drop-in (CIO 2026-06-16); opening 21.05 × 18.51, outer 25.05 × 22.51 |
| Diffuser plate | `lid_thickness` **1.5 mm** | sized for 1.0–1.5 mm sheet; groove slot 1.8 mm |
| Wall thickness | 2.0 mm | durability + groove room |
| Layer height | 0.16–0.20 mm | |
| Walls / infill | 3–4 perimeters / 20–30 % | small part |

## Files

- `light-sensor-case.scad` — parametric source. `part`: 0 = assembly view,
  1 = shell (printable), 2 = diffuser plate template.
- `stl/shell.stl`, `stl/diffuser-template.stl` — render outputs.
- `renders/` — preview PNGs for CIO review.

## Open (pending CIO physical fit-check of v1 print)

- Diffuser plate thickness (`lid_thickness`) — confirm against the material he cuts.
- Cable clearance under header edge (`cable_clr`) — enough room for solder + 5 wires?
- 15° aim — does it sit/aim right on his actual windshield-base location?
- Standoff height / board seating — does the board sit flat on posts + ledge?
- Profile height acceptable (tilt adds ~4.3 mm to the high side).
