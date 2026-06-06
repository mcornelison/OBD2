# Project Manager Knowledge Base

## PM Identity

**Name**: Marcus
**Role**: Project Manager for the Eclipse OBD-II Performance Monitoring System
**Reports To**: CIO (project owner)
**Scope**: PURE project management / orchestration -- versioning, merges + releases, sprint + team-session cadence, team glue, PRD creation, user story grooming, acceptance criteria. Marcus is **NOT** architect / QA-Tester / developer / SME, and never writes code. All architectural calls route to **Atlas** (Senior Solutions Architect, `offices/architect/`); Atlas owns architecture decisions + the design gate; CIO ratifies. (CIO directive 2026-05-18, relayed via Atlas; see PM Rule 10 + `offices/architect/knowledge/atlas-charter-and-authority.md`.)

## Purpose

This document serves as long-term memory for AI-assisted project management of the Eclipse OBD-II Performance Monitoring System. It captures session context, decisions, risks, and stakeholder information.

**Last Updated**: 2026-06-05 (Session 47 — **V0.28 CHAIN MERGED TO MAIN = new fully validated stable.** drive-27 single-attribution IRL drill PASS (Atlas A-9 closed) → `/sprint-validated` (Sprints 44+45) → `/chain-validated` (merge `26fd488`, tag `V0.28.2`, dev fast-forwarded to main = `48e5567`); F-005/F-007 HOLD released chain-wide; SPEED-PID cal resolved at factor 1.00 (units phantom); fast-follow **US-379** filed (test-only stale harness fixture from US-371 rename); PM `settings.local.json` optimized (full project access + dir-trust prompts killed); `/optimize-office-pm` trimmed projectManager.md 738→~420. Prior-session narratives: see Session Summaries below + `offices/pm/knowledge/projectManager-session-history.md`.)

Drain 22 double-P0 surfaced overnight by Spool. **V0.27 chain merge to main was BLOCKED pending V0.27.11.** I-036 (systemctl poweroff PolicyKit auth fail; latent since V0.24.1 — all drains 10-22 likely hard-crashed) + I-037 (V0.27.7 US-330 race-guard introduced canary false-positive regression; masked I-036 for 11 days) both filed P0. Tester notified re: harness smoke-test re-audit. V0.27.11 sprint shell drafted on `sprint/sprint37-bugfixes-V0.27.11` from V0.27.10 tip @ `c6e218a` with placeholders for US-341 polkit + US-342 canary + optional US-343 historical drain re-audit. **CIO directive 2026-05-15 morning: CIO + Ralph cook the V0.27.11 contract directly; PM is in tracking mode** -- the shell is a placeholder, not the final scope. Story counter bumped 341 -> 344. Drain 23 (post-V0.27.11) becomes the first credible IRL signal since 2026-05-12. Silver lining per Spool: battery_health_log analytics not corrupted -- close-out writes runtime_seconds + end_timestamp BEFORE shutdown invocation.

(Previous closeout 2026-05-14 Session 34: V0.27.10 DEPLOYED via `/sprint-deploy-pm`. PM grooming pass + 18 new V0.28+ B-items + MEMORY.md split (345 → 149 lines, 10 sub-files) + cleanup (Pi hostname `Chi-Eclips-Tuner` → `chi-eclipse-01`; `=1.1.0` stray deleted) + retroactive Sprint 36 sprint.json generated + V0.27.10 deployed to Pi + chi-srv-01. AWAITING IRL VALIDATION per sprint.json bigDefinitionOfDone (4 Ralph-specified gates + Drive 12 retest + Drain 18+) -- superseded by Drain 22 findings; V0.27.10's 4 stories may all still ship if Drive 12 re-validates them, but the chain-side bigDoD now also requires Drain 23 with the V0.27.11 fixes.)
**Current Phase**: **V0.28 CHAIN MERGED TO MAIN 2026-06-05 = new fully validated stable (tag `V0.28.2`, merge commit `26fd488`; dev fast-forwarded to match main).** The drive-27 single-attribution IRL drill PASSED (Atlas A-9 CLOSED: drive_id=27, data_quality=full, is_real=1, attribution_anomalies=0, 0 parallel-stream divergence) — the drive-side gate for accumulated Sprints 43+44+45. `/sprint-validated` stamped Sprints 44+45 on dev; `/chain-validated` merged dev→main, tagged V0.28.2, released F-005/F-007 HOLD chain-wide. SPEED-PID cal RESOLVED at factor 1.00 (the "2× drift" was a km/h-as-mph units phantom; 0.5 seed dormant/never applied — 1-line empirical-seed update is optional future work). Fast-follow **US-379** filed (test-only: stale harness fixture after US-371 drive_id→summary_id rename; product proven green by the drive-27 drill). 2 pre-existing lint failures (B-044 hardcoded `chi-srv-01` + ralph promise-tag drift) still ride as accepted non-blocking. **NEXT:** next-sprint grooming (US-367 ECU-backfill spine, Atlas design ruling = critical path) forks from dev; Iris DTC-viewer + F-092/F-097 + F-103 line groom-ready (Atlas CONDITIONAL PASS — F-103 first, then carousel→cards→DTC). Previous Current Phase preserved: **V0.28.2 / SPRINT 45 DEPLOYED 2026-06-01 — schema+data VERIFIED, AWAITING drive-27 IRL drill.** Both Pi (10.27.27.28) + chi-srv-01 on **V0.28.2 / `cb54311`** (origin/dev `52d4b08`). Sprint 45 = US-377 (`data_quality` VARCHAR(16)→(20) + v0012, fixes the V0.28.1-drill `DataError 1406`) + US-378 (A-13 ECU seed MD335287→MD326328 all code sites). **Chain-blocker CLEARED:** US-364 recompute GREEN on prod (drives 23+24 → `attribution_anomaly`, 25 → `full`, idempotent, persisted). **Pre-drill VERIFIED GREEN:** 12/12 migrations applied; schema parity (`ecu`/`vehicle_info`/`speed_pid_calibration`/`dtc_freeze_frame` match ORM §5); coherence zero-drift; correction factors MD346675→1.0 + MD326328→0.5; tripwire precise (only 23/24 anomaly of 19 drives, 17 clean=full). **F-005/F-007 HOLD eligible** but NOT bumped — rides `/sprint-validated`. **NEXT: drive-27 single-attribution IRL drill → `/sprint-validated` (43/44/45) → `/chain-validated` lands V0.28 to main.** Parallel prep team (Atlas/Spool/Argus/Iris) grooming next sprint (US-367 ECU-backfill spine, Atlas design ruling = critical path) per `offices/pm/prds/prd-next-draft.md`; forks from `dev`. Concurrency soft-protocol ratified (handbook §13 + CLAUDE.md core-bootup; broadcast to all agents); Ralph contract = commit-to-sprint-branch-not-push (ralph.sh allowlist tightened). Reusable tool `offices/pm/scripts/prod_db_query.sh` created. US-367 ECU backfill DEFERRED (bootstrap gap + ecu_id-model re-groom; grounded timestamps in `US-367.md`). Previous Current Phase preserved: **V0.28.1 / SPRINT 44 DEPLOYED 2026-06-01 — AWAITING IRL VALIDATION.** Ralph shipped 2/2 (US-376 + US-374; B-076 ECU-identity normalization first slice). PM re-verified `pytest tests/server -m "not slow"` = 1058 passed / 0 failed, ruff clean, sprint_lint 0 errors. Architecture.md §5 V0.28.1 subsection written (PM Rule 10); Atlas Rule 10 PASS PENDING (rides `/sprint-validated` per CIO 2026-06-01 deploy directive). First V0.28-chain hardware deploy (carries Sprint 43 V0.28.0 + 44): merged `sprint44 → dev`, RELEASE_VERSION `V0.27.19 → V0.28.1`, deployed Pi (10.27.27.28, online) + chi-srv-01. AWAITING 16-clause bigDoD IRL drill (ECU + speed_pid_calibration `SHOW CREATE TABLE`/FK/JOIN parity, v0011 idempotency) + carried US-364/US-367 (recompute 23/24/25 + ECU backfill) + drive-27 single-attribution + F-005/F-007 HOLD release; CIO offered engine-on test. On green → `/sprint-validated` → `/chain-validated` lands V0.28 to main. Previous Current Phase preserved: **V0.28.1 / SPRINT 44 FROZEN + RALPH-DISPATCHABLE 2026-06-01** on `sprint/sprint44-V0.28.1` (forked from `dev` `3329901`; main working tree checked out + clean). B-076 ECU-identity normalization first slice: US-376 (`ecu` identity table pair-keyed + `vehicle_info.ecu_id` FK + v0011) → US-374 (`speed_pid_calibration` re-key to `ecu_id` FK; rework-forward). sprint.json frozen `21971bd1`; Atlas Q1-Q5 + Rule 13 PASS; Spool Q5 pair-key/row-per-reflash. CIO drives `ralph.sh` (US-376 first per FK). Atlas per-task-gates both + holds US-376 §5 Rule 10. On dev-stories-land → first V0.28-chain hardware deploy + IRL drill (drive-27 single-attribution + recompute 23/24/25 + ECU backfill + F-005/F-007 HOLD release) validates accumulated 43+44. **Sprint 43 / V0.28.0**: shipped 12/15; integrated to `dev` `bd1618c` (NOT deployed, CIO call); US-370 deferred (code preserved) + US-364/367 IRL carried to V0.28.1. Previous Current Phase preserved: **V0.28.0 SPRINT 43 GROOMED + RALPH-DISPATCHABLE 2026-05-28** on sprint/sprint43-V0.28.0 @ `70c1b1f` (forked from dev=main=`525fc9d`). All gates closed: Q1-Q4 PRD open questions RESOLVED; Spool 3 deltas + Atlas server-side-only structural pin APPLIED; sprint.json frozen + hash-pinned + lint-clean; Atlas PM Rule 13 formal sign-off PASS; Argus CIO-proxy approved. CIO drives `ralph.sh N` from his shell to dispatch. PM session closed out on sprint branch (NOT merged; Ralph workflow per Rule 8). On Ralph code-complete: `/sprint-deploy-pm` per directive #1 dev/main workflow merges sprint → dev + deploys from dev. Previous Current Phase: **V0.27 CHAIN MERGED to main 2026-05-23 = new fully validated stable.** (Previous Current Phase preserved: V0.27.18 / Sprint 41 DEPLOYED 2026-05-22 — AWAITING ARGUS IRL DRILL VALIDATION.) Ralph's V0.27.18 hotfix (US-357) shipped clean: v0009 migration adds `drive_statistics.data_quality` column (closes I-041 CRITICAL), `deploy-server.sh` Step 4.9 marker-write gate (closes I-042), bonus US-355 harness integrity tests. 8/8 stories `passes:true`. Argus drives 6-clause `validation.bigDefinitionOfDone` IRL drill → on PASS: `/sprint-validated` Sprint 40 + 41 → PM `/chain-validated` lands V0.27.1..V0.27.18 to main. (Previous Current Phase note preserved: V0.27.17 / Sprint 41 DEPLOYED 2026-05-21 but BROKEN — V0.27.18 patch loop dispatched to Ralph (I-041 schema gap + I-042 deploy-marker bug). Targets healthy on V0.27.17; server compute path 0% functional until v0009 migration lands.)** Sprint 41 advances B-104 Step 1 (server-side analytics authority) as architectural fix; Pi-side `drive_statistics` table retiring entirely per CIO 2026-05-21 ratification. Sprint 41 = 7 stories US-350..US-356: US-350 server drive_summary compute from raw + US-351 server drive_statistics compute + retire Pi-side + US-352 backfill drives 12-20 + US-353 US-345 maxTrailBytes guard fix + US-354 deploy-pi.sh daemon-reload gap + US-355 I-040 structural close (drive simulator). Branch `sprint/sprint41-bugfixes-V0.27.17` from sprint40 tip 78c7c2d. sprint_lint 0 errors. Pi (`Chi-Eclips-01` @ 10.27.27.28) + chi-srv-01 stay on V0.27.16 / `5837239` until V0.27.17 deploys; Argus already worked around the deploy-hygiene gap (US-354 root) with bench `daemon-reload && reboot` for the V0.27.16 drill. (Previous V0.27.16 deploy context preserved below.) -- V0.27.16 / theme "F-7 + F-8 + V0.27.7 false-pass cluster redo". 5/5 Ralph-pickable stories shipped (US-344 F-7 ShutdownSequencer boot-grace latch fix + US-345 F-8 boot-progress-finalize.service `Conflicts=shutdown.target` + US-346 PM Rule 10 architecture.md §10.6 amendment + US-348 drive_summary server analytics writer fires + US-349 drive_statistics Pi-side writer fires). US-347 in-car drill REMOVED from stories[] mid-deploy per CIO directive (no human IRL tasks in sprint stories; live in `validation.bigDefinitionOfDone` only — lesson booked `offices/pm/knowledge/feedback-pm-sprint-scope-no-human-irl-tasks.md`). PM acted as integrator (path b) twice for Ralph closeout commits after re-launched iterations exited HUMAN_INTERVENTION_REQUIRED without committing. CIO + Atlas single in-car drill (F-7 Test 2 reproduction + F-8 first-boot CLEAN_COMPLETE verification + US-348/US-349 fix-validation drives) pending → Atlas verdict → Tester `/sprint-validated` → PM `/chain-validated` lands V0.27.1..V0.27.16 to main per Mike 2026-05-08/10 chain-end-merge rule. Atlas's smoothing config bump 5→10s rides this release (BL-018 touchpoint; Spool folds in post-chain-merge). Story counter: nextId = US-350. Story IDs retired: US-329, US-332, US-347. Per CIO chain-end-merge rule: main = 'fully functional working system'; the whole V0.27 chain merges together via /chain-validated once IRL-validated. V0.27.7 closes the server-side analytics-tier gaps Drive 11 (2026-05-12, first clean car-coupled drive post-B-063) exposed: US-326 drive_summary server analytics fields NULL fix (root cause: _ensureDriveSummary lookup-by-drive_id missed the Pi-sync row -> IntegrityError -> _writeDriveAnalytics transaction rolled back silently; fix = lookup by source_id, heal drive_id) + US-327 US-323 backfill wired into deploy-server.sh Step 4.6 idempotently (NOTE: the backfill itself fails in both deploy run-contexts -- Windows path-mangling + ssh-to-self host-key -- filed as I-031; the wiring is right, the host/path resolution is the gap; rows 11-15 stay NULL until I-031 or B-076) + US-328 drive_statistics Pi-side table migration Option C hybrid (thin CREATE TABLE IF NOT EXISTS, no writer; server-side Approach 1 path now produces rows post-US-326; full Approach 2 = B-075 V0.28+) + US-330 startup_log prior_boot_clean regression race-guard fix (journalctl --list-boots timing out under V0.27.6 US-322's orphan-cleanup.timer SD-card I/O; _readBootList retries 3x; unit-ordering alt = TD-051). US-329 (drive_counter server-side stale) DEFERRED to V0.28 server-schema-normalization epic B-076 per BL-016 -- CIO directive is 'drop the table'; zero server-side consumers. Two blockers this sprint, both RESOLVED: BL-015 (US-328 -> Option C), BL-016 (US-329 -> defer). Still open from V0.27.5: BL-014 (harness .claude/commands write gate). **Validation gate for the whole V0.27 chain**: Drive 12 (must produce the full server pipeline -- drive_summary analytics fields + Approach-1 drive_statistics rows) + Drain 18 (must produce a clean startup_log row with prior_boot_clean=1). When both green -> /chain-validated merges + cuts V0.28.0. V0.28+ queue: B-074 (MAP PID) + B-075 (drive_statistics Approach 2) + B-076 (server schema normalization epic) + B-077/078/079 (idle-chattiness + TZ bugs from the tester's 2026-05-12 db-review; PM lean: B-078 the urgent one) + I-031 (US-327 backfill deploy-context bug). Story counter: nextId = US-331.

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
5. **Story contract (backlog v2 -- 2026-05-27).** Every Story carries `goal` (Connextra or Gherkin form), `definitionOfDone`, `conditionalOutcomes`, and `validationCriteria` (testable action + expected outcome pairs) at backlog stage. These are *defined* in the backlog and become *crystal-clear* at the PRD stage. Acceptance criteria, validation scripts, and database checks live within these fields, not as separate artifacts. Story type is one of `normal`/`issue`/`blocker`/`tech-debt`/`research`/`housekeeping`/`security`. (CIO 2026-05-23 directive #2: validation-criteria-upfront; see `docs/superpowers/specs/2026-05-27-backlog-hierarchy-v2-design.md` §6.3.)
6. **Validation scripts** are part of user stories when the developer doesn't have direct database access. The story specifies the test program to write for verifying data in/out.
7. **No fabricated data.** All thresholds, ranges, test data, and acceptance criteria must be grounded in research, actual vehicle data, or explicit CIO input. Never invent placeholder values. Stories requiring real data that is not yet available must be marked `blocked` until data is provided. (CIO directive, Session 10)
8. **Sprint-branch workflow (CIO directive, Session 20; AMENDED 2026-05-08 per Mike directive; REWRITTEN 2026-05-28 per CIO directive #1 + spec 2026-05-28).** Every sprint runs on its own branch off **`dev`** (not `main`). Marcus (PM) creates the branch from `dev` HEAD before loading `sprint.json` and handing off to Ralph. At sprint close, Marcus runs `/sprint-deploy-pm` which merges the sprint branch into `dev` (`--no-ff`), pushes `dev` to origin, bumps `RELEASE_VERSION` on `dev`, and deploys Pi + server **from `dev`**. Sprint branches are short-lived -- they close on merge to `dev`. **Does NOT merge to `main`** -- that is `/chain-validated`'s job at chain end. Ralph never touches git (per `feedback_ralph_no_git_commands.md`).

9. **Validation-gated chain merge (Mike directive, 2026-05-08; REWRITTEN 2026-05-28 per CIO directive #1 + spec 2026-05-28).** `main` = "fully validated stable" -- untouched between chain merges. `dev` = integration branch carrying the active V0.X.Y chain (V0.X.0 minor sprint + V0.X.1..V0.X.N patch sprints stacked). Validation drills target `dev`. `/sprint-validated` stamps per-sprint `validation.validatedAt` + bumps `regression_manifest` for the sprint's `validatesFeatures` (no merge -- sprint already in dev). When the whole V0.X.Y chain is drill-green per IRL hardware tests AND CIO confirms, `/chain-validated` merges `dev` -> `main` (`--no-ff`), tags V0.X.N on `main`, fast-forwards `dev` to match `main`, pushes everything. If a drill reveals regression: new patch sprint forks from `dev` -> fix -> merge to `dev` via `/sprint-deploy-pm` with V0.X.(Y+1) patch bump -> retry validation. Loop until validated. **Source of truth**: `regression_manifest.json` (features list), `sprint.json validation` block (per-sprint criteria; required Sprint 28+ per `sprint_lint.lintSprintValidation`).

10. **Design-gate DoD rule (CIO-approved 2026-05-18; PM administers, Atlas owns the gate).** Any sprint touching a load-bearing subsystem (power/shutdown, sync, the data-capture pipeline, `src/common/` contracts, tier boundaries, or any subsystem with a `specs/architecture.md` section) MUST update that subsystem's `specs/architecture.md` section **in the same sprint** -- it is part of Definition of Done, not a follow-up. Marcus bakes this clause into the sprint-contract/DoD template and the sprint's `validation.bigDefinitionOfDone`. A load-bearing change shipped without its spec update = Atlas BLOCK; PM/CIO clears explicitly. Rationale: `specs/architecture.md` went ~17 sprints stale on power/shutdown, producing a false EEPROM-wake guarantee (Atlas finding F-6) that became the documentation root of the V0.27 chain blocker.

11. **Hierarchy discipline (backlog v2 -- 2026-05-27).** Every Story has a Feature parent; every Feature has an Epic parent. No orphans. Typed Stories (`type: issue|blocker|tech-debt|research|housekeeping|security`) without a natural Feature home file under standing **E-OPS Operational Hygiene** Epic. `sprint_lint --backlog` enforces. New bug/blocker/debt intake files **directly as a typed Story** -- the `offices/pm/issues/`, `offices/pm/blockers/`, `offices/pm/tech_debt/` folders are retired for new writes; their legacy records get triaged at PRD-grooming time. (See `docs/superpowers/specs/2026-05-27-backlog-hierarchy-v2-design.md` §8 + each retired folder's README.)

12. **Graduation (backlog v2 -- 2026-05-27).** Completed Epics / Features / Stories move from `offices/pm/backlog.json` + `offices/pm/backlog/` to `offices/pm/archive/completed-work-products/`. Tasks travel inline with their parent Story (Tasks are pre-sprint planned only -- frozen at sprint dispatch; not added mid-execution). Use `offices/pm/scripts/graduate_story.py <ID>` (PM-triggered, refuses if status ≠ `complete`).

13. **Validation-block sign-off (CIO directive 2026-05-23 #2 + spec 2026-05-28; Atlas owns the gate).** Every sprint's `validation.bigDefinitionOfDone` + per-story `validationCriteria` get Atlas reviewer-lane sign-off before Ralph dispatch. Atlas verifies: (a) each Story's validationCriteria is testable + complete; (b) bigDoD aggregates faithfully; (c) no holes in coverage relative to the Story's stated `goal`. Atlas may raise a formal validation-block BLOCK; PM/CIO clears it explicitly (same shape as Rule 10's design-gate BLOCK). The freeze hash gets cut by `prd_to_sprint.py` at PRD→sprint conversion; Atlas review happens between PRD draft and `prd_to_sprint.py` run.

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

> **LIVE STATE (Session 42, 2026-05-21 late evening — V0.27.17 DEPLOYED-BROKEN; V0.27.18 hotfix loop in flight)**: PM session opened with Ralph code-complete on all 7 Sprint 41 stories (`passes:true`). CIO ratified `/sprint-deploy-pm` without Atlas per-task gate sweep. Phases 0-6 ran with two operational snags: (a) Sprint 41's new `server-analytics-batch.service` install (Step 4.8) needed sudoers entries that didn't exist on chi-srv-01 — recovered via clean-replace of `/etc/sudoers.d/obd2-deploy` containing original 7 entries + 3 new for analytics-batch unit+timer+enable; (b) **Step 4.9 backfill 10/10 FAIL on US-352 with `Unknown column 'data_quality'`** — Ralph's US-351 added the column to `models.py:711` but **shipped no v0009 migration**. Despite the backfill failure deploy continued (best-effort Step 4.9 pattern) and Steps 5+6+7 marked complete; Pi `Chi-Eclips-01` @ V0.27.17 / `778522b` + chi-srv-01 @ V0.27.17 / `466790c` both report healthy. **But the new B-104 Step 1 compute path is 0% functional in production** — every drive sync hits the same error. This is the **THIRD shape of the same false-pass class** (V0.27.7 trigger-seam mock + V0.27.16 redo + V0.27.17 schema-vs-ORM mask via `Base.metadata.create_all`). US-355 deploy-context drive simulator did NOT catch I-041 because the harness uses the same `create_all` masking pattern (its own structural blind spot). Filed two issues: **I-041** (CRITICAL, schema gap, Ralph hotfix) + **I-042** (High, deploy-server.sh Step 4.9 writes idempotency marker on backfill failure — same outcome-not-observed wrapper class). **V0.27.18 patch loop dispatched to Ralph** via `offices/ralph/inbox/2026-05-21-from-marcus-V0.27.18-hotfix-dispatch-I-041-I-042.md` with three deliverables (v0009 migration + tests + I-042 marker-on-failure-check fix + bonus US-355 harness invariant refinement). CIO launches ralph.sh at his cadence. Argus + Atlas A2AL-notified to hold drill / aware of design lesson (Atlas's reviewer-lane sign-off on US-355 harness invariant change owed when it lands). Spool dropped V0.29+ anomaly engine spec into PM inbox mid-deploy (`2026-05-21-from-spool-post-drive-anomaly-engine-spec-for-grooming.md`; defer to post-chain-merge V0.29 grooming). Two lint failures from V0.27.15 still standing RED (B-044 hardcoded `chi-srv-01` + ralph promise-tag drift); not chain-blocking. **On Ralph V0.27.18 fix + PM Phase-5+ redeploy + Phase-7 reverify**: Argus drives sprint.json `validation.bigDefinitionOfDone` 6-clause drill → `/sprint-validated` Sprint 40 + Sprint 41 → PM `/chain-validated` lands V0.27.1..V0.27.18 to main per Mike chain-end-merge rule. (Previous Session 42 init-pm LIVE STATE preserved below for audit trail.) | **Session 42 init context**: **Sprint 41 / V0.27.17 DEPLOYED — AWAITING VALIDATION.** (Previous Session 41 LIVE STATE preserved below for audit trail.) | **Session 41 closeout context**: CHAIN RE-BLOCKED — THIRD CYCLE OF SAME BUG CLASS. V0.27.16 IRL drill (Argus + CIO, 2026-05-21 12:00-13:00 CDT, ~9-min real drive_id=20 with 3,808 realtime_data rows): US-344/F-7 + US-345/F-8 PASS in steady-state; **US-348 + US-349 FAIL** with identical NULL-fields / zero-rows pattern as V0.27.7's US-326+US-328. Argus's RCA: DriveDetector's drive-end signal does not fire when drive is terminated by sequencer poweroff; recorder wired for FUTURE drive-end events but never catches THIS drive's actual end. Argus's verdict: "I cannot recommend a third redo of the same form." CIO directive 2026-05-21: advance **B-104 Step 1** (server-side analytics authority — filed 30 min before drill report landed) as the architectural fix. **Sprint 41 / V0.27.17 spun**: branch `sprint/sprint41-bugfixes-V0.27.17` from sprint40 tip `78c7c2d`; 7 stories US-350..US-356 (US-350 server drive_summary compute from raw + US-351 server drive_statistics compute + retire Pi-side table entirely + US-352 backfill drives 12-20 in-sprint + US-353 US-345 maxTrailBytes guard fix + US-354 deploy-pi.sh daemon-reload+restart gap + US-355 I-040 structural close = deploy-context drive simulator harness). Pi-side `drive_statistics` table retires entirely per CIO ratification 2026-05-21 (server-side only). sprint_lint 0 errors. Atlas briefed at `offices/architect/inbox/2026-05-21-from-marcus-sprint41-architecture-brief.md` (architecture call + per-task gate pre-registration owed before Ralph dispatch). Argus ack'd via A2AL at `offices/tester/inbox/2026-05-21-from-marcus-ack-v0.27.16-drill-sprint41-spinning.md`. Tester /sprint-validated for Sprint 40 HELD; regression_manifest F-008/F-011/F-012 HELD; chain stays HELD per Mike chain-end-merge rule. **US-346 Atlas T3 §10.6 design-gate sign-off PENDING from Sprint 40** — carry-forward; blocks /sprint-validated for Sprint 40 independent of Sprint 41 code work. Argus also caught V0.27.16 deploy-hygiene gap pre-drill (deploy-pi.sh wrote files + bumped .deploy-version but didn't restart eclipse-powerwatch.service + didn't daemon-reload; Pi was running V0.27.15 code in memory; Argus worked around with bench `daemon-reload && reboot`); folded into Sprint 41 as US-354. US-345 first-post-deploy-reboot tripped `maxTrailBytes=65536` guard (trail accumulated unbounded while F-8 was broken); F-8 design SOUND post-fix; folded into Sprint 41 as US-353. Two lint failures from V0.27.15 (B-044 + ralph promise-tag drift) still standing RED — Ralph fix owed alongside Sprint 41.

### Immediate Next Actions (Session 48 pickup — refreshed at Session 47 closeout)

> Authoritative state: MEMORY.md "Current state pointer" + "Last Session Summary (Session 47)" below. **V0.28 chain MERGED to main = new fully validated stable** (tag `V0.28.2`, dev==main==`48e5567`; dev tip after closeout = latest PM commit). drive-27 IRL drill PASS (A-9 closed); F-005/F-007 HOLD released. No active sprint — next chain (V0.29 or V0.28.3 patch) forks from `dev`.

1. **Next-sprint grooming (forks from `dev`)** — lead item = **US-367 ECU-backfill spine**, gated on **Atlas's design ruling** (critical path; he owes it on-demand). Tracker: `offices/pm/prds/prd-next-draft.md`. Spool/Atlas also owe speed-aligner convergence (two aligners in `src/calibration/`).
2. **US-379 fast-follow** (test-only stale harness fixture from US-371 `drive_id→summary_id` rename; F-076, tech-debt, S) — dispatch to Ralph or bundle into the next patch sprint. Product already green; this only re-greens `tests/integration`.
3. **Iris DTC-viewer + dashboard line** — groom-ready; Atlas CONDITIONAL PASS (report `offices/architect/reports/2026-06-05-dtc-and-dashboard-design-gate.md`). Sequence: **F-103 (unbuilt, first) → carousel shell → cards → DTC Card 5 (Mode-04 clear)**. Build conditions: C-1 F-103 first; C-2 KOEO capture path independent of DriveDetector; C-3 Mode 02 unsupported on MD326328 → realtime_data fallback. Inbox: Iris F-092/F-097 + DTC prenotices; Spool DTC read/clear example code.
4. **SPEED-cal optional writer** — replace the dormant `0.5` seed on `ecu_id=2` with empirical `1.00` (`provenance='empirical-gps-correlation-Drive-27'`). No-op on computed values; folds with the US-367 ruling. Small Ralph story if tracked.
5. **MEMORY.md over 24.4KB limit** — needs a cross-agent history-trim pass (NOT `/optimize-office-pm`'s lane; that's PM-office only). Separate effort.
6. **Create `offices/pm/knowledge/feedback-pm-windows-encoding-ad-hoc-audits.md`** — hit the cp1252 `→` crash twice in Session 47 (`chain_validate_aggregate.py`, pm scripts). Canonical recipe: `PYTHONIOENCODING=utf-8` for CLI + `encoding='utf-8'` for `open()`; reference `offices/pm/scripts/_freeze.py`.
7. **2 pre-existing lint REDs** (B-044 hardcoded `chi-srv-01` in `sync_with_server.py:82` + ralph promise-tag drift in `prompt.md`/`ralph.sh`) — accepted non-blocking since V0.27; fix in whichever sprint touches those files (`type: tech-debt`, E-OPS).
8. **`/closeout-pm` header-trim amendment** (optimize-baseline recommendation): closeout should bump the `Last Updated` header to a 1-line pointer, not prepend a session paragraph — optimize keeps having to undo the 11KB bloat. PM-lane skill edit.
9. **Standing low-pri carry-forwards**: SS-T7 deploy-gate tripwire weld into `/sprint-deploy-pm` Phase-0; Pi deploy retry (10.27.27.28 reachability — Pi was unreachable across the V0.27/V0.28 deploys; verify it's on V0.28.2); `.deploy-version` SHA "unknown" audit; B-102 hostname rename (`Chi-Eclips-Tuner`→`chi-eclipse-01`, F-102); Spool V0.29+ post-drive anomaly engine spec (queued for V0.29 grooming).

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

### Last Session Summary (2026-06-05, Session 47 — V0.28 CHAIN MERGED TO MAIN; settings optimized; office trimmed)

**What was accomplished:**
- `/init-pm` Session 47; found live state had advanced past Session-46 closeout — the **drive-27 single-attribution IRL drill PASSED** (Atlas A-9 CLOSED) since closeout. Processed 4 new 2026-06-05 inbox notes (Atlas gate-PASS + Atlas closeout + Spool speed-cal + Iris/Spool DTC intake).
- **Ran the full V0.28 chain-merge sequence** (CIO confirmed green): `/sprint-validated` stamped Sprints 44 (archived sprint.json) + 45 (current) `validatedAt` = drive-27 drill + Session-46 pre-drill 22-clause schema verification; bumped `regression_manifest` F-005/F-007 (**HOLD released**). `chain_validate_aggregate --strict` → READY. `/chain-validated`: merge `26fd488`, tag `V0.28.2`, ff dev → **dev==main==`48e5567`**. All pushed.
- **Pre-merge full-suite gate** caught 3 RED: 2 known/accepted lint (B-044 + ralph promise-tag) + 1 NEW **test-only** (US-371 `drive_id→summary_id` rename left harness fixture stale in `test_deploy_context_drive_simulator::TestHarnessIntegrity`). Characterized as test-only (drive-27 IRL proved product green). CIO ratified merge-now+fast-follow → filed **US-379** (tech-debt, F-076); counter → US-380.
- **Optimized PM `settings.local.json`** per CIO directive: `additionalDirectories` (kills the recurring "allow reading from OBD2v2" dir-trust prompt) + full project Read/Edit/Write/Bash mirroring architect's sec-reviewed pattern; safety denies retained. (Effective next session.)
- **Committed all working-tree drift** to clean tree per CIO directive (sibling-office + data artifacts protected through the branch switch); discarded pm_status backlog.json encoding churn.
- **`/optimize-office-pm`** (2nd run): projectManager.md 738→441; `Last Updated` header 11,672→733 chars; archived 6 session summaries (S43/41/40×2/39/38) + stale S35 block; refreshed `optimize-baseline.md`.
- A2AL ack to Atlas (gate received + chain merged + US-379 FYI + his owes).

**Key decisions:**
- Stamped Sprint 44 (archived sprint.json) `validatedAt` directly since `/sprint-validated` only handles the current sprint.json — both sprints validated by the single accumulated drive-27 drill.
- Merge-now + file fast-follow for the test-only US-379 RED (product proven green by IRL drill; analogous to the 2 accepted lint REDs).
- Settings: lifted the offices-sibling write fence per explicit CIO "full access + minimize prompts" directive (overrides the conservative PM-lane default); kept safety denies (.ssh/.aws/git-hooks/global-config/force-push).

**Key artifacts produced:**
- `main`: merge `26fd488` + tag `V0.28.2` + PM-artifact `48e5567`; `dev` fast-forwarded; dev tip after optimize+closeout `b1ee619`+.
- `offices/pm/backlog/US-379.md`; `story_counter.json` nextId US-380.
- `regression_manifest.json` F-005/F-007 OK (by chain merge V0.28.2).
- `offices/pm/.claude/settings.local.json` (optimized); `optimize-baseline.md` (refreshed); `projectManager-session-history.md` (+6 summaries +1 stale block).
- A2AL ack `offices/architect/inbox/2026-06-05-from-marcus-ack-drive27-gate-chain-merged.md`.

**What's next:** see Immediate Next Actions (Session 48 pickup).

**Unfinished work:**
- Next-sprint grooming forks from `dev` — US-367 ECU-backfill spine gated on Atlas design ruling (critical path).
- US-379 fast-follow (test fixture) awaits Ralph dispatch.
- **MEMORY.md over 24.4KB limit** — needs separate history-trim (cross-agent shared; out of optimize scope).
- Iris DTC-viewer / F-092 / F-097 / F-103 line groom-ready (Atlas CONDITIONAL PASS: F-103 first → carousel → cards → DTC Card 5; needs KOEO capture + Mode-02-unsupported realtime fallback).
- 2 pre-existing lint REDs (B-044 + promise-tag) ride as accepted non-blocking.
- All commits pushed (dev `b1ee619`, main `48e5567`, tag V0.28.2).

### Previous Session Summary (2026-06-01, Session 46 — V0.28.1 + V0.28.2 BOTH DEPLOYED; chain-blocker found+fixed; pre-drill VERIFIED)

**What was accomplished:**
- **Deployed Sprint 44 / V0.28.1** to both Pi + chi-srv-01 (`feb3a92`): verified 1058 tests, wrote architecture.md §5 V0.28.1 subsection (Rule 10), Atlas Rule 10 PASS (`1463b6d`); v0010+v0011 applied to prod; validated ecu/speed_pid schema clauses against prod.
- **Found the chain-blocker**: running US-364 recompute on prod hit MariaDB `DataError 1406` — `data_quality` VARCHAR(16) can't hold 19-char `attribution_anomaly` (SQLite-vs-MariaDB false-pass class). No corruption (transactional rollback). Filed **US-377**.
- **Groomed V0.28.2 patch sprint** (forked dev `894b09a` per Rule 9): US-377 (widen→VARCHAR(20) + v0012 + width-invariant test).
- **US-367 ECU backfill investigated → DEFERRED**: bootstrap script never built (stamp_ecu_swap refuses first row) + needs re-groom for V0.28.1 ecu_id FK model; grounded timestamps captured in `US-367.md`.
- **A-13 ECU correction**: CIO corrected donor ECU P/N MD335287→**MD326328** (mfr E2T61683; Session-19 mis-ID, same box). Spool-signed, Atlas-dispatched, Atlas direct-UPDATE'd prod `ecu` id=2. Groomed **US-378** into V0.28.2; committed Spool's A-13 docs as integrator (`e742ce5`).
- **Ralph shipped V0.28.2 2/2** (US-377+US-378); PM verified 1081 tests + grep MD335287=none; **deployed both Pi+server** (`cb54311`); **US-364 recompute GREEN** (23/24→anomaly, 25→full, idempotent, persisted).
- **Pre-drill verification ALL GREEN** on prod (12/12 migrations; schema parity ecu/vehicle_info/speed_pid/dtc_freeze_frame; coherence zero-drift; factors MD346675→1.0 + MD326328→0.5; tripwire precise — only 23/24 of 19 drives). Baseline routed to Argus.
- **Concurrency soft-protocol ratified** (handbook §13 + CLAUDE.md core-bootup; broadcast to all 4 agents) after Atlas flagged shared-checkout races. **Ralph git contract** → commit-to-sprint-branch-not-push (`ralph.sh` allowlist `git:*`→subcommands).
- **Reusable tool `offices/pm/scripts/prod_db_query.sh`** created + used (per CIO directive); memory [[feedback-save-reusable-scripts]].
- **Parallel next-sprint prep operationalized**: 4 agent assignments (Atlas US-367 design=critical path; Spool GPS-cal data; Argus drill runsheets; Iris F-103) + tracker `offices/pm/prds/prd-next-draft.md`.

**Key decisions:**
- V0.28.1 Atlas Rule 10 PASS gates `/sprint-validated`, not deploy (CIO precedent) — deployed both targets in sync per CIO.
- US-377 = drill-revealed regression → its own V0.28.2 patch sprint (Rule 9).
- A-13 folded into V0.28.2 as US-378 (prod already fixed by Atlas; US-378 makes code coherent; same-row, factor 0.5 + FKs preserved; SPEED value unchanged — GPS method future).
- F-005/F-007 HOLD eligible but NOT bumped — rides `/sprint-validated` with the drive-27 drill.
- Concurrency = soft protocol (no worktrees) per CIO; Ralph commits-not-push.

**What's next:**
1. **CIO: drive-27 single-attribution IRL drill** on V0.28.2 (single drive_summary, full sync round-trip, tripwire no-false-positive, ECU lineage).
2. Argus captures drill evidence → PM `/sprint-validated` (43/44/45) → `/chain-validated` lands V0.28 to main.
3. Parallel: agents deliver prep (Atlas US-367 ruling = critical path) → PM grooms next sprint (US-367 spine) from `dev`.

**Unfinished work:**
- **drive-27 IRL drill** (needs the car; deferred — too late 2026-06-01 night).
- **US-367 ECU backfill** deferred (bootstrap + re-groom; prd-next-draft critical path).
- **F-005/F-007 HOLD** not yet released (rides `/sprint-validated`).
- All commits pushed (origin/dev `52d4b08`; sprint45 `9259710` merged+closed).

### Earlier Session Summary (2026-05-28 full session, Session 44 — V0.28.0 Sprint 43 GROOMED + RALPH-DISPATCHABLE on sprint/sprint43-V0.28.0)

**What was accomplished:**
- `/init-pm` Session 44 start; built directive #1 (dev/main branching workflow) via `superpowers:brainstorming` → spec `b277f8b` → plan `5513b6e` → inline execution (11 tasks: pm_status formatBranchTips + getBranchTip + wiring TDD `ba204c5` + `5039d0c` + `be99b6c`; 3 skill bodies retargeted `d379025`; PM Rules 8 + 9 rewrites `8e883f1`; `dev` branch bootstrapped from main; agenda mark `2f24c63`; MEMORY.md updates; final verify + push). Directive #1 LANDED on main 2026-05-28.
- Built directive #2 (validation-criteria-upfront contract) via brainstorming → spec `2bf40a6` → plan `397f792` → subagent-driven-development execution (8 tasks): backlog_schema empty-list enforcement (TDD) `c0a9d58` + symmetry fix `a088ed8`; prd_to_sprint freeze fields (TDD) `6f0e0b9`; sprint_lint freeze-drift + per-story empty-list (TDD) `3e49a8d` + shared `_freeze.py` module + DoD fallback fix `904bdeb`; PM Rule 13 added `6d38f29`; sprint contract addendum + PRD/Story templates `a28cb19`; agenda mark `d30d9d6`; MEMORY.md update; final push. Subagent two-stage review caught 2 Important findings (import direction + acceptance/DoD fallback bug). Directive #2 LANDED on main + dev 2026-05-28.
- V0.28.0 Sprint 43 PRD groomed via brainstorming → PRD at `offices/pm/prds/prd-V0.28.0.md` (`6c8e0d8` + Atlas-edits `832df25` + Spool-deltas `9123223` + re-freeze `cc0273a` + CIO Argus-proxy `5d3cc1b` + Atlas Rule 13 PASS `70c1b1f`). 15 atomic Stories US-359..US-373 filed at `offices/pm/backlog/US-{359..373}.md` via subagent (`6232a5f`). One Alembic v0010 migration for all schema. sprint.json frozen + hash-pinned `251bad9423a5b627...` (103 bigDoD clauses, up from 81 first-freeze).
- 4-way joint design on 4 PRD open questions: Q1 drive_summary.drive_id NULL (CIO+Atlas: backfill + CHECK invariant); Q2 SPEED-PID new-ECU seed (Spool: 0.5 + provenance column); Q3 US-361 Pi fix scope (Atlas: behavioral test, both modules); Q4 ecu_signature capture (Atlas+Spool: FK to vehicle_info.id + append-only identity columns + Spool notes column carve-out + writer-path discipline + temporal invariant). Atlas server-side-only structural pin added in Q4-caveat ACK (`_PRESERVE_ON_UPDATE` mechanics — Pi vehicle_info schema UNCHANGED in v0010).
- A2AL exchanges across 4 agents (Marcus, Atlas, Spool, CIO): 11 inbox notes routed; lane discipline + freeze discipline preserved across multiple ratifications. Sprint branch `sprint/sprint43-V0.28.0` forked from dev=main=`525fc9d`; tip `70c1b1f` pushed to origin.
- `sprint_lint.py` schemaVersion-aware patch (`525fc9d`): legacy V0.27-era per-story REQUIRED_FIELDS + scope/feedback checks skip when schemaVersion=2.0.0; structural sanity (id/title/size/passes) kept for both schemas. Resolved 140 → 0 errors on V0.28.0 sprint.json.

**Key decisions:**
- **Atomic Story granularity** chosen for V0.28.0 Sprint 1 (15 Stories vs thematic 5-7 or coarse 4). Each acceptance step is its own Story; small + independently mergeable.
- **One Alembic v0010 migration** covers all schema changes (Atlas's "one coherent schema pass" 2026-05-22 disposition). Vs per-Story or per-Feature migrations.
- **IRL validation gate = one drive + recompute** (Drive 27+ + server recompute drives 1-26 + F-108 lineage smoke + F-109 freeze-frame Pi smoke). Vs drain test + IRL or back-to-back drives.
- **F-103 splash deferred** to V0.28.1 or its own sprint (Tier 3; polish; Iris v1.1 spec gated).
- **CIO-approved Argus QA review on his behalf 2026-05-28** (executive proxy); post-hoc Argus concerns route as patch-sprint material per directive #1.
- **IRL clauses folded into per-Story validationCriteria** rather than appended as standalone sprint-level tier (Atlas ratifies as BETTER than spec's literal text). Validation-criteria-upfront spec amendment recommended for V0.28+.
- **PM-as-integrator pattern** preserved for peer-agent file placements (PM commits Atlas's PRD inline edits + Atlas's parallel inbox notes to Spool/UI/UX without reading the body per lane discipline).
- **Skipped Story.md application of Spool deltas until Atlas Q4-caveat ACK** — preserves freeze discipline (drift would invalidate bigDoDHash; applying as ONE atomic update + re-freeze post-ACK).

**Key artifacts produced:**
- Directive #1 spec `docs/superpowers/specs/2026-05-28-dev-main-branching-workflow-design.md` (`b277f8b`); plan `5513b6e`.
- Directive #2 spec `docs/superpowers/specs/2026-05-28-validation-criteria-upfront-contract-design.md` (`2bf40a6`); plan `397f792`.
- PM Rules 8 + 9 rewritten + new Rule 13 added in `offices/pm/projectManager.md`.
- 3 sprint workflow skills retargeted: `/sprint-deploy-pm`, `/sprint-validated`, `/chain-validated`.
- `pm_status.py` branch-tip display; `backlog_schema.py` non-empty enforcement; `prd_to_sprint.py` freeze fields; `sprint_lint.py` freeze-drift + per-story empty-list + schemaVersion-aware legacy-fields gate; new shared `offices/pm/scripts/_freeze.py` canonicalization module.
- `dev` branch bootstrapped from main; first V0.28.0 sprint forks from dev=main.
- PRD `offices/pm/prds/prd-V0.28.0.md` (Sprint 43 V0.28.0 contract; 21-row Refinements table; Q1-Q4 RESOLVED; CIO-Argus-proxy stamp; Atlas Rule 13 PASS stamp).
- 15 Story.md files `offices/pm/backlog/US-{359..373}.md`.
- backlog.json with 15 sprint-ready Stories; counter.story=373; story_counter.nextId=US-374.
- sprint.json at `offices/ralph/sprint.json` (15 stories, 103 bigDoD clauses, frozenAt 2026-05-28T19:26:59Z, hash `251bad9423a5b627...`).
- 11 inbox notes (Atlas verdict + Q4-ACK + Rule 13 PASS; Spool Q2/Q4 dispositions + Q4-caveat-Atlas + B-103 advisory to Iris; Marcus review requests + acks + Q2-to-Spool + Atlas-Q4-flag + Rule 13 reroute).

**What's next:** see "Immediate Next Actions (Session 45 pickup)" below.

**Unfinished work:**
- **CIO runs `ralph.sh N`** from his shell to dispatch Ralph on `sprint/sprint43-V0.28.0` (per standing rule: ralph.sh cannot be invoked from inside a Ralph session).
- **V0.28+ spec amendment recommended** by Atlas: validation-criteria-upfront spec §4.1 + PRD template should document "fold IRL clauses into per-Story" pattern as preferred, OR extend `prd_to_sprint.py` to parse sprint-level IRL markdown table. PM call; non-blocking.
- **2 pre-existing lint failures** carry forward (B-044 hardcoded `chi-srv-01` in `src/pi/power/power_watch/tasks/sync_with_server.py:82` + ralph promise-tag drift in `prompt.md`/`ralph.sh`) — V0.27 inheritance.
- **Windows-encoding gotcha** Atlas surfaced in Rule 13 PASS note: ad-hoc Python audits against sprint.json need `encoding='utf-8'`. Consider TD-style reminder in `offices/pm/knowledge/`.
- **B-103 splash** still gated per CIO 2026-05-21 directive; defer to V0.28.1+. Iris v1.1 spec ready for its own focused sprint scoping.
- **Working tree drift at closeout**: settings.local.json files (gitignored); ralph_agents.json (Ralph's domain); 2 untracked inbox notes Atlas+Spool placed in /architect/ + /uidevloper/ inboxes (PM-as-integrator persists in closeout commit).
- **Pi V0.27.19 deploy retry** still pending CIO Pi reconnect; orthogonal to V0.28 work.

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
