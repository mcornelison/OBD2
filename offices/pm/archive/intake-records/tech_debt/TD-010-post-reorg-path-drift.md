# TD-010: Post-Reorg Path Drift Cleanup

**Priority**: Medium
**Status**: Mostly closed — 1 item blocked by permissions (see "Closeout 2026-04-17" below)
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

## Closeout 2026-04-17 (Rex, Sprint 10 / US-179)

Addressed during US-179 alongside the systemd service rewrite. Status of the
original affected-files list:

| File | Status |
|---|---|
| `Makefile` lines 72, 75 | ✅ Fixed (`run`/`run-dry` → `src/pi/main.py`) |
| `README.md` lines 42-43, 173-176 | ✅ Fixed (+ project structure block also updated) |
| `deploy/README.md` line 32 (112) | ✅ Fixed |
| `deploy/install-service.sh` lines 106-107, 153 | ✅ Fixed (script rewritten) |
| `deploy/eclipse-obd.service` line 46 | ✅ Fixed (full service file rewritten) |
| `docs/cross-platform-development.md` lines 178, 192, 205 | ✅ Fixed |
| `.claude/commands/review-stories-tuner.md` line 49 | ❌ BLOCKED — Edit denied by harness permission allowlist; `Edit(Z:/o/OBD2v2/.claude/commands/**)` not in `offices/ralph/.claude/settings.local.json`. One-line operator edit required to close. |

**Additional drift fixed during US-179** (scope-extended from original TD-010
list because the US-179 acceptance grep authoritatively scans `docs/`):
- `docs/testing.md` — all `python src/main.py` refs updated
- `docs/hardware-reference.md` — all `python src/main.py` refs updated
- `docs/deployment-checklist.md` — all `python src/main.py` and `/home/pi/obd2` refs updated

**Intentionally NOT fixed** (historical record): `docs/superpowers/archive/*.md`
— these are the archived reorg-design documents that describe the reorg
itself. Touching them would rewrite history. The US-179 acceptance grep
passes when that subtree is excluded.

**Close condition**: operator edits `.claude/commands/review-stories-tuner.md:49`
(`src/obd_config.json` → `config.json`) OR PM adds
`Edit(Z:/o/OBD2v2/.claude/commands/**)` to Ralph's permission allowlist and a
follow-up Ralph iteration lands the one-line fix. Then flip this file's
Status field to Closed.
