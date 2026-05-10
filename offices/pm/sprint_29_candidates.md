# Sprint 29 / V0.27.3 candidates -- bug-fix sprint queue

**Compiled**: 2026-05-10 by Marcus (PM)
**Source notes**:
- Spool 2026-05-10 evening (3-drive test + hardware blocker + 2 priority bumps): `offices/pm/inbox/archive/2026-05/2026-05-10-from-spool-three-drives-tonight-power-blocker-drive-counter-clarification.md`
- Spool 2026-05-09 (3 specs + housekeeping): `offices/pm/inbox/archive/2026-05/2026-05-09-from-spool-*.md`
- Sprint 28 deferred work (B-060, B-061): post-validation reservations
- CIO 2026-05-09 directive: bug-fix sprint chain V0.27.X until clean; "do it correct, no band-aids"

## CRITICAL BLOCKER (CIO hardware task; not a sprint story)

| ID | Title | Owner | Status |
|---|---|---|---|
| **B-063** | Pi 5 power: fuse-box buck converter (replaces stereo USB-C tap) | Mike | **CIO hardware task** |

**Sprint 28 V0.27.2 IRL validation is GATED on B-063 completion.** Spool 2026-05-10 evidence: ALL 4 drains tonight unclosed (drain_event_id 9/10/11/12) + Drive 9 captured at 36 rows/min vs Drive 8's 459 rows/min (12x brownout-throttling) + UPS battery never fully recharging due to chronic micro-drain from voltage flicker. Until Pi has stable 5V/5A from fuse-box buck converter, every IRL drill produces compromised data.

V0.27.3 IRL repro protocols (especially I-019) ALSO gated on B-063 -- running on flaky power confounds DriveDetector behavior with brownout-throttling.

## Story candidates (priority stack per Spool 2026-05-10)

### P1 (load-bearing for V0.27.3)

| ID | Title | Source | Size |
|---|---|---|---|
| **B-059** | drive_summary writer 12-field contract (Spool Spec 3) | Sprint 28 deferred + Spool housekeeping Item 2 P1 reclassification | M |
| **I-019** | DriveDetector misses short warm-restart trips (1,078 NULL-drive_id rows tonight) | Spool 2026-05-10 Bug A | M (size depends on root-cause investigation) |
| **I-018** | calibration.py stdlib types.py shadow + missing baselines table | Mike 2026-05-09 + Spool 2026-05-09 housekeeping Item 1 | S-M (two-part fix: rename + migration) |

### P2

| ID | Title | Source | Size |
|---|---|---|---|
| **B-062** | drain_event close-event flush at TRIGGER (post-Drain-Test-11 evidence) | BL-012 Option A follow-up + Spool 2026-05-10 Bug B (BUMPED P3 -> P2; frequency 4-of-4 vs occasional) | S-M (depends on hypothesis evidence) |
| **B-056** | mod_state enum (Spool Spec 1) | Spool 2026-05-09 | S |

### P3

| ID | Title | Source | Size |
|---|---|---|---|
| **B-064** | drive_counter server-side sync gap (Pi=10, server=3) | Spool 2026-05-10 housekeeping | S |
| **B-058** | connection_log noise re-profile (post-deploy passive audit) | Spool 2026-05-09 housekeeping Item 3 | S |
| **B-057** | drive_annotations table (Spool Spec 2) | Spool 2026-05-09 | M -- depends on B-056 mod_state column |

### V0.27.3+ deferred (filed for completeness; will roll into next bug-fix sprints)

| ID | Title | Source |
|---|---|---|
| **B-060** | Wire UpsMonitor SOC% through orchestrator (BL-013 Step 2) | depends on B-061 path forward |
| **B-061** | Drop battery_health_log start_soc / end_soc legacy columns (BL-013 Step 3) | V0.28.0+ candidate; depends on B-060 + consumer audit |
| **B-055** | Weather API for drive context | depends on B-057 drive_annotations (FK column shape) |
| **TBD** | B-047 self-update IRL drill -- validate F-013 + F-014 with V0.27.X as test payload | Sprint 27 close session note (V0.27.2 ship triggered the question) |

## Recommended V0.27.3 sprint shape

**Core (3 stories, 1M + 2M = 3M)**: B-059 + I-019 + I-018 -- all P1, all blocking Mike's primary use cases.

**Plus 2-3 P2/P3 hygiene (3-4 S = 3-4S)**: B-062 + B-056 + B-064 = lights up the drain-analytics integrity + mod_state tagging + drive_counter sync.

**Total**: ~3M + 3S = 9 size-points (slightly larger than Sprint 28's 1M + 5S = 6 points). Trim B-064 or B-056 to reach 7-8 points if preferred; both are P3 and can defer to V0.27.4.

## Pre-grooming verifications (per `feedback_pm_run_pre_flight_during_grooming.md`)

When grooming the V0.27.3 sprint contract, PM MUST run each story's pre-flight `rg` BEFORE entering sprint. Sprint 28 had 3-of-6 stories with pre-flight contradictions (BL-011 / BL-012 / BL-013); 50% defect rate. Pre-flight at grooming time prevents recurrence.

Specific verifications needed:

| Story | Pre-flight check |
|---|---|
| B-059 | `rg _ensureDriveSummary src/server/services/` -- confirm Spool's pointer to the analytics-side writer; verify trigger wiring + 12-field contract clauses against current code |
| I-019 | `rg DriveDetector|MIN_INTER_DRIVE_SECONDS|driveCooldown src/pi/obdii/drive/` + read `detector.py` state machine; confirm Spool's "debounce window" hypothesis is wrong (already done -- MIN_INTER_DRIVE_SECONDS = 5, not minutes); identify alternative hypothesis to investigate |
| I-018 | Confirm rename approach: target name (analytics_types.py? domain_types.py?); audit all importers via `rg "from .* import .*types" src/server/analytics/` |
| B-062 | Drain Test 11 evidence (post-V0.27.2 deploy) MUST land first; confirm hypothesis A/B/C from US-307 forensic log; B-062 acceptance branches per hypothesis |
| B-056 | `rg mod_state|premod src/ tests/` -- 0 matches expected pre-fix; sanity-check schema add doesn't conflict with existing column names |

## Sprint sequencing notes

1. **B-063 hardware fix MUST land before V0.27.3 starts.** Otherwise I-019 repro protocol can't be run cleanly.
2. **V0.27.2 must validate first.** Drive 8 (post-B-063) + Drain Test 11 satisfy V0.27.2 bigDoD; `/sprint-validated` merges to main.
3. **V0.27.3 sprint branch forks from V0.27.2 stable on main**, NOT from V0.27.2 sprint branch. Standard sprint flow once V0.27.2 merges.
4. **B-062 specifically depends on Drain Test 11 evidence.** If Drain Test 11 happens before V0.27.3 starts, evidence is captured + hypothesis identified; B-062 acceptance is clear at sprint start. If Drain Test 11 happens DURING V0.27.3, B-062 may need re-grooming mid-sprint.

## Open questions for CIO

1. **V0.27.3 size cap**: 6 / 7 / 8 / 9 size-points? Sprint 28 was 6; recommended 7-8.
2. **B-056 mod_state inclusion**: is this V0.27.3 or V0.28+? It's groomed as P2 but it's MORE feature-shaped than bug-shaped; CIO previously said V0.27.X is bug-fix-only.
3. **B-058 deferral**: passive audit story; could just sit as a backlog observation rather than burning a sprint slot.
4. **B-057 drive_annotations + B-055 weather API + B-056 mod_state ordering**: these three interlock (B-056 must precede B-057 for FK; B-057 must precede B-055 for column shape). Sprint 30+ if treated as a feature mini-arc?
