# OBD2v2 Structural Reorganization — Design Document

**Date**: 2026-04-12
**Author**: Ralph (developer agent), in collaboration with CIO (Michael Cornelison)
**Status**: Draft — pending CIO approval
**Related backlog**: B-019 (Split Oversized Files), TD-002 (Re-export Facades), TD-003 (Orchestrator Refactoring Plan). This document supersedes those as the execution plan.

---

## 1. Purpose

Restructure the OBD2v2 codebase to reflect the locked 3-tier architecture (Pi / Chi-Srv-01 / Spool-AI), eliminate technical debt that accumulated during prior refactors, and establish the skeleton for upcoming companion-service and server-analysis work — all without changing runtime behavior.

This is not a feature project. No new user-facing functionality is built. Every change is either **a move**, **a merge**, **a deletion**, or **a rename**. Business logic is untouched except where it must change to accommodate the structural shift.

## 2. Motivation

The codebase has accumulated three overlapping forms of drift that make future work increasingly expensive:

1. **Facade duplication from the Phase 4 refactor.** Modules were moved into proper subpackages (`src/obd/data/`, `src/obd/drive/`, etc.) but the original flat files remained as re-export shims. Both files are now imported from different call sites. This is TD-002.

2. **Oversized files.** At least 10 source files exceed the 300-line guideline. The orchestrator alone is 2,504 lines. This is TD-003 / B-019.

3. **Tier confusion.** The codebase is physically Pi-only today, but several modules (AI, analysis) are destined for the server tier. There is no structural boundary between "Pi-only code" and "shared contracts," which means deploying the server side will require disentangling this later — when it's harder.

On top of that, the architecture we locked on 2026-04-12 (CLAUDE.md decisions 1–7) requires shared contracts, a tier-aware deploy story, and a protocol version handshake — none of which have code homes today.

This reorg solves all three problems in a single coordinated effort before the first real end-to-end data flow happens. Doing it now is cheap: nothing is deployed, no stories are in flight on this code, and the test suite is the safety net.

## 3. Scope

### In scope

- Delete all facade files (TD-002)
- Merge the legacy profile threshold system into the tiered threshold system
- Create the physical tier split: `src/common/`, `src/pi/`, `src/server/`
- Populate `src/common/contracts/` with shared type definitions (skeleton, not business logic)
- Restructure `config.json` into a single file with shared top-level keys and `pi:`/`server:` sections
- Split every source file over 300 lines and every test file over 500 lines
- Split the orchestrator per the existing TD-003 plan
- Enforce camelCase on all Python functions and variables per `specs/standards.md`
- Create living `README.md` files at `src/`, `src/common/`, `src/pi/`, `src/server/`
- Archive or delete the empty `OBD2-Server` sibling repo

### Out of scope

- Building the companion service (B-022) — only the skeleton is created
- Building the server-side analysis pipeline (B-031) — only the skeleton
- Writing the deploy script — deferred until real deployment is needed
- Implementing the protocol handshake — deferred until real Bluetooth data flow starts
- **Populating `src/common/contracts/` with real type definitions** — the skeleton files are created empty. Contracts get populated in a dedicated post-reorg task once real OBD-II data flows from the dongle. Defining contracts against hypothetical data shapes would bake in wrong assumptions.
- ECMLink integration (blocked on physical V3 install, summer 2026)
- The snake_case migration (B-006) — explicitly closed: camelCase stays
- Phase 2 ECMLink data architecture — deferred until Phase 1 yields real data
- Any behavior change, new feature, or bug fix unrelated to structural correctness
- Spool review — no tuning values change during this reorg; if one does, we stop and file to Spool

## 4. Architectural decisions this reorg honors

From `offices/ralph/CLAUDE.md` (locked 2026-04-12):

1. Pi pushes to server, server never pulls
2. Tuning recommendations are staged for human review, never auto-applied to ECU
3. Shared contracts live in `src/common/`, versioned, no silent breaking changes
4. ECMLink writer out of scope until V3 is physically installed
5. Single `config.json` with tier-specific sections, not split files
6. Single lockstep deploy script — out of scope for this reorg but the tier split enables it
7. Protocol version handshake — contracts created, handshake itself lands later

And the CIO development rules:
- No hardcoded values
- Parameterize everything
- Config files over constants
- Reusable, flexible code
- Services take dependencies via constructor injection
- Know which tier your code runs on

And the Spool-authoritative value rule: every parameter, constraint, min/max, and threshold that came from Spool is preserved byte-for-byte. If a literal value would need to change to accommodate the reorg, we stop and file to Spool's inbox instead.

## 5. Target layout

After all six sweeps complete, `src/` looks like this:

```
src/
├── README.md                    # Living TOC — sweep 6 keeps it current
├── __init__.py
│
├── common/                      # DEPLOYED TO BOTH TIERS
│   ├── __init__.py
│   ├── README.md
│   ├── config/
│   │   ├── validator.py         # From src/common/config_validator.py
│   │   ├── secrets_loader.py    # From src/common/secrets_loader.py
│   │   └── schema.py            # NEW — dataclass types for config.json
│   ├── errors/
│   │   ├── base.py              # AppError hierarchy
│   │   ├── retry.py             # Retry classifier + backoff policy
│   │   └── handler.py           # From src/common/error_handler.py
│   ├── logging/
│   │   └── setup.py             # From src/common/logging_config.py
│   ├── analysis/
│   │   └── calculations.py      # From src/analysis/calculations.py (pure math)
│   ├── contracts/               # NEW — empty skeletons, populated post-reorg when real data flows
│   │   ├── __init__.py
│   │   ├── protocol.py          # Will hold: protocolVersion, UploadEnvelope, HandshakeRequest
│   │   ├── drive_log.py         # Will hold: DriveLog, Reading, DriveSummary
│   │   ├── vehicle.py           # Will hold: VehicleInfo (VIN-decoded)
│   │   ├── alerts.py            # Will hold: AlertEvent wire format
│   │   ├── recommendations.py   # Will hold: Recommendation, RecommendationStatus
│   │   └── backup.py            # Will hold: BackupMetadata
│   └── constants.py             # Protocol/schema versions, time formats
│
├── pi/                          # DEPLOYED TO RASPBERRY PI ONLY
│   ├── __init__.py
│   ├── README.md
│   ├── main.py                  # Moved from src/main.py
│   ├── obd/
│   │   ├── connection.py        # Renamed from obd_connection.py
│   │   ├── parameters.py        # Renamed from obd_parameters.py
│   │   ├── config/              # Existing subpackage, facades killed
│   │   ├── data/                # logger, realtime, polling_tiers
│   │   ├── drive/               # detector
│   │   ├── vehicle/             # vin_decoder, static_collector
│   │   ├── export/
│   │   ├── service/
│   │   ├── shutdown/            # Consolidated from shutdown_manager + shutdown_command + shutdown/
│   │   ├── simulator/
│   │   ├── orchestrator/        # Split per TD-003 into 7 modules
│   │   └── database.py
│   ├── hardware/                # From src/hardware/
│   ├── display/                 # From src/display/
│   ├── power/                   # From src/power/
│   ├── alert/                   # From src/alert/ (tiered only, legacy deleted)
│   ├── profile/                 # From src/profile/ (alertThresholds field removed)
│   ├── calibration/             # From src/calibration/
│   ├── backup/                  # From src/backup/
│   ├── analysis/                # From src/analysis/ (minus calculations.py)
│   ├── clients/                 # NEW
│   │   ├── ollama_client.py     # Wraps calls to remote Ollama
│   │   └── uploader.py          # Pushes drive logs to companion service
│   └── inbox/                   # NEW — Recommendation review inbox
│       └── reader.py            # Reads staged Recommendation files
│
└── server/                      # DEPLOYED TO CHI-SRV-01 ONLY
    ├── __init__.py
    ├── README.md
    ├── main.py                  # Server entry point (FastAPI app — placeholder)
    ├── api/                     # NEW — FastAPI routes (placeholder)
    │   ├── app.py
    │   ├── health.py
    │   └── middleware/
    ├── ingest/                  # NEW — Upload receiver, delta sync (placeholder)
    ├── ai/                      # From src/ai/ — full migration
    │   ├── analyzer.py
    │   ├── data_preparation.py
    │   ├── prompt_template.py
    │   ├── ranker.py
    │   ├── types.py
    │   ├── helpers.py
    │   └── ollama_manager.py    # From src/obd/ollama_manager.py
    ├── analysis/                # NEW — post-drive server analysis (placeholder)
    ├── recommendations/         # NEW — writes Recommendation files to Pi inbox
    └── db/                      # NEW — MariaDB schema + models (placeholder)
```

### Key properties

1. **Clear deployment boundaries.** The deploy script's job is trivial: `common/ + pi/` → Pi, `common/ + server/` → Chi-Srv-01.
2. **`src/common/contracts/` is the single source of truth** for the Pi↔Server wire format. Both tiers import from it. Breaking changes require a `protocolVersion` bump.
3. **No file-level facades.** Every module has exactly one canonical file. Package-level `__init__.py` files that re-export from submodules are allowed and expected — they are the standard Python package entry point, not the banned pattern. The banned pattern is a separate top-level `.py` file that exists only to re-export from another location (e.g., `src/obd/data_logger.py` shimming to `src/obd/data/logger.py`).
4. **Every directory has a README.md.** Enforced as a checklist item going forward.
5. **Skeleton placeholders are explicit.** `src/server/api/`, `ingest/`, `db/`, `analysis/`, `recommendations/` and `src/pi/inbox/`, `clients/` exist with `__init__.py` containing a one-line "filled in by story X" comment. No structural arguments when future stories land.
6. **Tier violations become structurally impossible.** Pi code cannot accidentally import `src/server/` because it's not deployed to the Pi. Server code cannot accidentally touch hardware because `src/pi/` is not on Chi-Srv-01.

## 6. Deletion list

### Facade files to delete (sweep 1)

- `src/obd/data_logger.py`
- `src/obd/drive_detector.py`
- `src/obd/vin_decoder.py`
- `src/obd/static_data_collector.py`
- `src/obd/profile_statistics.py`
- `src/obd/profile_manager.py`
- `src/obd/profile_switcher.py`
- `src/obd/alert_manager.py`
- `src/obd/battery_monitor.py`
- `src/obd/power_monitor.py`
- `src/obd/calibration_manager.py`
- `src/obd/calibration_comparator.py`
- `src/obd/recommendation_ranker.py`
- `src/obd/ai_analyzer.py`
- `src/obd/ai_prompt_template.py`
- `src/obd/display_manager.py`
- `src/obd/adafruit_display.py`
- `src/obd/obd_config_loader.py`

The shutdown trio (`src/obd/shutdown_manager.py`, `src/obd/shutdown_command.py`, `src/obd/shutdown/__init__.py`) is consolidated into a single `src/obd/shutdown/` package in sweep 1 rather than naively deleted, because all three contain real logic.

### Legacy threshold system (sweep 2)

- `src/alert/thresholds.py` (169 lines, legacy)
- `profiles.availableProfiles[*].alertThresholds` section from `src/obd_config.json`
- `alertThresholds` field from `src/profile/types.py` dataclass
- All tests that assert legacy threshold behavior (rewritten to use tiered system, or deleted if redundant)

### Repo-level cleanup

- `OBD2-Server` sibling repository — archive or delete (empty, unused)

## 7. Sweep plan

Six sweeps, executed in order. Each sweep has a single concern, produces a committable test-green state, and must be merged to `main` before the next begins.

### Sweep 1 — Facade cleanup (TD-002)

**Goal**: Delete every facade file. Update imports to canonical locations. Zero behavior change.

**In scope**:
- Delete the ~19 facade files listed in section 6
- Consolidate the three-way shutdown mess into a single `src/obd/shutdown/` package with real logic merged
- Rewrite every import site to point at the canonical location
- Update test imports the same way

**Out of scope**: Moving files out of `src/obd/`, splitting oversized files, camelCase changes, tier-aware paths. Everything stays under `src/` flat.

**Entry**: Clean `main`, all tests green, new sweep branch `sprint/reorg-sweep1-facades`.

**Exit**: All tests green, zero facade files, `grep -r "from src.obd.data_logger"` returns zero hits, PR merged to `main`.

**Risk**: Low. Facades are dumb re-exports. If a facade has drifted from its canonical (has extra logic), stop and file an issue before deleting.

**Rollback**: `git revert` the merge commit.

**Estimated effort**: 1–2 days.

### Sweep 2 — Legacy threshold merge

**Goal**: Delete the legacy profile threshold system. Merge any lost concepts into the tiered system.

**In scope**:
- Delete `src/alert/thresholds.py`
- Remove `alertThresholds` from `profiles.availableProfiles[*]` in `src/obd_config.json`
- Remove `alertThresholds` field from `src/profile/types.py`
- Update `src/alert/manager.py` to consume only the tiered system
- Audit `src/obd/profile_manager.py` for legacy threshold reads; rewrite to call the tiered system
- Update or delete legacy-threshold test assertions; rewrite to use tiered system where the coverage is still valuable
- Keep the `daily`/`performance` profile concept — only threshold fields are stripped

**Out of scope**: Refactoring the tiered system itself. Changing any threshold values (Spool already audited them). Creating new profile types.

**Entry**: Sweep 1 merged, tests green.

**Exit**: `grep -r "alertThresholds" src/` returns zero hits outside `tieredThresholds` keys. `grep -r "from src.alert.thresholds"` returns zero hits. All tests green.

**Risk**: Medium. `ProfileManager` is the unknown — it may couple to legacy thresholds in non-obvious ways. First action in this sweep is a read-through of `profile_manager.py` and `alert/manager.py` to map all legacy references before deleting anything.

**Rollback**: `git revert` the merge commit.

**Estimated effort**: 1–3 days.

### Sweep 3 — Tier split and shared contracts

**Goal**: Create `src/pi/`, `src/server/`, expand `src/common/`. Physically move every module to its correct tier. Create contracts skeleton.

**In scope**:
- Create directories: `src/pi/`, `src/server/`, `src/common/contracts/`, `src/common/config/`, `src/common/errors/`, `src/common/logging/`, `src/common/analysis/`
- `git mv` every Pi-only module from `src/*` into `src/pi/*`
- `git mv src/main.py` → `src/pi/main.py`
- `git mv src/ai/*` → `src/server/ai/*`
- `git mv src/analysis/calculations.py` → `src/common/analysis/calculations.py`
- `git mv` the rest of `src/analysis/*` → `src/pi/analysis/*`
- `git mv src/obd_config.json` → `src/pi/obd_config.json` (stays at this location until sweep 4 promotes it to repo root and restructures it)
- Restructure `src/common/` per section 5
- Create `src/common/contracts/` skeleton as **empty file stubs**, not type extractions. Each contract file (`protocol.py`, `drive_log.py`, etc.) contains only a module docstring explaining what will eventually live there and which future story populates it. No classes, no dataclasses, no business logic. Rationale: the Pi has not yet connected to the OBD-II Bluetooth dongle, so we have no real data flowing through the system. Defining contract types against hypothetical data shapes would bake in assumptions that reality will contradict. The contracts get populated as a dedicated task **immediately after this reorg completes** — which will be the next big priority once real bluetooth telemetry starts flowing.
- Create empty skeleton packages: `src/pi/clients/`, `src/pi/inbox/`, `src/server/api/`, `src/server/ingest/`, `src/server/analysis/`, `src/server/recommendations/`, `src/server/db/`
- Each skeleton `__init__.py` contains a one-line comment: `# Filled in by story X / backlog item Y`
- Update every import statement across `src/` and `tests/`
- Create `src/README.md`, `src/common/README.md`, `src/pi/README.md`, `src/server/README.md`

**Config file at the end of sweep 3**: lives at `src/pi/obd_config.json`, still using the old flat structure (not yet restructured). Sweep 4 handles promotion to repo root and restructuring.

**Out of scope**: Splitting oversized files. Config restructure. Writing any new business logic. Writing any new tests.

**Entry**: Sweep 2 merged, tests green.

**Exit**: All tests green. Every import uses new tier-aware paths. `src/pi/`, `src/common/`, `src/server/` match the target layout in section 5. READMEs exist.

**Risk**: **High**. This is the biggest sweep. Mitigation: do it in small commits (one directory at a time), run full test suite after each commit, use `git mv` so git tracks rename history. Expect 15–25 commits in this sweep.

**Rollback**: `git revert` viable but painful across many commits. Better: keep the sweep branch alive until sweep 4 is also merged, so we can fix forward on a still-living branch if something surfaces.

**Estimated effort**: 3–5 days.

### Sweep 4 — Config restructure

**Goal**: Single `config.json` at repo root with shared top-level keys plus `pi:`/`server:` sections. Config schema types live in `src/common/config/schema.py`.

**In scope**:
- Move `src/pi/obd_config.json` → `config.json` (repo root) and rename `obd_config.json` → `config.json`
- Rewrite `config.json` into the new structure:
  ```json
  {
    "protocolVersion": "1.0.0",
    "schemaVersion": "1.0.0",
    "deviceId": "${DEVICE_ID}",
    "logging": { ... },
    "pi": {
      "bluetooth": { ... },
      "display": { ... },
      "pollingTiers": { ... },
      "tieredThresholds": { ... },
      ...
    },
    "server": {
      "ai": { ... },
      "database": { ... },
      "api": { ... }
    }
  }
  ```
- Promote `config.json` to repo root
- Update `src/common/config/validator.py` to validate the new shape (top-level + pi + server sections independently)
- Write `src/common/config/schema.py` (dataclass types)
- Update every config-reading call site to use nested paths
- Update `validate_config.py` and `.env.example`

**Out of scope**: Adding new config keys for unimplemented features. Changing Spool-authoritative values. Format migration (stays JSON).

**Entry**: Sweep 3 merged, tests green.

**Exit**: `config.json` at repo root with new shape. `python validate_config.py` passes. All tests green. Every config reader uses nested structure.

**Risk**: Medium. Many call sites. Validator logic gets subtler with nested sections.

**Rollback**: `git revert` the merge commit.

**Estimated effort**: 2–3 days.

### Sweep 5 — Split oversized files

**Goal**: Every `src/**/*.py` file is ≤300 lines; every `tests/**/*.py` file is ≤500 lines.

**In scope**:
- **Orchestrator** (`src/pi/obd/orchestrator.py`, 2,504 lines): convert the single file into a package `src/pi/obd/orchestrator/` with 7 submodules per TD-003 plan — `types.py`, `core.py`, `lifecycle.py`, `connection_recovery.py`, `event_router.py`, `backup_coordinator.py`, `health_monitor.py`, `signal_handler.py`. The package `__init__.py` re-exports `ApplicationOrchestrator` from `core.py` so existing import sites (`from src.pi.obd.orchestrator import ApplicationOrchestrator`) continue to work unchanged. This is a standard Python package pattern, not a banned file-level facade.
- `data_exporter.py` (1,309 lines) — split by export format
- `shutdown` package — split internally if still oversized after sweep 1 consolidation
- `simulator_integration.py` (1,048)
- `simulator/drive_scenario.py` (1,234), `simulator/simulator_cli.py` (992), `simulator/failure_injector.py` (985)
- `power/power.py` (903)
- `server/ai/analyzer.py` (882)
- `tiered_thresholds.py` (737)
- Any other file over 300 lines
- Split oversized test files if `tests/test_orchestrator_*.py` approaches the 500-line limit

**Critical constraints**: Preserve component init order and shutdown order per TD-003. Ralph re-reads TD-003 before touching orchestrator code.

**Out of scope**: Behavior changes. New functionality. Renaming outside camelCase sweep (sweep 6). Tier moves (done in sweep 3).

**Entry**: Sweep 4 merged, tests green.

**Exit**: All tests green. `find src -name "*.py" -exec wc -l {} + | awk '$1>300'` returns zero hits (or only explicitly-documented exemptions in `src/README.md`). Same check for tests at 500.

**Risk**: Medium-High. Orchestrator split is the critical sub-task. Pure refactors of load-bearing code can introduce timing/lifecycle bugs. Mitigation: orchestrator gets its own sub-sweep with an extra checkpoint.

**Rollback**: `git revert` the merge commit.

**Estimated effort**: 5–7 days.

### Sweep 6 — camelCase sweep and README finalization

**Goal**: All Python functions, methods, function parameters, local variables, and module-level variables conform to camelCase. All READMEs are authoritative.

**In scope**:
- Audit every `src/**/*.py` and `tests/**/*.py` for non-conforming identifiers:
  - Function definitions (`def snake_case_func(...)` → `def snakeCaseFunc(...)`)
  - Method definitions inside classes
  - Function/method parameters
  - Local variables inside functions
  - Module-level variables that aren't constants
  - Dataclass and NamedTuple field names
- Rename one symbol at a time, verify tests pass after each rename
- Update `src/README.md`, `src/common/README.md`, `src/pi/README.md`, `src/server/README.md`
- Write sub-package READMEs where helpful
- Update `specs/standards.md` with any clarifications
- Update `CLAUDE.md` path references if any changed

**Out of scope**: Classes (already PascalCase). SQL names. Constants. External API names (OBD-II parameter names).

**Entry**: Sweep 5 merged, tests green.

**Exit**: `ruff check` passes. Custom grep for snake_case function defs returns zero hits (or only explicitly-exempted symbols in a standards file). READMEs match actual directory contents. All tests green.

**Risk**: Low. Cosmetic. Watch for accidental renames of JSON keys or string literals that look like identifiers.

**Rollback**: `git revert` the merge commit.

**Estimated effort**: 2–4 days.

### Sweep summary

| Sweep | Concern | Risk | Effort | Blocks next |
|---|---|---|---|---|
| 1 | Facade cleanup | Low | 1–2d | Yes |
| 2 | Legacy threshold merge | Medium | 1–3d | Yes |
| 3 | Tier split + contracts | **High** | 3–5d | Yes |
| 4 | Config restructure | Medium | 2–3d | Yes |
| 5 | Split oversized files | Med-High | 5–7d | Yes |
| 6 | camelCase + READMEs | Low | 2–4d | No |

**Total**: ~14–24 focused working days. Likely 3–4 sprint-sized chunks at realistic velocity.

## 8. Execution strategy

### 8.1 Branching

One sprint branch per sweep:
```
sprint/reorg-sweep1-facades
sprint/reorg-sweep2-thresholds
sprint/reorg-sweep3-tier-split
sprint/reorg-sweep4-config
sprint/reorg-sweep5-file-sizes
sprint/reorg-sweep6-casing
```

Each branch is merged to `main` before the next begins. No long-lived integration branch. This bounds blast radius, matches the existing workflow, and keeps `git bisect` useful.

### 8.2 Test strategy

**Green at every commit. No exceptions.**

- Fast suite (`pytest -m "not slow"`) on every commit during a sweep
- Full suite (including slow tests) before each PR merge to `main`
- Coverage floor: 80% (existing `pyproject.toml` gate), must not drop
- Test files move with source files in the same commit — no orphan tests
- No new tests written during the reorg. Missing-coverage discoveries go to `offices/pm/tech_debt/`, fixed in a future sprint.

### 8.3 Work tracking: CIO↔Ralph direct

Per Marcus's own architectural-decisions brief: architecture-related work is CIO-direct and bypasses PM story grooming.

**Artifacts**:
1. This design doc: `docs/superpowers/specs/2026-04-12-reorg-design.md`
2. Implementation plan (next step, from writing-plans skill): `docs/superpowers/plans/2026-04-12-reorg-plan.md`
3. Notice to Marcus in `offices/pm/inbox/` saying "CIO and Ralph running the reorg per the design doc, resolves TD-002/TD-003/B-019, don't create stories."

**Marcus's role during the reorg**: Adds B-040 "Structural Reorganization" as a backlog summary item pointing at this design doc. Closes TD-002, TD-003, B-019 as resolved after sweeps land. Does not groom stories for sweep work.

**Spool's role**: Uninvolved. If any tuning value is threatened, stop and file to Spool's inbox.

**`offices/ralph/stories.json`**: Not touched.

### 8.4 Rollback

- Per-sweep rollback is `git revert` the merge commit
- Sweeps 3 and 5 have a 24-hour cooling period after merge before the next sweep starts — time for issues to surface
- Tag `main` before sweep 1 as `reorg-baseline` for nuclear rollback
- Never force-push, never amend merged commits, never `git reset --hard` without CIO approval

### 8.5 Checkpoints

Three mid-reorg checkpoints where work pauses for review before proceeding, plus one final completion gate:

**Checkpoint A — After sweep 1**
- Verify zero facade imports remain
- Full test suite passes (including slow tests)
- Update this design doc's appendix with status
- CIO approval to proceed

**Checkpoint B — After sweep 3** (critical)
- Full test suite passes
- Import audit: every `from src.` import targets `src.common`, `src.pi`, or `src.server`
- `src/README.md` matches reality
- OBD simulator end-to-end smoke test
- 24-hour cooling period
- CIO approval to proceed

**Checkpoint C — After sweep 5**
- Full test suite
- Init/shutdown order verified against TD-003 via simulator startup logs
- File size audit: all `src/**/*.py` ≤300 lines
- 24-hour cooling period
- CIO approval to proceed

**Completion gate — After sweep 6**
- Full test suite
- Update `CLAUDE.md` if any decisions need refining
- Archive design doc and plan to `docs/superpowers/archive/`
- Notify Marcus: reorg complete, close TD-002/TD-003/B-019/B-040

### 8.6 Communication

- **Blockers**: file to `offices/pm/blockers/BL-reorg-sweepN-<desc>.md` and stop immediately
- **Surprises**: file to `offices/pm/tech_debt/TD-reorg-<N>.md` even if fixed inline — no silent absorption
- **Session logs**: each Ralph session during the reorg updates a status appendix in this design doc
- **Spool only engaged if a tuning value is at risk**

### 8.7 Deployment (non-concern)

Nothing is deployed during the reorg. No coordinated deploys, no downtime, no rollback-to-production concerns. Simulator path is run end-to-end as sweeps land to catch regressions. The real deploy script is a future sprint.

## 9. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Sweep 3 import churn breaks test suite | High | High | Small commits, one directory at a time, green-at-every-commit |
| Orchestrator split introduces timing bugs | Medium | High | Dedicated sub-sweep, extra checkpoint, TD-003 plan re-read, simulator smoke test |
| ProfileManager has hidden legacy coupling | Medium | Medium | Read-through audit before sweep 2 starts |
| Facade has drifted from canonical (has extra logic) | Low | Medium | Audit each facade file before deletion; if logic exists, merge then delete |
| camelCase sweep renames a string literal | Low | Low | Rename function defs first, tests catch mismatches at call sites |
| Tests are flaky, hiding real regressions | Low | High | If a test is flaky, fix the flake or mark it and file tech debt — don't ignore |
| A tuning value gets touched accidentally | Low | **Critical** | Sweep 2 explicitly preserves all Spool-authoritative values; any threatened value stops the sweep |
| Merge to `main` between sweeps goes wrong | Low | High | Each sweep is a single PR, reviewed before merge, rollback is a single revert |
| CIO discovers the reorg is misconceived mid-execution | Low | High | The `reorg-baseline` tag allows nuclear rollback; each sweep is small enough to pause after |

## 10. Success criteria

At the end of sweep 6, all of the following must be true:

1. `find src -name "*.py" -exec wc -l {} + | awk '$1>300'` returns zero hits (or only documented exemptions)
2. `grep -r "from src\." src tests | grep -v "src\.common\|src\.pi\|src\.server"` returns zero hits
3. `grep -r "alertThresholds" src/ | grep -v tieredThresholds` returns zero hits
4. Every directory under `src/` has a `README.md`
5. `src/README.md` is a current TOC of the tree
6. `config.json` lives at repo root with `pi:` and `server:` sections
7. `ruff check`, `mypy`, and `pytest tests/` all pass
8. Coverage ≥80%
9. Simulator runs end-to-end without errors
10. TD-002, TD-003, B-019 marked resolved in the backlog
11. `OBD2-Server` sibling repo deleted or archived
12. `CLAUDE.md` paths (if any) updated for the new layout

## 11. Non-goals

This reorg does NOT:
- Add any new feature
- Change any tuning value
- Deploy anything to any host
- Build the companion service (B-022)
- Build the server analysis pipeline (B-031)
- Build the deploy script
- Touch ECMLink
- Migrate to snake_case

If any sweep starts to drift toward one of these, stop and file a tech-debt item for later.

## 12. Appendix — Session log

_Updated by Ralph at end of each reorg session._

| Date | Sweep | Session notes |
|---|---|---|
| 2026-04-12 | — | Design doc drafted during brainstorming session. Pending CIO approval. |
| 2026-04-13 | 1 | Sweep 1 complete. Deleted 18 facade files, consolidated shutdown trio into src/obd/shutdown/ subpackage, rewrote src/obd/__init__.py to import from canonical package locations. Option A adopted for obd_config_loader (canonical = obd.config package, not config/loader.py submodule) — tech debt note filed and resolved. Orchestrator.py lazy imports (8 call sites) rewired in Task 6 alongside 7 test files with stale patch targets. Full suite: 1517 passed, 1 skipped (exact baseline match). Fast suite: 1499 passed. Simulator --dry-run smoke test clean. Ruff: 4 pre-existing warnings in src/ai/ollama.py and tests/test_remote_ollama.py remain untouched (out of scope); sweep 1 I001 introduced in Task 5 fixed in Task 8. Checkpoint A gate ready for CIO approval. Parallel PM session interleaved with sweep — committed PRD draft (1bfcb86) and Session 14 closeout (99320c9) on sprint branch, harmless to the sweep work. |
| 2026-04-13 | 2a | Sweep 2 **split into 2a (rewire) + 2b (delete)** after Task 2 audit found AlertManager was 100% legacy-bound (consumes only profile.alertThresholds, never tieredThresholds). A pure delete would have made alert firing inert. Sweep 2a completed: added AlertManager.setThresholdsFromConfig() sourcing rpm.dangerMin and coolantTemp.dangerMin from config['tieredThresholds']; rewired createAlertManagerFromConfig() + orchestrator profile-switch handler; updated 15 test files (13 orchestrator + test_simulate_db_validation + test_e2e_simulator) to include tiered section in fixtures; 3 profile-switch-rebinds-thresholds tests mark-skipped (premise invalidated by global-tiered model). **Semantic changes (CIO Option A approved)**: RPM redline now fires at 7000 (was 6500/6000 legacy — 7000 is the Spool-authoritative US-139 value); coolant temp critical 220°F unchanged; boost pressure and oil pressure alerts **silent** until Spool specs tiered values (PM inbox note filed). Task 2 investigation also confirmed STFT/battery/IAT/timing alerts were never wired to any consumer — pre-existing coverage gap filed as TD-alert-coverage-stft-battery-iat-timing.md. Full suite: 1521 passed, 4 skipped (baseline 1517 + 7 new task 3 tests − 3 mark-skipped = 1521, exact match). Ruff clean on all 15 touched files; 4 pre-existing errors in test_remote_ollama.py out of scope. Simulator smoke test clean. tieredThresholds config section byte-identical to pre-sweep snapshot (diff empty). Runtime-layer preservation check passed: AlertManager._profileThresholds[daily/performance] contains RPM=7000 ABOVE and COOLANT_TEMP=220 ABOVE after construction from real obd_config.json. Legacy files (src/alert/thresholds.py, Profile.alertThresholds field, alert_config_json DB column, profiles.alertThresholds/thresholdUnits config blocks) remain alive — Sweep 2b handles removal. Sprint branch sprint/reorg-sweep2a-rewire ready for CIO merge approval. |
