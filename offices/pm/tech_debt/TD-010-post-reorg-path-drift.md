# TD-010: Post-Reorg Path Drift Cleanup

**Priority**: Medium
**Status**: Open
**Category**: Infrastructure
**Related**: B-040 (Structural Reorganization)
**Filed**: 2026-04-15 (from Ralph Sweep 6 exit report)

## Description

Several files outside the codebase proper still reference pre-reorg paths (`src/main.py`, `src/obd_config.json`). These were explicitly out of Sweep 6's scope per invariant #6 (no bug fixes unrelated to structural correctness) and process optimization #14 (scope escape hatch).

## Affected Files

| File | Lines | Issue |
|---|---|---|
| `Makefile` | 72, 75 | `python src/main.py` / `--dry-run` |
| `README.md` | 42-43, 173-176 | Run examples |
| `deploy/README.md` | 32 | Install-path check reference |
| `deploy/install-service.sh` | 106-107, 153 | Runtime path checks + systemd ExecStart rewrite |
| `deploy/eclipse-obd.service` | 46 | `ExecStart=.../python src/main.py --config src/obd_config.json` |
| `docs/cross-platform-development.md` | 178, 192, 205 | Dev workflow examples |
| `.claude/commands/review-stories-tuner.md` | 49 | Spool story-review skill reference |

## Impact

- `deploy/eclipse-obd.service` will **actively fail** if installed (ExecStart references wrong path)
- Other references are misleading but not runtime-breaking

## Fix

Mechanical one-PR cleanup. Update all paths to post-reorg locations:
- `src/main.py` → `src/pi/main.py`
- `src/obd_config.json` → `config.json` (repo root)

No sweep-style ceremony needed.
