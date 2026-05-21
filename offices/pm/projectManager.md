# Project Manager Knowledge Base

## PM Identity

**Name**: Marcus
**Role**: Project Manager for the Eclipse OBD-II Performance Monitoring System
**Reports To**: CIO (project owner)
**Scope**: PURE project management / orchestration -- versioning, merges + releases, sprint + team-session cadence, team glue, PRD creation, user story grooming, acceptance criteria. Marcus is **NOT** architect / QA-Tester / developer / SME, and never writes code. All architectural calls route to **Atlas** (Senior Solutions Architect, `offices/architect/`); Atlas owns architecture decisions + the design gate; CIO ratifies. (CIO directive 2026-05-18, relayed via Atlas; see PM Rule 10 + `offices/architect/knowledge/atlas-charter-and-authority.md`.)

## Purpose

This document serves as long-term memory for AI-assisted project management of the Eclipse OBD-II Performance Monitoring System. It captures session context, decisions, risks, and stakeholder information.

**Last Updated**: 2026-05-21 (Session 40 cont. — Sprint 40 / V0.27.16 DEPLOYED to Pi + server, AWAITING VALIDATION. 5 stories shipped (US-344 F-7 + US-345 F-8 + US-346 §10.6 amendment + US-348 drive_summary writer + US-349 drive_statistics writer). US-347 in-car drill REMOVED from stories[] mid-deploy per CIO directive: human IRL tasks NEVER go in stories[] — they live in validation.bigDefinitionOfDone and outcomes drive next sprint scope (lesson booked as feedback-pm-sprint-scope-no-human-irl-tasks). PM acted as integrator twice (path b) for Ralph's closeout commits after re-launched iterations exited HUMAN_INTERVENTION_REQUIRED without committing. CIO + Atlas IRL drill (F-7 reproduction + F-8 first-boot + US-348/349 fix-validation) pending; outcomes will shape Sprint 41 or /chain-validated trigger.)

Drain 22 double-P0 surfaced overnight by Spool. **V0.27 chain merge to main was BLOCKED pending V0.27.11.** I-036 (systemctl poweroff PolicyKit auth fail; latent since V0.24.1 — all drains 10-22 likely hard-crashed) + I-037 (V0.27.7 US-330 race-guard introduced canary false-positive regression; masked I-036 for 11 days) both filed P0. Tester notified re: harness smoke-test re-audit. V0.27.11 sprint shell drafted on `sprint/sprint37-bugfixes-V0.27.11` from V0.27.10 tip @ `c6e218a` with placeholders for US-341 polkit + US-342 canary + optional US-343 historical drain re-audit. **CIO directive 2026-05-15 morning: CIO + Ralph cook the V0.27.11 contract directly; PM is in tracking mode** -- the shell is a placeholder, not the final scope. Story counter bumped 341 -> 344. Drain 23 (post-V0.27.11) becomes the first credible IRL signal since 2026-05-12. Silver lining per Spool: battery_health_log analytics not corrupted -- close-out writes runtime_seconds + end_timestamp BEFORE shutdown invocation.

(Previous closeout 2026-05-14 Session 34: V0.27.10 DEPLOYED via `/sprint-deploy-pm`. PM grooming pass + 18 new V0.28+ B-items + MEMORY.md split (345 → 149 lines, 10 sub-files) + cleanup (Pi hostname `Chi-Eclips-Tuner` → `chi-eclipse-01`; `=1.1.0` stray deleted) + retroactive Sprint 36 sprint.json generated + V0.27.10 deployed to Pi + chi-srv-01. AWAITING IRL VALIDATION per sprint.json bigDefinitionOfDone (4 Ralph-specified gates + Drive 12 retest + Drain 18+) -- superseded by Drain 22 findings; V0.27.10's 4 stories may all still ship if Drive 12 re-validates them, but the chain-side bigDoD now also requires Drain 23 with the V0.27.11 fixes.)
**Current Phase**: **V0.27.16 DEPLOYED 2026-05-21 — AWAITING VALIDATION (real-hardware drill pending).** Pi (`Chi-Eclips-01` @ 10.27.27.28) + chi-srv-01 both on gitHash `5837239` / V0.27.16 / theme "F-7 + F-8 + V0.27.7 false-pass cluster redo". 5/5 Ralph-pickable stories shipped (US-344 F-7 ShutdownSequencer boot-grace latch fix + US-345 F-8 boot-progress-finalize.service `Conflicts=shutdown.target` + US-346 PM Rule 10 architecture.md §10.6 amendment + US-348 drive_summary server analytics writer fires + US-349 drive_statistics Pi-side writer fires). US-347 in-car drill REMOVED from stories[] mid-deploy per CIO directive (no human IRL tasks in sprint stories; live in `validation.bigDefinitionOfDone` only — lesson booked `offices/pm/knowledge/feedback-pm-sprint-scope-no-human-irl-tasks.md`). PM acted as integrator (path b) twice for Ralph closeout commits after re-launched iterations exited HUMAN_INTERVENTION_REQUIRED without committing. CIO + Atlas single in-car drill (F-7 Test 2 reproduction + F-8 first-boot CLEAN_COMPLETE verification + US-348/US-349 fix-validation drives) pending → Atlas verdict → Tester `/sprint-validated` → PM `/chain-validated` lands V0.27.1..V0.27.16 to main per Mike 2026-05-08/10 chain-end-merge rule. Atlas's smoothing config bump 5→10s rides this release (BL-018 touchpoint; Spool folds in post-chain-merge). Story counter: nextId = US-350. Story IDs retired: US-329, US-332, US-347. Per CIO chain-end-merge rule: main = 'fully functional working system'; the whole V0.27 chain merges together via /chain-validated once IRL-validated. V0.27.7 closes the server-side analytics-tier gaps Drive 11 (2026-05-12, first clean car-coupled drive post-B-063) exposed: US-326 drive_summary server analytics fields NULL fix (root cause: _ensureDriveSummary lookup-by-drive_id missed the Pi-sync row -> IntegrityError -> _writeDriveAnalytics transaction rolled back silently; fix = lookup by source_id, heal drive_id) + US-327 US-323 backfill wired into deploy-server.sh Step 4.6 idempotently (NOTE: the backfill itself fails in both deploy run-contexts -- Windows path-mangling + ssh-to-self host-key -- filed as I-031; the wiring is right, the host/path resolution is the gap; rows 11-15 stay NULL until I-031 or B-076) + US-328 drive_statistics Pi-side table migration Option C hybrid (thin CREATE TABLE IF NOT EXISTS, no writer; server-side Approach 1 path now produces rows post-US-326; full Approach 2 = B-075 V0.28+) + US-330 startup_log prior_boot_clean regression race-guard fix (journalctl --list-boots timing out under V0.27.6 US-322's orphan-cleanup.timer SD-card I/O; _readBootList retries 3x; unit-ordering alt = TD-051). US-329 (drive_counter server-side stale) DEFERRED to V0.28 server-schema-normalization epic B-076 per BL-016 -- CIO directive is 'drop the table'; zero server-side consumers. Two blockers this sprint, both RESOLVED: BL-015 (US-328 -> Option C), BL-016 (US-329 -> defer). Still open from V0.27.5: BL-014 (harness .claude/commands write gate). **Validation gate for the whole V0.27 chain**: Drive 12 (must produce the full server pipeline -- drive_summary analytics fields + Approach-1 drive_statistics rows) + Drain 18 (must produce a clean startup_log row with prior_boot_clean=1). When both green -> /chain-validated merges + cuts V0.28.0. V0.28+ queue: B-074 (MAP PID) + B-075 (drive_statistics Approach 2) + B-076 (server schema normalization epic) + B-077/078/079 (idle-chattiness + TZ bugs from the tester's 2026-05-12 db-review; PM lean: B-078 the urgent one) + I-031 (US-327 backfill deploy-context bug). Story counter: nextId = US-331.

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
3. **Atlas owns architecture decisions + the design gate; Marcus orchestrates spec-edits into sprints/TDs.** (CIO directive 2026-05-18, relayed via Atlas.) `specs/architecture.md` and load-bearing design calls are Atlas's lane -- Marcus routes architectural questions to Atlas, does not make architectural rulings, and lands Atlas's corrected-architecture decisions into sprint/TD work. Marcus still owns non-architectural specs hygiene (`standards.md` conventions, story/PRD quality) and the sprint-contract template. Atlas may raise a formal design-gate BLOCK; PM/CIO clears it explicitly. See PM Rule 10 + `offices/architect/knowledge/atlas-charter-and-authority.md`.
4. **No duplicate information.** Each fact lives in exactly one document. Documents reference each other.
5. **Clear acceptance criteria** on every backlog item and user story. Assume working code, but the CIO must be able to validate input/output matches expectations.
6. **Validation scripts** are part of user stories when the developer doesn't have direct database access. The story specifies the test program to write for verifying data in/out.
7. **No fabricated data.** All thresholds, ranges, test data, and acceptance criteria must be grounded in research, actual vehicle data, or explicit CIO input. Never invent placeholder values. Stories requiring real data that is not yet available must be marked `blocked` until data is provided. (CIO directive, Session 10)
8. **Sprint-branch workflow (CIO directive, Session 20; AMENDED 2026-05-08 per Mike directive).** Every sprint sent to Ralph runs on its own repo branch. Marcus (PM) creates the branch before loading `sprint.json` and handing off. At sprint close, Marcus runs `/sprint-deploy-pm` which commits all changed files on the sprint branch + pushes branch to `origin` + bumps `RELEASE_VERSION` on sprint branch + deploys Pi + server FROM SPRINT BRANCH. **DOES NOT MERGE TO MAIN.** Ralph never touches git (per `feedback_ralph_no_git_commands.md`).

9. **Validation-gated merge (Mike directive, 2026-05-08).** Main branch = "fully validated stable." Sprint branches stay deployed-but-pre-merge until real-hardware drill validates the sprint's `validation.bigDefinitionOfDone` clauses (Drive N IRL + Drain Test N IRL etc.). When Mike confirms drill green, Marcus runs `/sprint-validated` which: updates `regression_manifest.json` `lastValidated` for the sprint's `validatesFeatures`; merges sprint branch to main `--no-ff`; pushes main. If drill reveals regression: fix on sprint branch + bump V0.X.Y -> V0.X.(Y+1) (patch) + re-run `/sprint-deploy-pm` + retry validation. Loop until validated. Sprint N+1 grooming does NOT begin until Sprint N is merged to main. **Source of truth**: `regression_manifest.json` (14 user-facing features tracked); `pm_regression_status.py` reports STALE/NEVER status; sprint.json `validation` block (required Sprint 28+ per `sprint_lint.lintSprintValidation`).

10. **Design-gate DoD rule (CIO-approved 2026-05-18; PM administers, Atlas owns the gate).** Any sprint touching a load-bearing subsystem (power/shutdown, sync, the data-capture pipeline, `src/common/` contracts, tier boundaries, or any subsystem with a `specs/architecture.md` section) MUST update that subsystem's `specs/architecture.md` section **in the same sprint** -- it is part of Definition of Done, not a follow-up. Marcus bakes this clause into the sprint-contract/DoD template and the sprint's `validation.bigDefinitionOfDone`. A load-bearing change shipped without its spec update = Atlas BLOCK; PM/CIO clears explicitly. Rationale: `specs/architecture.md` went ~17 sprints stale on power/shutdown, producing a false EEPROM-wake guarantee (Atlas finding F-6) that became the documentation root of the V0.27 chain blocker.

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

> **LIVE STATE (Session 40, 2026-05-20 evening)**: **CHAIN RE-BLOCKED** — Atlas + CIO live in-car drill 2026-05-20 evening surfaced two findings that reverse the morning's chain-unblock-candidate verdict. **F-7 (CRITICAL, chain-blocking, BL-019)**: ShutdownSequencer state-machine bug in `src/pi/power/power_watch/__main__.py:301-322` — boot-grace-ignored loss events latch the polling loop blind (Test 2: engine crank within boot-grace + no alternator recovery before key-off -> sequencer silent 5.5 min while GPIO6 stays LOW and HAT drains). **F-8 (HIGH, parallel, I-039)**: `boot-progress-finalize.service` ExecStop never fires during shutdown (missing `Conflicts=shutdown.target`) — every clean shutdown classified `crashed_during_operation`. F-8 is the root cause of what was tracked as "Finding A / CLEAN_COMPLETE instrument honesty" since V0.27.13. **Sprint 40 / V0.27.16 spun**: branch `sprint/sprint40-bugfixes-V0.27.16` from sprint39 tip `62dae11`; 4 stories US-344..US-347 (T1 F-7 fix ~10 lines Python + T2 F-8 fix one-line systemd + T3 PM Rule 10 §10.6 amendment + T4 in-car re-validation drill); contract style = standard sprint.json per CIO directive (return to standard pipeline after 4 plan-driven sprints V0.27.12-15); Atlas pre-registers per-task gate criteria at Ralph dispatch (mirrors Sprint 39 cadence). Sprint 39 / V0.27.15 IRL ACCEPTANCE PASS verdict (Atlas 3-of-3 Cycle-A) **stands on externally-observable facts** but chain-merge candidacy is now **HELD pending V0.27.16 fix + re-validation**. Tester /sprint-validated for Sprint 39 is HELD. regression_manifest F-008/F-011/F-012 stay frozen. Pi + server remain on V0.27.15 / gitHash `88f055e`. Spool's Finding C (12 boots today classified crashed_during_operation, 19-min BATTERY_V trail, zero `power_log` battery transitions) is the F-8 evidence trigger; Spool's hypothesis (b) ruled out by CIO topology info (battery -> relay -> 10A fuse -> buck -> Pi; key-off = buck-off). Two lint failures from V0.27.15 (B-044 hardcoded `chi-srv-01` in `sync_with_server.py:82` + ralph promise-tag drift) still standing RED — Ralph fix owed alongside Sprint 40.

### Immediate Next Actions (Session 41 pickup — refreshed at Session 40 closeout)

> Authoritative state: MEMORY.md "Current state pointer" + "Last Session Summary (Session 40)" above + `[[project-v027-chain-status]]`. **V0.27.16 DEPLOYED 2026-05-21 — AWAITING VALIDATION.** Pi (`Chi-Eclips-01` @ 10.27.27.28) + chi-srv-01 both on gitHash `5837239`. Sprint 40 = 5/5 Ralph-pickable stories `passes:true`. US-347 retired mid-deploy (no human IRL tasks in stories[] ever; lives in `validation.bigDefinitionOfDone`). Real-hardware drill is the next event.

1. **Run `python offices/pm/scripts/pm_status.py`** at session start. Should show Sprint 40 = 5 stories all `passed`. `sprint_lint` clean (0 errors).
2. **PRIMARY: await CIO + Atlas in-car drill.** Single drive event bundles 5 IRL gates per `validation.bigDefinitionOfDone`: F-7 Test 2 reproduction (engine crank within boot-grace + 3-min wait + key-off fires sequencer) + F-7 Test 1 control (fresh boot, no in-grace transient, key-off still fires cleanly) + F-8 first-boot CLEAN_COMPLETE verification + US-348 server `drive_summary` real-drive read-back NON-NULL + US-349 Pi `drive_statistics` real-drive read-back ≥1 row per parameter. Atlas pre-registers full drill procedure when CIO is ready (mirrors Sprint 39 §9 cadence).
3. **Parallel: Atlas US-346 §10.6 amendment reviewer-lane sign-off** — Ralph's gate ask is in `offices/architect/inbox/2026-05-20-from-ralph-US-346-T3-architecture-md-amendment-gate-request.md`. Atlas signs independent of drill timing.
4. **On Atlas drill verdict + §10.6 gate-pass:** Tester runs `/sprint-validated` for Sprint 40. They pull DB read-back evidence for US-348 + US-349 (server `drive_summary` + Pi `drive_statistics`). Per Spool 2026-05-20 preliminary HOLD: F-008/F-011/F-012 manifest bump needs ≥1 real drain on rested ≥8h pack with sync running, not just fix-validation drives — Tester's call on whether bundle into this `/sprint-validated` or hold.
5. **On Tester `/sprint-validated` pass:** PM runs `/chain-validated` to merge V0.27.1..V0.27.16 to main per Mike 2026-05-08/10 chain-end-merge rule + tag. Update `/chain-validated` summary to reflect F-8 / I-039 CLOSED ("Finding A / CLEAN_COMPLETE instrument honesty" superseded by US-345 fix, not carry-forward).
6. **CIO smoothing bump `pi.powerWatch.smoothingSec` 5→10** ships with V0.27.16. Spool folds into BL-018 empirical-tuning path post-chain-merge.
7. **SS-T7 deploy-gate tripwire** (Atlas standing recommendation, still owed): weld `pytest -m "not slow"` exit-0 capture into `/sprint-deploy-pm` Phase-0 as permanent contract item. PM-lane skill edit at `offices/pm/.claude/commands/sprint-deploy-pm.md` + addendum to `docs/superpowers/specs/2026-04-14-sprint-contract-design.md`. Land before next chain (would catch the standing-RED lint failures pre-deploy).
8. **Two lint failures standing RED** (carry-forward through V0.27.15 + V0.27.16): (a) B-044 hardcoded `chi-srv-01` in `src/pi/power/power_watch/tasks/sync_with_server.py:82`; (b) `prompt.md`/`ralph.sh` promise-tag drift. File TD-054 to formalize defer if Ralph doesn't address pre-chain-merge.
9. **ralph.sh bash bug** `Sprint progress: N / M: integer expression expected` in iteration output — cosmetic, defer to V0.28.
10. **Atlas-owned doc-hygiene follow-ups (NOT chain-blocking; Atlas's later pass)**: `architecture.md:172`/`:417` residual `PowerDownOrchestrator` refs outside §10.6 scope; `deploy-pi.sh` stale comments at 28/644/654/657/1118 saying `=0`; runsheet §1 #34 INFO-log check unreachable. PM tracks; Atlas owns the edits.
11. **B-102 hostname rename** — Pi reports `Chi-Eclips-01` (confirmed in V0.27.16 deploy output). Close-out on chain merge.
12. **V0.28 grooming opens AFTER V0.27 chain merge.** Theme = B-076 server schema normalization epic. Queue: B-083 Mahalanobis + B-086..B-098 GEM family + B-099 Telegram + B-100 drive_summary writer broken + B-101 power_log/startup_log sync + B-102 hostname cleanup + Spool PRD drafts B-088 + B-092.
13. **Other agents' memory-boundary migrations** — Atlas + PM done. Ralph/Spool/Tester own their own; PM does not migrate.
14. **`.deploy-version` SHA "unknown" investigation** Atlas flagged Session 39: not yet dug into. Worth a one-line audit next sprint-close.

### Stale (Session 35 pickup — kept for reference)

Session 35 actually addressed: Drain 22 double-P0 triage, V0.27.11 sprint shell drafted, B-099 Telegram filed. See "Last Session Summary" above for full closeout. The original Session 35 pickup list below is preserved as audit trail:

1. **Generate Sprint 36 V0.27.10 sprint.json retroactively** — Ralph SHIPPED 4 stories US-338/339/340/340b @ `6184a7f` (285 tests, lint clean) but on the "interactive was a one-off" pattern (no sprint.json). CIO directed in Session 33 to revert to standard pipeline. Generate sprint.json from Ralph's inbox notes + Ralph's `2026-05-14-from-ralph-v028-backlog-research-findings.md` report; all 4 stories marked `passes:true`; include `validation.bigDefinitionOfDone` per Ralph's 4 IRL gates. Then `sprint_lint.py` clean. Then `/sprint-deploy-pm` works on Phase 0.
2. **`/sprint-deploy-pm`** — after item #1; deploys V0.27.10 to Pi + server from sprint branch (no merge).
3. **CIO IRL validation drills (the 4 Ralph-specified gates)** post-deploy:
   - **US-338**: 2-leg pharmacy pattern → drives 13+14 both materialize with >100 rows + correct `drive_id`
   - **US-339**: 6h+ bench soak → zero `disk I/O error` in journal; eclipse-obd PID fd count stays ~5-10 (not climbing)
   - **US-340**: 10-min drive → server `connection_log` + `sync_history` row counts during drive should be near-zero
   - **US-340b**: post-deploy bench soak → `connection_log` row volume during sustained adapter outage ~5-10 total (not 2000)
   - **PLUS Drive 12-retest** (the V0.27 chain bigDoD): server `drive_summary` analytics fields + Approach-1 `drive_statistics` rows produced
   - **PLUS Drain 18+** (the V0.27 chain bigDoD): clean `startup_log` with `prior_boot_clean=1` after V0.27.7 US-330 + V0.27.8 US-333/334 stress
4. **Outcome branch per CIO 2026-05-14 directive**:
   - **If all IRL gates green** → `/sprint-validated` Sprint 36 + `/chain-validated` whole V0.27 chain V0.27.1…V0.27.10 → main + cut **V0.28.0**
   - **If any IRL gate red** → file new I-### bug(s) + open **V0.27.11 bug-fix sprint** + loop until validated
5. **V0.28.0 theme = B-076 server schema normalization epic** (CIO-confirmed Session 34). PRD grooming when V0.27 chain validates. V0.28.0 candidates (filed in active backlog):
   - **B-076** (schema epic — owns DROP TABLE drive_counter + source_id→vehicle_id + ghost-row cleanup; rolls up tester's 16 N-/D-items via B-082)
   - **B-083 Mahalanobis baseline scoring** (Ralph HIGH-priority V0.28.0 recommendation; data-quality work in Spool analytics layer; rides alongside B-076)
   - **B-074** MAP PID 0x0B, **B-075** drive_statistics Approach 2, **B-077** connection_log idle chatter, **B-078** sync_history idle chatter, **B-080** Pi clock drift, **B-081** Spool ATRV engine-state proxy, **B-082** tester rollup (16 sub-items)
6. **18 new B-items filed Session 34** — all in `offices/pm/backlog/` as `Pending (V0.28+ candidate)`:
   - **B-083/B-084/B-085** (Ralph's 3 from his V0.28+ research note 2026-05-14)
   - **B-086..B-094** (Spool's 9 GEMs from gem-filter note 2026-05-14)
   - **B-095..B-098** (Spool's 4 S-additions from same note)
   - **`offices/pm/rejected-ideas.md`** seeded with REJECT-A..F audit trail
   - **Spool offered preliminary PRDs** for B-088 (GEM-3 knock-retard alert) + B-092 (GEM-7 system status tile) on PM go-ahead; accepted no-rush
7. **Run `python offices/pm/scripts/pm_status.py` at session start** for sprint state. **Currently shows STALE Sprint 35 contract** — will refresh once item #1 (Sprint 36 sprint.json) lands.
8. **Standing rule**: V0.27.X = bug-fixes-only (still in effect until `/chain-validated` cuts V0.28.0).
9. **Owed bookkeeping (NOT load-bearing, getting more overdue)**: condense MEMORY.md (now ~340 lines, cap 200 — closed-history → one-liners); condense the stale "Current State" historical bullets in this file; clean the stray `=1.1.0` junk file in repo root; resolve `Chi-Eclips-Tuner` hostname-rename-never-actually-applied drift (file as TD-053?).
10. **BL-014** (harness `.claude/commands/` write gate from US-318) — still open, P3, mostly moot. Resolve or close at CIO discretion.


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

### Last Session Summary (2026-05-20 / 2026-05-21, Session 40 — Sprint 40 / V0.27.16 DEPLOYED awaiting validation; full arc)

**What was accomplished (in roughly chronological order):**
- `/init-pm` Session 40 start (2026-05-20 evening); read Atlas's inbox note flagging F-7 (ShutdownSequencer boot-grace latch state-machine bug, CRITICAL chain-blocking) + F-8 (`boot-progress-finalize.service` ExecStop never fires, root cause of CLEAN_COMPLETE instrument honesty since V0.27.13).
- AskUserQuestion: contract style + branch timing → CIO ratified standard sprint.json + spin branch now.
- Spun `sprint/sprint40-bugfixes-V0.27.16` from sprint39 tip `62dae11`; pushed -u origin.
- Filed BL-019 (F-7 chain-blocker pointer) + I-039 (F-8 parallel issue pointer) — short pointer files; Atlas's findings docs are contract of record. Bumped story_counter 344 → 348 reserving US-344..US-347 for Atlas's T1..T4 task spine. Archived dead Sprint 37 contract to `sprint.archive.2026-05-21_025206Z.json`. Wrote initial 4-story sprint.json with all S sizes + bigDefinitionOfDone clauses. Sprint commit `5596df0` (12 files, +1247).
- Carry-forward commit `f56978b` for 18 Sprint 39 Atlas→Ralph gate-pass notes (orphaned from Session 39 deploy).
- BL-020 from Ralph (Rex): Sprint 40 T1+T2+T3 code-side complete; US-347 in-car drill outside Ralph's lane. Tester filed I-039 concurrently for V0.27.7 false-pass cluster (US-326+US-328 never fire IRL) — ID collision with my I-039; renumbered Tester's to I-040. Saved `offices/pm/knowledge/` collision-resolution path. CIO 3-question pack ratified: (a) Ralph re-launch for closeout, (b) add I-040 to Sprint 40 as US-348+US-349, (c) drill ASAP after deploy. Routing: Ralph closeout instructions + Tester scope-ratification + Atlas A2AL scope-expansion 4→6. PM orchestration commit `0d6bfab`.
- Ralph re-launched (CIO drove ralph.sh) but exited HUMAN_INTERVENTION_REQUIRED without committing — re-acked existing BL-020 without integrating PM's closeout-commit directive. AskUserQuestion → CIO shifted to path (b) PM-integrator. Integrator commit `dbf49c8` (9 files, +1020) covering Ralph's T1+T2+T3 src + tests + sprint.json status updates + Ralph's US-346 Atlas-gate ask. Scope expansion commit `5fb7cdc` added US-348 (drive_summary server writer) + US-349 (drive_statistics Pi-side writer) with Tester's IRL round-trip + DB read-back discipline + bumped story_counter 348 → 350.
- Ralph re-launched again, shipped US-348 + US-349 (Rex Sessions 182/183) with passes:true, filed BL-021 (Sprint 40 Ralph-pickable work COMPLETE; await PM `/sprint-deploy-pm`). Atlas filed aside note that CIO applied a `pi.powerWatch.smoothingSec` 5→10 tuning bump in `config.json` (BL-018 touchpoint, NOT PM Rule 10). Integrator commit `b26344e` (13 files, +1985) covered Ralph's US-348/US-349 src + tests + sprint.json updates + Atlas's aside note + config.json smoothing bump.
- `/sprint-deploy-pm` Phase 0 halted on US-347 (passes:false + status:pending). Atlas's "T4 = in-car drill" structurally belonged in `validation.bigDefinitionOfDone`, not stories[]. CIO ratified removing US-347 from stories[]; bigDefinitionOfDone already had the F-7 reproduction / F-8 first-boot / Test 1 control clauses. Saved lesson as `feedback-pm-sprint-scope-no-human-irl-tasks.md`. Sprint became 5 stories all passes:true. Phase 1-4 commits: `bump_passed_statuses` flipped 5 statuses pending→passed; archived sprint.archive.2026-05-21_160428Z.json; deploy commit `c04d36e` (20 files, +3029 catch-all per skill); RELEASE_VERSION commit `5837239` V0.27.15→V0.27.16.
- Server deploy succeeded immediately (`5837239` active, obd-server.service healthy). Pi deploy halted on SSH connect timeout (Pi off-network); CIO confirmed WiFi was disabled on Pi → enabled. Re-pinged + retried; Pi came up after ~35s; Pi deploy succeeded (`Chi-Eclips-01` hostname confirmed in deploy output, `POWER_OFF_ON_HALT=1 already set`, sequencer service active). Phase 7 verified both targets on V0.27.16 / gitHash `5837239`.
- Routing notes to Spool (markdown) + Tester (A2AL) about V0.27.16 deploy + drill state + post-drill lane responsibilities. Commit `e5f970a`.

**Key decisions:**
- **Returned to standard sprint.json pipeline** after 4 plan-driven sprints (V0.27.12-15). CIO directive at session start.
- **PM-integrator path b** extended to code commits (Sprint 39 precedent was non-code). Ralph's iteration logic re-acks existing blockers instead of committing pending work; PM acts as integrator to keep the chain moving.
- **Removed US-347 from stories[] mid-deploy** rather than override Phase 0 halt. The deeper structural fix: human IRL tasks live in `validation.bigDefinitionOfDone`, not stories[]. Lesson booked; future sprint contracts will be code-only.
- **Renumbered Tester's I-039 → I-040** to resolve concurrent-filing collision. Mine was committed first; Tester's substance unchanged.
- **Bundled Atlas's smoothing config bump** into integrator commit `b26344e` — config-only, not Rule-10, but ships with V0.27.16 anyway. Spool folds into BL-018 post-chain-merge.

**Key artifacts produced:**
- Branch tip: `e5f970a chore(pm): notify Spool + Tester of V0.27.16 deploy + drill state`
- 8 commits on `sprint/sprint40-bugfixes-V0.27.16` (5596df0, f56978b, 0d6bfab, dbf49c8, 5fb7cdc, b26344e, c04d36e, 5837239, e5f970a)
- Pi (`Chi-Eclips-01`) + server (chi-srv-01) both on V0.27.16 / `5837239`
- BL-019 (F-7) + BL-020 (Ralph handoff) + BL-021 (Ralph code-complete handoff)
- I-039 (F-8) + I-040 (V0.27.7 false-pass cluster, was I-039)
- Sprint 40 contract: 5 stories all passes:true; sprint_lint 0 errors
- `offices/pm/knowledge/feedback-pm-sprint-scope-no-human-irl-tasks.md`
- Archived: `sprint.archive.2026-05-21_025206Z.json` (Sprint 37 dead contract) + `sprint.archive.2026-05-21_160428Z.json` (Sprint 40 deploy archive)
- 11 outbound notes to Ralph / Tester / Atlas / Spool (BL-020 ack, Atlas A2AL × 3, Tester × 3, Ralph × 2, Spool × 1, Sprint 40 dispatch × 1)
- MEMORY.md Current State Pointer updated; projectManager.md Last Updated + Current Phase + this summary

**What's next:** see "Immediate Next Actions (Session 41 pickup)".

**Unfinished work:**
- **CIO + Atlas in-car drill** (the bigDefinitionOfDone IRL gates) — single drive event bundles F-7 reproduction + F-8 first-boot + US-348/US-349 fix-validation. Atlas pre-registers procedure when CIO is ready.
- **Atlas US-346 §10.6 amendment reviewer-lane sign-off** — Ralph's gate ask is in Atlas's inbox; independent of drill timing.
- **Tester `/sprint-validated`** queued post-Atlas-pass.
- **PM `/chain-validated`** queued post-Tester-pass; lands V0.27.1..V0.27.16 to main per Mike chain-end-merge rule.
- **Working tree drift left unstaged at closeout** (per Rule 8): `.deploy-version` (auto-managed), `docs/phase2-deploy-and-acceptance-runsheet.md` (Sprint 39 carry-forward), 5 per-agent `.claude/settings.local.json` (NEVER commit per skill).
- **Two lint failures from V0.27.15** still standing RED (B-044 hardcoded `chi-srv-01` in `sync_with_server.py:82` + ralph promise-tag drift `prompt.md`/`ralph.sh`) — carried forward; not chain-blocking.
- **ralph.sh "integer expression expected" bash bug** (`Sprint progress: 3 / 4: integer expression expected` in iteration output) — cosmetic, defer to V0.28.
- **`.deploy-version` SHA "unknown" quirk** Atlas flagged Session 39 — not yet investigated.
- **B-102 hostname rename** — Pi reports `Chi-Eclips-01` (confirmed in V0.27.16 deploy output); close-out on chain merge.

### Earlier Session 40 Summary (2026-05-20 evening — Atlas in-car drill reverses chain-unblock verdict; F-7 + F-8 filed; Sprint 40 / V0.27.16 spun)

**What was accomplished:**
- `/init-pm` Session 40 start; ran `pm_status.py` (still showing dead Sprint 37 contract from V0.27.12-15 plan-driven gap — expected drift). Read Atlas's inbox note at PM's lane: `offices/pm/inbox/2026-05-20-from-atlas-chain-merge-BLOCKED-F7-and-F8-findings.md`.
- **Verdict reversal absorbed**: Atlas's evening in-car drill with CIO produced **F-7 (CRITICAL, chain-blocking)** ShutdownSequencer boot-grace latch bug in `src/pi/power/power_watch/__main__.py:301-322` + **F-8 (HIGH, parallel)** `boot-progress-finalize.service` ExecStop missing `Conflicts=shutdown.target`. F-8 is the concrete RCA for what had been tracked as "Finding A / CLEAN_COMPLETE instrument honesty" since V0.27.13. Spool's Finding C (12 boots today classified `crashed_during_operation`) is the F-8 evidence trigger; Spool's hypothesis (b) ruled out by CIO topology info.
- Asked CIO: contract style + branch timing (AskUserQuestion). CIO ratified: standard sprint.json (return to standard pipeline after 4 plan-driven sprints) + spin branch now from V0.27.15 tip.
- Created sprint branch `sprint/sprint40-bugfixes-V0.27.16` from current sprint39 tip `62dae11`, pushed `-u origin`.
- Filed **BL-019** (F-7 chain-blocking pointer) + **I-039** (F-8 parallel issue pointer). Short pointer files; technical detail stays in Atlas's findings docs per lane discipline.
- Bumped `story_counter.json` `nextId` 344 → 348 to reserve US-344..US-347 for T1..T4 task spine.
- Archived dead Sprint 37 contract to `offices/ralph/archive/sprint.archive.2026-05-21_025206Z.json` (V0.27.12-15 plan-driven sprints never archived it; cleared the drift before writing Sprint 40).
- Wrote `offices/ralph/sprint.json` Sprint 40 contract: 4 stories US-344..US-347 (T1 F-7 fix + T2 F-8 fix + T3 Rule 10 architecture.md §10.6 amendment + T4 in-car re-validation); all size S; deps wired T3↩T1+T2, T4↩all; `validation.bigDefinitionOfDone` per Atlas's Test 2 reproduction + Test 1 control + F-8 instrument verification. Atlas pre-registers per-task gate criteria at Ralph dispatch (mirrors Sprint 39 §9 cadence).
- Ran `sprint_lint`: 0 errors, 5 warnings (feedback-shape placeholders — fill at story-complete; US-345 title 1 char over cap). Contract validates clean for `/sprint-deploy-pm` Phase-0.
- Updated `projectManager.md` LIVE STATE + Immediate Next Actions for Session 41 pickup + this Session 40 summary.

**Key decisions:**
- **Returned to standard sprint.json pipeline** after 4 plan-driven sprints (V0.27.12-15). CIO directive. Restores `pm_status` + `sprint_lint` discipline + `/sprint-deploy-pm` Phase-0 gate.
- **Filed BL-019 + I-039 as pointer files only**, not full RCA docs. Atlas's findings docs are the contract of record; PM pointer files cross-link. Honors lane discipline (PM does NOT duplicate Atlas's content).
- **Wrote sprint.json with sufficient detail to express the contract** without over-specifying per-task gates (Atlas's lane). Acceptance criteria mirror Atlas's inbox note proposal; Atlas amends at Ralph dispatch if needed.
- **Archived dead Sprint 37 contract** before overwriting (preserves audit trail; was missed during V0.27.12-15 plan-driven gap because neither `/sprint-deploy-pm` nor `/sprint-validated` fired for those releases).
- **Did NOT bump version yet** — V0.27.16 happens at `/sprint-deploy-pm` time when Ralph T1+T2 + Atlas gate-pass land.

**Key artifacts produced:**
- Branch `sprint/sprint40-bugfixes-V0.27.16` from `62dae11`, pushed.
- `offices/pm/blockers/BL-019.md` (F-7 chain-blocking pointer)
- `offices/pm/issues/I-039-boot-progress-finalize-execstop-never-fires.md` (F-8 parallel pointer)
- `offices/pm/story_counter.json` bumped 344 → 348
- `offices/ralph/sprint.json` Sprint 40 / V0.27.16 contract (4 stories, 0 sprint_lint errors)
- `offices/ralph/archive/sprint.archive.2026-05-21_025206Z.json` (dead Sprint 37 archived)
- `projectManager.md`: header `Last Updated`, LIVE STATE rewritten, Immediate Next Actions rewritten for Session 41, Session 40 summary added

**What's next:** see "Immediate Next Actions (Session 41 pickup)". Atlas pre-registers T1 gate criteria when Ralph picks up; sprint runs; deploy on T1+T2 pass; in-car drill on T4; Tester gate; chain merge.

**Unfinished work:**
- **Ralph dispatch note** to be sent at end of this session (`offices/ralph/inbox/2026-05-20-from-marcus-sprint40-v0271_6-dispatch.md`).
- **Tester ack** (chain re-blocked; hold `/sprint-validated` for Sprint 39) to be sent.
- **Atlas A2AL ack** of his inbox note + sprint-spun confirmation to be sent.
- **MEMORY.md Current State Pointer** update to reflect chain re-block.
- **Commit + push** PM-side Sprint 40 spin to `origin/sprint/sprint40-bugfixes-V0.27.16`.
- **SS-T7 deploy-gate tripwire weld** still owed before next `/sprint-deploy-pm` (would catch the 2 lint failures still standing RED from V0.27.15).
- **Two lint failures from V0.27.15** (B-044 hardcoded `chi-srv-01` + ralph promise-tag drift) — bundle into Sprint 40 dispatch or defer.

### Previous Session Summary (2026-05-20, Session 39 — Sprint 39 / V0.27.15 Shutdown Sequencer IRL ACCEPTANCE PASSED + memory-boundary migration + chain-unblock orchestration begins)

**What was accomplished:**
- `/init-pm` context load Session 39 start (2026-05-18 evening). Acted on the relayed CIO role-boundary directive (Marcus → PURE orchestration; architecture → Atlas): rewrote PM Identity scope + PM Rule 3 + added PM Rule 10 (design-gate DoD); landed Sprint-Contract spec addendum (Atlas reviewer lane + Sprint-Level DoD addendum + mod-history). Atlas acked via A2AL. MEMORY.md Cross-Agent Rules updated.
- Created sprint branch `sprint/sprint39-bugfixes-V0.27.15` from chain tip `48e3538`, pushed (upstream set). Committed Atlas office + sequencer design + plan + Atlas inbox notes + my A2AL ack as `48e3538` (12 files, +1585).
- Atlas/Ralph ran the entire sequencer sprint in parallel sessions while PM did bookkeeping; came back to discover 24 sequencer commits + 14 Atlas gate-pass notes already landed (Sprint 39 code-complete; Atlas Rule-10 sign-off at T9). Honest stale-state correction made — pivoted to deploy.
- Refused `/sprint-deploy-pm` once based on the (then-current) hazard-documented-as-forbidden state; CIO corrected with the actual state + "just deploy" directive. Lesson booked: parallel-session-branch-gotcha + verify-diagnostic-premises apply to PM too.
- Pushed `48e3538..d529a57` to origin, ran `deploy-pi.sh` + `deploy-server.sh` — both targets on gitHash `d529a57`. Corrected EEPROM step (plan T8) confirmed `POWER_OFF_ON_HALT=1 already set` — deploy hazard genuinely lifted.
- Ran Atlas's tripwire (`pytest -m "not slow"`) pre-deploy and caught 2 lint failures (B-044 hardcoded `chi-srv-01` in new sequencer code + ralph promise-tag drift). CIO chose deploy-anyway override; both failures stand for Ralph fix.
- ~20s post-deploy the Pi went offline — turned out to be the sequencer firing (CIO/Atlas drill cycle, not a regression) → **Finding B EMPIRICALLY CLEARED in production for the first time** (Pi auto-recovered at +2.5 min via X1209 HAT + EEPROM=1 power-cycle). Atlas later confirmed **3-of-3 clean Cycle-A drills**; Sprint 39 IRL ACCEPTANCE PASSED; architecture deterministic.
- Bumped `RELEASE_VERSION` V0.27.14 → V0.27.15 (commit `88f055e`, theme "Shutdown Sequencer: GPIO6 SSOT + EEPROM=1 lock"), pushed, re-deployed both targets — label V0.27.15 now reflected in `.deploy-version`.
- Ticket relinks (no double-track): I-038 → SUPERSEDED by sequencer (T2/T5/T8 closes root cause); the dangerous Session-38 "unmask eclipse-powerwatch" re-deploy gate REMOVED from I-038 and projectManager.md and replaced with DEPLOY HAZARD note. TD-053 → RELINKED to plan T7. F-1..F-6 → closed by T9+T8. BL-018 → UNCHANGED, config-only.
- Hostname clarification recorded: Pi @ 10.27.27.28 = current `Chi-Eclips-Tuner`; future rename → `chi-eclipse-01` pending (B-102). Fixed MEMORY.md Key Infrastructure line that contradicted `reference_ssh_access`.
- **CIO memory-boundary directive 2026-05-20 landed**: `~/.claude/projects/.../memory/` = cross-agent shared ONLY; PM/agent-personal knowledge in `offices/<agent>/knowledge/`. Migrated 27 PM-detail files (16 `feedback_pm_*` + 11 PM-tracking `project_*`) from `~/.claude/` to `offices/pm/knowledge/`. MEMORY.md Shared Memory Index PM subsection collapsed to one-line pointer; User & project trimmed of migrated entries; Standing CIO directives gained the boundary rule.

**Key decisions:**
- **Refused `/sprint-deploy-pm` once on stale state.** Right discipline (don't deploy a documented-as-forbidden state), wrong premise (Sprint 39 was actually code-complete; the parallel session shipped while I was bookkeeping). CIO corrected; lesson is real and books `feedback-parallel-session-branch-gotcha` precedent for PM lane.
- **Removed the dangerous "unmask eclipse-powerwatch" instruction** from projectManager.md + I-038 BEFORE the sequencer deploy — exactly the Rule-10 / F-6 failure class one layer up (stale instruction in PM's own governing doc).
- **Did NOT file I-039** for the post-deploy poweroff: Atlas's 3-of-3 cycle pass + deterministic-architecture sign-off reframes the event as a drill cycle, not a regression.
- **Migrated PM files conservatively** — 27 obvious PM-detail; left borderline cross-agent feedback (Ralph dev lessons, Spool/Tester rules) in shared memory since other agents consume them. Other agents own their own migrations.
- **Did NOT run /sprint-validated** — Tester owns that gate per Atlas's IRL-PASS handoff.
- **Bumped V0.27.14 → V0.27.15 label** at CIO request (cosmetic; the gitHash field carried the runtime truth).

**Key artifacts produced:**
- Commits on `sprint/sprint39-bugfixes-V0.27.15`: `48e3538` (charter + Atlas office + sequencer artifacts), `88f055e` (V0.27.15 release bump). Ralph's 24 sequencer commits in between (`3d752c1`..`d529a57`).
- MEMORY.md: Current State pointer rewritten for IRL PASS, PM subsection collapsed, User & project trimmed, Standing CIO directive (memory-boundary) added, Pi hostname line corrected.
- projectManager.md: PM Identity scope + Rule 3 + new Rule 10 + LIVE STATE + Immediate Next Actions rewritten earlier in session; this Session 39 summary added now; Session-38 narrative preserved below as Previous.
- I-038 + TD-053: SUPERSEDED/RELINKED with sequencer plan cross-references.
- `docs/superpowers/specs/2026-04-14-sprint-contract-design.md`: Sprint-Level DoD Addendum + Atlas reviewer lane.
- 3 A2AL acks to Atlas (role-boundary+F6 / sequencer-sprinted+relinks / IRL-pass+chain-unblock-orchestration).
- Pi/server `.deploy-version`: V0.27.15 with sequencer theme on both targets.
- 27 PM files migrated to `offices/pm/knowledge/` (new dir).

**Session 39 closeout continuation (post-/exit, same-day):**
- Authored `/optimize-office-pm` slash command from CIO-provided portable template (`offices/pm/.claude/commands/optimize-office-pm.md`, commit `b8cdb65`). Adapted for PM's 2-file boot reality (init-pm + projectManager.md, no separate CLAUDE.md); baseline file routed to `offices/pm/knowledge/` not MEMORY.md per memory-boundary rule; operator-triggered Phase-0 dry-run-vs-live gate.
- Ran `/optimize-office-pm` first-ever pass (live, commit `d809651`): **projectManager.md 2513 → 452 lines**. Archived 35 older session summaries (Sessions 1–37, chronological oldest→newest) + 5 stale "Previous State" Quick Context snapshots + "Old Sprint 14 grooming" section to new append-only `offices/pm/knowledge/projectManager-session-history.md` (2088 lines). Trimmed bloated Last Updated header. Fixed 2 broken `[[atlas-architect]]` wikilinks (Atlas migrated his memory; PM repointed to path).
- New `feedback_pm_stay_in_your_lane.md` saved to `offices/pm/knowledge/` (this closeout): CIO directive 2026-05-20 — PM reads only PM-domain files + PM inbox; other-office content (even incidentally visible via `git status` / terminal output) is off-limits to read, summarize, or surface. Trust is mutual + symmetric. MEMORY.md Standing CIO directives gained the same rule.
- Received Spool ack note (`2026-05-20-from-spool-ack-v0271x-state-and-bl018-sequencing.md`) closing the V0.27.x state-reconciliation loop. **One orchestration item for Tester:** Spool's preliminary read = HOLD F-008/F-011/F-012 manifest bump until at least one real drain on a rested ≥8h pack exercises the new sequencer end-to-end with sync running (3 Cycle-A bench passes are architectural validation, not empirical re-validation of the now-retired drain-ladder surface those features were originally validated against). Recorded in Immediate Next Actions item 2.

**What's next:** see "Immediate Next Actions (Session 40 pickup)".

**Unfinished work:**
- **Chain merge orchestration (PM lane, awaiting Tester):** (1) Tester runs `/sprint-validated` for Sprint 39, (2) Tester decides regression_manifest re-validation (F-008/F-011/F-012 obvious candidates), (3) PM runs `/chain-validated` to merge V0.27.1..V0.27.15 to main per Mike 2026-05-08/10 chain-end-merge rule.
- **SS-T7 deploy-gate tripwire**: Atlas's standing recommendation to weld `pytest -m "not slow"` exit-0 capture into `/sprint-deploy-pm` Phase-0 as a permanent contract item — not blocking chain merge but worth landing before next chain (PM-lane skill edit).
- **Two lint failures from V0.27.15 deploy** standing RED (B-044 `chi-srv-01` log string in `src/pi/power/power_watch/tasks/sync_with_server.py:82` + `prompt.md`/`ralph.sh` promise-tag drift `COMPLETE`/`PARTIAL_BLOCKED`): Ralph code fix or in-place exempt + TD if not done before next deploy.
- **Doc-hygiene quirks Atlas flagged (NOT chain-blocking; Atlas-owned later pass):** `architecture.md:172`/`:417` `PowerDownOrchestrator` refs; `deploy-pi.sh` stale comments at 28/644/654/657/1118 saying `=0`; runsheet §1 #34 INFO log check unreachable.
- **Finding A (`CLEAN_COMPLETE` instrument honesty):** distinct OPEN item; must NOT be assume-closed by chain merge.
- **Other agents' memory-boundary migrations** (Ralph/Spool/Tester) — each owns their own per Atlas's pattern; PM doesn't migrate other agents' files.
- **`.deploy-version` SHA "unknown" quirk** Atlas noted: investigate at sprint-close.

### Previous Session Summary (2026-05-18, Session 38 — V0.27.14 Phase-2 power-watch DEPLOYED → SELF-BRICKED IRL → CIO BIG FAIL verdict → Ralph hotfix pushed (not re-deployed))

**What was accomplished:**
- `/init-pm` context load; ran pm_status/sprint_lint (dead Sprint-37 contract's 1 error is the documented plan-driven drift — NOT mutated). Cross-checked the 2026-05-17 Spool→Ralph "arm never ran / boot_id unknown" notes → confirmed superseded by the 2026-05-18 clean-reboot validation (no live contradiction).
- CIO directed `/sprint-deploy-pm` so he could run a car power on/off test. Confirmed scope via AskUserQuestion: **Pi + server**; wake-enabler "already on Pi". Bumped V0.27.13→**V0.27.14** (theme/desc within caps). Commits: `17625d5` (deploy artifacts: docs contract-of-record + PM state + 2 Spool→Ralph notes + tuner log), `0125417` (RELEASE_VERSION), `8c5dc51` (.deploy-version reconcile V0.24.0-stale→V0.27.14, resolving the Session-37 cross-session hazard). Deployed Pi + chi-srv-01; both verified V0.27.14 @ `0125417`; `eclipse-powerwatch`/`eclipse-obd`/`boot-progress-arm` + `obd-server` active.
- Deploy log surfaced a **record correction**: `deploy-pi.sh` US-253 step DOES enforce EEPROM `POWER_OFF_ON_HALT=0` and **rewrote it 1→0 this run** — the earlier-this-session "deploy doesn't touch firmware" framing was wrong; corrected in all trackers.
- **SEV-1 during the same session**: CIO ran the IRL test → V0.27.14 **bricked the Pi** (eclipse-powerwatch self-poweroff ~10-15s after every boot, even on external power; 3× repeated; Pi unusable). **CIO verdict: Sprint 38 / Phase-2 = BIG FAIL** (bricking regression shipped to hardware). Ralph RCA'd + hotfixed (`84b5469` debounced sustained-confirmation gate + `bootGraceSec` + reversed uncertain-VCELL direction; `4edbdc1` trigger on X1209 **GPIO6 PLD ground-truth** instead of the VCELL heuristic; `3047673` RCA/recovery/GPIO6-open-Q handoff). Recovery: CIO masked `eclipse-powerwatch` (collector untouched); Phase-1 EEPROM wake NOT implicated.
- Closeout actions: caught + refused the generic "DataWarehouse ETL" `/close-out-pm` boilerplate (un-corrected Session-34 propagation artifact; literal execution would have archived+wiped the dead Sprint-37 contract + Ralph's progress.txt mid-chain), pivoted to the project-correct `closeout-pm` skill. Filed **I-038** (SEV-1 bricking) + **TD-053** (T8 guard stubbed `isOnBattery=True`, never exercised the real transient/boot-sag signal) + feedback memory. Corrected projectManager.md/MEMORY.md/chain-status (had falsely read "awaiting validation"). Ack'd Ralph; archived 2 processed inbox notes. Pushed PM-side + Ralph's hotfix stack to the sprint branch (NOT main, NOT re-deployed).

**Key decisions:**
- **Recorded the FAIL honestly and prominently** — the hotfix does not erase that a bricking regression shipped to hardware on first IRL test (Ralph's explicit ask; honest-reporting duty).
- **Did NOT re-deploy the hotfix in closeout.** Re-deploy is a gated `/sprint-deploy-pm` Phases 4–7 action requiring (a) Ralph's hotfix verification gate complete + (b) the GPIO6 open question resolved + (c) CIO direction. Not a closeout step.
- **Pushed Ralph's local-only hotfix stack to origin/sprint branch** — sprint branch only, never main; pushing ≠ deploying (Pi/server stay on the bricking `0125417` until a gated re-deploy). Keeps the parallel-session work off a single machine.
- **Refused the boilerplate `/close-out-pm`** rather than execute a destructive generic workflow — flagged the un-purged Session-34 propagation artifact again.
- Filed the incident as **I-038** (issue, per the I-036/I-037 SEV precedent) + **TD-053** (the test-validation-gap debt Ralph named) — two distinct artifacts.

**Key artifacts produced:**
- Commits on `sprint/sprint38-bugfixes-V0.27.12`: `17625d5`, `0125417`, `8c5dc51` (PM deploy), + Ralph's `84b5469`/`4edbdc1`/`3047673`/`99f554d` pushed at closeout, + this closeout's PM commit.
- `offices/pm/issues/I-038-phase2-powerwatch-bricking-regression.md`
- `offices/pm/tech_debt/TD-053-phase2-trigger-validated-against-stubbed-predicate.md`
- `offices/ralph/inbox/2026-05-18-from-marcus-ack-sprint38-fail-recorded.md`
- Feedback memory `feedback_spec_invariant_validated_against_real_signal.md` + MEMORY.md index line
- Corrected: projectManager.md (header/LIVE STATE/this summary/next-actions), MEMORY.md current pointer, `project_v027_chain_status.md` Session-38 block

**What's next:** see "Immediate Next Actions (Session 39 pickup)".

**Unfinished work:**
- Ralph hotfix-verification gate (full not-slow pi suite + runsheet "deploy-safe" claim) — status unknown at closeout; **GPIO6 open question** (commit `3047673`) must be resolved before re-deploy.
- **Re-deploy gate**: once hotfix verified deploy-safe + GPIO6 settled + CIO direction → `/sprint-deploy-pm` Phases 4–7 (V0.27.14→V0.27.15) + `systemctl unmask eclipse-powerwatch.service` + the corrected runsheet (must add a "boot N× on external power, Pi STAYS UP > bootGrace+confirmWindow (~3 min), no self-poweroff" precondition BEFORE on-battery cycles).
- Pi/server still run the bricking `0125417` with `eclipse-powerwatch` masked. Chain stays BLOCKED. BL-018 Spool tuning now also covers the new debounce/grace bounds. regression_manifest F-008/F-011/F-012 stay FROZEN. Drain 27 + Drive 12 retest + US-338/339/340/340b IRL still open. `offices/architect/` appeared untracked (new, non-PM — left as-is).

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
| 2026-02-02 | Marcus (PM) | Session 6: Chi-Srv-01 specs finalized — i7-5960X (8c/16t), 128GB DDR4, GT 730 (display only), 2TB RAID5 SSD at /mnt/raid5, NAS mount at /mnt/projects, Debian 13. IP: 10.27.27.10. Updated B-022 PRD with server specs, CPU-only Ollama inference (no usable GPU). Model recommendations: Llama 3.1 8B (fast) or 70B (quality). GitHub repo created: `OBD2-Server`. |
| 2026-02-03 | Marcus (PM) | Session 7: Chi-Srv-01 infrastructure COMPLETE. MariaDB: database `obd2db`, user `obd2`, subnet access `10.27.27.%`. Ollama: installed, systemd enabled, `llama3.1:8b` model pulled. Server ready for companion service development. |
| 2026-02-05 | Marcus (PM) | Session 8: OBDLink LX dongle specs captured (MAC `00:04:3E:85:0D:FB`, FW 5.6.19) — updated architecture.md and glossary.md. CIO provided PMO template from PMO_Template project. Full adoption approved: backlog.json (Epic>Feature>Story), global story counter (US-101+), tester agent, PMO layer, sprint retrospectives, rework tracking. 9-phase migration plan created. |
| 2026-02-05 | Marcus (PM) | Session 9: Ralph agent system upgraded from DataWarehouse template. Consolidated agent.py (5 commands), upgraded ralph.sh (6 stop conditions, status/help), upgraded prompt.md (agent coordination, sprint summary), created README.md. Fixed AGENT.md case sensitivity for Pi. Cleared stale agent assignments. Tester agent confirmed active (test cleanup). |
| 2026-02-05 | Marcus (PM) | Session 10: CIO knowledge capture (2 rounds — driving patterns, preferences, hardware plan). 4 parallel research tasks: polling frequency, stock PIDs, DSMTuners community, mobile apps. Created `specs/obd2-research.md` (13 sections, comprehensive OBD-II reference). Added PM Rule 7 (no fabricated data). 9 new key technical decisions. Expanded CIO profile with operational context. |
| 2026-02-05 | Marcus (PM) | Session 11: Specs housekeeping — 10 files cleaned up. Converted groundedKnowledge.txt and best practices.txt to markdown with project alignment notes. Reviewed/deleted 7 raw hardware txt dumps (data already in PRD, extracted new details: motherboard MSI MS-7885, CPU turbo 3.5GHz, RAM Corsair CMK64GX4M4A2666C16 quad-channel, kernel 6.12.63). Reviewed 3 CIO input files (Answers.txt, Answers2.txt, Eclipse Projects.xlsx) — confirmed 100% extraction, captured VIN `4A3AK54F8WE122916` and bolt-on mods. specs/ now has zero .txt files. |
| 2026-02-13 | Marcus (PM) | Session 12: PMO migration executed. Created `pm/backlog.json` (9 epics, 27 features, 128 stories, 9 tech debt, 10 issues) and `pm/story_counter.json` (global counter at US-101). Renamed `techDebt/` → `tech_debt/`. Archived 7 completed B-items and 3 completed PRDs to `pm/archive/`. Updated 11 files with new paths. 32 files changed, 701 insertions. |
| 2026-04-13 | Marcus (PM) | Session 14: Marathon session 2026-04-11 → 2026-04-13. **6 sprints shipped** (54 stories, 1,517 tests passing): Sprint 1 B-002/B-015/B-024/B-026, Sprint 2 B-028/B-032, Sprint 3 B-030, Sprint 4 hotfix US-139, Sprint 5 B-033, Sprint 6 hotfix US-145. **Epic E-10 Tuning Intelligence created** from Spool's 2026-04-10 tuning spec (5 items, 32 stories). **Spool review gate established**: 3 reviews delivered (original spec, corrections, code audit) catching 7 variances. **offices/ restructure finally committed** (108 files). **Draft PRD for Infrastructure Pipeline MVP** (sprints 7/8/9, 9 stories US-147–155) pending Ralph's B-040 reorg completion. **Architectural decisions brief** delivered to Ralph's inbox covering 5 open decisions. Main is 5 commits ahead of origin (not pushed — waiting for reorg to land). Ralph active on `sprint/reorg-sweep1-facades`. |
