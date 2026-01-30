# Project Roadmap

**Project**: Eclipse OBD-II Performance Monitoring System
**Last Updated**: 2026-01-29
**Target Platform**: Raspberry Pi 5

---

## Phase Summary

| Phase | Name | Status | Key Deliverable |
|-------|------|--------|-----------------|
| 1 | Foundation | Complete | Config, logging, error handling, test framework |
| 2 | OBD-II Core | Complete | 12 modules: database, OBD connection, VIN, alerts, stats, profiles, display, export, AI |
| 3 | Simulator | Complete | Physics-based OBD simulator for hardware-free testing |
| 4 | Module Refactoring | Complete | Clean subpackage architecture, 16 user stories |
| 5 | Application Orchestration | **Active** | Main loop, startup/shutdown, deployment |
| 5.5 | Pi Deployment | **Planned** | Pi setup, CI/CD, database init, testing on hardware |
| 6 | Hardware Integration | Planned | Touch screen display, Pi-specific hardware |
| 7 | Polish & Deploy | Planned | snake_case migration, dependency cleanup, production hardening |

---

## Phase 5: Application Orchestration (Active)

**PRD**: `pm/prds/prd-application-orchestration.md`
**Status**: 0/20 user stories complete

### Scope

- ApplicationOrchestrator class (central lifecycle management)
- Startup/shutdown sequences
- Component wiring (connect all 12 modules)
- Background thread management
- Backup integration (Google Drive)
- systemd service setup for Pi
- Integration and end-to-end testing

### Related Backlog Items

- B-002: Comprehensive Backup Strategy (partially covered by US-TD-012, US-TD-013)

---

## Phase 5.5: Pi Deployment (Planned)

No PRD yet. Composed of backlog items. The Pi 5 with HDMI touch screen is now available (no UPS power unit yet).

### Scope

- Pi 5 initial setup (OS, SSH, networking, display)
- CI/CD pipeline (Windows dev → Pi deployment)
- Database verify and initialize script
- Testing on Pi hardware (simulator + real Bluetooth OBD2)
- Remote Ollama server integration

### Pre-Deployment (do before deploying to Pi)

- B-020: Fix Config Drift in obd_config.json (High, S) -- display 480x320, retention 365 days
- B-021: Push Unpushed Commits to Remote (High, S) -- 77 commits ahead of origin

### Related Backlog Items

- B-012: Pi 5 Initial Setup and Configuration (High, M)
- B-013: CI/CD Pipeline -- Windows to Pi (High, M) -- depends on B-012, B-021
- B-015: Database Verify and Initialize Script (High, S)
- B-014: Pi 5 Testing -- Simulated + Real OBD2 (High, L) -- depends on B-012, B-013, B-015
- B-016: Remote Ollama Server Integration (Medium, M)

### Dependency Chain

```
B-020 (Fix Config) ──┐
                      ├── B-021 (Push Commits) ──┐
                      │                           │
B-012 (Pi Setup) ─────┤                           │
    |                 │                           │
    ├── B-013 (CI/CD Pipeline) ──── depends on B-021
    │       |
    │       └── B-014 (Pi Testing)
    |
    └── B-015 (Database Init)
            |
            └── B-014 (Pi Testing)

B-016 (Remote Ollama) -- independent, can proceed in parallel
```

---

## Phase 6: Hardware Integration (Planned)

**PRD**: `pm/prds/prd-raspberry-pi-hardware-integration.md`

### Scope

- OSOYOO 3.5" HDMI touch screen driver (480x320)
- Touch input handling (tap, swipe)
- Full-screen dashboard UI
- Power management via Geekworm X1209 UPS HAT (when available)

### Related Backlog Items

- B-007: Touch Screen Display Support

---

## Phase 7: Polish & Deploy (Planned)

No PRD yet. Composed of backlog items:

- B-019: Split oversized files (XL) -- orchestrator.py critical
- B-006: snake_case migration (XL)
- B-004: Dependency evaluation (S)
- B-003: Ollama fallback documentation (S)
- B-008: Data retention update (S)
- B-009: Error classification docs fix (S)
- B-010: Pi target docs update (S)
- B-001: Test runner cleanup (S)
- B-005: Commit untracked docs (S)

---

## Backlog Summary

| ID | Title | Priority | Size | Status | Phase |
|----|-------|----------|------|--------|-------|
| B-001 | Clean Up Test Runner Scripts | Low | S | Pending | 7 |
| B-002 | Comprehensive Backup Strategy | Medium | L | Groomed | 5 |
| B-003 | Document Ollama Fallback | Medium | S | Pending | 7 |
| B-004 | Evaluate Dependencies | Medium | S | Pending | 7 |
| B-005 | Commit Untracked Docs | Low | S | Pending | 7 |
| B-006 | snake_case Migration | Medium | XL | Pending | 7 |
| B-007 | Touch Screen Display | Medium | L | Pending | 6 |
| B-008 | Data Retention Update | Low | S | Pending | 7 |
| B-009 | Error Classification Docs | Low | S | Pending | 7 |
| B-010 | Pi Target Docs Update | Low | S | Pending | 7 |
| B-011 | OBD2 Patterns Reference | Low | L | Complete | -- |
| B-012 | Pi 5 Initial Setup | **High** | M | Pending | 5.5 |
| B-013 | CI/CD Pipeline (Win → Pi) | **High** | M | Pending | 5.5 |
| B-014 | Pi 5 Testing (Sim + Real) | **High** | L | Pending | 5.5 |
| B-015 | Database Verify & Initialize | **High** | S | Pending | 5.5 |
| B-016 | Remote Ollama Server | Medium | M | Pending | 5.5 |
| B-017 | Add Coding Rules to Standards | **High** | S | Complete | -- |
| B-018 | Fix Specs-to-Code Drift | **High** | M | Complete | -- |
| B-019 | Split Oversized Files | Medium | XL | Pending | 7 |
| B-020 | Fix Config Drift (obd_config) | **High** | S | Groomed | 5.5 |
| B-021 | Push Unpushed Commits | **High** | S | Groomed | 5.5 |

---

## Critical Path

```
Phase 5 (Orchestration)
    |
    ├── US-OSC-001: ApplicationOrchestrator class
    │       |
    │       ├── US-OSC-002: Startup sequence
    │       │       |
    │       │       └── US-OSC-005: Main loop wiring
    │       │               |
    │       │               └── US-OSC-015: Integration tests
    │       |
    │       └── US-OSC-003: Shutdown sequence
    |
    └── US-TD-012/013: Backup integration
            |
            v
Phase 5.5 (Pi Deployment)
    |
    ├── B-012: Pi Setup
    │       |
    │       ├── B-013: CI/CD → B-014: Testing
    │       |
    │       └── B-015: DB Init → B-014: Testing
    |
    └── B-016: Remote Ollama (parallel)
            |
            v
Phase 6 (Hardware) → Phase 7 (Polish)
```

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-29 | Marcus (PM) | Initial roadmap from restructured project data |
| 2026-01-29 | Marcus (PM) | Added Phase 5.5 (Pi Deployment): B-012 through B-016, expanded B-002 |
| 2026-01-29 | Marcus (PM) | Added B-017 through B-021 from developer reports; B-017, B-018 completed (specs fixes) |
