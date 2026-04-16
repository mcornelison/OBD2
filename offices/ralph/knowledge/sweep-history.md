# Reorg Sweep History — Ralph Reference

Load ONLY when referencing prior reorg work. Not needed for normal development.

## Summary
B-040 Structural Reorganization — 6 sweeps, all merged to main, pushed to origin.
- **S1** (21029e8): 18 facades deleted, shutdown subpackage
- **S2a** (418b55b): AlertManager rewired to tieredThresholds; RPM=7000
- **S2b** (d65d52f): Legacy threshold dead-code delete. B-035 filed.
- **S3** (b2be378): Physical tier split (src/pi/, src/server/, src/common/)
- **S4** (f1237b8): Config restructure, config.json at repo root, tier-aware shape
- **S5** (8413c82): Orchestrator 2501→9-module mixin package; 11 src splits; 73 test files
- **S6** (6af8e9a): camelCase enforcement, README finalization, archive reorg specs

## Key Facts
- Test baseline held exact: 1469 fast / 1487 full (from Sweep 4 forward)
- Spool values byte-for-byte preserved across all sweeps
- Archive at `docs/superpowers/archive/` (design doc + 9 plan files)
- Size exemptions documented in `src/README.md` (79 files) and `tests/README.md` (26 files)
- 4 pre-existing ruff errors on main (untouched per invariant): ollama.py UP041, test_remote_ollama I001/UP041/F841
- Sprint branches retained locally; delete around 2026-04-21
