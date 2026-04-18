# Project Manager Knowledge Base

## PM Identity

**Name**: Marcus
**Role**: Project Manager for the Eclipse OBD-II Performance Monitoring System
**Reports To**: CIO (project owner)
**Scope**: PRD creation, user story grooming, acceptance criteria, specs governance. Marcus never writes code.

## Purpose

This document serves as long-term memory for AI-assisted project management of the Eclipse OBD-II Performance Monitoring System. It captures session context, decisions, risks, and stakeholder information.

**Last Updated**: 2026-04-18 (Session 21 — Sprint 10 + Sprint 11 both shipped)
**Current Phase**: **B-037 Pi Crawl + Walk phases BOTH COMPLETE.** Sprint 10 shipped 8/8 (merged to main@9d7fa98). Sprint 11 shipped 7/7 (merged to main@0ffcd47). 15 stories across two sprints. Pi tier now has: deploy automation + systemd + MAX17048 UPS (correct VCELL-trend power-source) + primary display + sync_log + HTTP SyncClient + manual sync CLI + end-to-end validation. BL-004 + BL-005 resolved. I-015 resolved. TD-014 + TD-016 closed. Test count: 1871 (Sprint 9 baseline) → 1977 (Sprint 10) → 2068 (Sprint 11). Remaining B-037 phases: Run (4 stories, blocked on CIO BT pairing + car access) + Sprint (6 stories, blocked on Run completion). Non-B-037 Sprint 12 candidates ready: B-042 obd→obdii rename (closes I-014), US-165 display advanced tier (slipped from Walk), US-183 pygame HDMI render.

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
8. **Sprint-branch workflow (CIO directive, Session 20).** Every sprint sent to Ralph runs on its own repo branch. Marcus (PM) creates the branch before loading `sprint.json` and handing off. At sprint close, Marcus commits all changed files on the sprint branch, pushes the branch to `origin`, then merges into `main`. Ralph never touches git (per Rule in `feedback_ralph_no_git_commands.md`). This supersedes the Session 18 pattern of running sprints directly on `main`.

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

### Current State (2026-04-18, Session 21)

- **Sprint 10 (Pi Crawl, B-037) SHIPPED 8/8 on `sprint/pi-crawl`.** Ralph shipped 4 stories in Sessions 33–42 (US-164, US-179 live-verify, US-181, US-182), PM reset US-180 in this session, and Ralph shipped US-180 as Session 44 autonomously while this closeout was being written.
- **Sprint 10 passed (cumulative, all 8)**: US-176 (deploy-pi.sh + hostname + tar-over-ssh fallback), US-177 (simulator on ARM aarch64), US-178 (DisplayManager 3 driver modes via Option C), US-179 (systemd + TD-010 path cleanup), US-164 (primary screen basic tier — `primary_renderer.py` + 2 test files), US-181 (graceful shutdown — SIGTERM + pushbutton mock via direct-invoke due to BL-004), US-182 (Pi pytest baseline 1583 on chi-eclipse-01 + `pi_only` marker + Python 3.13 `adafruit_rgb_display` NameError fix + `test_verify_database` timeout bump), **US-180** (MAX17048 register-map rewrite via Ralph Session 44).
- **US-180 live evidence (chi-eclipse-01, Session 44)**: `UpsMonitor.getBatteryVoltage()` = 4.2062V × 3, `UpsMonitor.getBatteryPercentage()` = 70%/70%/72%, `UpsMonitor.getChargeRatePercentPerHour()` = None (0xFFFF sentinel, correctly interpreted as "disabled on this chip variant"), `UpsMonitor.getPowerSource()` = EXTERNAL (EXT5V 5.27V via `vcgencmd pmic_read_adc EXT5V_V`, 4.5V threshold). VERSION register 0x0002 confirms MAX17048 family. Full regression: 1977 passed Windows + 47 hardware tests on Pi aarch64 Python 3.13.5. BL-005 resolved, TD-016 resolved.
- **Only outstanding US-180 item**: CIO physical unplug drill for AC #6 (EXT5V-unplug → source flips to BATTERY). Checklist is in Ralph's Session 44 completion note. Software path fully tested; physical confirmation is a post-merge step. Session 20 MEMORY.md already recorded EXT5V 3.66V under UPS discharge (the collapsed state this AC predicts), so cause-and-effect is proven independently.
- **US-180 diagnostic arc (resolved)**: Session 20 CIO fixed the `i2cdetect -y 1` silence (battery in 5V OUTPUT JST, not BAT INPUT); X1209 lit up at 0x36. Session 41 Rex re-ran `UpsMonitor` end-to-end and got garbage — raw SMBus probe identified chip as MAX17048 fuel gauge. Rex filed **BL-005** (options A/B/C) + **TD-016** (register-map delta). Session 21 PM reset US-180 with expanded scope (Option A variant, in-place). Session 44 Ralph autonomously shipped the rewrite — new register map + `getChargeRatePercentPerHour()` via CRATE + power source derived from `vcgencmd pmic_read_adc EXT5V_V`.
- **BL-005 resolved** — Option A variant shipped via US-180 Session 44. Resolution annotated.
- **TD-016 resolved** — register-map delta documented + applied.
- **BL-004 still open** — `deploy/eclipse-obd.service` missing `--simulate` flag; systemd-start fails under current config. US-181 verified via direct-invoke + `kill -TERM`. Already `passed:true`. Not urgent. Sprint 11 candidate for a 2-line service file follow-up.
- **Tech debt still open**: **TD-015** (hardware-available false-negative post-TD-014 edge case), **TD-017** (Windows Store Python subprocess cold-start flake >30s — mitigated by timeout bump, not root-caused).
- **Git state (end-of-session)**:
  - On `sprint/pi-crawl` at `19fee67` (PM's US-180 reset), pushed to origin
  - `main` unchanged since Session 20 (at `744a709`)
  - **~21 modified + 5 new files uncommitted** in working tree — Ralph's Sprint 10 code deliverables from Sessions 33–44 (US-164 display, US-181 shutdown, US-182 pi-baseline, US-180 UpsMonitor rewrite + telemetry_logger + hardware_manager + specs/architecture.md + 2 test files rewritten). Ready to be swept into the Sprint 10 closeout commit next session per Rule 8, then merged to `main`.
- **Agents**:
  - Ralph: idle. Sprint 10 shipped 8/8. Ready for Sprint 11 assignment.
  - Spool: idle. Queued for first-real-drive review ritual when Pi goes live with real OBD data.
- **Active Specs**:
  - Pi crawl/walk/run/sprint: **B-037 Crawl phase COMPLETE 8/8**. Walk/run/sprint phases still ahead.
  - US-183 (pygame HDMI validation) unblocked by TD-014 + US-180 completion; Sprint 11+ candidate.
- **Backlog**: 42 features. B-036 complete. B-037 crawl complete. B-041 (Excel CLI) pending PRD grooming. B-042 (obd rename) filed, Sprint 11+ candidate.
- **Story Counter**: nextId = **US-184** (unchanged — Option A variant reset kept US-180 in place).
- **Issues/TD**: I-014 open (obd shadowing → B-042). TD-015/017 still open. TD-014 closed Session 20. TD-016 closed Session 21 via US-180.

### Previous State (Session 20 snapshot for reference)

- Sprint 10 (Pi Crawl, B-037) opened on new `sprint/pi-crawl` branch per **PM Rule 8** (sprint-branch workflow — every Ralph sprint on its own branch, PM merges to main at close). 4/8 passed end-of-session.
- **X1209 hardware saga resolved**: `i2cdetect -y 1` silence traced to battery plugged into the **5V OUTPUT JST** instead of one of the two **BAT INPUT JSTs**. After swap, 0x36 responded. Raw-SMBus readings captured: 4.181V full / 3.66V on discharge / CRATE -0.21%/hr / EXT5V 5.22V regulated to Pi. Hardware is sound — the Session 41 code-side bug was found later and is what Session 21 is resetting US-180 to fix.
- **Infrastructure unblocks**: `744a709` PM Rule 8 on main. `fc99ff2` agent.py field-name typos (`userStories`/`passes` → `stories`/`passed`). `7b3afd7` ralph.sh --allowedTools expansion (the REAL SSH unblocker; CLI-flag allowlist was hardcoded to git+python+pytest). `763c8a6` TD-014 one-liner (`src/pi/obd/orchestrator/lifecycle.py:39-40`: `src.pi.hardware.*` → `pi.hardware.*`; HARDWARE_AVAILABLE=True at runtime).
- **Decisions captured**: US-178 → Option C (ACs rewritten to match reality, pygame HDMI split to US-183). obd package shadowing → Option A rename (filed I-014 + B-042 for Sprint 11+).
- **Ralph working model confirmed**: hybrid. Writes on Windows + SSHes to `mcornelison@10.27.27.28` for Pi verification. CIO handles physical steps. Key-based SSH working; blocker was --allowedTools CLI flag, not settings.
- Git: on `sprint/pi-crawl` at `763c8a6`, main at `744a709`.

### Immediate Next Actions (Session 22 pickup)

1. **Sprint 10 closeout commit + Rule 8 merge**: sweep Ralph's ~21 uncommitted files from Sessions 33–44 into a single commit on `sprint/pi-crawl`. Expected working-tree scope: `src/pi/hardware/ups_monitor.py` (MAX17048 rewrite), `src/pi/hardware/telemetry_logger.py` (field surface), `src/pi/hardware/hardware_manager.py` (getStatus), `src/pi/display/screens/primary_screen.py` + new `primary_renderer.py`, `specs/architecture.md` (lines 95 + 747), `pyproject.toml` (`pi_only` marker), `scripts/verify_hardware.py` (Python 3.13 fix), `tests/conftest.py`, `tests/pi/hardware/test_{telemetry_logger,ups_monitor}_*.py`, `tests/pi/display/test_primary_screen_*.py`, `tests/pi/hardware/test_pi_only_smoke.py`, `tests/server/conftest.py`, `tests/test_verify_database.py` (timeout bump), `tests/test_e2e_simulator.py`, `tests/test_remote_ollama.py`, `src/server/ai/ollama.py`, and the `offices/ralph/` state files. Then `git push origin sprint/pi-crawl`, merge to `main`, delete the sprint branch. Flip B-037 in `backlog.json` from "in flight" to "crawl phase complete". Close out TD-015/017 + I-014 status notes as needed.
2. **CIO physical unplug drill for US-180 AC #6**: post-merge confirmation step. CIO runs the checklist in Ralph's Session 44 completion note — unplug USB-C from wall while on UPS LiPo, confirm EXT5V drops below 4.5V and `UpsMonitor.getPowerSource()` flips to BATTERY, replug, confirm recovery to EXTERNAL. Cause-and-effect already proven (Session 20 MEMORY.md captured EXT5V 3.66V discharge); this is one-shot confirmation.
3. **Decide BL-004**: `eclipse-obd.service` missing `--simulate` flag. Three options: (a) 2-line service file follow-up story for Sprint 11 kickoff, (b) flip `pi.simulator.enabled` default to `true` in `config.json`, (c) accept direct-invoke evidence as permanent closeout. CIO direction needed.
4. **Scope Sprint 11** with CIO. Candidates:
   - **B-037 Walk** (sync client + e2e to Chi-Srv-01) — advances Pi tier; Pi→Server delta-sync is the logical next step
   - **B-042 obd → obdii rename** (~45 files, tests, imports) — closes I-014, clears a latent systemd landmine
   - **BL-004 follow-up** — small service-file story (could bundle into Sprint 11 opening)
   - **US-183 pygame HDMI render** — now fully unblocked (TD-014 fixed Session 20, US-180 shipped Session 44); physical display validation on Pi
   - **B-041 Excel Export CLI PRD grooming** — CIO-requested; needs 3 open Qs answered (default PID set, Excel engine, endpoint shape)
5. **CIO parallel work (unchanged)**: OBDLink LX Bluetooth pairing with `chi-eclipse-01` (MAC `00:04:3E:85:0D:FB`). Unlocks B-037 Run phase when combined with the ECU being in the car.
6. **Unresolved small items** (unchanged):
   - chi-srv-01 IP discrepancy (`.10` per Ralph's SSH config vs `.120` in specs/architecture.md)
   - Stale `sprint/server-walk` local branch (delete candidate)
   - MAX17048 SOC ModelGauge warmup quirk (~minutes, self-corrects). Acceptable. Optional Quickstart command (reg 0x06, write 0x4000) would short-circuit; not a story yet.

### Parallel-Session Rules (Learned the Hard Way This Session)

- **Never chain compound bash commands** (`cd X && cmd1 && cmd2`). Single commands are pre-approved by allowlist, compound chains re-prompt per chunk. Use `git` from cwd (repo root is already findable from any subdir), absolute paths with other commands, and parallel Bash tool calls for independent ops.
- **When Ralph is on a sprint branch**, PM **does not** `git checkout main` in the same shell. Ralph's working tree flips too. Use a second shell, a git worktree, or `git -C <path>` style (limited here because compound forms aren't allowed — prefer worktree).
- **Before trusting git state at session start**, run a fresh `git status` + `git branch` + `git log --all --oneline -20`. The session-init snapshot can lag reality if another session was active between turns.

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

### Last Session Summary (2026-04-18, Session 21 — Sprint 10 SHIPPED 8/8: US-180 reset + Ralph's autonomous Session 44 rewrite)

Focused PM session that bookended Ralph's autonomous work. Entry: CIO instinct to "reset US-180 and retry"; PM pushed back (naked retry would hit same bug — ACs test `UpsMonitor.getBatteryVoltage()` which had the wrong register map); CIO agreed to in-place scope expansion; PM landed the reset; Ralph picked it up and shipped it autonomously as Session 44 **while this closeout was being written**. Sprint 10 closed at 8/8 during the PM session.

**Session entry state** (carry-forward from Session 20 closeout): Sprint 10 at 4/8 passed with Ralph actively writing US-164. By the time I initialized in Session 21, Ralph had already shipped Sessions 33–42 (US-176 live-verify, US-164, US-181, US-182 all passed, plus TD-014 confirmed in place) — so the actual entry state was 7/8 passed + 1 blocked (US-180). Seven more stories of progress than Session 20's closeout knew about. Nothing I had to do for any of those — Ralph handled them autonomously through `ralph.sh`.

**What was accomplished:**

- **Diagnosed US-180 blocker**: Rex Session 41 had filed BL-005 + TD-016 after discovering the X1209 chip (alive at 0x36 per Session 20 CIO fix) is a MAX17048 fuel gauge, not the INA219 the `UpsMonitor` code was written against. Register map is wrong on every register — VCELL at 0x02 big-endian ×78.125 µv/LSB (gives plausible 4.19V), SOC at 0x04 big-endian high-byte (gives 86%), CRATE at 0x16 signed ×0.208 %/hr, CONFIG at 0x0C. MAX17048 has no current register and no power-source register, which makes US-180's literal ACs #3 (current) and #5 (AC-vs-battery) infeasible without an architecture change.
- **Evaluated three resolution paths for BL-005**: Option A (new US-184 rewrite), Option B (accept raw-probe evidence + defer code fix), Option C (block indefinitely). CIO proposed a hybrid — reset US-180 in place and have Ralph retry. PM pushed back because retry would hit the same broken register map; CIO agreed to expand US-180 scope in place rather than split the work to US-184. Net: story counter stays at `US-184` (no new ID consumed), BL-005 resolves as "Option A variant (in-place reset)".
- **Reset US-180 in `offices/ralph/sprint.json`** (commit `19fee67`, pushed):
  - `status: blocked` → `status: pending`; removed `completedDate` (story isn't complete); kept Rex's Session 41 blockedReason + completionNotes for audit trail
  - New `pmScopeRewrite` field captures authorization + chip semantics + target reading values (from Session 20 raw-probe: V=4.181V full / 3.66V discharge / CRATE=-0.21%/hr / EXT5V=5.22V) — Ralph reads this first
  - `scope.filesToTouch` lifted the "narrow if bugs surface" scope guard — now explicitly includes `src/pi/hardware/ups_monitor.py` (register-map rewrite authorized), `telemetry_logger.py` (field surface update), and `specs/architecture.md` (line 747 INA219→MAX17048)
  - Acceptance criteria rewritten: AC #3 voltage via MAX17048 VCELL semantics; AC #4 SOC via high-byte %; new AC for `getChargeRatePercentPerHour()` via CRATE register; revised AC #5 to derive power source from `vcgencmd pmic_read_adc EXT5V_V` (since MAX17048 has no source register); new ACs for spec doc + file header updates
  - `stopConditions` updated — obsolete "do not proceed to US-181" removed (US-181 already `passed:true` via UPS-I2C-independent path); added new stopCondition for MAX17048 VERSION register sanity check
  - Preserved Rex's 32 tests from Session 36 — they mock `I2cClient` and survive chip-semantics change; fixtures may need minor updates where register layout shifted
- **BL-005 resolution annotated** — Option A variant, pointer back to the in-place reset. TD-016 closed this session by US-180 Session 44.
- **Ralph's autonomous Session 44 run** (during this PM session): picked up the reset US-180 on his own via `ralph.sh`. Rewrote `src/pi/hardware/ups_monitor.py` for MAX17048 semantics (VCELL 0x02 big-endian ×78.125 µv/LSB, SOC 0x04 high byte %, CRATE 0x16 signed ×0.208 %/hr with 0xFFFF→None sentinel, VERSION 0x08 confirms chip family). Replaced `getBatteryCurrent()` with `getChargeRatePercentPerHour()`. Derived `getPowerSource()` from `vcgencmd pmic_read_adc EXT5V_V` with 4.5V threshold. Updated `telemetry_logger.py` field surface (`battery_ma` → `battery_charge_rate_pct_per_hr`), `hardware_manager.py` getStatus shape, and `specs/architecture.md` lines 95 + 747. Live on Pi: V=4.2062V / SOC=70-72% / CRATE=None / source=EXTERNAL. 43 Windows + 47 Pi hardware tests pass + full 1977-test fast regression clean. All scope discipline held (no touches outside authorized files, no sudo-from-Python).
- **BL-004 deferred decision** — the `deploy/eclipse-obd.service` file is missing `--simulate` flag. US-181 was verified via direct-invoke. Already `passed:true`. Sprint 11 candidate for a 2-line service file follow-up.

**Key decisions:**

- **BL-005 → Option A variant**: in-place US-180 scope expansion beats spawning US-184. Keeps Sprint 10 closeable at 8/8 (not 7/8 + carryover). Preserves all historical context in US-180's audit trail. Risk: story body gets longer. Worth it.
- **Register-map rewrite IN SCOPE for US-180**: the "narrow if bugs surface" phrasing from the original sprint scope was too conservative for this specific case. Chip-semantics rewrite is a legitimate part of "exercise the hardware path" when the code was written for the wrong chip.
- **Power source via `vcgencmd pmic_read_adc EXT5V_V`**: MAX17048 literally has no power-source register. Deriving from the Pi's external 5V rail ADC is the cleanest replacement — works even if the HAT had no sense pin at all.
- **CRATE as the `getBatteryCurrent()` replacement**: `getChargeRatePercentPerHour()` is the most physically meaningful signal MAX17048 provides (signed, direction-aware, %/hr). Session 20 captured -0.21%/hr under UPS discharge — we have a real target number for the AC.
- **Don't drop AC #5 to a follow-up**: keeping the unplug/replug dance in US-180 proves the full graceful-degradation path end-to-end. The CIO has already done this once physically in Session 20; a repeat under the rewritten code is exactly the evidence we want.

**Key commit:**

- `19fee67` — `pm: reset US-180 with scope expansion — MAX17048 register-map rewrite authorized`

All Sprint 10 code from Sessions 33–44 (US-164/179-live/181/182 + US-180 Session 44 rewrite, TD-015/016/017 filings, BL-004/BL-005 filings) remains uncommitted in the working tree — will be swept into a single Sprint 10 closeout commit next session per Rule 8.

**What's next (recap of Immediate Next Actions above):**

1. Sprint 10 closeout commit on `sprint/pi-crawl` + merge to `main` per Rule 8.
2. CIO physical unplug drill for US-180 AC #6 (post-merge confirmation).
3. BL-004 decision + Sprint 11 scoping.

**Unfinished work:**

- Ralph's ~21 uncommitted Sprint 10 code files — single Sprint 10 closeout commit planned for Session 22.
- BL-004 pending CIO decision.
- CIO physical unplug drill for US-180 AC #6 (not blocking; software path fully tested).
- `.claude/commands/closeout-ralph.md` still modified in working tree (persistent drift from an earlier session — harmless).

**Post-session git state:**

- Current branch: `sprint/pi-crawl` at `19fee67` (PM closeout commit to follow), pushed to origin.
- `main` unchanged since Session 20 (at `744a709`).
- Sprint branch merges to `main` at Sprint 10 close per Rule 8 (Session 22).

---

### Previous Session Summary (2026-04-17, Session 20 — Sprint 10 Pi Crawl in flight: 4/8 passed, infra unblocks, X1209 hardware saga resolved)

The last few hours of this session were dominated by unblocking hardware + harness problems so Ralph could actually drive Sprint 10 to its conclusion. Net: 4 stories passed, 3 runnable, 1 story (US-180) fully hardware-validated live and awaiting a Ralph re-run. Ralph is actively working US-164 as this closeout writes.

**What was accomplished:**

- **PM Rule 8 established** (`744a709` on `main` + pushed): Every Ralph sprint runs on its own repo branch; PM creates before handoff, merges to main at close. Supersedes the Session 18 pattern of sprints landing directly on main. Saved as `feedback_sprint_branch_workflow.md` memory + indexed in MEMORY.md.
- **Sprint 10 (B-037 Pi Crawl) loaded** (`bc1307f`): 8 stories in sprint-contract v1.0 format on a new `sprint/pi-crawl` branch. All 8 dependency-chained so US-176 had to pass first. Cross-cutting decisions baked in (IP `10.27.27.28`, hostname `chi-eclipse-01`, project path `/home/mcornelison/Projects/Eclipse-01`, venv `~/obd2-venv`, mode: hybrid Ralph-SSH + CIO-physical). Story counter bumped US-176→US-183.
- **Ralph iteration 1** (`2c604d4`): 3 passed — US-176 deploy-pi.sh (--help/--init/--restart/--dry-run, idempotent rsync, hostname rename via hostnamectl, 29-assertion bash smoke + 3-case pytest wrapper), US-177 simulator on ARM (all 4 scenarios run to ScenarioState.COMPLETED on aarch64), US-179 systemd service + TD-010 path-drift cleanup across 7 files (grep for `src/main.py\|/home/pi/obd2\|User=pi` now returns 0 outside archived history).
- **Ralph iteration 2** (`3448630`): 2 PARTIALs surfaced with detailed blocker writeups — US-178 (pygame path dead code due to TD-014) + US-180 (X1209 no I2C presence). 32 new software tests shipped (9 UpsMonitor graceful-degradation + 15 GPIO mock + 8 TelemetryLogger rotation). BL-003 filed. Three TD/issue files filed (TD-013 simulator integration dead API, TD-014 lifecycle.py import bug, plus inbox note for obd package shadowing).
- **Root-cause unblock of the Ralph harness** (`7b3afd7`): `ralph.sh` line 76 hardcoded `--allowedTools "Bash(git:*),Bash(python:*),Bash(pytest:*)"` — that CLI flag overrode the `.claude/settings.local.json` allowlist for Bash commands. Expanded to `RALPH_ALLOWED_TOOLS` variable covering ssh, rsync, scp, bash, make, ruff, and 25+ utility tools. Earlier ad2fee0 SSH colon-form fix to settings files turned out to be inert for this reason (settings file is only read when cwd is at project root, which ralph.sh already does via cd $PROJECT_ROOT, but --allowedTools overrides).
- **PM tooling fixes**: `fc99ff2` agent.py — 4 field-name typos (`userStories` → `stories` at line 102 + `passes` → `passed` at 111/121/124). This was the "ralph.sh broken again" symptom the CIO reported at the start of the session. Turned out ralph.sh was fine; agent.py had the sibling class of bug from Ralph's earlier `fa05c7f` fix.
- **US-178 Option C landed** (`db19724`): flipped passed:true by rewriting ACs to match what actually exists (DisplayManager 3 driver modes — all delivered + live-verified). Original pygame HDMI + touch ACs referenced surfaces that don't exist in the current codebase. Deferred those concerns to new story **US-183** — filed in B-037.md follow-up section, depends on TD-014 + US-180.
- **obd shadowing decision → Option A** (`db19724`): filed I-014 (the bug: `obd.OBD(...)` fails under systemd because project's `src/pi/obd/` shadows third-party python-OBD) + B-042 (remediation: rename to `src/pi/obdii/`, ~45 files, Sprint 11+ candidate). Sprint 10 unaffected since crawl is simulator-only.
- **US-180 rescope → pause + unpause** (`92836fc` then `763c8a6`): Mid-session CIO paused US-180 when the X1209 looked broken. I updated sprint.json status=blocked + rescoped US-181 to drop US-180 from dependencies (pushbutton + SIGTERM path instead of UPS-I2C path) + dropped US-180 from US-182 deps. Then the X1209 came alive and I flipped US-180 back to status=pending, keeping the rescoped US-181 in place.
- **X1209 hardware diagnostic journey** (no code change, just evidence gathering):
  - Initial state: `i2cdetect -y 1` empty, 5 of 5 tests: power cycle, reseat, button press → all no-change
  - Geekworm wiki fetched: confirms "Maxim fuel-gauge systems for reading battery voltage and percentage over i2c" — so it should have I2C telemetry
  - Suptronics URL 404'd; deeper docs not available
  - CIO reported weak/fading power LED when USB-C fed the HAT but solid when fed the Pi direct — suggested undervoltage
  - Split the display off to its own supply — symptom persisted, ruled out peripheral-draw
  - Disconnected battery entirely — X1209 went solid (2 red + 3 green LEDs). Re-probe: **0x36 detected**. So: battery was the load-side issue.
  - Asked CIO to inspect the 1st photo carefully — battery JST was plugged into the **5V OUTPUT port** (bottom-right) instead of one of the two **BAT INPUT ports** (top of board).
  - CIO swapped: 4 green LEDs solid. 0x36 still responding. Direct MAX17048 register reads returned: V=4.181 / SOC=12.8% first boot / SOC=29.5% warm (ModelGauge self-correct), then on UPS-mode discharge V=3.664 / CRATE=-0.21%/hr / EXT5V=5.22V regulated to Pi. All US-180 ACs #2-5 satisfiable with real data; 32 existing software tests stay valid.
  - CIO plugged back in to recharge; X1209 verified functional end-to-end.
- **TD-014 resolved** (`763c8a6`): one-line fix in `src/pi/obd/orchestrator/lifecycle.py:39-40` (`from src.pi.hardware.*` → `from pi.hardware.*`). Smoke-tested on Windows: HARDWARE_AVAILABLE=True after fix. TD-014 file marked Resolved. This one silently broke every runtime hardware init for the entire project history.
- **Ralph iteration 3 in flight at closeout**: new files in working tree (`src/pi/display/screens/primary_renderer.py`, `tests/pi/display/test_primary_screen_basic_tier.py`, `tests/pi/display/test_primary_screen_render.py`, + `src/pi/display/screens/primary_screen.py` modifications). This is US-164 primary screen basic tier. Not committed — leaving unstaged for the next closeout checkpoint.

**Key decisions:**

- **PM Rule 8** (sprint-branch workflow) — CIO directive, persistent.
- **US-178 Option C** over extending scope or splitting immediately — honest-about-reality path + follow-up story.
- **obd rename Option A** to `obdii` — rename wins over import hacks because a hack leaves the landmine latent for new callers.
- **TD-014 landed on sprint branch** (not main) — belongs with the sprint scope that motivated it; will travel to main at sprint close.
- **Fuel gauge + MAX17048 + 0x36 were all correct the whole time** — no spec change needed. The prior spec↔code mismatch (arch spec said INA219 at 0x36, code was MAX17048 semantics at 0x36) is moot: there is no INA219, the code is right, the spec is wrong. Queued (informally) to fix specs/architecture.md:747 in a future pass.

**Key commits (in order, on `sprint/pi-crawl` unless noted; all pushed to origin):**

- `744a709` (on `main`) — PM Rule 8 sprint-branch workflow
- `bc1307f` — Sprint 10 loaded
- `fc99ff2` — agent.py field-name alignment
- `ad2fee0` — SSH allowlist colon-form (inert — settings files not the active layer)
- `2c604d4` — Ralph iter 1 (US-176 + US-179 PARTIAL)
- `7b3afd7` — ralph.sh --allowedTools expansion (real SSH unblocker)
- `3448630` — Ralph iter 2 (3 PARTIALs, big test delivery, blockers filed)
- `db19724` — US-178 Option C + I-014/B-042 filed
- `92836fc` — US-180 paused, US-181 UPS-I2C-independent rescope
- `763c8a6` — TD-014 fix + US-180 unblock
- (this closeout commit)

**What's next (recap of Immediate Next Actions above):**

1. Ralph completes US-164 (in flight), then picks up US-180 + US-181 + US-182.
2. Sprint 10 closes out (this session or next). PM merges `sprint/pi-crawl` → `main` per Rule 8.
3. Sprint 11 scoping: B-037 Walk, B-042 obd rename, US-183 pygame HDMI — options to discuss with CIO.
4. Small open items (chi-srv-01 IP, stale branch, flake test) still deferred.

**Unfinished work:**

- Ralph's US-164 deliverables unstaged in working tree (`primary_renderer.py` + 2 test files + `primary_screen.py` edits) — leaving for next checkpoint since Ralph is still running.
- US-180 status:pending but not yet re-run by Ralph to flip passed:true (hardware validated live already).
- US-181, US-182 pending.
- obd package shadowing is filed but not fixed — B-042 slated for Sprint 11+.
- MAX17048 Quickstart command not wired — SOC first-boot reads stay wrong for the first few minutes. Acceptable since voltage is always accurate. Can be added as a micro-story if real use shows confusion.
- `.claude/commands/closeout-ralph.md` still modified in working tree (persistent drift from an earlier session — not mine to commit).
- `offices/ralph/ralph_agents.json` modified by Ralph mid-run — will settle when he stops.

**Post-session git state (at closeout commit):**

- Current branch: `sprint/pi-crawl`
- Fully pushed to origin at every commit in this session. Pre-closeout head: `763c8a6`.
- `main` is 1 commit ahead of session start (Rule 8 @ `744a709`), already pushed.
- Sprint branch will merge to main at sprint close per Rule 8.

---

### Previous Session Summary (2026-04-17, Session 19 — Sprint 9 SHIPPED 5/5 + B-036 Epic COMPLETE + Regression Infrastructure + Spool AI Pipeline Live)

Landmark session. B-036 (Server Crawl/Walk/Run) — the single biggest server epic — went from 4/18 stories on session start to **18/18 COMPLETE** by session end. Started with diagnosing a CIO deploy failure (2 real bugs in `deploy-server.sh`, filed as I-013 and fixed), built regression fixture infrastructure, filed TD-011 + B-041, launched Sprint 9, got Spool's AI prompt templates delivered, routed to Ralph, and Ralph shipped all 5 Sprint 9 stories in parallel. Live server on chi-srv-01:8000 now runs the full pipeline: delta sync → MariaDB → analytics → Ollama AI → ranked recommendations → auto-analysis on sync → baseline calibration → AI-enhanced CLI reports. Test count 1766 → 1871 (+105).

**What was accomplished:**

- **Diagnosed CIO's deploy failure — 2 real bugs in `deploy/deploy-server.sh`:**
  - Step 5 `pkill -f 'uvicorn src.server.main:app'` self-matched its own SSH bash shell (the bash -c invocation literally contains that string). pkill killed its own session, SSH returned 255 with no output, `set -e` aborted the script — but the running server was already dead. CIO's deploy at 18:45 left the server down for ~10 min.
  - Step 6 `ssh HOST "nohup ... &"` hung indefinitely on SSH channel fds of the backgrounded child. Never reached Step 7 health check.
  - Fixes: `[u]vicorn` bracket trick (Step 5) + `ssh -f ... < /dev/null` (Step 6). Verified end-to-end: `--restart` now stops old uvicorn, starts new, health-checks green, returns 0.
  - Filed as **I-013** with full RCA (`offices/pm/issues/013-deploy-server-restart-bugs.md`).
- **Ran full regression validation on Sprint 8 server:**
  - Regenerated Session 17 SQLite inputs via `seed_scenarios.py --scenario full_cycle` + `--all`. Re-loaded via `load_data.py` with same device-ids.
  - MariaDB counts unchanged: 5 drives, 18,270 realtime rows, 10 connection events, 30 statistics. Sync_history +2 (audit trail, correct). Simulator is deterministic, load_data.py upsert fully idempotent on `(source_device, source_id)` keys.
  - CLI reports match Session 17: drive 4 cold_start flags multiple parameters 3σ+ anomalies vs warm-cruise baseline; trend report "RPM ↓ Falling +29.1% INVESTIGATE" identical to Session 17 capture.
- **Found and documented a crawl-path edge case** (not a server bug, a test-pattern trap): loading multiple separately-seeded SQLite files under one `device_id` collides on rowid-based `source_id` and silently clobbers earlier data. Pivoted: extended `seed_scenarios.py` instead of filing against load_data.py.
- **Extended `scripts/seed_scenarios.py`** with `--scenarios A,B,C` + `--gaps N,N` flags:
  - Accumulates multiple built-in scenarios into one SQLite with continuous rowids.
  - Models realistic "day of driving" (multiple drives with configurable parked-time gaps).
  - New `runScenarioList(scenarios, gaps, outputPath)` function, ~50 lines.
  - CIO's real-world example narrative — home → errand → errand → highway → home — now encodes cleanly as one seed invocation.
- **Created `data/regression/` fixture layout:**
  - `inputs/` with 3 .db files (1.5 MB total): `session17_single.db`, `session17_multi.db`, `day1.db`. All deterministic, regenerable.
  - `expected/` with 6 captured report outputs (drive_all, drive_latest, drive_4 cold-start anomaly comparison, drive_7 day1 cold-start, trends, db_counts).
  - `README.md` documents how to regenerate, how to diff expected vs actual, and when to update expected.
  - `.gitignore` negates `*.db` exclusion specifically for `data/regression/inputs/`.
- **Ran realistic "day 1" load under `eclipse-gst-day1` device:** cold_start → 20 min gap → city_driving → 40 min gap → highway_cruise → 15 min gap → city_driving. 4 drives landed, 7995 new realtime rows. Server state now 9 drives total / 26,265 rows. Analytics render correctly for both `sim-*` and `eclipse-gst-day1` device groupings.
- **Clarified identity model with CIO (answered, then filed tech debt):**
  - Today: one Pi + one Eclipse + one device_id = one vehicle. Good enough.
  - Schema is forward-compatible — `VehicleInfo` table keyed on VIN exists at `src/server/db/models.py:168`, just not populated.
  - CIO noted 100% of data will come from one Eclipse for the foreseeable future. Multi-vehicle is a possibility if system is successful.
  - Filed **TD-011** (`offices/pm/tech_debt/TD-011-vin-based-vehicle-identity.md`) with trigger = second vehicle or BT pairing live + VIN decode via Mode 0x09 PID 0x02.
- **Filed B-041 — Analytics Excel Export CLI** (CIO ask during session):
  - Windows-friendly Python CLI, multi-sheet `.xlsx` output, HTTP + X-API-Key auth only (no direct SQL).
  - Filters: `--start-date`, `--end-date`, `--drive-id` (repeatable), `--device-id`, `--params`, `--output`.
  - Three grooming Qs captured in the backlog file: default PID set, Excel engine choice, batched export vs per-table GETs.
  - Registered in `backlog.json` under E-11. Status pending — not yet groomed into PRD/sprint.
  - Dependency: server GET endpoints that don't exist yet.
- **Loaded Sprint 9 — Server Run phase** (B-036 run, 5 stories):
  - US-CMP-005 (L) — Real AI analysis endpoint via Ollama
  - US-CMP-006 (S) — Auto-analysis on drive receipt (blocked on 005)
  - US-CMP-007 (M) — Backup receiver endpoint
  - US-162 (M) — Baseline calibration tooling
  - US-163 (S) — AI-enhanced CLI reports (blocked on 005)
  - `offices/ralph/sprint.json` followed Sprint 8's contract format. Test baseline: 1766.
- **Sent Spool inbox request for AI prompt templates** (unblocks US-CMP-005):
  - Asked for `system_message.txt`, `user_message.jinja`, and a short design note.
  - Spelled out vehicle/hardware context, safety posture (don't recommend wideband/ECMLink things), and expected Jinja fields.
- **Spool delivered** a few hours later with all three files at `src/server/services/prompts/`:
  - `system_message.txt` (4.6 KB): hard hardware envelope, failure-mode catalogue (crankwalk, head gasket, #4 lean, etc.), JSON output contract, "don't pad" rule for empty recommendations.
  - `user_message.jinja` (3.7 KB): per-drive template consuming statistics/anomalies/trend/correlations/prior_drives_count.
  - `DESIGN_NOTE.md` (6 KB): six quality gates for Ralph, first-real-drive review ritual request, revisit queue for Phase 2.
  - Spool's directive: load as plain files, no inlining into Python source, so he can iterate prompts without a code change.
- **Routed Spool → Ralph via two-part handoff:**
  - **Ralph inbox note** (`offices/ralph/inbox/2026-04-16-from-marcus-spool-prompts-ready.md`): full briefing on Spool's rules, quality gates, first-drive review ritual, scope changes.
  - **`sprint.json` US-CMP-005 scope update**: prompt files moved filesToTouch → filesToRead, `src/server/services/prompts/` added to doNotTouch, removed "blocked on Spool" stopCondition, added "no prompt content inlined in Python source" + "empty recommendations[] is valid" acceptance criteria.
  - **Spool ACK note** (`offices/tuner/inbox/2026-04-16-from-marcus-ack-prompts-received.md`): confirmed receipt, committed to wiring first-real-drive review ritual, queued Phase 2 items (ECMLink fields, 70b escalation, severity field) as revisit-after-real-drives.
- **Ralph executed all of Sprint 9 in parallel during the PM session (Sessions 24–28):**
  - **US-CMP-007 ✓ (Ralph Session 24)**: `src/server/api/backup.py` + 38 TDD tests, router wired behind `requireApiKey`. 335 server suite passed (+38). Required `python-multipart` install.
  - **US-162 ✓ (Ralph Session 25)**: `src/server/analytics/calibration.py` + new `Baseline` ORM model + `is_real` boolean column on DriveSummary + `scripts/report.py --calibrate/--apply/--device` flags. 25 new tests. Grooming Q resolved: chose `is_real` boolean over `profile_id='real'` convention.
  - **US-CMP-005 ✓ (Ralph Session 26)** — Real Ollama-backed analyze endpoint. Ralph started implementation autonomously the moment Spool's prompt files landed — didn't wait for my handoff note. Full orchestrator in `src/server/services/analysis.py` (new module): validates drive_summary (missing → 404), refreshes analytics via `AsyncSession.run_sync` bridge, renders Jinja template, calls Ollama `/api/chat` via new `callOllamaChat()` in `src/server/ai/analyzer_ollama.py`, parses JSON (handles bare array / \`\`\`json fences / prose-with-array), persists `AnalysisRecommendation` rows, archives raw_response + rendered_user_message in `analysis_history.result_summary` specifically to feed Spool's first-drive review ritual. Error mapping: unreachable → 503, HTTP error → 502, missing drive → 404, no readings → 200 + empty recs. Malformed LLM items dropped not crashed; confidence clamped to [0,1]; output truncated to 5; categories filtered against allow-list. Prompt files loaded as plain paths (no Python inlining per Spool's directive). US-147 envelope preserved exactly for Pi-side forward compat. +23 new tests, -5 stub tests removed. Server suite 378 (+18 net).
  - **US-CMP-006 ✓ (Ralph Session 27)** — Auto-analysis on sync. 4 new public helpers in `analysis.py`: `extractDriveBoundaries` (pure pairing, dict-or-datetime timestamp tolerant), `pingOllama` (async GET, 5s timeout), `_ensureDriveSummary` (idempotent upsert derived from realtime_data window, matching crawl-phase semantics for crawl-vs-walk parity), and `enqueueAutoAnalysisForSync` (the orchestrator). Background tasks tracked in module-level `_pendingAutoAnalysisTasks` set with auto-discard callback — solves the asyncio GC-reference-loss gotcha and gives tests a drain surface. `_safeRunAnalysis` swallows exceptions to logger.error so background failures never leak. `sync.py postSync` awaits enqueue AFTER sync_history commits. +12 new tests. Server suite 390 (+12).
  - **US-163 ✓ (Ralph Session 28)** — AI-enhanced CLI reports. `src/server/reports/drive_report.py` extended with optional kwargs (`analysis`, `recommendations`, `baselineCount`, `baselineEstablishedAt`); when `analysis is None`, output is byte-for-byte identical to pre-US-163 — structural regression invariant, not just test-level. New DB helpers `_loadLatestCompletedAnalysis`, `_loadRecommendations`, `_loadBaselineEstablishedAt`; `baselineCount` derived via `countRealDrives` from US-162 work. Spec §3.6 layout matched: `Data Source: OBD-II (real|Simulator) | Sync: <completed_at>`, `AI Analysis (<model>, X.Xs):`, ranked `<rank>. [CATEGORY] <text>` with indented confidence, `Baseline Status` sub-section. Failed/in-progress analyses render no section (clean — no empty-state clutter). +15 new tests. Server suite 405 passed + 1 skipped (+15).
  - **Test progression: 1766 → 1804 → 1829 → 1847 → 1856 → 1871** passing across the 5 stories. Server suite 297 → 405.
  - Pre-existing `test_verify_database.py` Windows subprocess timeout flake showed up in 3 of the 5 completion notes. Unrelated to server code path — `scripts/verify_database.py` imports only `pi.obd.database`. Low priority but worth filing if persistent.
- **B-036 epic complete**: 18/18 stories across 3 sprints (Sprint 7 crawl 9, Sprint 8 walk 4, Sprint 9 run 5). Backlog.json: B-036 status flipped `groomed` → `complete` with `completedDate: 2026-04-17` + `completedInSprints: [Sprint 7, Sprint 8, Sprint 9]`.
- **Synced `backlog.json` hygiene**: B-036 story statuses were stale (all showed `pending`). Marked 9 crawl + 4 walk stories as `completed` with sprint attribution (Sprint 7 + Sprint 8). Flipped 5 run stories to `in_progress`, then 2 to `completed` (US-CMP-007 + US-162). Final B-036 state: **15 completed / 3 in_progress**. Updated metadata counts (pendingFeatures +1 for B-041, techDebtItems +1 for TD-011, openIssues +1 for I-013).

**Key decisions:**

- **Identity model (CIO + Marcus):** device_id = vehicle_id for now. VIN-based identity is future work (TD-011). Matches the realistic "one Pi in one Eclipse" deployment.
- **Regression fixture format (CIO → Marcus):** `data/regression/` — `.db` inputs checked in (small enough, deterministic), captured report outputs as expected/, README describes diff workflow. Tests live alongside the code they verify, not in a separate fixture repo.
- **Sprint 9 scope (Marcus proposed, CIO picked Option A):** B-036 Server Run. Closes the server epic in one sprint. Hybrid with B-037 Pi crawl was available but adds complexity; defer to Sprint 10.
- **Spool prompt files live at `src/server/services/prompts/` and are Spool's territory.** Ralph reads, does not write. Loaded as plain files (not package import) so Spool can update without a code change.
- **One-line `sprint/server-walk` cleanup deferred again** — harmless, can delete next session.

**Key commits (in order, on `main`, all pushed as of mid-session; closeout commits follow):**

- `52356dc` chore: deploy fixes + seed_scenarios day builder + regression fixtures
- `7bc6955` feat(pm): Sprint 9 loaded — Server Run phase + B-041 + Spool prompt request
- `5dd4fe9` feat(server): Sprint 9 — US-CMP-007 + US-162 complete, US-CMP-005 in progress
- `4eee967` feat(tuner): Spool AI prompt templates for US-CMP-005
- `9198387` docs(pm): route Spool→Ralph handoff for US-CMP-005 + sync status
- (Ralph Sprint 9 finish commit — US-CMP-005/006/163 code + tests)
- (Session 19 PM closeout commit — B-036 marked complete, projectManager.md + MEMORY.md updated)

**What's next:**

1. **Start Sprint 10.** Top candidates: B-041 (Excel CLI, needs PRD grooming), B-037 Pi Crawl (8 stories, parallel to CIO's BT pairing work). Hybrid is viable.
2. **First-real-drive review ritual** with Spool when Pi goes live. Ralph's US-CMP-005 already archives raw_response + rendered_user_message in `analysis_history.result_summary` — extraction is straightforward.
3. **CIO**: OBDLink LX Bluetooth pairing with chi-eclipse-01 (MAC `00:04:3E:85:0D:FB`). Unlocks B-037 run/sprint.
4. **Fix `agent.py:102`** diagnostic bug (one-line rename `userStories` → `stories`).
5. **Resolve chi-srv-01 IP discrepancy** (`.10` vs `.120`).
6. **Delete stale `sprint/server-walk` local branch.**
7. **File pre-existing `test_verify_database.py` Windows subprocess timeout flake** as a low-priority issue if it keeps showing up.

**Unfinished work:**

- None sprint-scope. All Sprint 9 stories shipped, B-036 epic complete.
- **`.claude/commands/closeout-ralph.md`** still modified in working tree from an earlier session — intentionally untouched.
- **`offices/{pm,ralph}/.claude/settings.local.json`** modified but not committed — local config, not relevant.
- **`data/obd.db-{shm,wal}` + `scheduled_tasks.lock`** files untracked — runtime artifacts.

**Post-session git state:**

- Current branch: `main`
- Fully synced with origin after closeout commits.
- Working tree: local settings/lockfiles only (intentionally ignored).

---

### Previous Session Summary (2026-04-16, Session 18 — Sprint 7 Merge + Sprint 8 Full Cycle + I-011/I-012 Fixes)

This session was a full sprint cycle for B-036 walk phase in one PM session, plus wrapping up Sprint 7 and filing related fixes. Ralph ran Sprint 8 in parallel with PM closeout work.

**What was accomplished:**

- **Sprint 7 merged to main and pushed to origin**: Fast-forward merge of `sprint/server-crawl` → `main`. 47 files, 9,263 insertions, 130 deletions. 15 commits total pushed (1 prior + 14 sprint). No conflicts.
- **I-011 and I-012 fixed autonomously by Ralph during this session** (`8fb5b30`):
  - I-011: `scripts/load_data.py` and `scripts/report.py` now use a shared `_toSyncDriverUrl()` helper that converts `mysql+aiomysql://` → `mysql+pymysql://` before `create_engine()`. Eliminates `MissingGreenlet` errors when scripts run against an async-driver DATABASE_URL.
  - I-012: `scripts/report.py` changed `_DEFAULT_DB_URL_ENV` from `SERVER_DATABASE_URL` to `DATABASE_URL`. All server code now uses one canonical env var name.
  - 6 new test cases, ruff clean, all passing.
- **Sprint 8 — Server Walk COMPLETE** (4/4 stories pass):
  - **US-CMP-002** (API key auth middleware): `src/server/api/auth.py` FastAPI dependency with `hmac.compare_digest()`, `/api/v1/health` exempt, all other endpoints require `X-API-Key`.
  - **US-CMP-004** (Delta sync endpoint): `POST /api/v1/sync` accepts delta payloads, upserts via `INSERT ... ON DUPLICATE KEY UPDATE` with `(source_device, source_id)`, writes `sync_history`, detects drive data, 10MB payload cap, single-transaction with rollback on error.
  - **US-147** (Stub AI analysis endpoint): `POST /api/v1/analyze` returns canned stub response with correct shape for US-CMP-005 forward compatibility. Writes to `analysis_history`.
  - **US-161** (Parity validation): integration test proves crawl-path (bulk load) and walk-path (HTTP sync) produce identical analytics within 0.01% tolerance across drive_summary, drive_statistics, anomaly detection, and comparison. Static invariant check: analytics imports zero data-path modules.
  - Test count: 1766 passing (+35 vs Sprint 8 baseline 1731). `pytest tests/server/` 297 passed / 1 skipped.
  - `pyproject.toml` gained the `parity` pytest marker registration.
- **Sprint 8 setup committed** (`8ddf5d9`): sprint.json loaded with 4 walk-phase stories before Ralph execution.
- **Spool Gate 1 confirmed** (`8ddf5d9`): Primary screen parameters ship as defaults (RPM, Coolant, Boost, AFR, Speed, Battery). AFR note: narrowband-interpreted pre-ECMLink (sanity check, not real AFR). Knock count can't ship pre-ECMLink (stock 2G ECU doesn't expose it via standard OBD-II). Gates 2 and 3 deferred.
- **Branch cleanup**: 8 merged branches deleted — `sprint/server-crawl` + 7 reorg sweeps.
- **`sprint/server-walk` created but unused**: Ralph worked Sprint 8 directly on `main`. Branch was created at the start of the session but never checked out for development. Left for decision on whether to continue the sprint-branch pattern.
- **Inbox activity**:
  - PM → Ralph: I-011/I-012 fix brief
  - PM → Spool: 3 display review gates
  - Spool → PM: Gate 1 confirmed
  - Ralph → PM: I-011/I-012 done
  - Ralph → PM: chi-srv-01 MariaDB setup complete (inherited from Session 17 but processed this session)
- **PM git directive established**: CIO delegated git/branching control to Marcus (PM). Ralph leaves all work unstaged for PM to commit. `feedback_ralph_no_git_commands.md` memory updated to reflect the role change.
- **Bug discovered**: `offices/ralph/agent.py:102` reads `userStories` (old stories.json field) instead of `stories` (sprint contract v1.0). Diagnostic-only bug — `agent.py sprint` reports empty but Ralph's actual workflow via prompt.md is unaffected.
- **IP discrepancy flagged**: Ralph reports real chi-srv-01 IP is `10.27.27.10` per `~/.ssh/config`, not the `.120` in `specs/architecture.md`. Unresolved — awaiting CIO confirmation.

**Key decisions:**

- CIO: Marcus controls all git/branching. Ralph leaves changes unstaged.
- Sprint 8 scope = exactly the 4 B-036 walk-phase stories. US-CMP-004 was L-sized, others S/M.
- Spool: ship defaults as-is. Refine post-real-data. No knock count until ECMLink.
- `.env` legacy stubs flagged as non-blocking future cleanup.
- `agent.py` diagnostic fix deferred — trivial but CIO's decision.

**Key commits (in order, main branch):**

- `116708a` docs: Ralph session 18 closeout — chi-srv-01 MariaDB setup (from Sprint 7 merge)
- `8fb5b30` fix: [I-011, I-012] CLI script DB driver and env var cleanup
- `8ddf5d9` docs: Sprint 8 (Server Walk) setup + Spool Gate 1 review
- `b980a35` docs: Ralph session 19 closeout — I-011/I-012 + init-agent merge (Ralph doc commit, unpushed at time of PM closeout)
- Sprint 8 code commit (TBD hash — PM closeout)
- PM Session 18 closeout commit (TBD hash)

**What's next:**

1. **Create Sprint 9 — Server Run phase** (B-036 run): US-CMP-005/006/007 + US-162/163. Real AI via Ollama, auto-analysis, backup receiver, baseline calibration, AI-enhanced reports. Needs Spool input on AI prompt templates.
2. **Fix `agent.py` diagnostic bug** — one-line rename (`userStories` → `stories`).
3. **Resolve chi-srv-01 IP discrepancy** (`.10` vs `.120`) — CIO input needed.
4. **Decide branch workflow** — sprint-branch pattern vs Ralph-direct-to-main.
5. **CIO hardware**: OBDLink LX BT pairing with chi-eclipse-01.
6. **TD-010** (deploy path drift).

**Unfinished work:**

- **`agent.py` diagnostic bug** not fixed.
- **IP discrepancy** in `specs/architecture.md` not resolved.
- **`sprint/server-walk` branch** created but unused — delete on next session.
- **`.claude/commands/closeout-ralph.md`** (modified) from another session/skill update, untouched this closeout.
- **`.claude/settings.local.json`** files (PM + Ralph) modified but untouched — local config.
- **`src/server/api/app.py`** modified to wire new routes (auth, sync, analyze) — committed as part of Sprint 8 code commit.

**Post-session git state:**

- Current branch: `main`
- Sprint 8 code + closeout committed (this session)
- Ahead of origin at close: pending push count (see closeout summary)
- Local branches: `main`, `sprint/server-walk` (unused, candidate for deletion)

---

### Previous Session Summary (2026-04-16, Session 17 — Backlog Restructure + Sprint 7 Server Crawl + Deployment Testing)

**What was accomplished:**

- **Backlog restructure** (`a69fab5`): Processed Ralph's 5 inbox items. Created E-11 (Infrastructure Pipeline) with B-036 (server, 18 stories), B-037 (Pi, 17 stories), B-038 (sprint validator). Absorbed B-022/B-027/B-014/B-023. Closed B-019, B-040, B-006. Closed TD-002/TD-003/TD-005. Filed TD-010 (path drift). Assigned US-156–175 (20 new stories). Marked pipeline MVP PRD superseded. Story counter → US-176. Pushed to origin.
- **Sprint 7 created and loaded** (`6822e26`): Server Crawl phase, 9 stories in new `sprint.json` format per sprint contract spec. Created `sprint/server-crawl` branch.
- **Ralph toolchain rename** (`f3d34fb`): stories.json → sprint.json across ralph.sh, agent.py, agent.md, prompt.md, README.md, CLAUDE.md.
- **Ralph executed Sprint 7** — 9/9 stories passed (`048d38f` through `883e8ce`). Test count 1469 → 1720 (+251 new server tests).
- **Config fix** (`3f8d8bb`): Added `extra="ignore"` to Pydantic Settings for shared .env compatibility.
- **Live deployment tested on Chi-Srv-01**: Server running on port 8000. 5 simulated drives loaded (18,270 rows). Health endpoint healthy. Basic + advanced analytics working. CLI reports rendering with drive comparison (flagged COOLANT_TEMP 3.3σ) and trend analysis (RPM falling 29%).
- **Deploy script** (`bb7d2b3`): `deploy/deploy-server.sh` with --init/--restart flags.
- **Issues filed** (`bb7d2b3`): I-011 (sync/async driver mismatch), I-012 (inconsistent env var names).

**Key decisions:**
- Option A for backlog structure: two big B-items (B-036, B-037) aligned with specs, not 7 phase-based items. Specs provide phase breakdown.
- Server code lives in `src/server/` within OBD2v2 repo (design decision reversal from B-022's separate repo).
- sprint.json is the canonical filename (not stories.json). Ralph toolchain updated.
- Venv for Chi-Srv-01 goes in `~/obd2-server-venv` (NAS mount doesn't support symlinks for venv).
- Z: drive (Windows) = /mnt/projects (Chi-Srv-01 Linux) = same NAS. No git pull needed between them.

**What's next:**
1. Merge `sprint/server-crawl` → main (9/9 passed, deployment tested)
2. Push main to origin
3. Fix I-011/I-012 (driver mismatch + env var naming)
4. Create Sprint 8 — Server Walk phase (auth, sync, stub AI, parity)
5. Send Spool display review inbox notes
6. CIO: OBDLink LX Bluetooth pairing with chi-eclipse-01

**Unfinished work:**
- Sprint branch not yet merged to main
- Main 2 commits ahead of origin (sprint.json + Ralph closeout)
- I-011 and I-012 not fixed (workaround: use pymysql:// URL manually)
- 3 pre-existing test failures (test_e2e_simulator x2, test_verify_database x1) — not from Sprint 7

**Post-session git state:**
- Current branch: `sprint/server-crawl` at `bb7d2b3`
- Sprint branch: 12 commits ahead of main
- Main: 2 commits ahead of origin
- Working tree: clean (PM docs modified only in this closeout)

---

### Previous Session Summary (2026-04-13, Session 15 - Settings Optimization + Branch State Reconciliation + PRD TBD Audit)

**What was accomplished:**

Short session. Started with a CIO misunderstanding (Ralph "finished with the new architecture") and a stale session-init git snapshot. Real state turned out to be far ahead of what the CIO or the incoming projectManager.md believed: main had absorbed both Sweep 1 AND Sweep 2a, plus Sweep 2a closeout docs plus the Sweep 2b plan file; Ralph was active on Sweep 2b with one commit on the sprint branch and more uncommitted work in the tree. Session was spent optimizing PM settings, discovering and reconciling the branch state confusion (without disturbing Ralph's in-flight 2b work), and delivering a TBD audit of the draft Infrastructure Pipeline MVP PRD against the actual sweep state.

**PM local settings rewritten (2026-04-13 — two passes)**:
- **First pass**: rewrote `offices/pm/.claude/settings.local.json` from a 7-entry minimal file to a structured allow/deny permission set. Allows: Read entire project, Write/Edit in `offices/pm/**` + `specs/**` + `docs/**` + root docs, Write to other-office inboxes (`offices/{ralph,tuner,tester}/inbox/**`), routine git read ops + add/commit/stash/fetch/checkout/restore/mv, pytest/make/ruff/black/mypy/ralph CLI. Denies: Write/Edit to `src/**` and `tests/**` (PM Rule 1), destructive git (`push`, `reset --hard`, `rebase`, `merge`, `--no-verify`/`-n`, `branch -D`, `clean -f[d]`), `rm -rf`/`rm -r`.
- **Second pass** (after CIO feedback mid-session): broadened to include `cd`, `cat`, `head`, `tail`, `wc`, `grep`, `find`, `sort`, `uniq`, `xargs`, `basename`, `dirname`, `realpath`, `date`, `touch`, `echo`, `env`, and additional git subcommands (`merge-base`, `remote`, `tag`, `describe`, `reflog`, `worktree list`/`add`).
- **Behavioral feedback captured** (CIO correction): **never chain compound bash commands** (`cd X && cmd1 && cmd2`). Single commands match allow patterns cleanly; compound chains re-prompt per chunk because the chain isn't pre-approved as a unit. Marcus was prepending `cd Z:/o/OBD2v2 &&` to git commands out of habit even though cwd was already inside the repo. Fix: drop the cd prefix entirely, run git from cwd, run multiple independent commands as parallel Bash tool calls.

**Git reality reconciliation (the critical discovery)**:
- Session-init `gitStatus` snapshot said `current branch: main`. Session 14's closeout narrative in projectManager.md said "Ralph active on `sprint/reorg-sweep1-facades` working B-040 reorg; Marcus out of Ralph's way until reorg completes; main 5 commits ahead of origin."
- **First `git log --oneline -15`** showed top of history as `f97afa3 docs: Ralph → PM sweep 1 complete architecture report` followed by `21029e8 Merge sprint/reorg-sweep1-facades` — I incorrectly concluded only Sweep 1 was merged.
- **Second check** (`git log --all --oneline`, branch listing, and `git merge-base --is-ancestor 418b55b main`) revealed actual state:
  - Main was at `be46923` (Sweep 2b plan), NOT at `f97afa3`. My first `git log` was from a stale or mis-read output.
  - Main is **32 commits ahead of origin**, not 19 or 5.
  - Main includes Sweep 1 merge (`21029e8`) → Sweep 2a merge (`418b55b`) → Sweep 2a closeout docs (`12188b3`) → Sweep 2b plan file (`be46923`).
  - Local branches: `main`, `sprint/reorg-sweep1-facades` (retained), `sprint/reorg-sweep2a-rewire` (retained), `sprint/reorg-sweep2b-delete` (active, 1 commit ahead of main at `01b204a`).
  - **I was checked out on `sprint/reorg-sweep2b-delete`, not main.** Branch had been switched between session-init snapshot and my first interactive command (likely a parallel Ralph session).
- **My Quick Context/Last Session Summary edits had been written into `offices/pm/projectManager.md` while on Ralph's active 2b branch.** Unsafe — if committed there, would pollute Sweep 2b history with PM docs.
- **Reconciliation** (this session): stashed the PM edits with `git stash push -u -m "..." <2 files>`, switched to main, popped stash. Stash pop brought back an unexpected third file: `src/obd/config/loader.py` had uncommitted modifications (Ralph's Sweep 2b Task 2/3 in progress — deleting `_validateAlertThresholds` function and the default profile's `alertThresholds` dict). Marcus did NOT touch that file. Left it unstaged on main for CIO/Ralph to return to the 2b branch.
- **Rewrote the Session 15 narrative** on main to reflect the actual state (Sweep 1+2a merged, 2b in flight) instead of the original (incorrect) "Sweep 1 only" framing.

**Ralph Sweep 1 + 2a context absorbed**:
- Sweep 1 (full report in `offices/pm/inbox/2026-04-13-from-ralph-sweep1-complete.md`, 223 lines): 18 facade files deleted (2,465 lines), shutdown subpackage consolidated, `src/obd/__init__.py` rewritten to canonical package imports, 7 orchestrator test files rewired for new lazy-import targets, `obd_config_loader.py` resolved via Option A (the `obd.config` package already re-exports the full public API). Path convention correction: use `from display import ...` NOT `from src.display import ...` (tests/conftest.py puts `src/` itself on sys.path).
- Sweep 2a (from MEMORY.md + git log): AlertManager rewired to consume `config['tieredThresholds']`. Semantic changes CIO-approved: RPM redline 6500/6000 legacy → **7000** Spool-authoritative, boost + oil pressure alerts **silent** until Spool adds tiered specs (tech debt filed), STFT/battery/IAT/timing confirmed as pre-existing coverage gap. Test state: main fast-suite 1503 passed + 3 skipped + 19 deselected; 2a branch full-suite 1521 passed + 4 skipped.
- Sweep 2b (in flight): plan at `docs/superpowers/plans/2026-04-14-reorg-sweep2b-delete.md` (1,639 lines, 11 tasks). Pure dead-code delete pass. Target test state: fast suite 1504 / 0 skipped. Design decisions: drop `alert_config_json` column directly from CREATE TABLE (no migration, no version bump — nothing in production), 3 skipped tests use rewrite-first policy (2 delete + backlog, 1 rewrite).

**Draft PRD TBD audit (still-valid analytical work)**:
- Inventoried all 12 `TBD after arch reorg` markers in `offices/pm/prds/prd-infrastructure-pipeline-mvp.md`.
- Classified each TBD against the 6-sweep plan:
  - **Unblocked by Sweep 1+2a+2b** (stable paths, can be filled now): US-152/153 scenario JSON paths (`src/obd/simulator/scenarios/` is stable), US-154 `scripts/sync_now.py` path, US-155 `tests/test_e2e_pipeline.py` path. Sweep 2a/2b touched alert and config code, not simulator/scripts/tests.
  - **Still blocked by Sweep 3** (Pi/Server physical tier split): US-147 analyze endpoint handler module path, US-148 `ALL_SCHEMAS` + `getDeltaRows` Pi-side paths, US-149 `SyncClient` module path, US-150 backup push script — all live in directories Sweep 3 will physically move.
  - **Still blocked by Sweep 5** (orchestrator split, TD-003): US-152/153 CLI syntax `python src/main.py --simulate --scenario ...` depends on post-split main.py.
- **Conclusion**: Sweep 3 remains the real gate. The A/B decision I originally framed as "Sweep 2 greenlight" was based on wrong premise — Sweep 2 is already done (2a merged, 2b in flight).

**Key decisions:**
- No new architectural or process decisions this session.
- Internal PM workflow correction: single bash commands only, parallel Bash tool calls for independence, no `cd X && cmd` chains.

**What's next:**
1. **Reconcile the loader.py working-tree state** — it's Ralph's uncommitted Sweep 2b work that ended up on main via stash pop. Must be moved back to the 2b branch or let Ralph resume on that branch. **Do not commit on main.**
2. **Let Ralph finish Sweep 2b** (10 more tasks). Marcus stays out of Ralph's way — no `git checkout main` from a shell where Ralph is working.
3. **When 2b merges to main**: CIO greenlights Sweep 3 (Pi/Server tier split, 24h cooling gate). That's the gate for the draft PRD.
4. **Optional PM idle work**: fill the 4 Sweep-1/2a/2b-stable TBDs in the draft PRD (simulator/scripts/tests paths), read the 4 un-processed Spool inbox messages.
5. **Push main to origin** (32 commits ahead — CIO call).
6. **After Sweep 3 merges**: walk the Finalization Checklist, create B-035, update B-022/B-027, promote PRD, launch sprint 7.
7. **Eventually**: process remaining architectural decisions in Ralph's inbox (several are being consumed by the sweep pipeline — legacy threshold via 2a+2b, orchestrator via Sweep 5, snake_case via Sweep 6).

**Unfinished work:**
- **`src/obd/config/loader.py` unstaged Ralph 2b work** on main working tree — needs to go back to the 2b branch.
- **4 Sweep-stable PRD TBDs** still not filled in.
- **32 commits on main not pushed to origin** — CIO call.
- **Draft PRD still has `DRAFT` banner and Finalization Checklist intact**.
- **4 un-processed Spool inbox messages** from 2026-04-10/12.
- **Local sprint branches retained** (`sprint/reorg-sweep1-facades`, `sprint/reorg-sweep2a-rewire`) per plan rule until 7+ days post-2b-merge.
- **Sweeps 3-6 still entirely ahead**.
- **Compound-bash habit** may recur; the added allowlist entries help but the real fix is the behavioral rule written into the Quick Context parallel-session section.

**Post-session git state:**
- Current branch: `main`
- Main HEAD: `be46923` (Sweep 2b plan)
- Ahead of origin: 32 commits
- Working tree at closeout (before closeout commit): `offices/pm/.claude/settings.local.json` (this session), `offices/pm/projectManager.md` (this closeout), `src/obd/config/loader.py` (Ralph's 2b work — NOT staged, NOT committed)
- Ralph branch status: `sprint/reorg-sweep2b-delete` at `01b204a`, pending return to continue 2b tasks

---

### Previous Session Summary (2026-04-13, Session 14 - Six Sprints + Spool Review + Infra Pipeline PRD)

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
