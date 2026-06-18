---
name: pattern-flat-base-and-print-orientation
description: Design enclosure bottoms FLAT (not recessed) for bed adhesion, and orient parts so the solid/show face is on the bed; a part that releases mid-print is warping/small-contact, not live-Z
metadata:
  type: pattern
---

Two linked rules learned helping the CIO (new to 3D printing) get enclosures to
actually print on his MK3S+ (2026-06-17).

## 1. Design the bottom FLAT — recesses kill bed adhesion
A VHB tape-recess (a shallow pocket in the bottom face) seems harmless but, printed
bottom-down, **only the thin perimeter lip-ring touches the bed**. Measured on the
light-sensor case: the lip-ring is **~24 % of the footprint** (133.7 vs 563.9 mm²).
Adhesion force scales with contact area, so a recessed bottom has ~1/5 the grip and
**lets go mid-print** as the part grows taller (warping/shrinkage overcomes the small
hold). VHB tape sticks fine to a flat face anyway, so default to a **flat bottom**
(parameterize the recess `= 0`). This single change ~5×'d the grip on both enclosures.

## 2. Diagnose mid-print release correctly
**A part that prints ~45 min and THEN breaks loose is NOT a live-Z / first-layer
problem** — those fail at layer 1. If the user has calibrated live-Z repeatedly and it
still releases mid-print, stop chasing live-Z. It's **warping / corner-lift on a small
contact area**, usually plus a greasy bed. Fix order (MK3S+ / PLA):
1. Flat full-contact bottom (rule 1).
2. **Clean the smooth/satin PEI sheet with dish soap + warm water** (removes finger-oil
   that IPA can't); handle the sheet by the edges only. #1 beginner cause.
3. **5 mm brim.**
4. Bed 60 °C (try 65 if corners lift); keep printer out of drafts.
5. **Disable part-cooling fan for the first 3 layers** (fan curls small-part edges up).
Escalation: mouse-ear corner tabs, draft shield.

## 3. Orient each part so its flat/show face is on the bed
- **Box / tray:** flat bottom on the bed, open top up — support-free.
- **Lid:** **top face DOWN on the bed.** The solid top plate becomes the first layer
  (no bridging across the lid interior, stable, and the smooth PEI gives the show face
  + debossed text/arrow a clean finish). Printing a lid lip-down makes the top plate
  bridge the whole opening → PrusaSlicer warns "long bridging extrusions."
- Model the print orientation explicitly as its own `part=N` in the SCAD (e.g. lid
  rotated 180° about X, dropped onto the bed) rather than relying on slicer rotate
  flags — see [[pattern-prusaslicer-cli-slicing]].

Related: [[reference-mk3s-plus-first-print-guide]], [[reference-cio-3d-printing-setup]],
[[pattern-openscad-cli-numeric-part-selector]].
