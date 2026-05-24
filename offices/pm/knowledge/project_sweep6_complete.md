---
name: Sweep 6 Complete — REORG COMPLETE
description: Sweep 6 (camelCase + README finalization) merged to main as 6af8e9a on 2026-04-14 and pushed to origin. All 6 reorg sweeps landed. B-040 resolved.
type: project
originSessionId: 80486ffb-119a-446a-964d-742825a3ca0b
---
# Sweep 6 Complete — REORG COMPLETE

**Merged**: 2026-04-14 as commit `6af8e9a` on `main`.
**Pushed**: Same day to `origin/main`. Origin now has Sweeps 5 AND 6 (Sweep 5 had been sitting local since `8413c82`).

**Why**: Final reorg sweep. camelCase enforcement across src/ and tests/, README finalization, CLAUDE.md path references, specs/standards.md exemption list, reorg archive. Closes the structural reorganization tracked as B-040.

**How to apply**: No Sweep 7. No more reorg work. Next priority per CIO is connecting Pi 5 to the OBD-II dongle and getting real data flowing. Infrastructure Pipeline MVP PRD (currently DRAFT) can be promoted by Marcus now that the reorg is done.

## What shipped

- **7 commits on `sprint/reorg-sweep6-casing`** (7eb0552 → 509aa00), merged as `6af8e9a` with `--no-ff`:
  1. Audit notes — 10-pattern grep found the codebase was ~99% camelCase-clean
  2. camelCase renames — 4 actionable renames, 2 files, ~10 lines of diff total
  3. READMEs finalized (new src/pi/obd/ + src/pi/obd/orchestrator/ sub-READMEs)
  4. CLAUDE.md path references (repo root + offices/ralph/)
  5. specs/standards.md 9-point exemption list
  6. Session log row + archive moves (spec + 9 plan files)
  7. Marcus completion notification in PM inbox

- **New files created**:
  - `src/pi/obd/README.md` — 8 OBD subpackages, top-level files, facade pattern explanation
  - `src/pi/obd/orchestrator/README.md` — 9-module mixin architecture, line-count/role table
  - `offices/pm/inbox/2026-04-14-from-ralph-reorg-complete.md` — Marcus closure request

- **Renames**: `src/pi/obd/shutdown/command_scripts.py` (signal_handler/initiate_shutdown/button_callback inside the f-string template for generated GPIO trigger script + 4 call sites) and `src/pi/hardware/i2c_client.py` (voltage_mv in docstring Example).

## Exemptions documented in specs/standards.md section 2 (new)

9-point list added below the camelCase naming examples:
1. Test functions (`test_*` — pytest discovery)
2. Pytest hooks (`pytest_configure`, etc.)
3. Short loop variables
4. Python dunders
5. External API duck types — `SimulatedResponse.is_null()` and `SimulatedObd.is_connected()` mirror python-OBD's public interface; `SimulatedObdConnection.isConnected()` (our class) coexists in the same file as the correct contrast
6. SQL in string literals (snake_case column names)
7. External JSON field names (NHTSA, Ollama)
8. Module filenames (per-file decision, not code-style)
9. Generated Python code follows project standards (we don't get a pass because it's in an f-string)

## Tests held exact at baseline

- Fast suite: **1469 passed, 0 skipped, 19 deselected** (same as Sweep 4/5 baseline)
- Full suite: **1487 passed, 1 skipped** (Task 7 once-through)
- Ruff: 4 pre-existing errors untouched (`src/server/ai/ollama.py` UP041, `tests/test_remote_ollama.py` I001/UP041/F841) — same parity as Sweep 5 handoff
- Simulator smoke test: clean via `python src/pi/main.py --simulate --dry-run`
- Tier boundaries: ZERO Pi→Server, Server→Pi, Common→tier violations
- **Spool `tieredThresholds` byte-for-byte identical** at sweep start vs. sweep end — preservation check has passed at the end of every one of the 6 sweeps

## Archive structure (post-reorg)

Everything reorg-related is now at `docs/superpowers/archive/`:
- `2026-04-12-reorg-design.md` (561-line design doc + Session Log — authoritative chronological record)
- `2026-04-12-reorg-sweep1-facades.md` through `sweep6-casing.md`
- `2026-04-13-reorg-sweep2a-rewire.md`
- `2026-04-14-reorg-sweep2b-delete.md`
- `REORG-HANDOFF.md` (session handoff + 14 process optimizations)

`docs/superpowers/plans/` and `docs/superpowers/specs/` are now **empty** after the archive moves.

## Backlog closures for Marcus

Marcus inbox note at `offices/pm/inbox/2026-04-14-from-ralph-reorg-complete.md` lists:
- **Resolve**: TD-002 (Sweep 1), TD-003 (Sweep 5), B-019 (Sweep 5), B-040 (all 6 sweeps)
- **Decline**: B-006 (camelCase confirmed as standard)
- **New TD to file**: wider path-drift cleanup (Makefile, repo README.md, deploy/, docs/cross-platform-development.md, `.claude/commands/review-stories-tuner.md` all still reference `src/main.py` / `src/obd_config.json`). These were out of Sweep 6's exit criterion #8 per invariant #6 (no bug fixes unrelated to structural correctness). **Moderate priority** because `deploy/eclipse-obd.service` and `deploy/install-service.sh` will actively fail if anyone runs them today.

## New backlog items filed during the reorg (reminder)

- **B-035** — Per-profile tiered threshold overrides (Sweep 2b filing)
- **TD-sweep4-legacy-validator-defaults** — Legacy `hardware.*`/`backup.*`/`retry.*` in validator.py DEFAULTS

## Key post-reorg facts for future Ralph sessions

- **Main branch**: at `6af8e9a`, pushed to origin/main. No local-only commits.
- **Test baseline**: 1469 fast / 1487 full — authoritative going forward.
- **Entry point**: `python src/pi/main.py [--simulate] [--dry-run]` (NOT `src/main.py`).
- **Config file**: `config.json` at repo root (NOT `src/pi/obd_config.json` — moved in Sweep 4).
- **Consumer config pattern**: `config.get('pi', {}).get('<section>', ...)` for Pi-tier, `config.get('server', {}).get('ai', ...)` for AI, `config.get('logging', ...)` / `config['protocolVersion']` for top-level shared.
- **Orchestrator**: package at `src/pi/obd/orchestrator/` (9 files, mixin composition). Backward-compat import still works.
- **Sprint branches retained** locally for 7 days post-merge (delete around 2026-04-21): sweep1, sweep2a, sweep2b, sweep3, sweep4, sweep5, sweep6.
