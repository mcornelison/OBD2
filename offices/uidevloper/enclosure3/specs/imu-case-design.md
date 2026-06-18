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

1. **Clearance** — **2.0 mm on all sides** of the board → interior ≈ 29.4 × 21.8 mm.
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
7. **Wire exit** — rounded slot for **4–5 wires** (~7 × 3.5 mm) on the long wall
   opposite the vents, kept clear of the FRONT axis.

## Print (carry-over from enclosure #2 / `enclosure2/3dprinter.md`)

PLA for prototype/fit-check (incl. snap-fit tuning); **PETG/ASA for the in-car part**.
MK3S+, 0.4 mm nozzle, 0.15 mm layers, 3 perimeters. Bottom-down, supports on build
plate only (for the VHB recess); lid prints flat-face-down separately.

## Files

- `imu-case.scad` — parametric source. `part`: 0 = assembly · 1 = box · 2 = lid ·
  3 = cross-section.
- `stl/` — render outputs. `renders/` — preview PNGs.

## Open (pending CIO render review + physical fit-check)

- Hole Ø (assumed M2.5) — confirm.
- Snap-fit tuning (`lid_clear`, `snap_d`) — dial in on the PLA print.
- Component clearance above board (`comp_clear`) — enough for STEMMA connectors +
  soldered wires?
- FRONT arrow direction + wire-exit wall — confirm orientation vs how it mounts.
