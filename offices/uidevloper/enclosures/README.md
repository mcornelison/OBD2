# enclosures/

3D-printable enclosure design — source (.scad), exports (.stl/.3mf),
and renders.

## Active work

| Item | Status | Primary doc |
|---|---|---|
| OBD2 Display Case (OSOYOO 3.5" v3.0) | **v1 STL rendered 2026-05-22** — awaiting print + fit-check | [display-case-spec.md](display-case-spec.md) |

## v1 deliverables

- Source: `display-case.scad` (parametric, single file)
- STLs: `stl/back_shell.stl`, `stl/front_shell.stl`, `stl/plunger.stl`
- Preview: `renders/assembly.png`
- Render commands (run from this folder):

```powershell
$o = "C:\Program Files\OpenSCAD\openscad.exe"
& $o -o stl/back_shell.stl  -D part=1 display-case.scad
& $o -o stl/front_shell.stl -D part=2 display-case.scad
& $o -o stl/plunger.stl     -D part=3 display-case.scad
```

To iterate: edit parameters at the top of `display-case.scad`, re-run
the render commands. STLs regenerate from source — don't edit STLs
directly.

## Future work

- Pi 5 + UPS HAT enclosure — separate, lives wherever in the car the
  Pi gets mounted. Not the display case's concern.

## Folder conventions

- `*.scad` — OpenSCAD source. Authored here, render to STL via F6 or
  command-line.
- `stl/` — Exported STL files for the slicer.
- `renders/` — PNG renders for documentation/review.
- `*-spec.md` — Per-enclosure build specifications. Each `.scad` file
  derives its parameters from the corresponding spec doc.

Commit `.scad` source. Large `.stl` exports are gitignore'd by default
(re-render from .scad); commit specific STL versions only when shipping
a print-ready release.
