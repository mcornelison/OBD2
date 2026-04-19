# Project Roadmap

**Project**: Eclipse OBD-II Performance Monitoring System
**Last Updated**: 2026-04-11
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
| 5.5 | Pi Deployment | **Active** | Pi setup, CI/CD, database init, testing on hardware |
| 6 | Hardware Integration | Planned | Touch screen display, Pi-specific hardware |
| 6.5 | ECMLink Integration | Future | Programmable ECU, wideband AFR, knock data |
| 7 | Polish & Deploy | Planned | snake_case migration, dependency cleanup, production hardening |
| -- | Tuning Intelligence | **Active** | Alert thresholds, display content, server analysis, PID validation (cross-cutting) |

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

## Phase 5.5: Pi Deployment (Groomed)

All backlog items groomed with PRDs or checklists. The Pi 5 with HDMI touch screen is available (no UPS power unit yet).

### Scope

- Pi 5 initial setup (OS, SSH, networking, display)
- CI/CD pipeline (Windows dev → Pi deployment)
- Database verify and initialize script
- Testing on Pi hardware (simulator + real Bluetooth OBD2)
- Remote Ollama server integration

### Pre-Deployment (do before deploying to Pi)

- B-020: Fix Config Drift in obd_config.json (High, S) -- **Complete**
- B-021: Push Unpushed Commits to Remote (High, S) -- **Complete**

### Related Backlog Items and PRDs

| Item | PRD | Stories | Status |
|------|-----|---------|--------|
| B-012: Pi 5 Initial Setup (EclipseTuner) | CIO manual checklist (in backlog item) | n/a | Groomed |
| B-013: CI/CD Pipeline | `pm/prds/prd-pi-deployment.md` | US-DEP-001 through US-DEP-007 | **Complete** |
| B-015: Database Verify & Init | `pm/prds/prd-database-verify-init.md` | US-DBI-001 through US-DBI-004 | **In Progress** (Ralph) |
| B-016: Remote Ollama (Chi-srv-01) | `pm/prds/prd-remote-ollama.md` | US-OLL-001 through US-OLL-005 | **In Progress** (Ralph) |
| B-022: Chi-srv-01 Companion Service | `pm/prds/prd-companion-service.md` | US-CMP-001 through US-CMP-009 | **Groomed** |
| B-023: WiFi-Triggered Sync & AI | None yet | n/a | Pending |
| B-024: Remove Local Ollama References | None yet | n/a | Pending |
| B-026: Simulate DB Validation Test | None yet | n/a | Pending |
| B-027: Client-Side Sync to Chi-Srv-01 | None yet | n/a | Pending (depends B-022, B-023) |
| B-014: Pi 5 Testing | `pm/prds/prd-pi-testing.md` | US-PIT-001 through US-PIT-004 | Groomed (blocked) |

### Dependency Chain

```
B-020 (Fix Config) ──── Complete
B-021 (Push Commits) ── Complete

B-012 (Pi Setup - EclipseTuner) ─────┐
    |                                 │
    ├── B-013 (CI/CD Pipeline) ───────┤
    │       |                         │
    │       └── B-014 (Pi Testing) ◄──┘
    |
    └── B-015 (Database Init) ────── B-014 (Pi Testing)

B-016 (Remote Ollama Config) ─── B-024 (Remove Local Ollama Refs)
    |
    └── B-022 (Chi-srv-01 Companion Service) ── separate repo: OBD2-Server
            |
            ├── B-027 (Client-Side Sync) ── EclipseTuner repo changes
            |
            └── B-023 (WiFi-Triggered Sync & AI) ── depends on B-012, B-013, B-022, B-027

B-026 (Simulate DB Validation Test) ── enforces new Definition of Done

B-014 (Pi Testing) ── last in chain, depends on B-012, B-013, B-015
```

### Named Infrastructure

| Name | Hostname | IP | Type | Purpose |
|------|----------|----|------|---------|
| **EclipseTuner** | chi-eclipse-tuner | 10.27.27.28 | Raspberry Pi 5 (8GB) | In-vehicle OBD-II monitor |
| **Chi-srv-01** | Chi-Srv-01 | 10.27.27.10 | Debian 13 server (i7-5960X, 128GB, 2TB RAID5) | Ollama LLM host (CPU) + companion service |
| **Chi-NAS-01** | Chi-NAS-01 | 10.27.27.121 | Synology 5-disk RAID NAS | Secondary backup target |
| **DeathStarWiFi** | -- | 10.27.27.0/24 | Home WiFi SSID | Triggers sync/backup/AI when Pi connects |

**Chi-srv-01 specs (updated 2026-04-09)**: i7-5960X (8c/16t), 128GB DDR4, 12GB NVIDIA GPU (GPU-accelerated Ollama), 2TB RAID5 SSD, Debian 13.

---

## Tuning Intelligence (Cross-Cutting, Active)

**Source**: Spool Tuning Spec (2026-04-10) — comprehensive tuning SME specifications
**Epic**: E-10 in `backlog.json`
**Status**: 32 stories across 5 backlog items. Phase 1 items buildable now, Phase 2 items blocked on ECMLink.

Spool (Tuning SME) delivered domain knowledge that drives the system's intelligence layer. This work spans multiple phases and systems.

### Backlog Items

| Item | Stories | Status | Phase Dependency |
|------|---------|--------|-----------------|
| B-028: Phase 1 Alert Thresholds | US-107 – US-112 (6) | Groomed | Buildable now |
| B-029: Phase 2 Alert Thresholds + Ethanol Interpolation | US-113 – US-120 (8) | Blocked | Needs ECMLink (summer 2026) |
| B-030: Tuning-Driven Display Layout | US-121 – US-128 (8) | Groomed | Needs B-007 hardware layer |
| B-031: Server Analysis Pipeline | US-129 – US-135 (7) | Groomed | Needs B-022 companion service |
| B-032: PID Polling Validation + Data Architecture | US-136 – US-138 (3) | Groomed | US-136 buildable now; US-137/138 design work |

### Spool's Vehicle Modification Roadmap

Maps software features to vehicle hardware state. Drives sprint planning.

**Tuning Phase 0 — Pre-Hardware (NOW, April 2026)**
- Vehicle: Car in garage, battery charger, Pi on desk
- System: 144+ modules built, simulator working, no live data
- Build: Current sprint work (orchestration, DB verify, Ollama cleanup)
- Build: Alert threshold engine (B-028) against simulator
- Build: Drive summary generation (US-135)
- Build: Display rendering for 3.5" screen (B-030)
- Spool provides: All thresholds, examples, analysis specs (delivered)

**Tuning Phase 1 — First Live Connection (May–June 2026)**
- Vehicle: Out of storage, driving on pump gas, stock ECU
- Pi: Installed in car, OBDLink LX Bluetooth connected
- Data: OBD-II only, ~5 PIDs/sec, ~18,000 rows/hour
- Milestone: **First real datalog uploaded to server**
- System: Core 5 PIDs at 1 Hz, coolant/RPM/status on display, Phase 1 alerts, local storage, WiFi sync, drive summaries
- Server: Baseline comparison, thermal analysis
- Spool validates: First live data, PID support, sensor accuracy, baseline establishment

**Tuning Phase 2 — ECMLink + Wideband (June–July 2026)**
- Vehicle: ECMLink flashed, wideband installed, pump gas
- New hardware: Fuel pump, flex fuel sensor, exhaust upgrade
- Data: OBD-II + ECMLink serial (if Pi can receive), ~540,000 rows/hour
- Milestone: **First WOT datalog with real AFR and knock data**
- System: All Phase 1 + ECMLink ingestion, AFR/boost on display, ALL Phase 2 alerts (B-029), knock correlation (US-129), AFR drift trending (US-130)
- Server: Establishes "real" baseline with full data

**Tuning Phase 3 — E85 + Full Tune (July–August 2026)**
- Vehicle: Injectors swapped, E85 in tank, flex fuel active, tuned
- Data: Full ECMLink + flex fuel sensor
- Milestone: **First E85 datalog with ethanol-adjusted thresholds**
- System: All Phase 2 + ethanol-aware AFR thresholds (US-115 interpolation), E85 content tracking (US-133), IDC tracking (US-131), full baseline comparison (US-134), all 6 server analyses

**Tuning Phase 4 — Mature System (September 2026+)**
- Vehicle: Fully tuned, E85, all monitoring active
- System: Multi-drive trend analysis, seasonal comparison, anomaly detection, advisory messages pushed to Pi

**Tuning Phase 5 — Edge Intelligence (Future, late 2026+)**
- Requires: Full summer of clean data, validated pipelines, proven thresholds
- Could become: Small ML model on Pi, predictive alerts, automatic tune suggestions (validated by Spool), closed-loop tune adjustments

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

## Phase 6.5: ECMLink Integration (Future)

**PRD**: None yet
**Prerequisite**: Programmable ECU installed in vehicle, Pi deployment complete
**Target**: Q2/Q3 2026 (ECMLink install planned for spring/summer when Chicago temps warm up)

The project's ultimate purpose is gathering OBD-II data to inform ECU tuning via ECMLink V3. This phase adds:

- Data export formatted for ECMLink's Excel import
- AI recommendations that reference specific fuel map / timing map cells
- Before/after drive comparison for tuning impact tracking
- Tuning session log (date, parameter, old value, new value)

### Related Backlog Items

- B-025: ECMLink Data Integration (Medium, L)

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
| B-012 | Pi 5 Initial Setup | **High** | M | Complete | 5.5 |
| B-013 | CI/CD Pipeline (Win → Pi) | **High** | M | Complete | 5.5 |
| B-014 | Pi 5 Testing (Sim + Real) | **High** | L | Groomed (blocked) | 5.5 |
| B-015 | Database Verify & Initialize | **High** | S | **In Progress** (Ralph) | 5.5 |
| B-016 | Remote Ollama Server | Medium | M | **Complete** | 5.5 |
| B-022 | Chi-srv-01 Companion Service | **High** | L | **Groomed** (PRD ready) | 5.5 |
| B-023 | WiFi-Triggered Sync & AI | **High** | M | Pending | 5.5 |
| B-024 | Remove Local Ollama References | **High** | S | Pending | 5.5 |
| B-025 | ECMLink Data Integration | Medium | L | Pending | 6.5 |
| B-026 | Simulate DB Validation Test | **High** | S | Pending | 5.5 |
| B-027 | Client-Side Sync to Chi-Srv-01 | **High** | M | Pending | 5.5 |
| B-017 | Add Coding Rules to Standards | **High** | S | Complete | -- |
| B-018 | Fix Specs-to-Code Drift | **High** | M | Complete | -- |
| B-019 | Split Oversized Files | Medium | XL | Pending | 7 |
| B-020 | Fix Config Drift (obd_config) | **High** | S | Complete | 5.5 |
| B-021 | Push Unpushed Commits | **High** | S | Complete | 5.5 |
| B-028 | Phase 1 Alert Thresholds | **High** | M | **Groomed** | Tuning |
| B-029 | Phase 2 Alert Thresholds + Ethanol | **High** | L | Blocked (ECMLink) | Tuning |
| B-030 | Tuning-Driven Display Layout | **High** | L | **Groomed** | Tuning |
| B-031 | Server Analysis Pipeline | **High** | L | **Groomed** | Tuning |
| B-032 | PID Polling + Data Architecture | **High** | M | **Groomed** | Tuning |

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
| 2026-01-31 | Marcus (PM) | Groomed all Phase 5.5 items. Created PRDs: prd-database-verify-init.md (B-015, 4 stories), prd-remote-ollama.md (B-016, 5 stories), prd-pi-testing.md (B-014, 4 stories). B-012 groomed as CIO checklist. B-013 already in progress via Ralph. |
| 2026-01-31 | Marcus (PM) | Added B-022 (Chi-srv-01 companion), B-023 (WiFi-triggered sync), B-024 (remove local Ollama refs). Named infrastructure: EclipseTuner, Chi-srv-01, DeathStarWiFi. Updated dependency chain. |
| 2026-01-31 | Marcus (PM) | Phase 5.5 now Active. B-012 In Progress, B-013 Complete, B-015/B-016 In Progress (Ralph). ECMLink target Q2/Q3 2026. |
| 2026-02-01 | Marcus (PM) | Groomed B-022 into PRD (9 stories, FastAPI, MySQL, separate repo). Created B-026 (simulate DB validation), B-027 (client-side sync). Updated dependency chain. |
| 2026-02-02 | Marcus (PM) | Chi-Srv-01 specs finalized. Repo created: `OBD2-Server`. Updated IP 10.27.27.100 → 10.27.27.10. CPU-only Ollama inference (GT 730 not usable for AI). |
| 2026-02-05 | Marcus (PM) | Session 10: OBD-II research complete — protocol constraints, stock PIDs, safe ranges, mobile apps. Created `specs/obd2-research.md` as grounding reference for all OBD-II stories. CIO knowledge captured (driving patterns, preferences, hardware plan). Added PM Rule 7 (no fabricated data). |
| 2026-04-11 | Marcus (PM) | Session 14: Processed Spool's tuning spec (2026-04-10) into backlog. Created Epic E-10 (Tuning Intelligence) with 5 new items (B-028 – B-032), 32 stories (US-107 – US-138). Added Spool's 5-phase vehicle modification roadmap. Updated Chi-Srv-01 specs (GPU upgrade). Updated B-016 to Complete. Story counter advanced to US-139. |
