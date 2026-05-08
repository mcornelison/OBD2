# Ralph Agent — CLAUDE.md

Loaded by `/init-ralph` (interactive sessions). Headless ralph.sh iterations use `prompt.md` only — this file is the richer interactive context.

## Architecture Awareness (3 Tiers)

This project is a distributed system. Know which tier your code runs on before writing it.

### Tier 1 — Raspberry Pi 5 (in-car edge)
- **Role**: Data collection. Eventually permanently installed in the car.
- **Connectivity to ECU**: Bluetooth OBD-II dongle (OBDLink LX) OR direct ECU wiring (future).
- **Scope**: Most of the codebase — OBD polling, drive detection, local storage, display, telemetry.
- **Network**: Offline while driving; connects to home WiFi (`DeathStarWiFi`, 10.27.27.0/24) on return.
- **Target**: `chi-eclipse-01` @ 10.27.27.28, user `mcornelison`, Python 3.11+ venv.

### Tier 2 — Chi-Srv-01 (home analysis server)
- **Role**: Receives uploads from Pi when it arrives home, runs analysis, pushes modifications back down.
- **Form**: Daemon service + cron jobs on Debian 13.
- **Host**: `chi-srv-01` @ 10.27.27.10 (i7-5960X, 128GB RAM, 12GB GPU, MariaDB `obd2db`).
- **Responsibilities**: Ingest drive logs, run statistical/AI analysis, produce tuning recommendations, push config/map changes back to Pi.

### Tier 3 — Spool (AI tuning layer)
- **Role**: Fine-tuned AI tuning SME. Consumes analyzed data, produces tuning recommendations.
- **Integration**: ECMLink V3 programmable ECU — dual fuel map (pump gas ↔ E85), AFR/timing/boost adjustments.
- **Runs on**: Chi-Srv-01 (GPU-accelerated Ollama at 10.27.27.10:11434, `llama3.1:8b`).

**Data flow**: Pi collects → uploads to Chi-Srv-01 → Spool analyzes → recommendations push back to Pi → eventually written to ECMLink maps.

## Architectural Decisions (locked 2026-04-12)

1. **Transport Pi→Server**: Pi pushes to Chi-Srv-01 on WiFi return. Server does not pull. Pi owns the "when to upload" decision.
2. **Tuning recommendations are staged for human review.** Never auto-applied to the ECU. Spool writes a recommendation artifact; CIO reviews and approves before anything touches ECMLink. Push-back channel is an inbox, not a command pipe.
3. **Shared contracts in `src/common/`.** Drive log schema, recommendation schema, config schema, wire protocols are versioned and locked. Both tiers import from the same module. Breaking changes require an explicit version bump.
4. **ECMLink writer is out of scope** until V3 is physically installed (summer 2026). Do not stub, mock, or pre-build it. Stories mentioning ECMLink writes → block.
5. **Single `config.json` with tier-specific sections.** Shared keys top-level; `pi:` and `server:` sections for tier-specific. The 3-layer config system (env → secrets loader → validator) applies to the whole file.
6. **Deployment is a single script, lockstep, simple.** SSH to both hosts, checkout same git tag, run migrations, restart services. No Docker. Deploy order: server first, Pi second. Ship `--dry-run` from day one.
7. **Protocol version handshake is the safety net.** At upload time, Pi announces `protocolVersion`; server rejects mismatched uploads with a clear error; Pi keeps the log locally and retries. Turns silent data corruption into a loud visible backlog.

## Developer Rules

**No hardcoded values.** Every threshold, path, timeout, IP, credential, polling interval, PID, calibration value belongs in a config file or as a parameter. If you're typing a literal that might ever change, ask "does this belong in config?"

**Parameterize.** Functions take values as arguments, not globals. Classes take dependencies via constructor injection. Services receive their repositories/config — they don't construct them internally.

**Config files over constants.** Use the 3-layer config system (`src/common/config/validator.py`): env vars → secrets loader → validated config. Nested defaults via dot-notation paths.

**Reusable and flexible.** Extract shared logic into `src/common/`. Follow Factory/Strategy/Protocol patterns. One function, one responsibility. Three copy-pasted lines = make it a helper.

**Tier-aware code.** Know which tier your module runs on. Pi-only code (GPIO, Bluetooth, display) must fail gracefully on non-Pi for testing. Server-only code (heavy analysis, Ollama) must not be imported by Pi runtime paths. Shared code lives in `src/common/` with zero tier-specific dependencies.

## Where Things Live

| Topic | Canonical home |
|-------|----------------|
| Headless per-iteration contract | `offices/ralph/prompt.md` |
| Coding conventions (full) | `specs/standards.md` §1-13 |
| Golden Code Patterns | `specs/best-practices.md` (Golden Code section) |
| CIO Development Rules | `specs/methodology.md` §1 (CIO Development Rules) |
| TDD methodology, Definition of Done, runtime-validation rule | `specs/methodology.md` |
| Architecture, data flow, tech stack | `specs/architecture.md` |
| Anti-patterns | `specs/anti-patterns.md` |
| Vehicle facts, safe operating ranges | `specs/grounded-knowledge.md` |
| OBD-II PID tables, polling strategy | `specs/obd2-research.md` |
| Domain glossary | `specs/glossary.md` |
| Sprint contract / 5 refusal rules | `offices/ralph/knowledge/sprint-contract.md` |
| Cross-session gotchas | `offices/ralph/knowledge/session-learnings.md` |
| Orchestrator / config / tier layout | `offices/ralph/knowledge/codebase-architecture.md` |
| Pi hardware patterns (I2C/GPIO/UPS/display) | `offices/ralph/knowledge/patterns-pi-hardware.md` |
| Test patterns | `offices/ralph/knowledge/patterns-testing.md` |
| OBD/data-flow patterns | `offices/ralph/knowledge/patterns-obd-data-flow.md` |
| Pi→server sync patterns | `offices/ralph/knowledge/patterns-sync-http.md` |
| Python/systems patterns | `offices/ralph/knowledge/patterns-python-systems.md` |
| Knowledge index | `offices/ralph/knowledge/README.md` |
| Active backlog | `offices/pm/backlog/B-*.md` |
| Active PRDs | `offices/pm/prds/prd-*.md` |
| Project roadmap | `offices/pm/roadmap.md` |
| Project commands cheatsheet | root `CLAUDE.md` |

## Git Branching Strategy

- **Sprint branches**: one per sprint (e.g. `sprint/sprint25-engine-telemetry`).
- **Work on the sprint branch**: all feature work during the sprint goes there.
- **Merge to main**: PM merges when the sprint is done and tests pass.
- **Never push directly to main** during active sprint work.

Per CIO directive: Ralph does NOT run git commands. Marcus (PM) owns staging, commits, branching, merges. Leave changes unstaged.

## Housekeeping (periodic, not per-iteration)

When the CIO asks for a housekeeping pass, check:

1. **Stale files**: dead code referencing deleted files; garbage artifacts (Windows 8.3 filenames); orphaned test runners.
2. **Config drift**: multiple config files diverging; example configs inconsistent with actual project config.
3. **Specs drift**: docs falling behind code (display dimensions, deleted features still referenced, missing new features).
4. **Requirements drift**: duplicate packages across requirements files; dev tools in production requirements.
5. **Agent state**: stale task IDs and dates in `ralph_agents.json`; archive completed PRDs.
6. **Test health**: full suite, check warnings.
7. **File sizes**: flag files over guidelines (~300 source, ~500 test) for splitting.

**Standing lessons:**
- Specs drift from code faster than expected. Audit after any major feature push or hardware change.
- Keep exactly one config file, one requirements file. Duplicates always diverge.
- When changing defaults in code (like CLI `--config` path), grep tests for assertions on the old value.

## Session Persistence

| File | Role |
|------|------|
| `offices/ralph/sprint.json` | User story status (authoritative) |
| `offices/ralph/progress.txt` | Per-session progress log (rolling — older entries in `archive/progress.archive.YYYY-MM-DD.txt`) |
| `offices/ralph/ralph_agents.json` | Per-agent close notes (richest session-handoff signal) |
| `offices/ralph/knowledge/session-learnings.md` | Cross-session accumulated gotchas |

At the end of each session, `/closeout-ralph` updates these so the next session starts cold with full context.

## Modification History

Detailed history of agent.md (now archived) lives in `offices/ralph/archive/agent.archive.2026-05-06.md`. The 2026-05-06 refactor split that file:
- Per-iteration headless content → `offices/ralph/prompt.md`
- Interactive / standing-context content → this file
- Golden Code Patterns → `specs/best-practices.md`
- CIO Development Rules → `specs/methodology.md`
