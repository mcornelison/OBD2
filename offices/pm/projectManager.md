# Project Manager Knowledge Base

## PM Identity

**Name**: Marcus
**Role**: Project Manager for the Eclipse OBD-II Performance Monitoring System
**Reports To**: CIO (project owner)
**Scope**: PRD creation, user story grooming, acceptance criteria, specs governance. Marcus never writes code.

## Purpose

This document serves as long-term memory for AI-assisted project management of the Eclipse OBD-II Performance Monitoring System. It captures session context, decisions, risks, and stakeholder information.

**Last Updated**: 2026-04-13 (Session 14)
**Current Phase**: Tuning Intelligence Active — 6 sprints shipped, Infrastructure Pipeline MVP PRD drafted (pending Ralph's B-040 arch reorg), Spool review gate operational

---

## Project Vision

The Eclipse OBD-II Performance Monitoring System is a **data collection and analysis platform** that ultimately feeds into ECU tuning decisions. The full workflow:

```
[Drive Vehicle] → [Collect OBD-II Data] → [Analyze with AI on Chi-Srv-01]
        ↓                                           ↓
[Store in SQLite] ← ← ← ← ← ← ← ← ← [AI Recommendations]
        ↓
[CIO reviews data + recommendations]
        ↓
[Apply tuning changes via ECMLink V3]
        ↓
[Drive again → compare before/after]
```

### ECMLink V3 Context

The CIO plans to upgrade the Eclipse GST with a **programmable ECU** running **ECMLink V3** from [ECMTuning](https://www.ecmtuning.com/). ECMLink is the industry-standard tuning tool for 1990-1999 DSM (Diamond Star Motors) vehicles.

**What ECMLink does:**
- Direct access to fuel maps, timing maps, airflow tables, boost control
- Datalogging at 1000+ samples/sec (much faster than standard OBD-II)
- Speed density mode, GM MAF translation, dual-bank injector control
- Wideband O2 integration for real-time air-fuel ratio monitoring
- Excel-compatible data import/export (copy-paste)

**What THIS project provides to the ECMLink workflow:**
- Long-term OBD-II data collection across multiple drives
- Statistical analysis (max, min, avg, std dev, outliers) per parameter
- AI-powered recommendations for fuel map and timing adjustments
- Drive-by-drive comparison to track tuning impact
- Alert system for out-of-range values during drives
- Data export for offline analysis

**Key tuning parameters our system monitors:**
- Air-fuel ratio (critical for fuel map tuning)
- RPM and load (the X/Y axes of fuel and timing maps)
- Coolant temperature (affects fuel enrichment)
- Throttle position (load input)
- Boost pressure (turbo tuning)
- Intake air temperature (density correction)

**Current status**: ECMLink not yet installed. The Eclipse is on the stock ECU. Our system monitors via standard OBD-II now. When the programmable ECU is installed, the data we're already collecting will inform the initial tune, and ongoing monitoring will track the impact of tuning changes.

---

## PM Rules

1. **Marcus never writes code.** He creates, grooms, and revises user stories and PRDs.
2. **Input sources**: CIO direction, `pm/tech_debt/`, `pm/issues/`, `pm/blockers/`, and project analysis.
3. **Marcus owns `specs/`** -- the core guidelines and principles developers follow.
4. **No duplicate information.** Each fact lives in exactly one document. Documents reference each other.
5. **Clear acceptance criteria** on every backlog item and user story. Assume working code, but the CIO must be able to validate input/output matches expectations.
6. **Validation scripts** are part of user stories when the developer doesn't have direct database access. The story specifies the test program to write for verifying data in/out.
7. **No fabricated data.** All thresholds, ranges, test data, and acceptance criteria must be grounded in research, actual vehicle data, or explicit CIO input. Never invent placeholder values. Stories requiring real data that is not yet available must be marked `blocked` until data is provided. (CIO directive, Session 10)

---

## Naming Conventions

### Prefixes

| Prefix | Meaning | Owner | Detail Level |
|--------|---------|-------|--------------|
| **B-XXX** | Backlog item | Marcus (PM) | High-to-medium level. Gets groomed into a PRD. |
| **US-XXX** | User story | Developer/Ralph | Developer-ready. Lives inside PRDs and `stories.json`. |
| **I-XXX** | Issue | Anyone | Bug or defect discovered during development. |
| **BL-XXX** | Blocker | Marcus (PM) | Item preventing progress on work. |
| **TD-XXX** | Tech debt | Marcus (PM) | Known shortcut needing future remediation. |

### Backlog Status Definitions

| Status | Meaning |
|--------|---------|
| **Pending** | Identified but not yet detailed. Needs grooming before work can begin. |
| **Groomed** | Acceptance criteria written, validation requirements defined. Ready for PRD creation. |
| **In Progress** | Actively being worked via a PRD and Ralph execution. |
| **Complete** | All acceptance criteria met, CIO has validated input/output. |

**Workflow**: `B-` items are groomed into PRDs containing `US-` stories. The PRD is converted to `ralph/stories.json` for autonomous execution.

---

## Folder Structure

```
pm/                              # Marcus's domain
├── projectManager.md            # This file (session memory, decisions, risks)
├── roadmap.md                   # Living project roadmap and phase tracking
├── backlog/                     # Active backlog items (B-XXX.md)
│   └── _template.md             # Standard template for new items
├── prds/                        # Product Requirements Documents
├── archive/                     # Completed B- items and historical data
├── issues/                      # Discovered bugs
├── blockers/                    # Items blocking progress
├── backlog.json                 # Hierarchical backlog (Epic > Feature > Story)
├── story_counter.json           # Global sequential story ID counter
└── tech_debt/                   # Known shortcuts needing future work

specs/                           # Developer reference (Marcus governs, devs consume)
├── architecture.md              # System design, data flow
├── standards.md                 # Coding conventions, naming rules
├── methodology.md               # TDD workflow, processes
├── anti-patterns.md             # What NOT to do
├── glossary.md                  # Domain terminology
├── samples/                     # Reference docs, hardware specs
└── user-stories/                # Ralph user story format guide
```

---

## Workflow

```
CIO provides direction / input
       |
       v
Marcus creates or updates pm/backlog/B-XXX.md
       |
       v
Marcus grooms B- items (adds acceptance criteria, validation requirements)
       |
       v
Marcus writes pm/prds/prd-feature.md (detailed PRD with US- user stories)
       |
       v
PRD converted to ralph/stories.json (US- prefixed stories)
       |
       v
Developer/Ralph executes user stories
       |
       v
CIO validates output against acceptance criteria
       |
       v
Completed B- items move to pm/archive/
```

---

## Quick Context for New Sessions

When starting a new session, read this section first:

### Current State (2026-04-13)

- **What's Done**:
  - **Sprints 1–6 complete across April**: 54 stories shipped across B-002 (Application Orchestration, 20), B-015 (DB Verify, 4), B-024 (Ollama Cleanup, 3), B-026 (Sim DB Validation, 3), B-028 (Phase 1 Alert Thresholds, 6+1 rework), B-030 (Display Layout, 8), B-032 (PID Polling + Phase 2 Data Architecture, 3), B-033 (Legacy Profile Cleanup, 5), B-034 (Battery Voltage Config hotfix, 1)
  - **Test count: 1,517 passing** (up from 408 at start of month)
  - **Epic E-10 Tuning Intelligence created** from Spool's 2026-04-10 tuning spec: 5 backlog items (B-028–B-032), 32 stories
  - **Spool review gate established**: `/review-stories-tuner` skill catches spec errors before sprints; sprint 4 (US-139 RPM hotfix) and sprint 5 (B-033 audit cleanup) are the result of the gate being applied retrospectively to sprint 1/2 work
  - **offices/ restructure committed**: 108 files renamed from root `pm/`, `ralph/`, `tester/` → `offices/` prefix
  - **Architectural decisions brief** delivered to `offices/ralph/inbox/2026-04-12-from-marcus-architectural-decisions-brief.md` covering 5 open decisions (legacy threshold deprecation, orchestrator refactor, snake_case migration, Phase 2 data architecture, companion service)
- **What's In Progress**:
  - **Ralph is running B-040 structural reorganization** on `sprint/reorg-sweep1-facades` branch. 6 sweep plans exist in `docs/superpowers/plans/2026-04-12-reorg-sweep*.md`. This is the architectural reorg CIO authorized. Marcus is OUT of Ralph's way until reorg completes.
  - **Infrastructure Pipeline MVP PRD exists as DRAFT**: `offices/pm/prds/prd-infrastructure-pipeline-mvp.md`. Covers sprints 7/8/9 (server MVP, drive scenarios, B-022/B-027 deepening). 9 new stories planned (US-147–155). **Cannot be promoted to active until Ralph's reorg completes** — 12 `TBD after arch reorg` markers await real file paths.
- **Active Sprint PRDs**: None active (Ralph working on B-040 reorg, no story-tracked sprint running)
- **Other Active PRDs**:
  - `prd-companion-service.md` (B-022, 9 stories — 7 go in sprint 7, 3 in sprint 9 per draft PRD)
  - `prd-application-orchestration.md` (B-002, complete)
  - `prd-database-verify-init.md` (B-015, complete)
  - `prd-simulate-db-validation.md` (B-026, complete)
  - `prd-ollama-local-cleanup.md` (B-024, complete)
  - `prd-pi-deployment.md` (B-013, complete)
  - `prd-pi-testing.md` (B-014, groomed, needs real Pi hardware time)
  - `prd-raspberry-pi-hardware-integration.md` (B-007, 13 stories, pending)
  - `prd-infrastructure-pipeline-mvp.md` (**DRAFT** — pending arch reorg)
- **Pi 5 Status**: Hardware up at `10.27.27.28` but NOT yet connected to the Eclipse. CIO confirmed 2026-04-12. Ready for future sim-mode testing once reorg completes.
- **Target Platform**: Raspberry Pi 5 (developing on Windows)
- **Backlog**: 34 items total (B-001 through B-034), 20/34 features complete. See `pm/backlog.json` for full hierarchy.
- **Git**: `main` is 5 commits ahead of origin (includes draft PRD at `d794048` + 4 Ralph reorg planning docs). **Not pushed** — CIO's call when. Ralph's reorg branch `sprint/reorg-sweep1-facades` has active work including a duplicate copy of the draft PRD (cherry-pick artifact — will merge cleanly).
- **Agents**: Ralph (Rex) actively working on B-040 reorg. Spool (Tuner SME) delivered review + code audit + hotfix acknowledgment 2026-04-12.
- **Story Counter**: Next ID is US-146 (Infrastructure Pipeline MVP PRD will advance to US-156 when promoted)
- **Stats**: 120/168 stories complete (71%), 20/34 features done, 8 stories blocked (B-029 Phase 2 thresholds + ECMLink-dependent work)

### Immediate Next Actions

1. **Wait for Ralph** to finish B-040 structural reorg. Do NOT launch new sprints or create backlog items until reorg is merged to main.
2. **When Ralph is done**: Promote Infrastructure Pipeline MVP PRD to active (walk the Finalization Checklist at bottom of PRD — fill TBD markers, create B-035, update B-022/B-027, update backlog.json + story_counter.json)
3. **Push to origin** (5 commits ahead, CIO's call on timing — may want to wait until Ralph's reorg lands so one clean push)
4. **After sprint 7 launches**: monitor Ralph's run of the 10-story Infrastructure MVP sprint
5. **CIO parallel work**: OBDLink LX Bluetooth pairing with Pi (MAC `00:04:3E:85:0D:FB`), real dongle testing — unlocks swap from `--simulate` to real OBD data
6. **After sprint 9 completes**: B-031 Server Analysis Pipeline (Spool's 7 analysis stories) unblocks — real AI analysis becomes possible
7. **Eventually**: Process the 5 open architectural decisions in Ralph's inbox (legacy threshold deprecation, orchestrator refactor, snake_case migration, Phase 2 data architecture, companion service review)

### Key Files to Read First

| Purpose | File |
|---------|------|
| Project instructions | `CLAUDE.md` |
| Architecture | `specs/architecture.md` |
| OBD-II reference | `specs/obd2-research.md` |
| Grounded knowledge | `specs/grounded-knowledge.md` |
| Roadmap | `pm/roadmap.md` |
| Active PRD | `pm/prds/prd-application-orchestration.md` |
| Backlog (structured) | `pm/backlog.json` |
| Backlog items (detail) | `pm/backlog/B-*.md` |
| Story counter | `pm/story_counter.json` |

---

## Stakeholder Information

### Project Owner (CIO)

- **Role**: Solo developer / hobbyist
- **Technical Level**: Experienced developer, familiar with Python. New to car tuning.
- **Vehicle**: 1998 Mitsubishi Eclipse GST (2G DSM, 4G63 turbo). VIN: `4A3AK54F8WE122916`. Weekend summer project car, city driving, no WOT/dyno/autocross. Stock ECU with bolt-on mods (cold air intake, BOV, fuel pressure regulator, fuel lines, oil catch can, coilovers, engine/trans mounts) -- full list tracked in `G:\My Drive\Eclipse\Eclipse 1998 Projects.gsheet`. No fuel/air map changes yet; that changes when ECMLink is installed.
- **Hardware**: Raspberry Pi 5, OBDLink LX Bluetooth dongle (see `specs/architecture.md`), OSOYOO 3.5" HDMI touch screen, Geekworm X1209 UPS (have it, waiting on battery + case mod)
- **Planned Upgrade**: Programmable ECU with ECMLink V3 (owned, not yet installed). Laptop available at car with network access for ECMLink use.
- **Pi Mounting**: Glovebox or trunk. Display on dash (low profile). Long HDMI cable to trunk is fine. Easy connect/disconnect: USB-C power + HDMI in trunk, cables stay routed.
- **Power**: Battery → fuse → UPS (Geekworm X1209) → Pi. Boots on AUX power. Multiple start/stop cycles per outing are normal.
- **Driving Pattern**: Summer car. Lots of short rides, several 30+ min, maybe 1-2 over 1 hour per weekend. Never tracked exact driving time.

### Working Preferences

- Prefers comprehensive documentation before implementation
- Uses Ralph autonomous agent system for routine development work
- Values TDD methodology -- tests before implementation
- Appreciates detailed PRDs with clear acceptance criteria
- Wants to validate data input/output against expectations
- Comfortable with AI assistance for both planning and coding
- **Data integrity is paramount**: "We MUST NOT GUESS or make up random stuff that is not grounded in reality." All values must be sourced from research, real data, or explicit CIO input. Stories needing real data should be blocked, not filled with placeholders.
- **Reports**: Human-readable text on Chi-Srv-01 first. Get it working, then format/delivery. Simple.
- **Comparison style**: Always have a baseline. Trend-oriented -- "are we getting better?"
- **Alerts**: Out-of-normal range, anything that would cause permanent engine damage. Values based on community-sourced safe ranges (see `specs/obd2-research.md`).
- **Data retention**: 90 days on Pi (purge only after confirmed sync), forever on server.
- **WiFi/Sync**: Offline is NORMAL. Never error on no network. Auto-sync when DeathStarWiFi detected.
- **Multi-vehicle**: Could see this used on another vehicle or shared with friends.

### Constraints

- Development environment: Windows (MINGW64)
- Production environment: Raspberry Pi 5 (Linux)
- Limited time availability -- work done in sessions
- No continuous integration yet -- manual testing
- No sample OBD-II data yet -- CIO will collect when possible. Stories requiring real data should be blocked.
- Chicago climate: summers hot (glovebox heat concern), winters the car is in storage

---

## Key Technical Decisions

| Date | Decision | Rationale | Alternatives Considered |
|------|----------|-----------|------------------------|
| 2026-01-21 | camelCase for functions | Project standard consistency | PEP8 snake_case |
| 2026-01-21 | SQLite for storage | Analytics queries, portability, Pi-friendly | Flat files, PostgreSQL |
| 2026-01-21 | WAL mode for SQLite | Better concurrent performance | Default journal mode |
| 2026-01-22 | Physics-based simulator | Realistic test data | Random value generation |
| 2026-01-22 | Re-export facades | Backward compatibility | Breaking change migration |
| 2026-01-23 | Orchestrator pattern | Central lifecycle management | Scattered initialization |
| 2026-01-29 | PM/specs restructure | Single source of truth, no duplication | Keep flat structure |
| 2026-01-29 | Remote Ollama server | Pi 5 lacks GPU; separate server hosts Ollama, Pi connects via HTTP on home WiFi | On-device Ollama, cloud API |
| 2026-01-29 | rsync+SSH for CI/CD | Simple, reliable Win→Pi deployment via MINGW64 | Docker, Ansible, GitHub Actions |
| 2026-01-29 | Rename prd.json → stories.json | Matches hierarchy: Backlog → PRD → User Stories. Ralph executes stories, not PRDs. | Keep prd.json |
| 2026-01-31 | Pi 5 hostname: EclipseTuner | CIO naming preference for the in-vehicle Pi | eclipse-pi, raspberrypi |
| 2026-01-31 | LLM server: Chi-srv-01 | Dedicated local server for Ollama (CPU inference, 128GB RAM); Pi never runs LLM locally | Local Ollama on Pi, cloud API |
| 2026-01-31 | Home WiFi: DeathStarWiFi | SSID triggers auto-sync, backup, and AI when Pi connects home | Manual trigger, always-on WiFi |
| 2026-01-31 | Companion service on Chi-srv-01 | Counterpart app to receive data/backups and serve AI from Chi-srv-01 | Direct Ollama API only |
| 2026-01-31 | Remove all local Ollama references | Pi 5 will never run Ollama locally; clean codebase of misleading references | Leave as-is with remote default |
| 2026-01-31 | Network: 10.27.27.0/24 | All devices on DeathStarWiFi LAN. Pi=.28, Chi-Srv-01=.120, Chi-NAS-01=.121 | -- |
| 2026-01-31 | Separate repo for companion service | Different deployment target (Chi-Srv-01 vs Pi), different deps, independent release cadence | Monorepo (CIO initially chose, then reversed) |
| 2026-02-01 | `main` is primary branch | CIO confirmed `main` as primary; previous plan to delete `main` and use `master` is reversed | `master` as primary |
| 2026-02-01 | Tightened Definition of Done | DB-writing stories MUST include test validating data was written correctly. Story blocked if validation fails. | Unit tests only |
| 2026-02-01 | B-026 created | Simulate DB validation test -- reference implementation for new DoD policy | Tech debt only (TD-005) |
| 2026-02-01 | Companion service: FastAPI + MariaDB | Async framework with auto OpenAPI docs; MariaDB mirrors Pi SQLite schema | Flask, PostgreSQL |
| 2026-02-01 | ID mapping: source_id + UNIQUE | Pi `id` stored as `source_id`, MySQL owns `id` PK. Upsert key = `(source_device, source_id)`. Multi-device ready. | Pi ID as MySQL PK (collision risk) |
| 2026-02-01 | Ollama: /api/chat endpoint | Conversational API with system/user/assistant roles. Server owns prompt templates. | /api/generate (less structured) |
| 2026-02-01 | All tests use real MySQL | No SQLite substitutes for companion service tests. Validates actual MySQL behavior. | SQLite for unit tests |
| 2026-02-01 | Backup extensions: .db .log .json .gz | Restricted set for security. Rejects all other extensions. | Accept any file type |
| 2026-01-31 | Chi-NAS-01 as secondary backup | Synology 5-disk RAID NAS for backup redundancy | Single backup to Chi-Srv-01 only |
| 2026-02-02 | Chi-Srv-01 specs finalized | i7-5960X (8c/16t), 128GB DDR4, 12GB NVIDIA GPU (upgraded April 2026, was GT 730), 2TB RAID5 SSD, Debian 13. | -- |
| 2026-04-09 | Ollama GPU-accelerated inference | 12GB GPU replaces GT 730. Models up to ~8B fit entirely in VRAM (fast). 13B+ possible with quantization. 70B spills to 128GB RAM. | CPU-only (previous), cloud API |
| 2026-01-31 | Pi hostname: chi-eclipse-tuner | Network hostname (display name: EclipseTuner) | EclipseTuner as hostname |
| 2026-01-31 | ECMLink V3 integration planned | Project's ultimate goal: collect OBD-II data → AI analysis → inform ECU tuning via ECMLink | Manual tuning without data, third-party tuning shop |
| 2026-02-03 | MariaDB on Chi-Srv-01 | Database: `obd2db`, user: `obd2`, subnet access `10.27.27.%`. MariaDB (MySQL-compatible) already installed on server. | PostgreSQL, MySQL |
| 2026-02-05 | OBD-II protocol: ISO 9141-2 | 1998 Eclipse uses K-Line at 10,400 bps. ~4-5 PIDs/sec through Bluetooth. Slowest OBD-II protocol. | CAN (not available on this vehicle) |
| 2026-02-05 | Tiered PID polling strategy | Weighted round-robin: 5 core PIDs at ~1 Hz, rotating Tier 2 at ~0.3 Hz, slow Tier 3 at ~0.1 Hz. 3x improvement over flat polling. | Flat polling all PIDs equally |
| 2026-02-05 | Core 5 PIDs for Phase 1 | STFT (0x06), Coolant Temp (0x05), RPM (0x0C), Timing Advance (0x0E), Engine Load (0x04). Optimized for safety + insight. | All 15 PIDs equally |
| 2026-02-05 | No fabricated data (PM Rule 7) | All thresholds, ranges, and test data must be grounded in research, real vehicle data, or CIO input. Stories needing unavailable data are `blocked`. | Placeholder values |
| 2026-02-05 | Recommended app: Torque Pro | $5 Android app, confirmed on 2G DSMs, CSV export, custom PIDs. BlueDriver incompatible with OBDLink LX (closed ecosystem). | OBDLink app, BlueDriver, Car Scanner |
| 2026-02-05 | OBD-II research document | Comprehensive reference at `specs/obd2-research.md`. Safe ranges, PIDs, protocol constraints, community wisdom. Grounding doc for all OBD-II stories. | Ad-hoc research per story |
| 2026-02-05 | Purge only after confirmed sync | Pi 90-day retention purge must verify data successfully synced to Chi-Srv-01 before deletion. | Time-based purge regardless |
| 2026-02-05 | OBD-II Phase 1, ECMLink Phase 2 | Standard OBD-II for health monitoring now. ECMLink V3 (MUT protocol, 15,625 baud) unlocks knock, wideband AFR, and 10x faster logging. | OBD-II only |

Architecture decisions are detailed in `specs/architecture.md`.

---

## Current Risks and Blockers

### Active Risks

| Risk | Likelihood | Impact | Mitigation | Owner |
|------|------------|--------|------------|-------|
| Bluetooth pairing issues on Pi | Medium | High | Document troubleshooting, test early | CIO |
| Thread synchronization bugs | Medium | High | Use established patterns, thorough testing | Developer |
| Memory leaks in long runs | Low | High | Profile memory usage, stress testing | Developer |

### Blockers

See `pm/blockers/` for active blockers. Currently none.

### Technical Debt

See `pm/tech_debt/` for tracked items:
- TD-001: TestDataManager pytest collection warning
- TD-002: Re-export facade modules (can be removed after B-006)

---

## Session Handoff Checklist

When ending a session, update this section:

### Last Session Summary (2026-04-13, Session 14 - Six Sprints + Spool Review + Infra Pipeline PRD)

**What was accomplished:**

This was a marathon session spanning 2026-04-11 → 2026-04-13. Six full sprint cycles completed, Spool's tuning spec fully processed into backlog, code audit executed, and the next phase of work designed.

**Sprint cycles (6 sprints, 54 stories shipped):**
- **Sprint 1 (2026-04-01)**: 30 stories — B-002 Orchestration (20), B-015 DB Verify (4), B-024 Ollama Cleanup (3), B-026 Sim DB Validation (3). Initially blocked by Ralph launching from wrong directory (`offices/ralph/` instead of repo root); fixed `ralph.sh` to go up 2 levels for `PROJECT_ROOT` and update all file paths. 939 tests passing.
- **Sprint 2 (2026-04-02)**: 9 stories — B-028 Phase 1 Alert Thresholds (6), B-032 PID Polling + Phase 2 Data Architecture (3). 1,197 tests passing.
- **Sprint 3 (2026-04-03)**: 8 stories — B-030 Tuning-Driven Display Layout (primary screen + 5 detail pages + touch + parked mode). 1,517 tests passing.
- **Sprint 4 (2026-04-04 HOTFIX)**: 1 story — US-139 RPM dangerMin correction (7200→7000 per 97-99 2G factory redline).
- **Sprint 5 (2026-04-05)**: 5 stories — B-033 Legacy Profile Threshold Cleanup (US-140–144) from Spool's code audit variances 1-5, 7.
- **Sprint 6 (2026-04-06 HOTFIX)**: 1 story — US-145 Battery Voltage 15.0V config boundary ambiguity from Spool audit Variance 6. Ralph proactively tracked as B-034.

**Epic E-10 Tuning Intelligence created** (from Spool's 2026-04-10 tuning spec):
- 5 new backlog items: B-028, B-029, B-030, B-031, B-032
- 32 new stories: US-107 through US-138
- B-029 blocked on ECMLink hardware (summer 2026)
- B-031 blocked on B-022 companion service
- All other stories shipped in sprints 2/3

**Spool (Tuning SME) review cycle established:**
- Spool delivered comprehensive tuning spec 2026-04-10 (PIDs, thresholds, display, 6 analyses, 5 examples, 5-phase roadmap)
- Spool reviewed B-028–032 2026-04-12 with 3 corrections (RPM gap, IAT gap, AFR Normal clarification)
- Spool delivered code audit 2026-04-12 finding 7 variances in sprint 1/2 delivered code (5 critical + 2 minor)
- Spool acknowledged RPM hotfix 2026-04-12 and closed out his action items
- `/review-stories-tuner` skill updated with threshold gap check, vehicle-specific value check, note/edit consistency check
- Spool's `knowledge.md` and original tuning spec updated with corrections

**offices/ restructure finally committed:**
- Commit `2682806`: 108 files renamed from root-level `pm/`, `ralph/`, `tester/` → `offices/` prefix. Git detected renames cleanly.
- Commit `8aa966a`: Sprint 1 closeout + Epic E-10 + Sprint 2 setup + ralph.sh path fix

**Infrastructure Pipeline MVP brainstorming (end-of-session):**
- CIO proposed 4-step plan: deploy, SSH debuggable, Pi↔Server comms, simulated drive scenarios
- Brainstorming session produced: Option C (reorder B-022), Approach A (scenario JSON), Option B (logs + /health), scrum iteration style
- **Draft PRD written**: `offices/pm/prds/prd-infrastructure-pipeline-mvp.md` (445 lines, 12 TBD markers)
- Plan spans sprints 7/8/9 with 9 new stories (US-147–155)
- **PRD is DRAFT** — pending Ralph's B-040 arch reorg completion before promotion

**Architectural decisions delivered to Ralph:**
- `offices/ralph/inbox/2026-04-12-from-marcus-architectural-decisions-brief.md`
- Covers 5 open decisions: legacy threshold deprecation, orchestrator refactor (TD-003 plan exists), snake_case migration (B-006), Phase 2 data architecture, companion service review
- CIO wants to work with Ralph directly on these (not an architect agent)

**Key commits (in order):**
- `2682806` chore: Complete offices/ restructure migration (108 files)
- `8aa966a` feat: Sprint 1 closeout + Epic E-10 + Sprint 2 setup
- `da06bc3` Merge sprint/2026-04-sprint1 (30 stories)
- `5971902` feat: Sprint 2 closeout + Sprint 3 setup
- `962c9c9` Merge sprint/2026-04-sprint2 (9 stories)
- `b4a22fe` feat: Sprint 3 closeout
- `1f18413` Merge sprint/2026-04-sprint3 (8 stories)
- `4548809` chore: Spool review + US-139 hotfix setup
- `6e81a10` feat: Sprint 4 hotfix complete + Spool code audit
- `9e2dd11` Merge sprint/2026-04-sprint4-hotfix
- `f3d24db` feat: Sprint 5 closeout (B-033 complete)
- `f802314` Merge sprint/2026-04-sprint5 (5 stories) — PUSHED to origin
- `39f3dad` chore: Sprint 6 hotfix setup
- `0cb6c0d` feat: US-145 Battery voltage config complete
- `cab4d03` docs: Architectural decisions brief to Ralph inbox
- `da203aa` Merge sprint/2026-04-sprint6-hotfix — PUSHED to origin
- `d794048` docs: Draft PRD for infrastructure pipeline MVP (pending arch reorg) — cherry-picked to main (original on reorg branch)

**Key decisions:**
- **B-022 Option C**: Reorder stories so "loop live" hits sprint 7 after 4-5 stories, defer 3 to sprint 9. All 9 B-022 stories tracked.
- **Simulation Approach A**: Scenario JSON files via existing physics sim, not pre-recorded fixtures. Same code path as real OBD data.
- **SSH debugging Option B**: Logs + `/health` endpoints. US-CMP-008 moved up to sprint 7.
- **Manual sync trigger for sprint 7/8**: CLI script `sync_now.py`, auto-trigger (B-023) deferred.
- **Scrum iteration style**: Build-test-adjust per sprint. Stories kept small and reversible.
- **Spool review gate**: All tuning stories go through `/review-stories-tuner` before sprint load. Sprint 3+ covered; sprint 1/2 caught retroactively via audit (B-033).
- **RPM dangerMin 7000 (not 7200)**: 97-99 2G factory redline per Spool's vehicle-specific correction. Earlier draft of Spool's spec had 7200 which was 95-96 2G value.
- **Legacy profile threshold system deprecation**: OPEN architectural question. Referred to Ralph via architect brief.
- **Draft PRD instead of direct backlog items**: CIO explicitly directed — don't create backlog items that reference paths while Ralph is reorganizing.

**What's next:**

1. **Wait for Ralph** to finish B-040 structural reorg (sprint/reorg-sweep1-facades branch). Do NOT create new backlog items, do NOT launch new sprints.
2. **When Ralph is done**: Promote Infrastructure Pipeline MVP PRD to active — walk the Finalization Checklist at bottom of PRD, fill TBD markers, create B-035 (if numbering still available), update B-022/B-027, update backlog.json + story_counter.json, commit as single clean changeset.
3. **Push main to origin** (5 commits ahead — includes draft PRD + Ralph's 4 reorg planning docs). Waiting until reorg lands means one clean push instead of two.
4. **Launch sprint 7** (Infrastructure Pipeline MVP): 10 stories — US-CMP-001/002/003/004/008/009 from B-022 + US-147 stub AI + US-148/149/151 from B-027.
5. **CIO parallel work**: OBDLink LX Bluetooth pairing with Pi, real dongle testing, car hardware verification. Unlocks swap from `--simulate` to real OBD data post-sprint 9.
6. **Sprint 8**: Drive scenarios + manual sync CLI + e2e integration test (4 stories).
7. **Sprint 9**: Real Ollama AI + auto-analysis + backup push/receive (4 stories). Unblocks B-031 Spool's Server Analysis Pipeline.
8. **Ongoing**: Process the 5 open architectural decisions in Ralph's inbox (legacy threshold, orchestrator, snake_case, Phase 2, companion service review).

**Unfinished work:**

- **Sprint 7 not yet loaded** into `offices/ralph/stories.json` — blocked on Ralph reorg completing
- **Draft PRD not promoted** — 12 TBD markers in `prd-infrastructure-pipeline-mvp.md` need file paths filled in post-reorg
- **B-035 not yet created** — conflicts with Ralph team's B-040 numbering for reorg work. May need renumbering at promotion time.
- **backlog.json not yet updated** for infrastructure MVP work — intentional, waiting for reorg
- **5 commits on main not pushed to origin** — CIO directive (wait for reorg to land, push all at once)
- **Ralph's reorg branch has duplicate copy of draft PRD** (`1bfcb86`) — same content as `d794048` on main. Will merge cleanly when Ralph's branch merges.
- **8 stories still blocked on hardware**: B-029 Phase 2 alert thresholds (US-113–120) waiting on ECMLink V3 install (summer 2026)
- **B-031 Server Analysis Pipeline** (7 stories) still blocked on B-022 companion service
- **B-014 Pi Testing** (4 stories) waiting on CIO physical hardware testing time

**Post-session git state:**
- Current branch: `main`
- Ahead of origin: 5 commits (draft PRD + 4 Ralph reorg planning docs)
- Ralph active on: `sprint/reorg-sweep1-facades` (do not touch)

---

### Previous Session Summary (2026-04-09, Session 13 - Sprint Merge + GPU Upgrade + Sprint Planning)

**What was accomplished:**
- **Merged `sprint/2026-02-sprint1` → `main`**: B-016 (Remote Ollama) complete. 7 commits merged (PMO migration + agent upgrades + 3 OLL stories + tester consolidation). Sprint branch deleted.
- **Chi-Srv-01 GPU upgrade recorded**: CIO upgraded from GT 730 (2GB, display-only) to 12GB NVIDIA GPU. Ollama now GPU-accelerated. Updated: `pm/projectManager.md` (decision table), `pm/prds/prd-companion-service.md` (server specs + model recommendations), `specs/architecture.md` (IP fix .100→.120, GPU-accelerated note).
- **Fixed stale IP in architecture.md**: Ollama on Chi-Srv-01 was still showing 10.27.27.100, corrected to 10.27.27.120.
- **Sprint 2026-04-01 planned and loaded**:
  - Created PRD: `prd-simulate-db-validation.md` (B-026, 3 stories: US-101–103)
  - Created PRD: `prd-ollama-local-cleanup.md` (B-024, 3 stories: US-104–106)
  - Loaded `ralph/stories.json` with 30 stories across 4 backlog items
  - Updated `backlog.json`: B-016 → complete, B-002/B-015/B-024/B-026 → in_progress
  - Story counter advanced to US-107
- **Commits**: `86de0b4` (docs: GPU + session handoff), `721f7c7` (chore: sprint setup)

**Key decisions:**
- GPU-accelerated Ollama inference replaces CPU-only strategy (key technical decision table updated)
- B-016 marked complete, `prd-remote-ollama.md` all stories passing
- Sprint loaded: B-015 (DB verify, 4 stories), B-026 (sim DB validation, 3), B-024 (Ollama cleanup, 3), B-002 (orchestration, 20)
- CIO: Car hardware testing planned for upcoming weeks as weather warms

**What's next:**
1. **Run Ralph** on sprint/2026-04-sprint1 (30 stories loaded, ready to execute)
2. CIO: OBD-II port hardware verify + Torque Pro + BT pairing (car coming out of storage)
3. Convert B-022 PRD to `stories.json` for OBD2-Server repo (separate repo)
4. Groom B-023 (WiFi-Triggered Sync) and B-027 (Client-Side Sync) into PRDs (blocked on B-022)
5. Review OBD-II stories against `specs/obd2-research.md` thresholds
6. Push to origin (12 commits ahead)

**Unfinished work:**
- Sprint stories not yet executed (30 pending in ralph/stories.json)
- B-022 PRD ready but not converted to stories.json (OBD2-Server repo)
- OBD2-Server repo exists but empty
- B-023, B-027 need PRDs (blocked on B-022)
- No sample OBD-II data yet — CIO will collect when car is accessible
- 12 commits on `main` not pushed to origin

---

### Previous Session Summary (2026-02-13, Session 12 - PMO Migration Executed)

**What was accomplished:**
- **PMO migration executed** — the primary outstanding action item since Session 8:
  - **Created `pm/backlog.json`**: Hierarchical Epic > Feature > Story structure. 9 epics mapping to project phases, 27 features (B-items), 128 user stories, 9 tech debt items, 10 issues. Single source of truth for all project work.
  - **Created `pm/story_counter.json`**: Global sequential counter starting at US-101. All existing story prefixes (US-001-043, US-MR, US-OSC, US-DEP, US-DBI, US-OLL, US-PIT, US-RPI, US-CMP) documented. New stories use US-101+ to prevent prefix collisions.
  - **Renamed `pm/techDebt/` → `pm/tech_debt/`**: snake_case convention. 12 files moved via `git mv`.
  - **Archived 7 completed backlog items**: B-011, B-012, B-013, B-017, B-018, B-020, B-021 moved to `pm/archive/backlog/`.
  - **Archived 3 completed PRDs**: prd-eclipse-obd-ii.md, prd-obd-simulator.md, prd-module-refactoring.md moved to `pm/archive/prds/`.
  - **Updated 11 reference files**: CLAUDE.md, ralph/agent.md, ralph/agent-pi.md, ralph/prompt.md, pm/projectManager.md, pm/README.md, specs/methodology.md, pm/backlog/B-019.md, and 3 tech_debt files — all `techDebt/` → `tech_debt/` path references.
- **Committed**: `440b060` — 32 files changed, 701 insertions

**Key decisions:**
- Epic hierarchy maps directly to project phases (E-01 through E-09)
- Existing story IDs preserved; new stories start at US-101 via global counter
- Completed items archived (not deleted) for historical reference
- backlog.json includes tech debt and issues sections alongside epics

**What's next:**
1. Convert B-022 PRD to `stories.json` for Ralph execution in OBD2-Server repo
2. CIO: Verify OBD-II port hardware (12V on pin 16, continuity on pin 7, fuse check)
3. CIO: Install Torque Pro ($5 Android), test OBDLink LX connection, scan PIDs
4. CIO: Pair OBDLink LX BT dongle with Pi (MAC: `00:04:3E:85:0D:FB`)
5. Groom B-026 (Simulate DB Validation Test) into PRD
6. B-016 implementation stories pending (US-OLL-001 through US-OLL-005)
7. Review existing OBD-II stories against `specs/obd2-research.md` — update thresholds with real values
8. B-024 (local Ollama cleanup) after B-016 implementation stories complete

**Unfinished work:**
- B-022 PRD ready but not yet converted to stories.json
- OBD2-Server repo exists but empty
- B-023, B-026, B-027 need PRDs
- No sample OBD-II data yet — CIO will collect when possible
- B-016 implementation stories not yet executed

---

### Previous Session Summary (2026-02-05, Session 11 - Specs Housekeeping & File Cleanup)

**What was accomplished:**
- **Reviewed and deleted 3 CIO input files** (Answers.txt, Answers2.txt, Eclipse 1998 Projects.xlsx) — all knowledge confirmed extracted. VIN `4A3AK54F8WE122916` captured. CIO vehicle description updated with bolt-on mods list.
- **Converted `specs/groundedKnowledge.txt` → `specs/grounded-knowledge.md`**: Created structured reference with 3 authoritative sources (DSMTuners, OBDLink LX, ECMLink V3), vehicle facts table, safe operating ranges table, and usage rules tied to PM Rule 7. Added to CLAUDE.md and projectManager.md key files tables.
- **Converted `specs/best practices.txt` → `specs/best-practices.md`**: Industry best practices for Python, SQL, REST API, and design patterns. Added project alignment notes mapping each practice to our current adoption status. Added to CLAUDE.md specs table.
- **Reviewed and deleted 7 raw hardware txt files** from `specs/`:
  - `cpu-specs.txt`, `cpu-specs-v2.txt` (lscpu + /proc/cpuinfo dumps)
  - `gpu-specs.txt` (lshw output)
  - `memory-specs.txt`, `memory-specs-v2.txt` (free + dmidecode dumps)
  - `system-info.txt` (hostnamectl output)
  - `OBDLink-LX-Info.txt` (dongle specs)
  - All data already in `prd-companion-service.md` and `architecture.md`. Extracted new details before deletion: motherboard (MSI MS-7885), CPU turbo (3.5GHz), L3 cache (20MB), RAM part number (Corsair CMK64GX4M4A2666C16), quad-channel config, max 512GB capacity, GPU chipset (GK208B), kernel (6.12.63).
- **Result**: `specs/` folder now has zero `.txt` files — all markdown. 10 total files cleaned up this session.

**Key decisions:**
- None new (housekeeping only)

**What's next:**
1. **Execute PMO migration plan** (9 phases in `.claude/plans/inherited-coalescing-wirth.md`) — still primary
2. Convert B-022 PRD to `stories.json` for Ralph execution in OBD2-Server repo
3. CIO: Verify OBD-II port hardware (12V on pin 16, continuity on pin 7, fuse check)
4. CIO: Install Torque Pro ($5 Android), test OBDLink LX connection, scan PIDs
5. CIO: Pair OBDLink LX BT dongle with Pi (MAC: `00:04:3E:85:0D:FB`)
6. Groom B-026 (Simulate DB Validation Test) into PRD
7. B-016 implementation stories pending (US-OLL-001 through US-OLL-005)
8. Review existing OBD-II stories against new research — update thresholds with real values

**Unfinished work:**
- PMO migration plan approved but NOT yet executed
- B-022 PRD ready but not yet converted to stories.json
- OBD2-Server repo exists but empty
- B-023, B-026, B-027 need PRDs
- No sample OBD-II data yet — CIO will collect when possible
- Tester agent active, doing test file cleanup

---

### Previous Session Summary (2026-02-05, Session 10 - OBD-II Research & CIO Knowledge Capture)

**What was accomplished:**
- **CIO knowledge capture (2 rounds)**: Captured driving patterns, usage preferences, report expectations, alert philosophy, Pi mounting plan, power design, WiFi/sync behavior, data retention policy, multi-vehicle aspirations.
- **4 parallel research tasks completed**:
  1. **Polling frequency**: ISO 9141-2 at 10,400 bps caps at ~4-5 PIDs/sec via Bluetooth. Tiered polling (weighted round-robin) gives 3x improvement over flat polling for core PIDs.
  2. **Stock PIDs for 4G63T**: Identified ~16 high-confidence supported PIDs. Recommended core 5: STFT, Coolant Temp, RPM, Timing Advance, Engine Load. MAP sensor is actually MDP (EGR only) — boost may be unreliable.
  3. **DSMTuners community mining**: Safe operating ranges captured (coolant 190-210F, boost ~12 psi stock, AFR 11.0-11.8 WOT, knock count 0 ideal). Community consensus: "OBDII loggers suck on 2G's" but adequate for health monitoring. PiLink discovered as concept validation.
  4. **Mobile app comparison**: BlueDriver incompatible with OBDLink LX (closed ecosystem — likely why CIO couldn't collect data). Torque Pro ($5, Android) is the community-proven choice. ELM327-emulator for development without car.
- **Compiled `specs/obd2-research.md`**: 13-section reference document with all findings, safe ranges, PID tables, protocol constraints, wiring diagrams, and sources. Grounding document for all OBD-II stories.
- **New PM Rule 7 added**: No fabricated data. All thresholds grounded in research/data/CIO input. Stories needing unavailable data are `blocked`.
- **Updated projectManager.md**: CIO profile expanded with driving patterns, preferences, hardware plan. 9 new key technical decisions recorded.

**Key decisions:**
- Tiered PID polling strategy (weighted round-robin) replaces flat polling
- Core 5 PIDs for Phase 1: STFT, Coolant, RPM, Timing, Load
- OBD-II is Phase 1 (health monitoring), ECMLink is Phase 2 (real tuning data)
- Purge only after confirmed sync
- No fabricated data — PM Rule 7
- Torque Pro recommended for CIO's phone testing
- Hardware verification checklist before any software troubleshooting

**What's next:**
1. **Execute PMO migration plan** (9 phases in `.claude/plans/inherited-coalescing-wirth.md`) — still primary
2. Convert B-022 PRD to `stories.json` for Ralph execution in OBD2-Server repo
3. CIO: Verify OBD-II port hardware (12V on pin 16, continuity on pin 7, fuse check)
4. CIO: Install Torque Pro ($5 Android), test OBDLink LX connection, scan PIDs
5. CIO: Pair OBDLink LX BT dongle with Pi (MAC: `00:04:3E:85:0D:FB`)
6. Groom B-026 (Simulate DB Validation Test) into PRD
7. B-016 implementation stories pending (US-OLL-001 through US-OLL-005)
8. Review existing OBD-II stories against new research — update thresholds with real values

**Unfinished work:**
- PMO migration plan approved but NOT yet executed
- B-022 PRD ready but not yet converted to stories.json
- OBD2-Server repo exists but empty
- B-023, B-026, B-027 need PRDs
- No sample OBD-II data yet — CIO will collect when possible
- CIO's answers2.txt follow-up answers captured but Google Sheet mods list not yet reviewed
- Tester agent active, doing test file cleanup

---

### Previous Session Summary (2026-02-05, Session 9 - Ralph Agent Upgrade)

**What was accomplished:**
- **Ralph agent system upgraded** from DataWarehouse template:
  - Replaced `get_next_agent.py` + `set_agent_free.py` with consolidated `agent.py` CLI (5 commands: getNext, list, sprint, clear, clear all)
  - Upgraded `ralph.sh`: added status/help commands, input validation, sprint progress display before/after each iteration, 6 stop conditions (was 2: COMPLETE, HUMAN_INTERVENTION_REQUIRED → now adds SPRINT_IN_PROGRESS, ALL_BLOCKED, PARTIAL_BLOCKED, SPRINT_BLOCKED)
  - Upgraded `prompt.md`: agent coordination protocol, priority-based story selection, mandatory Sprint Status Summary, tiered Required Reading, multiple stop conditions — all adapted for OBD-II project
  - Created `ralph/README.md`: operational guide with troubleshooting
  - Updated `Makefile` ralph-status target to use new `agent.py`
- **Committed**: `67144f8` — 7 files changed, 629 insertions, 167 deletions
- **Cleared stale agent assignments**: All 4 agents (Rex, Agent2, Agent3, Torque) reset to `unassigned`
- **Case sensitivity fix**: Old ralph.sh referenced `@ralph/AGENT.md` (uppercase) — fixed to `@ralph/agent.md` (critical for Pi/Linux)

**Key decisions:**
- Kept our richer `ralph_agents.json` schema (type, lastCheck, note fields) — DW only had id, name, status, taskid
- Kept `agent.md` content unchanged (project-specific OBD-II knowledge base)
- Kept `agent-pi.md` (Torque) unchanged
- Tester agent is active and doing cleanup work (test file reorganization)
- CIO batching PM doc commits — waiting for all agents to report in

**What's next:**
1. **Execute PMO migration plan** (9 phases in `.claude/plans/inherited-coalescing-wirth.md`) — still the primary next action
2. Convert B-022 PRD to `stories.json` for Ralph execution in OBD2-Server repo
3. CIO: Pair OBDLink LX BT dongle with Pi (MAC: `00:04:3E:85:0D:FB`)
4. Groom B-026 (Simulate DB Validation Test) into PRD
5. B-016 implementation stories still pending (US-OLL-001 through US-OLL-005)
6. B-024 (local Ollama cleanup) after B-016

**Unfinished work:**
- PMO migration plan approved but NOT yet executed
- B-022 PRD ready but not yet converted to stories.json
- OBD2-Server repo exists but empty
- B-023, B-026, B-027 need PRDs
- Tester agent active, doing test file cleanup (12 test files being reorganized)
- PM docs from Sessions 7-8 modified but uncommitted (CIO batching)

---

### Previous Session Summary (2026-02-05, Session 8 - OBDLink LX Specs + PMO Migration Planned)

**What was accomplished:**
- **OBDLink LX dongle specs captured**: MAC `00:04:3E:85:0D:FB`, FW 5.6.19, Serial 115510683434. Saved in `specs/OBDLink-LX-Info.txt`, updated `specs/architecture.md` (External Dependencies table) and `specs/glossary.md` (new OBDLink LX entry).
- **CIO provided PMO template**: Read all 10 files from CIO's PMO_Template folder (`C:\Users\mcorn\OneDrive - DUGGAN BERTSCH, LLC\Documents\Projects\PMO_Template\templates\coding\pm\`).
- **Full PMO adoption approved**: CIO directed full migration to new PMO template structure.
- **Migration plan created**: 9-phase plan covering backlog.json creation (128 stories across 9 epics), story_counter.json, new PM quality rules, folder restructuring, tester/PMO folder setup, and external reference updates. Plan saved at `.claude/plans/inherited-coalescing-wirth.md`.
- **Updated projectManager.md**: Hardware section, Session 4 BT MAC note, resolved OBD dongle question.

**Key decisions:**
- Full adoption of PMO template (backlog.json, story_counter.json, new folder structure)
- Global sequential story IDs going forward (US-101+), existing stories keep current IDs
- Tester agent being introduced (CIO setting up now)
- PMO layer work in progress (CIO building infrastructure)
- PRD markdown files will migrate into backlog.json, originals archived
- techDebt/ folder will be renamed to tech_debt/

**What's next:**
1. **Execute PMO migration plan** (9 phases) — the primary next action
2. Convert B-022 PRD to `stories.json` for Ralph execution in OBD2-Server repo
3. CIO: Pair OBDLink LX BT dongle with Pi (MAC now known: `00:04:3E:85:0D:FB`)
4. Groom B-026 (Simulate DB Validation Test) into PRD
5. B-016 implementation stories still pending
6. B-024 (local Ollama cleanup) after B-016

**Unfinished work:**
- PMO migration plan approved but NOT yet executed
- B-022 PRD ready but not yet converted to stories.json
- OBD2-Server repo exists but empty
- B-023, B-026, B-027 need PRDs
- Tester agent folder structure not yet created

---

### Previous Session Summary (2026-02-02, Session 6 - Chi-Srv-01 Specs + Repo Created)

**What was accomplished:**
- **Chi-Srv-01 specs finalized**: i7-5960X (8c/16t), 128GB DDR4, GT 730 (display only), 2TB RAID5 SSD at `/mnt/raid5`, NAS mount at `/mnt/projects`, Debian 13
- **IP corrected**: 10.27.27.100 → 10.27.27.120 (updated in 6 files)
- **GitHub repo created**: `OBD2-Server` (was planned as `eclipse-ai-server`)
- **Ollama strategy**: CPU-only inference — GT 730 has ~2GB VRAM, unsuitable for AI. 128GB RAM enables large models.
- **Model recommendations**: Llama 3.1 8B (fast iteration) or 70B Q4 (higher quality, ~48GB RAM)
- **Updated 6 files**: projectManager.md, prd-companion-service.md, B-022.md, B-027.md, roadmap.md

**Key decisions:**
- `OBD2-Server` is the companion service repo name
- Chi-Srv-01 IP is 10.27.27.120
- CPU-only Ollama inference (no usable GPU)
- Default model: `llama3.1:8b`

**What's next:**
- Convert B-022 PRD to `stories.json` for Ralph execution in OBD2-Server repo
- CIO: Pair OBDLink LX BT dongle with Pi
- Groom B-026 (Simulate DB Validation Test) into PRD
- B-016 implementation stories still pending
- B-024 (local Ollama cleanup) after B-016

**Unfinished work:**
- B-022 PRD ready but not yet converted to stories.json
- OBD2-Server repo exists but empty
- B-023, B-026, B-027 need PRDs

---

### Previous Session Summary (2026-02-01, Session 5 - Torque Review + Specs Update + DoD)

**What was accomplished:**
- **Reviewed Torque's (Pi 5 agent) work**: Git pull brought 11 changed files -- extensive Pi readiness testing
- **Torque's key accomplishments**: Simulate mode end-to-end verified, log spam fixed (3 sources), 4 missing DB indexes added, VIN decoder tested, smoke test 35/35 PASS, dry run PASS, 1171 tests passing
- **Processed I-010 (specs update request)**: Updated 4 spec files per Torque's findings:
  - `specs/architecture.md`: Database schema 7→12 tables, 16 indexes, PRAGMAs, VIN decoder (S14), component init order (S15), hardware graceful degradation (S16), Ollama→remote Chi-Srv-01
  - `specs/standards.md`: Added Section 13 (database coding patterns)
  - `specs/anti-patterns.md`: Added polling loop log spam anti-pattern
  - `specs/methodology.md`: Added Section 3 (Definition of Done) with mandatory DB output validation
- **Branch decision**: CIO confirmed `main` is primary branch (reversed previous plan to use `master`)
- **Created B-026**: Simulate DB output validation test, promoted from TD-005 by CIO directive
- **Tightened Definition of Done**: Any story writing to database MUST validate output. Stories that fail validation are `blocked`, not `completed`.
- **Groomed B-022 into full PRD** (`prd-companion-service.md`): 9 user stories (US-CMP-001 through US-CMP-009). CIO interview captured: FastAPI, MySQL, separate repo (`OBD2-Server`), push-based delta sync, API key auth, server-owned prompts, /api/chat for Ollama.
- **Created B-027**: Client-side sync to Chi-Srv-01 (EclipseTuner repo changes -- sync_log table, delta sync client, backup push)
- **Tightened all 9 user stories**: Added concrete DB validation queries, specific input/output tests, defined ID mapping strategy (source_id + UNIQUE constraint), testing strategy (real MySQL, no SQLite substitutes), config variables table, allowed file extensions, transaction rollback tests, and edge case coverage.

**Key decisions:**
- `main` is the primary branch (not `master`)
- Definition of Done now requires DB output validation for database-writing stories
- B-026 is the reference implementation for the new DoD pattern
- TD-005 promoted to backlog item (B-026) for next sprint
- Companion service: separate repo `OBD2-Server`, FastAPI, MySQL 8.x
- ID mapping: Pi `id` → MySQL `source_id`, server owns `id` PK, upsert key = `(source_device, source_id)`
- Ollama: `/api/chat` endpoint (conversational), server owns prompt templates
- Auth: API key via `X-API-Key` header, `hmac.compare_digest()` for constant-time comparison
- Testing: all tests use real MySQL test database, no SQLite substitutes
- Backup extensions: `.db`, `.log`, `.json`, `.gz`
- Dashboard and NAS replication deferred to future sprints

**What's next:**
- CIO: Continue Chi-Srv-01 OS install, provide GPU/RAM specs when available
- CIO: Pair OBDLink LX BT dongle with Pi (needs car ignition on, physical proximity)
- CIO: Create `OBD2-Server` GitHub repo when ready to start development
- Convert B-022 PRD stories to `stories.json` for Ralph execution (once repo exists)
- Groom B-026 into PRD for next sprint
- B-016 implementation stories (US-OLL-001 through US-OLL-003, US-OLL-005) still pending
- B-024 (local Ollama cleanup) after B-016 implementation
- B-023 (WiFi-triggered sync) needs grooming after B-022 and B-027 are underway
- B-014 (Pi testing) after BT dongle paired

**Unfinished work:**
- B-023 still needs PRD
- B-016 implementation stories not yet executed
- B-026 needs grooming into PRD
- `OBD2-Server` repo not yet created on GitHub

**CIO status updates:**
- Chi-Srv-01: OS being installed. Multi-CPU, mid-grade GPU, large RAM, high-speed SSD. Exact specs pending.
- OBDLink LX: CIO has physical dongle, needs proximity to car with ignition on
- Sprints: Still ad-hoc

---

### Previous Session Summary (2026-01-31, Session 4 - Pi Deployment + Ralph Queue)

**What was accomplished:**
- **Pi 5 deployment (B-012)**: CIO flashed OS, SSH key auth configured, pi_setup.sh run successfully, hardware verified (I2C, GPIO, platform detection all pass)
- **Pi debugging**: Discovered OSOYOO 3.5" display is HDMI (not SPI/GPIO) -- removed Adafruit deps from requirements-pi.txt, replaced Adafruit checks in check_platform.py with pygame check
- **Config path fix (I-005)**: main.py resolved config paths relative to CWD, broke systemd/remote execution. Fixed to resolve relative to script location using `Path(__file__).resolve().parent`. Updated tests to use `endswith()` assertions.
- **Git branch cleanup**: Config fix landed on wrong branch (`main`). Cherry-picked to `master`, pushed. `main` branch still exists and should be deleted.
- **Ralph queued**: Loaded stories.json with 9 stories across B-015 (Database Verify, 4 stories) and B-016 (Remote Ollama, 5 stories). TDD-ordered with test stories first. Committed and pushed.
- **B-013 confirmed complete**: All 7 US-DEP stories passed, 1133 tests passing

**Key learnings:**
- OSOYOO 3.5" HDMI display does NOT use GPIO/SPI -- Adafruit RGB display libs are irrelevant. Pygame renders to HDMI framebuffer directly.
- Config paths must be resolved relative to script location (`Path(__file__).resolve().parent`), not CWD, for systemd and remote SSH execution.
- `origin/HEAD` still points to `origin/main` -- GitHub default branch needs to be changed to `master` in repo settings.
- Pi username is `mcornelison` (not `pi`), path is `/home/mcornelison/Projects/EclipseTuner`
- `OBD_BT_MAC` env var should be set to `00:04:3E:85:0D:FB` (dongle specs in `specs/architecture.md`)

**What's next:**
- Ralph: Execute 9 stories (B-015 + B-016) -- run `./ralph/ralph.sh 10`
- CIO: Delete `main` branch, set GitHub default to `master`
- CIO: Power up Chi-Srv-01 and provide specs
- Groom B-022 (companion service) and B-023 (WiFi-triggered sync) into PRDs
- B-024 (local Ollama cleanup) after B-016
- B-014 (Pi testing) blocked until B-012, B-013, B-015 done

**Unfinished work:**
- `main` branch needs to be deleted (local + remote + GitHub default changed)
- B-022 and B-023 need PRDs before Ralph can work them
- Chi-Srv-01 specs needed for B-022 PRD

**Questions for CIO:**
- **REMINDER**: Power up Chi-Srv-01 and provide exact specs (CPU, RAM, GPU model, disk capacity). Not done yet as of 2026-01-31.
- **Ralph-Pi**: Second agent instance running on Pi 5, writes to pm/issues/, pm/backlog/, pm/techDebt/. Syncs via GitHub (push/pull delay expected). Complements Ralph (Windows) who writes code.
- **RESOLVED (Session 8)**: OBD dongle specs captured — MAC `00:04:3E:85:0D:FB`, FW 5.6.19. Details in `specs/architecture.md` and `specs/glossary.md`.
- **Display**: OSOYOO 3.5" HDMI plugged into HDMI port #1 but currently blank. Needs troubleshooting.
- **UPS**: Geekworm X1209 not yet acquired. Lower priority -- Pi must work first.
- **Sprints**: Keep ad-hoc, no formal sprint cadence.
- **ANSWERED**: ECMLink install planned for spring/summer 2026 when Chicago temps warm up. B-025 is a Q2/Q3 item -- no need to groom yet.
- **RESOLVED (Session 5)**: CIO confirmed `main` is primary branch. No branch deletion needed. Previous plan to switch to `master` is reversed.
- **B-022 companion service**: CIO changed decision to **separate repo** (was monorepo). Makes sense -- different deployment target, runtime, and dependencies. API contract between EclipseTuner and Chi-Srv-01 is the key interface to define. Framework decision deferred until Chi-Srv-01 specs available.

### Previous Session Summary (2026-01-31, Session 3 - PM Grooming)

**What was accomplished:**
- Groomed all Phase 5.5 (Pi Deployment) backlog items (B-012 through B-016)
- Created 3 new PRDs:
  - `pm/prds/prd-database-verify-init.md` (B-015, 4 user stories: US-DBI-001 through US-DBI-004)
  - `pm/prds/prd-remote-ollama.md` (B-016, 5 user stories: US-OLL-001 through US-OLL-005)
  - `pm/prds/prd-pi-testing.md` (B-014, 4 user stories: US-PIT-001 through US-PIT-004)
- Groomed B-012 as CIO manual checklist (5 phases, references existing scripts)
- Reviewed B-013 PRD -- already solid, Ralph working (US-DEP-001 complete)
- Key code discovery: Ollama URL already config-driven, B-016 scope smaller than expected
- Key code discovery: Database `initialize()` already idempotent, B-015 wraps in CLI tool
- Updated roadmap: Phase 5.5 status from "Planned" to "Groomed", all backlog items updated
- B-020 and B-021 confirmed complete
- **CIO decisions recorded**:
  - Pi 5 hostname: **EclipseTuner**
  - LLM server: **Chi-srv-01** (local network, Ollama never on Pi)
  - Home WiFi: **DeathStarWiFi** (triggers sync/backup/AI)
  - Need companion service on Chi-srv-01 (B-022)
  - WiFi-triggered sync and AI workflow (B-023)
  - Clean up all local Ollama references (B-024)
- Created 3 new backlog items: B-022, B-023, B-024
- Updated B-012 hostname to EclipseTuner, WiFi to DeathStarWiFi
- Updated B-016 PRD with Chi-srv-01 references
- Updated `deploy/deploy.conf.example` default host to EclipseTuner.local
- Added Code Quality Rules to `ralph/agent.md` (reusable code, small files, organized structure)
- Added explicit "always report back" reminder to Ralph's PM Communication Protocol
- **Network infrastructure recorded**: chi-eclipse-tuner (10.27.27.28), Chi-Srv-01 (10.27.27.120), Chi-NAS-01 (10.27.27.121), DeathStarWiFi (10.27.27.0/24)
- Created B-022 (Chi-Srv-01 companion service, L), B-023 (WiFi-triggered sync, M), B-024 (remove local Ollama refs, S)
- Updated B-012 hostname to chi-eclipse-tuner, WiFi to DeathStarWiFi, IP to 10.27.27.28
- Updated deploy.conf.example with chi-eclipse-tuner.local
- Chi-NAS-01 added as secondary backup target in B-022, B-023
- **ECMLink V3 context captured**: Project's ultimate purpose is data collection → AI analysis → ECU tuning
- Created B-025 (ECMLink Data Integration, L) as Phase 6.5
- Added Project Vision section to projectManager.md with full ECMLink workflow
- Updated glossary: ECMLink V3, ECU, DSM, MAP acronyms
- Repo decision: **same repo** (monorepo) for companion service

**What's next:**
- Ralph: Complete B-013 (US-DEP-002 through US-DEP-007) -- in progress now
- CIO: Power up Chi-Srv-01 and provide exact specs
- CIO: Pi 5 initial setup (B-012 checklist -- when ready)
- Ralph: Pick up B-015 and B-016 (convert PRDs to stories.json)
- Groom B-022 (Chi-Srv-01 companion service) and B-023 (WiFi-triggered sync) into PRDs
- B-024 (local Ollama cleanup) after B-016
- B-014 blocked until B-012, B-013, B-015 done
- B-025 (ECMLink) is future -- after programmable ECU installed

**Unfinished work:**
- B-022 and B-023 need PRDs before Ralph can work them
- B-024 needs grooming (small, may not need a full PRD)
- Chi-Srv-01 specs needed for B-022 PRD

**Questions for CIO:**
- **REMINDER**: Power up Chi-Srv-01 and provide exact specs (CPU, RAM, GPU model, disk capacity). Needed for companion service PRD and Ollama model sizing.
- B-022: Same repo or separate for companion service? **CIO preference: same repo** (monorepo)
- B-025: When is the programmable ECU + ECMLink install planned? (Affects Phase 6.5 timing)

### Previous Session Summary (2026-01-29, Session 2)

**What was accomplished:**
- Added 5 new backlog items for Pi 5 deployment (B-012 through B-016)
  - B-012: Pi 5 Initial Setup (High, M)
  - B-013: CI/CD Pipeline Windows → Pi (High, M, depends B-012)
  - B-014: Pi 5 Testing Simulated + Real OBD2 (High, L, depends B-012, B-013, B-015)
  - B-015: Database Verify & Initialize on Pi (High, S)
  - B-016: Remote Ollama Server Integration (Medium, M)
- Expanded B-002 from database-only backup to comprehensive strategy (db + logs + config)
- Updated `pm/roadmap.md` with Phase 5.5 (Pi Deployment) and dependency chain
- Renamed `ralph/prd.json` → `ralph/stories.json` to match hierarchy (Backlog → PRD → User Stories)
- Updated all 11+ files referencing prd.json (ralph.sh, CLAUDE.md, ralph/agent.md, specs/methodology.md, .claude/commands/ralph.md, .claude/commands/ralph-status.md, .claude/commands/prd.md, specs/user-stories/README.md, pm/prds/prd-eclipse-obd-ii.md, pm/README.md, pm/projectManager.md)
- Verified no active files still reference prd.json (only archived progress logs, which is correct)

**What's next:**
- Begin implementing `ApplicationOrchestrator` (US-OSC-001) via Ralph
- Groom Pi 5 deployment backlog items (B-012 through B-016) into PRDs
- CIO to acquire power unit for Pi 5

**Unfinished work:**
- None -- clean handoff point

**Questions for CIO:**
- None pending

### Previous Session Summary (2026-01-29, Session 1)

**What was accomplished:**
- PM/specs folder restructuring (single source of truth, no duplication)
- Created 11 backlog items (B-001 through B-011) from scattered task files
- Moved 5 PRDs to `pm/prds/` with parent backlog item traceability
- Created `pm/roadmap.md` (7 phases, backlog summary)
- Created `pm/README.md` (quick-start orientation)
- Created templates for issues (`I-`), blockers (`BL-`), and tech debt (`TD-`)
- Formalized 2 tech debt items: TD-001 (pytest warning), TD-002 (re-export facades)
- Established PM rules, naming conventions (B- vs US- vs I- vs BL- vs TD-), status definitions, and workflow
- Cleaned up `specs/` to developer-only reference material
- Updated stale path references in `CLAUDE.md`, `ralph/agent.md`, `specs/methodology.md`
- Added parent backlog item + status fields to all 5 PRD headers

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-23 | Claude | Initial project manager knowledge base |
| 2026-01-29 | Marcus (PM) | Major restructure: PM rules, naming conventions, folder reorganization, backlog creation |
| 2026-01-29 | Marcus (PM) | Added templates (I-, BL-, TD-), status definitions, PRD traceability, fixed stale paths |
| 2026-01-29 | Marcus (PM) | Added B-012 through B-016 (Pi 5 deployment), expanded B-002, Phase 5.5 in roadmap |
| 2026-01-29 | Marcus (PM) | Renamed prd.json → stories.json across all active project files (11+ files updated) |
| 2026-01-31 | Marcus (PM) | Groomed Phase 5.5: created 3 PRDs (B-015, B-016, B-014), groomed B-012 checklist, reviewed B-013 |
| 2026-01-31 | Marcus (PM) | CIO decisions: EclipseTuner hostname, Chi-srv-01 LLM server, DeathStarWiFi trigger. Created B-022, B-023, B-024. Updated Ralph agent.md with code quality rules and reporting reminders. |
| 2026-02-01 | Marcus (PM) | Session 5: Reviewed Torque's Pi work, processed I-010 (4 spec files updated), confirmed `main` as primary branch, tightened DoD (mandatory DB validation), created B-026, closed I-010. Groomed B-022 into PRD (9 stories), created B-027, tightened all story ACs with concrete DB validation, ID mapping, and test strategy. |
| 2026-02-02 | Marcus (PM) | Session 6: Chi-Srv-01 specs finalized — i7-5960X (8c/16t), 128GB DDR4, GT 730 (display only), 2TB RAID5 SSD at /mnt/raid5, NAS mount at /mnt/projects, Debian 13. IP: 10.27.27.120. Updated B-022 PRD with server specs, CPU-only Ollama inference (no usable GPU). Model recommendations: Llama 3.1 8B (fast) or 70B (quality). GitHub repo created: `OBD2-Server`. |
| 2026-02-03 | Marcus (PM) | Session 7: Chi-Srv-01 infrastructure COMPLETE. MariaDB: database `obd2db`, user `obd2`, subnet access `10.27.27.%`. Ollama: installed, systemd enabled, `llama3.1:8b` model pulled. Server ready for companion service development. |
| 2026-02-05 | Marcus (PM) | Session 8: OBDLink LX dongle specs captured (MAC `00:04:3E:85:0D:FB`, FW 5.6.19) — updated architecture.md and glossary.md. CIO provided PMO template from PMO_Template project. Full adoption approved: backlog.json (Epic>Feature>Story), global story counter (US-101+), tester agent, PMO layer, sprint retrospectives, rework tracking. 9-phase migration plan created. |
| 2026-02-05 | Marcus (PM) | Session 9: Ralph agent system upgraded from DataWarehouse template. Consolidated agent.py (5 commands), upgraded ralph.sh (6 stop conditions, status/help), upgraded prompt.md (agent coordination, sprint summary), created README.md. Fixed AGENT.md case sensitivity for Pi. Cleared stale agent assignments. Tester agent confirmed active (test cleanup). |
| 2026-02-05 | Marcus (PM) | Session 10: CIO knowledge capture (2 rounds — driving patterns, preferences, hardware plan). 4 parallel research tasks: polling frequency, stock PIDs, DSMTuners community, mobile apps. Created `specs/obd2-research.md` (13 sections, comprehensive OBD-II reference). Added PM Rule 7 (no fabricated data). 9 new key technical decisions. Expanded CIO profile with operational context. |
| 2026-02-05 | Marcus (PM) | Session 11: Specs housekeeping — 10 files cleaned up. Converted groundedKnowledge.txt and best practices.txt to markdown with project alignment notes. Reviewed/deleted 7 raw hardware txt dumps (data already in PRD, extracted new details: motherboard MSI MS-7885, CPU turbo 3.5GHz, RAM Corsair CMK64GX4M4A2666C16 quad-channel, kernel 6.12.63). Reviewed 3 CIO input files (Answers.txt, Answers2.txt, Eclipse Projects.xlsx) — confirmed 100% extraction, captured VIN `4A3AK54F8WE122916` and bolt-on mods. specs/ now has zero .txt files. |
| 2026-02-13 | Marcus (PM) | Session 12: PMO migration executed. Created `pm/backlog.json` (9 epics, 27 features, 128 stories, 9 tech debt, 10 issues) and `pm/story_counter.json` (global counter at US-101). Renamed `techDebt/` → `tech_debt/`. Archived 7 completed B-items and 3 completed PRDs to `pm/archive/`. Updated 11 files with new paths. 32 files changed, 701 insertions. |
| 2026-04-13 | Marcus (PM) | Session 14: Marathon session 2026-04-11 → 2026-04-13. **6 sprints shipped** (54 stories, 1,517 tests passing): Sprint 1 B-002/B-015/B-024/B-026, Sprint 2 B-028/B-032, Sprint 3 B-030, Sprint 4 hotfix US-139, Sprint 5 B-033, Sprint 6 hotfix US-145. **Epic E-10 Tuning Intelligence created** from Spool's 2026-04-10 tuning spec (5 items, 32 stories). **Spool review gate established**: 3 reviews delivered (original spec, corrections, code audit) catching 7 variances. **offices/ restructure finally committed** (108 files). **Draft PRD for Infrastructure Pipeline MVP** (sprints 7/8/9, 9 stories US-147–155) pending Ralph's B-040 reorg completion. **Architectural decisions brief** delivered to Ralph's inbox covering 5 open decisions. Main is 5 commits ahead of origin (not pushed — waiting for reorg to land). Ralph active on `sprint/reorg-sweep1-facades`. |
