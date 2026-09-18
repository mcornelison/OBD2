# Display case — OSOYOO 3.5" 480x320 Pi display

Two-shell snap-together case for the **display only** (the Pi was removed from scope by the
CIO, 2026-05-22). Was `enclosure1/`.

**Current: v2.8** (`src/display-case.scad`). Printed by the CIO; **physical fit-check open.**

| Print this | |
|---|---|
| `stl/back_shell.stl` | main shell |
| `stl/front_shell.stl` | bezel/front |
| `stl/plunger.stl` | button plunger |

Spec [`specs/display-case-spec.md`](specs/display-case-spec.md) - changelog
[`specs/display-case-v2.1-notes.md`](specs/display-case-v2.1-notes.md).

## Corrected facts - each one cost a print to learn

- **PCB is 85 x 56 mm.** The datasheet's "49" is the mount-hole vertical centre-to-centre,
  **not an edge dimension**.
- **Mount holes form a RECTANGLE**, 58 mm horizontal c-c x 49 mm vertical.
- 🔴 **The glass sits ~4 mm off the mount-hole centre.** A standoff-placed screen missed the
  window and the lid would not snap. `pcb_shift_x = 4.0` re-registers it.
- 🔴 **The board installs Y-FLIPPED from the model's assumption**, because the mounts are
  Y-symmetric and nothing in the geometry disambiguates it.
- 🔴 **The CIO measures from the GLASS surface edge, not the PCB edge** - 2.3 mm apart. Every
  clearance he quotes uses that datum.
- **90-degree micro-HDMI needs ~18 mm** from the glass edge; `clearance_top` is 18.0 for a
  21.5 mm glass-edge-to-wall gap.
- Both Type-C and the left-turning micro-HDMI exit **one** left-wall opening.

⚠️ **The CIO's photographs are taken FRONT-view (screen facing him); the model's frame is
BACK-view.** X is mirrored between them. Getting this wrong reverses every left/right call -
see `photos/` and the extracted-facts note in `datasheets/`.

`datasheets/2024009100-extracted-facts.md` is the authority for mechanical dimensions, not
the vendor PDF prose.
