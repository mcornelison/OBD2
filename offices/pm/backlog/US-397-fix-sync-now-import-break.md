---
id: US-397
title: "Fix sync_now.py import break -- normalize Pi entry-point to pi.*-on-src convention"
type: issue
parent: F-076
epicId: E-002
size: S
status: sprint-ready
sourceRefs: [F-076, prd-V0.29.2, I-sync-now-import-broken]
created: 2026-06-29
---

# US-397 — Fix sync_now.py import break (bug)

## Context

Found during the V0.29.1 deploy. `scripts/sync_now.py` inserts the repo ROOT on
`sys.path` + imports `src.pi.*`, but `src/pi/obdii/__init__.py:26` uses bare
`from pi.display import ...` (the `pi.*`-on-`src/`-path convention the services run
under) → `ModuleNotFoundError: No module named 'pi'`. The manual sync CLI can't run
without a PYTHONPATH workaround. BENCH-ONLY validation.

## Goal

As the operator, I want `python scripts/sync_now.py` to run on the Pi so I can
trigger a manual sync without a PYTHONPATH workaround.

## Definition of Done

- `sync_now.py` follows the project Pi-tier convention ([[feedback-path-convention-no-src-prefix]]): put `src/` on `sys.path` + import `pi.sync` / `pi.data` (matching the services), NOT ROOT + `src.pi.*`
- it imports + runs on the Pi with no PYTHONPATH override
- **batch-audit** other Pi-side `scripts/*.py` entry points for the same ROOT-insert + `src.pi.*` pattern; fix the cluster (Rule 5 batch)

## Validation Criteria (bench)

- (on the Pi, `python scripts/sync_now.py --dry-run`) → (runs, no `ModuleNotFoundError`)
- (run an import/smoke test covering the `sync_now.py` and any sibling entry-point import under the service convention) → (passes)

## Conditional Outcomes

- if 3+ scripts share the bug, fix all in this one story (batch)
- if a script genuinely needs the ROOT/`src.pi.*` convention (server-side), leave + document

## Notes

Independent of the F-103 chain (US-393..396). Issue ref:
`offices/pm/issues/I-sync-now-py-import-broken-on-pi.md`.
