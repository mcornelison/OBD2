---
name: pattern-prusaslicer-cli-slicing
description: Slice STL->gcode from the CLI using prusa-slicer-console.exe + a config extracted from the CIO's .3mf (so the gcode carries his real MK3S+ machine profile)
metadata:
  type: pattern
---

I can produce correct, printer-ready `.gcode` for the CIO from the command line —
no need for him to slice by hand. Proven 2026-06-17 (enclosure #2 + #3 parts).

**The exe:** `C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe` (the
*console* variant — `prusa-slicer.exe` is the GUI). Call it from the Bash (git-bash)
tool with the Windows path quoted.

**The hard part is the PROFILE, not running the slicer.** Guessing machine settings
produces gcode that won't run right (wrong start/end gcode, mesh leveling, live-Z,
temps). The fix: the CIO's own `.3mf` project **embeds his full dialed-in config** at
`Metadata/Slic3r_PE.config`. Extract that and slice against it → gcode comes out as if
he'd sliced it himself, MK3S+ machine settings and all.

**Extract the TARGET part's OWN `.3mf` profile — do NOT cross-use another part's ini.**
Different enclosures legitimately carry different print profiles, and the differences are
print-critical, not cosmetic. Proven 2026-06-26: the **display case** (`enclosure1`) embeds
**supports ON + brim 0 + 2 perimeters**, while the **flat sensor boxes** (`enclosure2/3`)
use **supports OFF + brim 5 + 3 perimeters**. Slicing the display case with the flat-box
ini would print its snap-clips/overhangs **without support** → failed part. So: per part,
unzip *that part's* `.3mf` and reproduce *its* config. When a folder has a stray ini that
doesn't match the part (e.g. a copied flat-box recipe sitting next to the display case),
treat it as a trap file — surface it / don't slice from it. Always confirm
`filament_type`, `support_material`, and `brim_width` in the extracted profile before you
slice — those three are the ones that bite.

**How to apply:**

1. A `.3mf` is a zip. Extract the config and strip the gcode-comment prefix (it's
   stored as `; key = value` lines, which `--load` won't parse):
   ```python
   import zipfile
   raw = zipfile.ZipFile('x.3mf').read('Metadata/Slic3r_PE.config').decode()
   d = {}
   for line in raw.splitlines():
       s = line[2:] if line.startswith('; ') else line
       if '=' in s:
           k, v = s.split('=', 1); d[k.strip()] = v.strip()
   # apply any overrides here, then write 'key = value\n' lines to config.ini
   ```
2. Slice each STL:
   ```bash
   PS="/c/Program Files/Prusa3D/PrusaSlicer/prusa-slicer-console.exe"
   "$PS" --export-gcode --load config.ini --output out.gcode input.stl
   ```
3. **Apply adhesion/finishing overrides in the ini** (more reliable than CLI flags) —
   but these are **part-specific, not universal**. The flat-bottom sensor boxes want
   `support_material = 0`, `brim_width = 5`, `brim_type = outer_only`,
   `disable_fan_first_layers = 3`, `seam_position = rear`. The display case wants
   `support_material = 1`, `brim_width = 0` (it has overhanging clips). Prefer the
   values already in the part's own extracted profile over a remembered recipe.
4. **Print estimate** lives in the gcode: grep `estimated printing time (normal mode)`
   and `filament used [g]`.

**Gotchas:**
- The input `.scad`/`.stl` path is relative to the *cwd* — `Can't open input file` means
  you're in the wrong dir (the office root vs the `enclosureN/` subdir). Use full
  relative paths from cwd.
- CLI transform flags (`--rotate-x 180 --ensure-on-bed`) are unreliable for
  re-orienting — they didn't reliably flip a lid. Better to model the print
  orientation in OpenSCAD (a dedicated `part=N`) and slice that. See
  [[pattern-flat-base-and-print-orientation]].
- Always tell the CIO to **preview each gcode** (PrusaGCodeViewer / drag into
  PrusaSlicer) before printing — CLI slicing is legit but he feeds it to hardware.

Related: [[pattern-openscad-cli-numeric-part-selector]] (the SCAD->STL half of the
toolchain), [[reference-mk3s-plus-first-print-guide]], [[reference-cio-3d-printing-setup]].
