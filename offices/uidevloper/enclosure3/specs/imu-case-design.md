# IMU Enclosure (#3) — Design Record v1

**Author:** Iris (UI/UX) · **Date:** 2026-06-17 · **Status:** DESIGN APPROVED (CIO interview) → building v1

Houses the **Adafruit TDK InvenSense ICM-20948 9-DoF IMU** breakout as part of the
Pi-5 black-box / EDR build. Spool's 2026-06-16 note wants the IMU as a live g-meter
(lateral + longitudinal g) + road grade — an **orientation-sensitive** instrument, so
the case mounts rigidly and encodes a forward-axis reference.

## Authoritative board facts (ICM-20948 datasheet Fab Print, last page, dims in INCHES)

Source: `datasheets/adafruit-tdk-invensense-icm-20948-9-dof-imu.pdf` p.18.

| Dim | inches | mm |
|---|---|---|
| Board overall (L × W) | 1.00 × 0.70 | **25.40 × 17.78** |
| Mounting-hole c-c (horiz × vert) | 0.80 × 0.50 | **20.32 × 12.70** |
| Hole inset from each edge | 0.10 | **2.54** |
| Holes | **4 corners** | ~M2.5 (Adafruit standard — confirm at fit-check) |

Standard Adafruit 1.0×0.7″ breakout: 0.1″ header on one long edge + STEMMA QT on the
short ends.

## Design decisions (CIO interview 2026-06-17)

1. **Clearance** — **5.0 mm on all sides** of the board (CIO 2026-06-17, for wire
   routing room) → interior ≈ 35.4 × 27.78 mm, outer ≈ 39.4 × 31.78 mm.
2. **Flat, no tilt** — board lies parallel to the dash/mount surface.
3. **4 mounting standoffs** — one printed post per corner hole (c-c 20.32 × 12.70),
   board screws down with **M2.5 self-tapping** into Ø2.1 pilots. Rigid = clean
   accel/gyro.
4. **Snap-on lid** — perimeter lip that drops into the box + a snap rib/catch that
   clicks into a groove in the inner wall. Tool-free, holds under vibration.
5. **Mount + orientation** — **VHB flat bottom** (0.5 mm tape-recess lip) + a molded
   **FRONT arrow** on the lid so the board's axes map to the car.
6. **Vents** — thin rounded-end slots like enclosure #2: 3 on one long wall, 2 on each
   short wall.
7. **Wire exit** — rounded (obround) slot on the long wall opposite the vents,
   **11 × 5 mm** (`cable_w` 7→10 v3, →11 v3.1 2026-07-31 so the wiring **connector**
   passes through, not just the wires). Lowered + made taller (CIO 2026-06-17) so it drops into the
   under-board/side gap (z ~2.5–7.5) and wires aren't blocked by the board.
8. **Lid markings** — debossed **FRONT arrow** (+X) + **"ICM-20948"** label.
9. **External mounting tabs (v3.2, CIO 2026-08-12)** — **4 screw-down ears, one per
   corner**, so the case can be fastened to wood, plastic, or metal (as well as, or
   instead of, the VHB base).
   - **Placement, per the CIO's framing:** the tabs **extend on the SHORT sides** and
     are **flush with the long lengthwise sides**. In model terms — since **+X is the
     board long axis** — they project in **±X past the end walls**, and their outer Y
     edges land exactly on the `y=0` / `y=case_y` planes. **The footprint therefore
     grows in length only: 39.4 × 31.78 → 59.4 × 31.78 mm** (Z unchanged at 15.6).
   - **Tab** 10 (projection) × 10 (width) × **5 mm thick**, outer corners r2.
   - **Screws: M3 / #6, countersunk** — Ø3.4 through + **90° cone opening to Ø7.0**
     at the tab face (CIO chose countersink over counterbore: *truly flush*, nothing
     protrudes). Cone depth = (7.0−3.4)/2 = **1.8 mm**, leaving **3.2 mm of land**
     below it — deliberate margin, because a shallow cone in thin PLA can split when
     over-torqued. Hole centers are 5.0 mm from the end wall and 5.0 mm from the tab
     tip (centered), which also keeps a driver clear of the 15.6 mm wall.
     *90° suits an M3 machine screw exactly; a #6 wood screw (82°) seats on the upper
     rim of the cone — the standard compromise for a hole meant to take both.*
   - **Tabs are COPLANAR WITH THE FLAT BOTTOM** (z = 0…5). Two reasons: the case sits
     flat against whatever it is screwed to (no rocking on a proud ear), and the added
     footprint is free bed adhesion on a printer that has fought adhesion on this
     family of parts. Verified in the STL: lowest Z = 0.000 and the Z=0 vertices span
     the full −10…49.40 in X.
   - **Short-wall vents moved inboard** `case_y*[1/3, 2/3]` → `case_y*[0.40, 0.60]`
     (y 10.59/21.19 → 12.71/19.07). At the old spacing the vent cut clipped a tab's
     inner top corner by 0.06 mm — below print resolution, so it would not have shown
     in this print, but it was a latent trap for any future `tab_w` increase.
     **Constraint to preserve: `tab_w < case_y*0.40 − vent_w/2` (= 12.06).**

## Print (carry-over from enclosure #2 / `enclosure2/3dprinter.md`)

PLA for prototype/fit-check (incl. snap-fit tuning); **PETG/ASA for the in-car part**.
MK3S+, 0.4 mm nozzle, 0.15 mm layers, 3 perimeters. Bottom-down, supports on build
plate only (for the VHB recess); lid prints flat-face-down separately.

## Files

- `imu-case.scad` — parametric source. `part`: 0 = assembly · 1 = box · 2 = lid
  (in-place, for assembly) · 3 = cross-section · **4 = lid in PRINT orientation
  (top-face-down)**.
- `stl/box.stl` (flat bottom) · `stl/lid.stl` (in-place) · **`stl/lid-print.stl`**
  (top-face-on-bed — slice THIS one; printing the lid lip-down bridges the whole top).
- `slicer/box.gcode`, `slicer/lid.gcode` — MK3S+/PLA gcode (CLI-sliced). **Box re-sliced
  v3.2: 1 h 22 m / 9.85 g** (was 1 h 04 m / 8.12 g — the four ears cost ~1.7 g); first
  layer at Z=0.20 confirms the flat base in the gcode itself. **Lid unchanged — do not
  re-slice it.** Config = `slicer/mk3s-pla.ini` (CIO's profile from his .3mf + adhesion
  overrides: supports off, 5 mm brim, fan off first 3 layers, rear seam).
- `renders/` — preview PNGs.

## Print orientation
- **Box:** flat bottom on the bed (open top up), support-free.
- **Lid:** **top face on the bed** (`lid-print.stl`) — solid top plate prints as the
  first layer (no bridging, stable, smooth top); lip + snap rib point up.

## Open (pending CIO render review + physical fit-check)

- Hole Ø (assumed M2.5) — confirm.
- Snap-fit tuning (`lid_clear`, `snap_d`) — dial in on the PLA print.
- Component clearance above board (`comp_clear`) — enough for STEMMA connectors +
  soldered wires?
- FRONT arrow direction + wire-exit wall — confirm orientation vs how it mounts.
