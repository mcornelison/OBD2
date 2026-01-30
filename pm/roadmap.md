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
| 6 | Hardware Integration | Planned | Touch screen display, Pi-specific hardware |
| 7 | Polish & Deploy | Planned | snake_case migration, dependency cleanup, production deploy |

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

- B-002: Daily Backup to Google Drive (partially covered)

---

## Phase 6: Hardware Integration (Planned)

**PRD**: `pm/prds/prd-raspberry-pi-hardware-integration.md`

### Scope

- OSOYOO 3.5" HDMI touch screen driver (480x320)
- Touch input handling (tap, swipe)
- Full-screen dashboard UI
- Power management via Geekworm X1209 UPS HAT

### Related Backlog Items

- B-007: Touch Screen Display Support

---

## Phase 7: Polish & Deploy (Planned)

No PRD yet. Composed of backlog items:

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

| ID | Title | Priority | Size | Status |
|----|-------|----------|------|--------|
| B-001 | Clean Up Test Runner Scripts | Low | S | Pending |
| B-002 | Daily Backup to Google Drive | Medium | M | Groomed |
| B-003 | Document Ollama Fallback | Medium | S | Pending |
| B-004 | Evaluate Dependencies | Medium | S | Pending |
| B-005 | Commit Untracked Docs | Low | S | Pending |
| B-006 | snake_case Migration | Medium | XL | Pending |
| B-007 | Touch Screen Display | Medium | L | Pending |
| B-008 | Data Retention Update | Low | S | Pending |
| B-009 | Error Classification Docs | Low | S | Pending |
| B-010 | Pi Target Docs Update | Low | S | Pending |
| B-011 | OBD2 Patterns Reference | Low | L | Complete |

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
    │       │                       |
    │       │                       └── Phase 6 (Hardware)
    │       │                               |
    │       │                               └── Phase 7 (Polish)
    │       |
    │       └── US-OSC-003: Shutdown sequence
    |
    └── US-TD-012/013: Backup integration
```

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-29 | Marcus (PM) | Initial roadmap from restructured project data |
