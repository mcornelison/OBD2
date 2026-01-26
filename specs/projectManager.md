# Project Manager Knowledge Base

## Purpose

This document serves as long-term memory for AI-assisted project management of the Eclipse OBD-II Performance Monitoring System. It captures project status, decisions, timeline, and context needed to resume work in new sessions.

**Last Updated**: 2026-01-23
**Current Phase**: Pre-Deployment (Application Orchestration)

---

## Quick Context for New Sessions

When starting a new session, read this section first:

### Current State (2026-01-23)

- **What's Done**: All 129 modules implemented, 324 tests passing, database ready, simulator complete
- **What's Blocking Deployment**: Main application loop (`runWorkflow()`) is a placeholder - components exist but aren't wired together
- **Active PRD**: `specs/tasks/prd-application-orchestration.md` (20 user stories, ~6-9 days work)
- **Target Platform**: Raspberry Pi 5 (developing on Windows)

### Immediate Next Actions

1. Implement `ApplicationOrchestrator` class (US-OSC-001)
2. Wire up startup/shutdown sequences (US-OSC-002, US-OSC-003)
3. Connect all components in main loop (US-OSC-005)

### Key Files to Read First

| Purpose | File |
|---------|------|
| Project instructions | `CLAUDE.md` |
| Architecture | `specs/architecture.md` |
| Current PRD | `specs/tasks/prd-application-orchestration.md` |
| This file | `specs/projectManager.md` |

---

## Stakeholder Information

### Project Owner

- **Role**: Solo developer / hobbyist
- **Technical Level**: Experienced developer, familiar with Python
- **Vehicle**: Personal vehicle for testing
- **Hardware**: Raspberry Pi 5, OBD-II Bluetooth dongle, Adafruit display (optional)

### Working Preferences

- Prefers comprehensive documentation before implementation
- Uses Ralph autonomous agent system for routine development work
- Values TDD methodology - tests before implementation
- Appreciates detailed PRDs with clear acceptance criteria
- Comfortable with AI assistance for both planning and coding

### Constraints

- Development environment: Windows (MINGW64)
- Production environment: Raspberry Pi 5 (Linux)
- Limited time availability - work done in sessions
- No continuous integration yet - manual testing

---

## Project Timeline

### Phase 1: Foundation (Completed - 2026-01-21)

**Milestone**: Basic project infrastructure

- Project structure created
- Configuration system (ConfigValidator, SecretsLoader)
- Logging infrastructure with PII masking
- Error handling framework (5-tier classification)
- Test utilities and fixtures

**Key Decision**: Use camelCase for Python functions (project standard, differs from PEP8)

### Phase 2: OBD-II Core (Completed - 2026-01-21/22)

**Milestone**: Core OBD-II functionality

PRD: `specs/tasks/prd-eclipse-obd-ii.md`
Archive: `ralph/archive/2026-01-22-eclipse-obd-ii/`

Delivered:
- Database schema (11 tables, 10 indexes, WAL mode)
- OBD connection management with retry logic
- VIN decoding via NHTSA API
- Realtime data logging
- Drive detection (state machine pattern)
- Alert system with thresholds
- Statistics engine
- Profile management
- Display manager (multiple modes)
- Data export (CSV, JSON)
- AI analysis integration (Ollama)
- Power/battery monitoring
- Calibration mode

**Key Decision**: SQLite over flat files for analytics capability on Pi 5

### Phase 3: Simulator (Completed - 2026-01-22)

**Milestone**: Hardware-free testing capability

PRD: `specs/tasks/prd-obd-simulator.md`
Archive: Part of eclipse-obd-ii archive

Delivered:
- SimulatedObdConnection (drop-in replacement)
- Physics-based sensor simulation
- Vehicle profiles (JSON configurable)
- Drive scenarios (cold start, city, highway)
- Failure injection (connection drops, sensor failures, DTCs)
- CLI commands for simulator control
- `--simulate` flag in main.py

**Key Decision**: Physics-based simulation over random values for realistic testing

### Phase 4: Module Refactoring (Completed - 2026-01-22/23)

**Milestone**: Clean architecture with subpackages

PRD: `specs/tasks/prd-module-refactoring.md`

Delivered:
- 16 user stories completed by Ralph agent
- Monolithic modules refactored into domain subpackages
- Standard structure: types.py → exceptions.py → core → helpers
- Backward compatibility via re-export facades
- All 324 tests passing after refactor

**Key Decision**: Maintain backward compatibility with re-exports during transition

### Phase 5: Pre-Deployment (Current - 2026-01-23)

**Milestone**: Production-ready application

PRD: `specs/tasks/prd-application-orchestration.md` (NEW)

Status:
- [x] Cross-platform development guide created
- [x] SQLite installed and verified
- [x] Platform verification script created
- [x] Deployment checklist created
- [x] PRD written (20 user stories)
- [ ] ApplicationOrchestrator implementation (NOT STARTED)
- [ ] Component wiring (NOT STARTED)
- [ ] Integration tests (NOT STARTED)
- [ ] systemd service setup (NOT STARTED)
- [ ] End-to-end testing (NOT STARTED)

---

## PRD Tracking

### Active PRDs

| PRD | Status | User Stories | Next Action |
|-----|--------|--------------|-------------|
| `prd-application-orchestration.md` | **Active - Converted to prd.json** | 0/20 complete | Run `./ralph/ralph.sh` |

### Completed PRDs

| PRD | Completed | Archive Location |
|-----|-----------|------------------|
| `prd-eclipse-obd-ii.md` | 2026-01-22 | `ralph/archive/2026-01-22-eclipse-obd-ii/` |
| `prd-obd-simulator.md` | 2026-01-22 | (merged with above) |
| `prd-module-refactoring.md` | 2026-01-23 | `ralph/archive/2026-01-23-module-refactoring/` |

### PRD Notes

- PRDs stored in `specs/tasks/` as markdown
- Ralph agent converts to `prd.json` for execution
- Completed work archived in `ralph/archive/YYYY-MM-DD-name/`
- Archive contains `prd.json` and `progress.txt`

---

## Key Technical Decisions

### Decision Log

| Date | Decision | Rationale | Alternatives Considered |
|------|----------|-----------|------------------------|
| 2026-01-21 | camelCase for functions | Project standard consistency | PEP8 snake_case |
| 2026-01-21 | SQLite for storage | Analytics queries, portability, Pi-friendly | Flat files, PostgreSQL |
| 2026-01-21 | WAL mode for SQLite | Better concurrent performance | Default journal mode |
| 2026-01-22 | Physics-based simulator | Realistic test data | Random value generation |
| 2026-01-22 | Re-export facades | Backward compatibility | Breaking change migration |
| 2026-01-23 | Orchestrator pattern | Central lifecycle management | Scattered initialization |

### Architecture Decisions

Refer to `specs/architecture.md` for detailed system design.

Key architectural choices:
- Configuration-driven behavior (no hardcoded values)
- Dependency injection via config dictionaries
- 5-tier error classification system
- State machine for drive detection
- Background threads for non-blocking operations

---

## Current Risks and Blockers

### Active Risks

| Risk | Likelihood | Impact | Mitigation | Owner |
|------|------------|--------|------------|-------|
| Bluetooth pairing issues on Pi | Medium | High | Document troubleshooting, test early | Human |
| Thread synchronization bugs | Medium | High | Use established patterns, thorough testing | AI Agent |
| Memory leaks in long runs | Low | High | Profile memory usage, stress testing | AI Agent |

### Blockers

| Blocker | Status | Waiting On |
|---------|--------|------------|
| None currently | - | - |

### Technical Debt

| Item | Priority | Notes |
|------|----------|-------|
| TestDataManager pytest warning | Low | Has `__init__` constructor, causes collection warning |
| Some re-export modules could be removed | Low | Once all code migrated to direct imports |

---

## Environment and Dependencies

### Development Environment

- **OS**: Windows 10/11 (MINGW64)
- **Python**: 3.11+ (currently 3.13.9)
- **SQLite**: 3.50.4 (bundled with Python)
- **Tools**: `tools/sqlite3.exe` for CLI access

### Production Environment

- **OS**: Raspberry Pi OS (Linux)
- **Python**: 3.11+
- **Hardware**: Raspberry Pi 5 (4GB or 8GB RAM)
- **Display**: Adafruit 240x240 TFT (optional)
- **OBD-II**: Bluetooth ELM327-compatible dongle

### Dependency Files

| File | Purpose |
|------|---------|
| `requirements.txt` | Core + dev dependencies |
| `requirements-pi.txt` | Raspberry Pi production dependencies |
| `pyproject.toml` | Tool configuration (pytest, black, ruff, mypy) |

---

## Testing Status

### Test Suite

- **Total Tests**: 324
- **Status**: All passing (as of 2026-01-23)
- **Coverage**: Target 80% (enforced in pyproject.toml)

### Test Categories

| Category | Count | Notes |
|----------|-------|-------|
| Unit tests | ~300 | Individual module testing |
| Integration tests | ~20 | Component interaction |
| Orchestrator tests | 0 | To be created (US-OSC-015) |

### Running Tests

```bash
pytest tests/                    # All tests
pytest tests/ -v -m "not slow"   # Skip slow tests
pytest tests/ --cov=src          # With coverage
```

---

## Documentation Index

### Specs (Reference)

| File | Purpose |
|------|---------|
| `specs/architecture.md` | System design, components, data flow |
| `specs/methodology.md` | TDD workflow, processes |
| `specs/standards.md` | Coding conventions, naming rules |
| `specs/anti-patterns.md` | What NOT to do |
| `specs/glossary.md` | Domain terminology |

### Docs (Guides)

| File | Purpose |
|------|---------|
| `docs/cross-platform-development.md` | Windows → Pi development guide |
| `docs/deployment-checklist.md` | Pre-deployment tasks |
| `docs/bluetooth-setup.md` | (To be created) Bluetooth pairing |

### Task PRDs

| File | Status |
|------|--------|
| `specs/tasks/prd-eclipse-obd-ii.md` | Completed |
| `specs/tasks/prd-obd-simulator.md` | Completed |
| `specs/tasks/prd-module-refactoring.md` | Completed |
| `specs/tasks/prd-application-orchestration.md` | **Active** |

---

## Ralph Agent System

### How It Works

1. PRD written in `specs/tasks/prd-*.md`
2. Converted to `ralph/prd.json` for execution
3. Ralph agent (`ralph/ralph.sh`) executes user stories
4. Progress tracked in `ralph/progress.txt`
5. Completed work archived in `ralph/archive/`

### Current Agent State

- **Agent File**: `ralph/agent.md` (operational tips)
- **State File**: `ralph/ralph_agents.json`
- **Progress**: `ralph/progress.txt`

### Running Ralph

```bash
./ralph/ralph.sh 1    # Run 1 iteration
./ralph/ralph.sh 10   # Run 10 iterations
make ralph-status     # Check status
```

---

## Session Handoff Checklist

When ending a session, update this section:

### Last Session Summary (2026-01-23)

**What was accomplished:**
- SQLite setup and verification
- Cross-platform development documentation
- Platform verification script (`scripts/check_platform.py`)
- Deployment checklist documentation
- PRD for application orchestration (20 user stories)
- This project manager knowledge base

**What's next:**
- Begin implementing `ApplicationOrchestrator` (US-OSC-001)
- Can use Ralph agent or manual implementation

**Unfinished work:**
- None - clean handoff point

**Questions for human:**
- None pending

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-23 | Claude | Initial project manager knowledge base |
