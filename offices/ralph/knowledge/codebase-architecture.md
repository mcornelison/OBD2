# Codebase Architecture — Ralph Reference

Load when working on code, not at startup.

## 3-Tier System
- **Pi** (in-car edge): data collection, OBD polling, local storage, display. `src/pi/`
- **Chi-Srv-01** (home server): receives uploads, runs analysis, pushes recommendations. `src/server/`
- **Common** (shared): config, errors, logging, contracts. `src/common/`

## Config System
- Single `config.json` at repo root. Tier-aware: top-level shared + `pi:` + `server:` sections.
- Consumer pattern: `config.get('pi', {}).get('X', ...)` for pi-tier; `config.get('server', {}).get('ai', ...)` for server.
- 3-layer: env vars → secrets loader → validator. Dot-notation defaults in `src/common/config/validator.py`.

## Orchestrator (package, not file)
`src/pi/obd/orchestrator/` — 9 files, mixin-composed:
- `core.py` (ApplicationOrchestrator), `lifecycle.py`, `event_router.py`, `backup_coordinator.py`, `connection_recovery.py`, `health_monitor.py`, `signal_handler.py`, `types.py`
- All use `logging.getLogger("pi.obd.orchestrator")` (NOT `__name__`) for caplog compat
- Backward compat: `from src.pi.obd.orchestrator import ApplicationOrchestrator` works

## src/ Layout
- `src/common/` — config/, errors/, logging/, analysis/, contracts/, constants.py
- `src/pi/` — main.py, obd/ (orchestrator/, export/, shutdown/, simulator/, service/), alert/, analysis/, backup/, calibration/, display/, hardware/, power/, profile/, clients/ (skel), inbox/ (skel)
- `src/server/` — main.py, ai/, api/ (skel), ingest/ (skel), analysis/ (skel), recommendations/ (skel), db/ (skel)

## Simulator
`python src/pi/main.py --simulate --dry-run` (config at repo-root `config.json`)
