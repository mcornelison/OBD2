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
3. **Apply adhesion/finishing overrides in the ini** (more reliable than CLI flags):
   `support_material = 0`, `brim_width = 5`, `brim_type = outer_only`,
   `disable_fan_first_layers = 3`, `seam_position = rear`.
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
