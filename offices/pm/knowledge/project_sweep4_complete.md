---
name: Sweep 4 Complete
description: Sweep 4 config restructure merged to main 2026-04-14 (commit f1237b8) and pushed to origin. config.json now at repo root with tier-aware pi:/server: shape. 32 legacy template tests deleted. 5 prod-code integration bugs fixed as followups.
type: project
originSessionId: eea27f9c-e6fd-46e2-9242-6d9a3810d228
---
**Status:** Merged to main as commit `f1237b8` on 2026-04-14 and **pushed to origin/main** in the same session — first push of the reorg work (104 commits went up together). The "main is ~45 commits ahead of origin, NOT pushed" line from earlier auto-memory is now resolved.

**Why:** Sweep 3 split the code tree into `src/common/` / `src/pi/` / `src/server/`, but the config file was still a flat `src/pi/obd_config.json` with server-tier sections (`aiAnalysis`) mixed in. Sweep 4 promotes it to `config.json` at the repo root and rewrites it into a tier-aware shape so the config file enforces the same Pi/server boundary as the source tree.

**How to apply:**
- **Config file location**: `Z:/o/OBD2v2/config.json` at repo root. `src/pi/obd_config.json` is **gone**.
- **Tier-aware shape**:
  ```
  {
    "protocolVersion": "1.0.0",
    "schemaVersion": "1.0.0",
    "deviceId": "${DEVICE_ID:chi-eclipse-tuner}",
    "logging": {...},                     // shared top-level
    "pi": {                                 // Pi-tier only, 19 sections
      "application": {...}, "database": {...}, "bluetooth": {...},
      "vinDecoder": {...}, "display": {...}, "autoStart": {...},
      "staticData": {...}, "realtimeData": {...}, "analysis": {...},
      "profiles": {...}, "calibration": {...}, "pollingTiers": {...},
      "tieredThresholds": {...}, "alerts": {...}, "dataRetention": {...},
      "batteryMonitoring": {...}, "powerMonitoring": {...},
      "export": {...}, "simulator": {...}
    },
    "server": {                             // server tier only
      "ai": {...},           // renamed from aiAnalysis
      "database": {},        // placeholder (future MariaDB)
      "api": {}              // placeholder (future FastAPI)
    }
  }
  ```
- **Consumer read pattern**: `config.get('pi', {}).get('<section>', ...)` for any Pi-tier section. `config.get('server', {}).get('ai', ...)` for AI (the `aiAnalysis` rename is real). `config.get('logging', ...)` / `config['protocolVersion']` for top-level shared. Tests and src/ were both updated to this pattern — don't write flat-shape fixtures.
- **Run the simulator**: `python src/pi/main.py --simulate --dry-run` still works. `main.py`'s `DEFAULT_CONFIG` now points at `<projectRoot>/config.json`.
- **New schema module**: `src/common/config/schema.py` exposes `AppConfig`/`PiConfig`/`ServerConfig`/`LoggingConfig` dataclasses + `AppConfig.fromDict(json.load(open('config.json')))` for typed loads. Optional; most callers still use dict access.

## Validator behavior changes

- `src/common/config/validator.py` now **fails loud** on flat-shape configs (raises `ConfigValidationError: Missing required top-level section(s): pi, server`).
- `REQUIRED_KEYS`: `protocolVersion`, `schemaVersion`, `deviceId`
- `REQUIRED_SECTIONS`: `pi`, `server` (structural, checked first)
- `OBD_REQUIRED_FIELDS` in `src/pi/obd/config/loader.py`: `pi.database.path`, `pi.bluetooth.macAddress`, `pi.display.mode`, `pi.realtimeData.parameters`
- All 40+ `OBD_DEFAULTS` paths use the `pi.*` / `server.*` nested form

## What broke and how it was fixed

During Task 8 fixture work, 5 production-code integration bugs surfaced — all in `src/pi/obd/orchestrator.py` and `src/pi/obd/shutdown/command.py`:

| Location | Before | After |
|---|---|---|
| `orchestrator.py:316` | `config.get('shutdown', {})` | `config.get('pi', {}).get('shutdown', {})` |
| `orchestrator.py:324` | `config.get('monitoring', {})` | `config.get('pi', {}).get('monitoring', {})` |
| `orchestrator.py:330` | `config.get('monitoring', {})` | `config.get('pi', {}).get('monitoring', {})` |
| `orchestrator.py:356` | `config.get('monitoring', {})` | `config.get('pi', {}).get('monitoring', {})` |
| `shutdown/command.py:1105` | `config.get('shutdown', {})` | `config.get('pi', {}).get('shutdown', {})` |

These were missed by the Task 6 subagent because its grep mask only looked for the 19 canonical pi-section names, and `shutdown`/`monitoring` are ad-hoc config keys that happen to accept `config.get(X, {})` patterns even though they aren't in the real config file. Fixed in commit `b492fe1`, 7 tests un-skipped.

## Test count change

- **Baseline before Sweep 4**: 1501 fast / 1519 full (the Sweep 3 baseline)
- **Baseline after Sweep 4**: **1469 fast / 1487 full** (authoritative going forward)
- **Delta**: -32 tests — all from deleting `TestHardwareConfigDefaults` (17) + `TestBackupConfigDefaults` (14) + 1 additional legacy template test in `test_config_validator.py`. These tests exercised legacy Python-template defaults (`hardware.*`, `backup.*`, `retry.*`) that no OBD2v2 consumer reads. Filed as `offices/pm/tech_debt/TD-sweep4-legacy-validator-defaults.md` — the legacy DEFAULTS entries themselves stay in `validator.py` until a later cleanup sweep.

## Spool preservation

Byte-for-byte identical. Snapshot at Task 1 (`/tmp/sweep4-tiered-before.json`) diffed against `config.json[pi][tieredThresholds]` at Task 10 — empty output. All six Spool-authoritative sections (`batteryVoltage`, `coolantTemp`, `iat`, `rpm`, `stft`, `timingAdvance`) unchanged. RPM `dangerMin=7000`, coolantTemp `dangerMin=220`, etc. all intact.

## Session mechanics notes

- **Task 6 subagent died mid-run**, then reappeared with a stale index state (HEAD correct, worktree/index reverted). Recovery: `git reset --hard HEAD`. Don't assume the state is broken just because `git status` looks wrong — check HEAD first.
- **Task 8 subagent (fixture sweep) was fast-suite-only** and missed two slow-marked test files (`test_simulate_db_validation.py`, `test_e2e_simulator.py`). Task 10 caught both and fixed them before final verification.
- **Auto-commit `9f518d2`** added two transient `Bash(wait <session-id>:*)` permissions to `offices/ralph/.claude/settings.local.json` — harness artifact, harmless.
- **Parallel PM session** touched `offices/pm/projectManager.md` and `offices/pm/.claude/settings.local.json` during the sweep — those modifications were left alone since they belong to a different session's owner.

## Ruff status

- Sweep 4 introduced zero new ruff errors. The 4 pre-existing errors (`src/server/ai/ollama.py` + `tests/test_remote_ollama.py`) are unchanged from main baseline. One new UP037 that landed in the initial `schema.py` was fixed in followup commit `536adac`.
- Mypy: not installed in this environment (pre-existing constraint), same as sweeps 1-3.

## Lessons captured

All four new lessons from Sweep 4 are in `docs/superpowers/plans/REORG-HANDOFF.md` optimizations #8-11:
1. When a subagent dies mid-report, check HEAD vs. index before assuming worktree state
2. Don't use `git stash` for transient checks (it can pop old session stashes)
3. Slow-marked tests are invisible to fast-suite-only runs but still need fixture updates
4. Canonical-section-name grep masks can miss ad-hoc config reads
