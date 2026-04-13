# Ralph Agent — CLAUDE.md

Load `agent.md` for full Ralph autonomous agent instructions.

## Architecture Awareness (3 Tiers)

This project is a distributed system. Know which tier your code runs on before writing it.

### Tier 1 — Raspberry Pi 5 (in-car edge)
- **Role**: Data collection. Runs in the car, eventually permanently installed.
- **Connectivity to ECU**: Bluetooth OBD-II dongle (OBDLink LX) OR direct ECU wiring (future).
- **Scope**: Most of the codebase lives here — OBD polling, drive detection, local storage, display, telemetry.
- **Network**: Offline while driving; connects to home WiFi (`DeathStarWiFi`, 10.27.27.0/24) on return.
- **Target**: `chi-eclipse-tuner` @ 10.27.27.28, user `mcornelison`, Python 3.11+ venv.

### Tier 2 — Chi-Srv-01 (home analysis server)
- **Role**: Receives uploads from Pi when it arrives home, runs analysis, pushes modifications back down.
- **Form**: Daemon service + cron jobs on Debian 13.
- **Host**: `chi-srv-01` @ 10.27.27.120 (i7-5960X, 128GB RAM, 12GB GPU, MariaDB `obd2db`).
- **Responsibilities**: Ingest drive logs from Pi, run statistical/AI analysis, produce tuning recommendations, push config/map changes back to Pi.

### Tier 3 — Spool (AI tuning layer)
- **Role**: Fine-tuned AI tuning SME. Consumes analyzed data, produces tuning recommendations.
- **Integration**: ECMLink V3 programmable ECU — dual fuel map (pump gas ↔ E85), AFR/timing/boost adjustments.
- **Runs on**: Chi-Srv-01 (GPU-accelerated Ollama at 10.27.27.120:11434, `llama3.1:8b`).
- **Future**: Model fine-tuning on project-specific tuning data.

**Data flow**: Pi collects → uploads to Chi-Srv-01 → Spool analyzes → recommendations push back to Pi → eventually written to ECMLink maps.

## Architectural Decisions (locked 2026-04-12)

1. **Transport Pi→Server**: Pi pushes to Chi-Srv-01 on WiFi return. Server does not pull. Pi owns the "when to upload" decision.
2. **Tuning recommendations are staged for human review.** Never auto-applied to the ECU. Chi-Srv-01/Spool writes a recommendation artifact; CIO reviews and approves before anything touches ECMLink. Design the push-back channel as an inbox, not a command pipe.
3. **Shared contracts live in `src/common/`**. Data exchange formats (drive log schema, recommendation schema, config schema, wire protocols) are versioned and locked. Both tiers import from the same module. Breaking changes require an explicit version bump — never silently mutate a contract.
4. **ECMLink writer is out of scope** until the V3 is physically installed in the car (summer 2026). Do not stub, mock, or pre-build it. If a story mentions ECMLink writes, block it.
5. **Single `config.json` with tier-specific sections**. Not split files. Shared keys (protocol version, DB schema version) live at the top level; `pi:` and `server:` sections hold tier-specific settings. The 3-layer config system (env → secrets loader → validator) applies to the whole file.
6. **Deployment is a single script, lockstep, keep it simple.** One deploy script runs from CIO's workstation, SSHes to both Pi and Chi-Srv-01, checks out the same git tag on both, runs migrations, restarts services. No Docker, no CI/CD, no build artifacts — matches the existing Python-venv reality. Deploy order: **server first, Pi second** (server stays backward-compatible to N-1 for a grace window; Pi may be offline when you deploy). Ship with a `--dry-run` flag from day one.
7. **Protocol version handshake is the safety net.** At upload time, Pi announces its `protocolVersion` (from `src/common/`). Server rejects mismatched uploads with a clear error; Pi keeps the log locally and retries on the next attempt. This turns silent data corruption into a loud visible backlog — the failure mode you'd otherwise miss until the next drive.

## Developer Rules

**No hardcoded values.** Every threshold, path, timeout, IP, credential, polling interval, PID, calibration value — belongs in a config file or is passed as a parameter. If you're typing a literal number or string that might ever change, stop and ask "does this belong in config?"

**Parameterize.** Functions take values as arguments, not read globals. Classes take dependencies via constructor injection (see golden code patterns in `agent.md`). Services receive their repositories/config — they don't construct them internally.

**Config files over constants.** Use the 3-layer config system (`src/common/config_validator.py`): env vars → secrets loader → validated config. Nested defaults via dot-notation paths.

**Reusable and flexible.** Extract shared logic into `src/common/`. Follow Factory/Strategy/Protocol patterns. One function, one responsibility. If you copy-paste three lines, make it a helper.

**Tier-aware code.** When writing a module, know which tier it runs on. Pi-only code (GPIO, Bluetooth, display) must fail gracefully on non-Pi for testing. Server-only code (heavy analysis, Ollama) must not be imported by Pi runtime paths. Shared code (data models, protocols, config schemas) lives in `src/common/` and has zero tier-specific dependencies.
