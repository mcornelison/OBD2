# 3D printing — project reference

**Single source of truth for this project's 3D-printing hardware, toolchain and
design rules.** Consolidated 2026-08-20 (CIO direction: project-shared information
lives in a shared location, one version of the truth). Previously scattered across
`offices/uidevloper/knowledge/` and `offices/uidevloper/enclosure2/3dprinter.md`.

Everything here is **read-on-demand** — load the file you need, not the folder.

| File | Load it when | Owns |
|---|---|---|
| `printer-and-materials.md` | Before slicing anything, or choosing a filament | Prusa i3 MK3S+ specs, build volume, PLA-vs-PETG rationale (in-car parts need PETG — PLA softens ~55-60 °C on a sun-loaded dash), PrusaSlicer version, the **validated black-PLA profile** (0.15 mm, 3 perimeters, 4 mm outer brim, rear seam) |
| `first-print-guide.md` | Setting up a print, or a print is failing to stick | MK3S+ first-print walkthrough + the bed-adhesion recipe (soap-clean smooth PEI, 5 mm brim, bed 60-65 °C, **fan off first 3 layers**, no drafts) |
| `debug-xyz-calibration.md` | XYZ calibration fails, or first-layer geometry is wrong | Calibration failure modes and what each one actually indicates |
| `slicing-cli.md` | Slicing without opening the GUI | `prusa-slicer-console.exe` invocation. **Extract each part's OWN profile from its `.3mf`** (`Metadata/Slic3r_PE.config`) — do not cross-use another part's ini. The display case needs supports + no brim; the flat sensor boxes need brim + no supports. Wrong profile = failed print. |
| `openscad-cli.md` | Rendering an OpenSCAD part from the command line | Headless render/export, and the **numeric `part` selector** trick — string-valued `-D` args get mangled crossing PowerShell → Windows arg parsing |
| `design-flat-base-and-orientation.md` | Designing any part that must stick to the bed | Flat-base rule + print orientation. **Rule 4: delete the bad artifact.** A recessed-bottom STL sat next to a good one under a friendlier filename and got printed six times; the durable fix is removing the trap file, not adding a good file beside it |
| `design-tilted-feature-shear.md` | Cutting a feature into a wall of a tilted body | A groove cut board-parallel inside a tilted frame shears through the outer face. Cut world-aligned |

## Related, elsewhere

- **Hardware specs** (Pi, UPS, sensors, display electrical) → `docs/hardware-reference.md`
- **OSOYOO display mechanical dimensions** (PCB, glass, mount-hole rectangle) →
  `offices/uidevloper/enclosure1/datasheets/2024009100-extracted-facts.md` — kept beside the
  vendor PDF and the extraction scripts that produced it, so any figure can be re-derived
- **Enclosure sources + STLs + gcode** → `offices/uidevloper/enclosure1|2|3/`
- **Iris's design-process lessons** (how she works, not how the printer works) →
  `offices/uidevloper/knowledge/`
