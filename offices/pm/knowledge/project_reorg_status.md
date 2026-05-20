---
name: Reorg Status — REORG COMPLETE
description: OBD2v2 6-sweep structural reorganization. ALL 6 SWEEPS MERGED AND PUSHED to origin as of 2026-04-14. Resolves B-040, TD-002, TD-003, B-019. Declines B-006.
type: project
originSessionId: eea27f9c-e6fd-46e2-9242-6d9a3810d228
---
# REORG COMPLETE

**Status**: All 6 sweeps landed. Main at `6af8e9a`, pushed to `origin/main`. Archive at `docs/superpowers/archive/`. Marcus has the closure request in his inbox. **No Sweep 7. No followups. The reorg is done.**

## Why

Three overlapping forms of tech debt were making future feature work increasingly expensive:
- Facade duplication from earlier refactoring (sweep 1)
- Oversized files, including a 2,501-line orchestrator (sweep 5 + TD-003)
- No tier-aware source structure (sweep 3)

Plus two medium-scope items piggybacked onto the sequencing:
- Config restructure to tier-aware shape (sweep 4)
- Legacy threshold system merging into the tiered system (sweeps 2a + 2b)

CIO directed the reorg 2026-04-12 during a brainstorm session that also locked 7 architectural decisions (see `project_architecture_tiers.md`). Doing the reorg now was cheap because nothing is in production — no data to preserve, no deploys to coordinate, no users to disrupt.

## How to apply

This is now a historical record. If any current work references the reorg, point at:
- **Design doc**: `docs/superpowers/archive/2026-04-12-reorg-design.md` (561 lines, with the Session Log as the authoritative chronological record of all 6 sweeps)
- **Individual sweep plans**: `docs/superpowers/archive/2026-04-12-reorg-sweep{1..6}*.md` + `2026-04-13-reorg-sweep2a-rewire.md` + `2026-04-14-reorg-sweep2b-delete.md`
- **Handoff doc with 14 process optimizations**: `docs/superpowers/archive/REORG-HANDOFF.md`

## The 6 sweeps

| Sweep | Merge commit | Date | Headline |
|---|---|---|---|
| 1 | `21029e8` | 2026-04-13 | 18 facade files deleted, shutdown trio consolidated into `src/obd/shutdown/` subpackage. Resolves TD-002. |
| 2a | `418b55b` | 2026-04-13 | AlertManager rewired to consume `config['tieredThresholds']` directly. RPM `dangerMin`=7000 (Spool US-139 value) honored throughout. Original Sweep 2 was split after audit revealed AlertManager was 100% legacy-bound. |
| 2b | `d65d52f` | 2026-04-13 | Pure dead-code delete of the orphaned legacy threshold system (169-line thresholds.py, alert_config_json DB column, 18 fixture cleanups). B-035 filed for future per-profile threshold overrides. |
| 3 | `b2be378` | 2026-04-13 | Physical tier split into `src/common/`, `src/pi/`, `src/server/`. Zero Pi↔Server imports on first try. Checkpoint B passed. Contracts skeleton created for future population. |
| 4 | `f1237b8` | 2026-04-14 | Config restructured into tier-aware shape at repo root. 32 legacy template tests deleted. 5 prod-code integration bugs (shutdown/monitoring reads) fixed as followups. **First push to origin (104 commits went up together).** |
| 5 | `8413c82` | 2026-04-14 | Orchestrator 2501-line file → 9-module mixin package (TD-003). 13 orchestrator test files → 73 focused files. 11 other src files split. 79 src + 26 test files documented in README size-exemption blocks. Resolves TD-003 + B-019. |
| 6 | `6af8e9a` | 2026-04-14 | camelCase enforcement (~10 lines of diff — codebase was ~99% clean). READMEs finalized. CLAUDE.md path references current. `specs/standards.md` 9-point camelCase exemption list added. Reorg spec + 9 plan files archived. Marcus notified. **Push 2 of 2: Sweeps 5 + 6 went up together.** |

## Test baselines held exact across all 6 sweeps

- **Fast suite**: 1469 passed, 0 skipped, 19 deselected — from Sweep 4 merge forward (Sweep 4 deleted 32 legacy template tests, resetting the baseline from 1501 to 1469)
- **Full suite**: 1487 passed, 1 skipped — same
- **Ruff**: 4 pre-existing errors in `src/server/ai/ollama.py` (UP041) and `tests/test_remote_ollama.py` (I001 + UP041 + F841). Unchanged across Sweeps 5 and 6 per invariant #6. Future cleanup.
- **Tier boundaries**: zero Pi→Server, Server→Pi, Common→tier imports — checked at the end of every sweep
- **Spool `tieredThresholds`**: **byte-for-byte identical** at sweep-start and sweep-end on every preservation check (sweeps 2, 4, 5, 6 each had their own snapshot + diff)

## Resolved backlog items

- **TD-002** — Re-export facade modules → Sweep 1 ✅
- **TD-003** — Orchestrator refactoring plan → Sweep 5 ✅
- **B-019** — Split oversized files → Sweep 5 ✅
- **B-040** — Structural Reorganization (tracked as the umbrella item) → all 6 sweeps ✅

Marcus inbox note requests these be marked RESOLVED.

## Declined backlog items

- **B-006** — snake_case migration → The Sweep 6 audit found the codebase already ~99% camelCase-clean (only 5 snake_case function defs in all of `src/`, of which 2 were legitimate python-OBD duck types). camelCase was explicitly reconfirmed as the project standard during the 2026-04-12 brainstorm. `specs/standards.md` section 2 now carries a 9-point exemption list for where snake_case is legitimately retained (pytest hooks, external API duck types, SQL in string literals, NHTSA/Ollama JSON fields, module filenames, etc.).

Marcus inbox note requests B-006 be marked DECLINED.

## New backlog items filed during the reorg

- **B-035** — Per-profile tiered threshold overrides. Filed during Sweep 2b when two profile-switch-rebinds-thresholds tests were deleted as square-pegs. Captures the future feature those tests were anticipating.
- **TD-sweep4-legacy-validator-defaults** — Legacy `hardware.*` / `backup.*` / `retry.*` entries in `src/common/config/validator.py` DEFAULTS/REQUIRED_KEYS that no production code reads. Low priority.
- **Wider path-drift cleanup** (to be filed by Marcus as a new TD) — `Makefile`, repo-root `README.md`, `deploy/eclipse-obd.service`, `deploy/install-service.sh`, `docs/cross-platform-development.md`, and `.claude/commands/review-stories-tuner.md` still reference pre-reorg paths (`src/main.py`, `src/obd_config.json`). Moderate priority because `deploy/install-service.sh` will actively fail if run today. Sweep 6 scope was bounded to CLAUDE.md path references only per exit criterion #8; this wider cleanup is a followup pass.

## Post-reorg repository state

- **Main**: `6af8e9a` on origin. Local and remote aligned. No pending pushes.
- **Sprint branches retained** locally until ~2026-04-21 per the 7-day rule: `sprint/reorg-sweep1-facades`, `sprint/reorg-sweep2a-rewire`, `sprint/reorg-sweep2b-delete`, `sprint/reorg-sweep3-tier-split`, `sprint/reorg-sweep4-config`, `sprint/reorg-sweep5-file-sizes`, `sprint/reorg-sweep6-casing`. All 7 alive for diagnostic access if a post-reorg issue surfaces.
- **`reorg-baseline` tag** still present for nuclear rollback. Unlikely to be needed.
- **`docs/superpowers/plans/`** and **`docs/superpowers/specs/`** are **empty** post-reorg. All reorg content lives in `docs/superpowers/archive/`.
- **Simulator invocation**: `python src/pi/main.py --simulate --dry-run` (loads repo-root `config.json` by default).
- **Consumer config read pattern**: `config.get('pi', {}).get('<section>', ...)` for Pi-tier; `config.get('server', {}).get('ai', ...)` for server AI; `config.get('logging', ...)` / `config['protocolVersion']` for top-level shared keys.
- **Orchestrator import path**: `from src.pi.obd.orchestrator import ApplicationOrchestrator` — still works; `orchestrator` is now a 9-file mixin-composed package, not a file.

## Process optimizations that came out of the reorg (all 14 captured in REORG-HANDOFF.md)

The handoff doc — now archived — contains 14 process lessons accumulated across the sweeps, from Sweep 2b onward. They're worth re-reading before any future multi-sweep work:

1. Preflight branch check in every subagent prompt
2. Trivial tasks (pure file-creation, pure re-exports) done directly, not via subagent
3. Lightweight review for pure-delete or pure-scaffolding commits
4. No compound bash (no `cd && cmd`, no `a && b` chains)
5. Ruff I001 auto-fix after mass rewrites — scoped to touched files
6. Run slow suite periodically for entry-point work
7. `/tmp/` unreliable on Windows — use project-local temp files
8. Check `git log` HEAD before `git status`/`git diff` when a subagent returns ambiguous state
9. Don't use `git stash` for transient checks — it can pop old stashes
10. Slow-marked tests invisible to fast-suite-only runs — grep tests independently for mass fixture sweeps
11. Section-match patterns miss ad-hoc config keys — grep all `config.get(...)` calls
12. Mechanical batch subagent — one dispatch with full file list, not one subagent per file
13. Ruff auto-fix scope discipline — revert pre-existing fixes in non-sweep files
14. Scope escape hatch — document exemptions in README blocks instead of expanding scope to chase exit criteria

## What's next

**The reorg is done.** No more sweeps. Real development starts next session. The next priority per CIO direction is the Pi 5 ↔ OBD-II Bluetooth dongle connection:

1. CIO continues Bluetooth/dongle work in parallel (hardware is up at 10.27.27.28 but not yet physically connected to the car)
2. When real data starts flowing, the empty `src/common/contracts/` skeleton populates with actual type definitions against observed data shapes
3. Marcus can then promote the Infrastructure Pipeline MVP PRD (currently DRAFT at `offices/pm/prds/prd-infrastructure-pipeline-mvp.md`) — the PRD's Finalization Checklist at the bottom has the fill-in items
4. Sprint 7 launches against the 9 stories (US-147–155) covering Pi→Server→AI pipeline + 2 simulated drive scenarios

Marcus's 4-step infrastructure plan (from the PRD): (1) deploy Pi+Server, (2) both running + SSH debuggable, (3) Pi↔Server comms, (4) 2 simulated drive scenarios (town 17min 35-40mph, highway 40min 65-75mph).
