---
name: Sweep 3 Complete
description: Sweep 3 physical tier split merged to main 2026-04-13 (commit b2be378). src/ now split into common/, pi/, server/ subtrees. Checkpoint B passed.
type: project
originSessionId: ff63b873-43d6-4637-ad1f-bdfd89d7fcd3
---
**Status:** Merged to main as commit `b2be378` on 2026-04-13. Checkpoint B passed.

**Why:** The flat `src/*` layout blended Pi-side, server-side, and shared code. Sweep 3 physically splits them into `src/common/` (shared), `src/pi/` (Pi-only), `src/server/` (server-only) so deployment boundaries are structurally enforced.

**How to apply:** When looking for anything under `src/`, the top-level directories are now `common/`, `pi/`, `server/`, plus `README.md`. Old paths (`src/hardware/`, `src/obd/`, `src/ai/`, `src/main.py`, etc.) **do not exist**. Import paths follow the new structure (`from src.pi.obd.X`, `from src.common.config.validator`, etc.). Pi code importing from `src.server.*` or server code importing from `src.pi.*` is forbidden — only `common ↔ *` is allowed.

## New layout

```
src/
├── README.md
├── common/              # deployed to both tiers
│   ├── README.md
│   ├── analysis/        # pure math: calculations.py, exceptions.py, types.py
│   ├── config/          # validator.py, secrets_loader.py
│   ├── contracts/       # 7 empty stubs + __init__.py (post-reorg work)
│   ├── errors/          # handler.py
│   ├── logging/         # setup.py
│   └── constants.py
├── pi/                  # deployed to chi-eclipse-tuner only
│   ├── README.md
│   ├── main.py          # moved from src/main.py
│   ├── obd_config.json  # moved from src/obd_config.json
│   ├── obd/             # the whole OBD-II subsystem (was src/obd/)
│   ├── alert/ analysis/ backup/ calibration/ display/ hardware/ power/ profile/
│   ├── clients/         # skeleton (ollama_client.py, uploader.py)
│   └── inbox/           # skeleton (reader.py)
└── server/              # deployed to chi-srv-01 only
    ├── README.md
    ├── main.py          # placeholder — B-022
    ├── ai/              # REAL code migrated from src/ai/
    ├── api/             # skeleton (app.py, health.py, middleware/) — B-022
    ├── ingest/ analysis/ recommendations/ db/   # all skeletons — B-022/B-031
```

## Key moves

- `src/common/` flat files → subpackages: `config_validator.py → config/validator.py`, `secrets_loader.py → config/secrets_loader.py`, `error_handler.py → errors/handler.py`, `logging_config.py → logging/setup.py`
- `src/analysis/` split: `calculations.py`, `exceptions.py`, `types.py` → `src/common/analysis/` (pure stdlib); `engine.py`, `helpers.py`, `profile_statistics.py`, `__init__.py` → `src/pi/analysis/`
- `src/ai/` → `src/server/ai/` (9 files including the real `ollama.py`)
- `src/obd/` → `src/pi/obd/` (the largest move — ~57 files, ~80 files changed in commit)
- 7 Pi-only dirs → `src/pi/`: hardware, display, power, alert, profile, calibration, backup
- `src/main.py` → `src/pi/main.py`, `src/obd_config.json` → `src/pi/obd_config.json`
- **Deleted** `src/pi/obd/ollama_manager.py` shim (was a thin re-export, zero callers — cleaner than the plan's "Option A" tier boundary violation)

## Tier boundary audit result

**Zero Pi→Server imports. Zero Server→Pi imports.** Better than the plan expected — the orphan ollama shim deletion removed the one documented exception the plan anticipated.

## Tests preserved

- Fast suite: **1501 passed, 0 skipped, 19 deselected** (exact baseline)
- Full suite: **1519 passed, 1 skipped** (exact baseline)
- Ruff: back to baseline 4 pre-existing errors (src/server/ai/ollama.py, tests/test_remote_ollama.py)
- Simulator smoke test: clean startup via new `src/pi/main.py`

## Run the simulator

```
python src/pi/main.py --simulate --dry-run
```

Not `python src/main.py` anymore — that path is gone.

## Test invocation

Test commands don't change:
- `pytest tests/ -q -m "not slow"` still works
- The test files themselves were updated to import from new paths

## Lessons captured in session

- Trivial file-creation tasks (empty docstrings, README boilerplate) can be done directly by the controller via parallel `Write` tool calls — no subagent overhead
- Slow-marked e2e tests (like `test_e2e_simulator.py`) don't run during fast-suite checks and can hide stale paths in subprocess invocations. Run slow suite periodically for sweeps that touch entry points.
- Ruff E402 in entry points with intentional `sys.path` manipulation — resolve with `# noqa: E402` markers on specific import lines, don't rewrite the structure
- Task 8 reality differed from plan: plan assumed real code at `src/pi/obd/ollama_manager.py` needing relocation; reality was an empty re-export shim with zero callers, so deletion was correct
- Task 5 interpretation: "pure math" meant "no project-domain deps," not "no sibling files" — calculations.py + exceptions.py + types.py all moved to common together because they're all pure stdlib and calculations imports from its siblings

## Spin-off

- `/tmp/` on Windows Write-tool unreliability → use project-local temp files for merge messages (`Z:/o/OBD2v2/.sweep<N>-merge-msg.txt`)
- Preflight branch check pattern proved effective — zero branch-state recoveries in Sweep 3
