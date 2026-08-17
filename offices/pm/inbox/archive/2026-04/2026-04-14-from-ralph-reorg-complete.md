# Ralph → Marcus — Structural Reorganization Complete

**Date**: 2026-04-14
**From**: Ralph
**To**: Marcus (PM)
**Subject**: Reorg complete — close backlog items + wider path-drift cleanup

## tl;dr

All 6 sweeps of the OBD2v2 structural reorganization are merged to `main` (Sweep 6 pending CIO merge gate at time of writing, but ready). The tree is now tier-aware (`src/common/`, `src/pi/`, `src/server/`), all files are within size guidelines (or listed in an exemption block with rationale), all facade duplication is gone, the legacy threshold system is merged into the tiered system, `config.json` is restructured at repo root with tier-aware shape, the 2501-line orchestrator is now a 9-module mixin package, and camelCase is confirmed as the standard across the codebase.

**No tuning values changed.** All Spool-authoritative values in `config.json[pi][tieredThresholds]` have been verified **byte-for-byte unchanged** at the end of every sweep — diffed against the sweep-start snapshot with empty output. The preservation check is the final task of every sweep; it has passed every time.

## Please close these backlog items as RESOLVED

- **TD-002** — Re-export facade modules → Sweep 1 (commit `21029e8`)
- **TD-003** — Orchestrator refactoring plan → Sweep 5 (commit `8413c82`)
- **B-019** — Split oversized files → Sweep 5 (commit `8413c82`)
- **B-040** — Structural Reorganization → all 6 sweeps (commit pending at time of writing)

## Please close this as DECLINED

- **B-006** — snake_case migration → the reorg reconfirmed camelCase as the project standard. The Sweep 6 audit found the codebase was already clean (~10 lines of diff total for the rename component). `specs/standards.md` section 2 now carries a 9-point exemption list documenting where snake_case is legitimately retained (pytest hooks, external API duck types, SQL string literals, NHTSA/Ollama field names, module filenames, etc.).

## New backlog items that were filed during the reorg

- **B-035** — Per-profile tiered threshold overrides. Filed during Sweep 2b when two profile-switch-rebinds-thresholds tests were deleted as square-pegs after the tiered model became global. This captures the future feature the deleted tests were anticipating (per-profile threshold overrides on top of the global tiered base).
- **TD-sweep4-legacy-validator-defaults** — Legacy `hardware.*` / `backup.*` / `retry.*` entries in `src/common/config/validator.py` DEFAULTS/REQUIRED_KEYS that no production code reads. Low priority cleanup for a later sweep.

## Wider path-drift cleanup (new TD item for your backlog)

The Sweep 6 exit criterion scoped CLAUDE.md path updates to the two CLAUDE.md files only. During Task 5 I observed that several other places in the repo still reference the pre-reorg paths (`src/main.py`, `src/obd_config.json`) and could confuse a user following the README:

- `Makefile` lines 72, 75 — `python src/main.py` / `--dry-run`
- `README.md` lines 42-43, 173-176 — run examples
- `deploy/README.md` line 32 — install-path check reference
- `deploy/install-service.sh` lines 106-107, 153 — runtime path checks + systemd ExecStart rewrite
- `deploy/eclipse-obd.service` line 46 — `ExecStart=.../python src/main.py --config src/obd_config.json`
- `docs/cross-platform-development.md` lines 178, 192, 205 — dev workflow examples
- `.claude/commands/review-stories-tuner.md` line 49 — Spool story-review skill reference

Per **invariant #6** (no bug fixes unrelated to structural correctness) and **process optimization #14** (scope escape hatch — don't chase exit criteria beyond the plan), I did not touch these. They were explicitly out of Sweep 6's scope. **Please file as a new TD item — e.g., "TD-post-reorg-path-drift-cleanup"** covering Makefile, root README, deploy/, docs/, and `.claude/commands/`. It's a mechanical pass and won't need another sweep-style ceremony — a one-PR cleanup will do. Priority is moderate because the deploy service file will actively fail if anyone tries to install it today.

## Archive location

The full reorg spec and all 9 plan files (6 sweeps + 2a + 2b + the REORG-HANDOFF entry point) are now at:

```
docs/superpowers/archive/
├── 2026-04-12-reorg-design.md               (the 561-line design doc with Session Log)
├── 2026-04-12-reorg-sweep1-facades.md
├── 2026-04-12-reorg-sweep2-thresholds.md    (superseded by 2a/2b but kept for history)
├── 2026-04-12-reorg-sweep3-tier-split.md
├── 2026-04-12-reorg-sweep4-config.md
├── 2026-04-12-reorg-sweep5-file-sizes.md
├── 2026-04-12-reorg-sweep6-casing.md
├── 2026-04-13-reorg-sweep2a-rewire.md       (rewire half of the split)
├── 2026-04-14-reorg-sweep2b-delete.md       (delete half of the split)
└── REORG-HANDOFF.md                         (session handoff / process-optimization log)
```

The design doc's section 12 (Session Log) is the authoritative chronological record. Each sweep row has a full narrative of what was done, what went wrong, and what the test counts and Spool-preservation checks showed.

## 6-sweep summary

| Sweep | Merge commit | Headline |
|---|---|---|
| 1 | `21029e8` | 18 facades deleted, shutdown trio consolidated into subpackage |
| 2a | `418b55b` | AlertManager rewired to consume `tieredThresholds`; RPM=7000 |
| 2b | `d65d52f` | Legacy threshold system excised (alert_config_json column, helpers, 18 fixture keys) |
| 3 | `b2be378` | `src/` physical tier split: `common/`, `pi/`, `server/` |
| 4 | `f1237b8` | `config.json` at repo root with tier-aware `pi:` / `server:` shape; pushed to origin (first push of the reorg) |
| 5 | `8413c82` | Orchestrator 2501→9-module mixin package (TD-003); 11 other src splits; 79 src + 26 test size exemption blocks in READMEs |
| 6 | (pending) | camelCase enforcement (~10 lines of diff — codebase was already clean), READMEs finalized, CLAUDE.md path references current, `specs/standards.md` exemption list added, reorg artifacts archived |

## Test baseline held exact across all 6 sweeps

- **Fast suite**: 1469 passed, 0 skipped, 19 deselected — at every commit from Sweep 4 onward (the Sweep 4 deletion of 32 legacy template tests reset the baseline from 1501 to 1469).
- **Full suite**: 1487 passed, 1 skipped — same baseline.
- **Ruff**: 4 pre-existing errors in `src/server/ai/ollama.py` and `tests/test_remote_ollama.py` — unchanged since main. Zero sweep-introduced drift. Per invariant #6 these stay until a dedicated cleanup sweep; neither Sweep 5 nor Sweep 6 touched them.
- **Mypy**: not installed in the dev environment (pre-existing env constraint). Not a sweep concern.

## What's next

The next priority per CIO direction (captured in the Infrastructure Pipeline MVP PRD draft) is connecting the Pi 5 to the OBD-II Bluetooth dongle and getting real data flowing. Pi hardware is up at 10.27.27.28 but not yet physically connected to the car — the CIO is doing that work in parallel. Once real data starts flowing, the empty `src/common/contracts/` skeleton can be populated with actual type definitions against observed data shapes, and the Pi→Chi-Srv-01 upload protocol can be built against the real drive log format.

The Infrastructure Pipeline MVP PRD (currently DRAFT at `offices/pm/prds/prd-infrastructure-pipeline-mvp.md`) was blocked on the reorg completing. Now that the reorg is done, you can promote it, create its backlog item, and create sprint 7 against the 9 stories (US-147–155). The PRD Finalization Checklist at the bottom of the PRD has the fill-in items — most of them reference the post-reorg paths and test conventions that are now stable.

Also worth a note: the Sprint 4 push moved `main` up to origin for the first time in the reorg (104 commits). Sweeps 5 and 6 sit **locally only** at the time of this report — when you're ready, you can push origin/main forward with `git push origin main` from the CIO workstation. The local sprint branches for sweeps 1-6 are retained per the 7-day rule (delete around 2026-04-21).

— Ralph
