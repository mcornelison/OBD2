# Display Case — v2.1 rebuild notes (2026-05-29)

Companion to `display-case-spec.md` (v1). Source: `display-case.scad`.
Facts: `datasheets/2024009100-extracted-facts.md`. Renders: `renders/v21_*.png`.

v2.1 is a **datasheet-driven rebuild** triggered by CIO's v1 print fit-check
(2026-05-28) and the official 2024009100 datasheet (2026-05-29).

## Frame (model ↔ CIO's measuring frame)

Model is built in the datasheet landscape frame, viewed from the BACK:

```
        +Y = TOP long edge (micro-HDMI / brightness / power)   <- +6mm clearance
   X=0 ────────────────────────────────────────────────── +X
  LEFT  |                                                 |  RIGHT short edge
 short  |               (back of display)                 |  (OSOYOO logo)
  edge  |                                                 |
(Type-C)|                                                 |
   ↑    ────────────────────────────────────────────────
 +6mm           Y=0 = BOTTOM long edge
        Z=0 = outer back face;  +Z = front / bezel
```

## CIO fit-check items (v1 → v2.1)

| # | Request | Implementation |
|---|---------|----------------|
| 1 | Tabs/slots didn't align | Clip finger centered on its width axis (`snap_clip_finger`); long-edge pairs at thirds, short-edge singles at center; front-shell slots already centered → they track. |
| 2 | Mount posts didn't align | Real datasheet **trapezoid** holes (top c-c 50, bottom c-c 58, 3.5 mm edge insets). |
| 3 | Drop the button | Plunger part + pocket removed. |
| 4 | Add 2 button holes | Ø3.5 back-face holes, 6 & 16 mm from LEFT edge, flush with TOP edge. |
| 5 | Cable exit too small | Opening height → 14 mm (passes connector bodies); on the TOP/HDMI wall. |
| 6 | +6 mm taller & wider | **Asymmetric**: +6 mm on TOP (+Y, HDMI) and LEFT (X=0, Type-C) only; display sits off-center; bezel thicker on those two sides. |
| 7 | Vents vs solid mounts | Vents are a filtered grid that auto-leaves solid rings around all 4 seats + the magnet pad. |
| — | 10 mm metal standoffs (CIO's own) | No printed posts — flush **countersunk M2.5 clearance holes** + 2 mm reinforcement pad + Ø6.6 locating recess per seat. Case depth grows to seat them (~19 mm external). |
| — | "Screen hole fit perfectly — don't change it" | Front window **FROZEN** at v1 size (94.04 × 60.6); the +6 mm grows the case around it, not the window. |

## Key parameters (in `display-case.scad`)

- `clearance_top = 6` (+Y), `clearance_left = 6` (X=0)
- `pcb_x = 85`, `pcb_y = 49`; `pcb_shift_x/y = 0` (PCB centered behind glass)
- Trapezoid hole knobs: `mh_top_left_x 28.5 / mh_top_right_x 78.5 / mh_bot_left_x 23.6 / mh_bot_right_x 81.6`, `mh_from_top/bottom = 3.5`
- Standoff seat: `standoff_h 10`, `seat_screw_d 3.0` (M2.5 clear), `seat_cs_*` countersink, `seat_reg_*` locating recess
- `glass_cutout_x/y` = 94.04 / 60.60 (FROZEN)

Both shells render manifold (`Simple: yes`): back 2437 facets, front 62.

## OPEN — verify on CIO's physical fit-check before final print

1. **Orientation** — connectors on TOP (+Y, HDMI) + LEFT (X=0, Type-C). Confirm vs real board.
2. **PCB centered behind glass** (`pcb_shift = 0`). CIO gaps hinted ~3 mm right; bump if screen sits off-window.
3. **Cable exit on the TOP wall** — confirm vs. preferring the LEFT (Type-C) wall.
4. **M2.5 screws** for the standoffs (datasheet confirms M2.5 thread).
5. **Depth stack** — `pcb_thick`/`glass_thick` estimated; confirm the glass meets the bezel on a test print.

## v2.2 (2026-05-29, CIO review round 2)

- **Cable exit moved** from the top (+Y/HDMI) wall to the **LEFT (X=0) wall,
  centered on the PCB short-edge midpoint** to align with the Type-C port.
  (`cable_slot_cy = pcb_origin_y + pcb_y/2`; cut through the X=0 wall.)
- **Standoff seats rebuilt as real HEX SOCKETS**: each seat is a raised cup
  (`seat_cup_d ~9.4`, `seat_cup_h 4.5`) with a `seat_pocket_depth 3` **hex
  pocket** (`seat_pocket_af = standoff_af + 0.5`) the hex standoff drops into
  and rests — anti-rotation when driving the case-back screw — plus the M2.5
  through clearance hole + flush countersink. v2.1's 0.6 mm skim recess is gone.
  `standoff_af = 5.0` (M2.5 standard across-flats); **datasheet only specs the
  M2.5 thread**, so this is the one number to confirm against the physical part.
- **Orientation cue blocks removed** from the assembly view — the red marker on
  the +Y rim read as a phantom 3rd clip. Real clip count is unchanged: **2 per
  long edge, 1 per short edge** (6 total).
- Depth stack updated: PCB rides on the standoff resting in the pocket
  (`pcb_back_z = wall_t + seat_cup_h + (standoff_h - seat_pocket_depth)`).

## File inventory (this folder)

- `display-case.scad` — v2.1 parametric source (single file, `part` selector)
- `display-case-spec.md` — v1 spec (still the long-form reference)
- `display-case-v2.1-notes.md` — this file
- `stl/back_shell.stl`, `stl/front_shell.stl` — v2.1 printable parts (regenerated)
- `stl/plunger.*` — OBSOLETE (plunger removed in v2; do not print)
- `renders/v21_back.png`, `renders/v21_assembly.png` — v2.1 visualization
- `datasheets/` — official PDFs + extracted facts + extraction scripts + `pcb_zoom.png`
