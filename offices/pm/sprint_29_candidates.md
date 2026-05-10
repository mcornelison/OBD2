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

### P3

| ID | Title | Source | Size |
|---|---|---|---|
| **B-064** | drive_counter server-side sync gap (Pi=10, server=3) | Spool 2026-05-10 housekeeping | S |

### DEFERRED to V0.28+ stable feature sprint (CIO 2026-05-10 directive: V0.27.X = bug-fixes only)

| ID | Title | Why deferred |
|---|---|---|
| **B-056** | mod_state enum | New schema column + tagging system = FEATURE not bug fix |
| **B-057** | drive_annotations table | New schema/feature; depends on B-056 |
| **B-055** | Weather API for drive context | New feature; depends on B-057 |
| **B-058** | connection_log noise re-profile | Passive audit, not a fix; doesn't validate sprint close; defer until needed |

### V0.27.3+ deferred (filed for completeness; will roll into next bug-fix sprints)

| ID | Title | Source |
|---|---|---|
| **B-060** | Wire UpsMonitor SOC% through orchestrator (BL-013 Step 2) | depends on B-061 path forward |
| **B-061** | Drop battery_health_log start_soc / end_soc legacy columns (BL-013 Step 3) | V0.28.0+ candidate; depends on B-060 + consumer audit |
| **B-055** | Weather API for drive context | depends on B-057 drive_annotations (FK column shape) |
| **TBD** | B-047 self-update IRL drill -- validate F-013 + F-014 with V0.27.X as test payload | Sprint 27 close session note (V0.27.2 ship triggered the question) |

## V0.27.3 sprint shape (CIO 2026-05-10 finalized)

**5 stories, all bug fixes, ~8 size-points** (under 9-cap):

| P | Story | ID | Size |
|---|---|---|---|
| P1 | drive_summary 12-field contract | B-059 | M |
| P1 | DriveDetector warm-restart fix | I-019 | M |
| P1 | calibration.py types.py shadow + missing baselines | I-018 | S-M |
| P2 | drain_event close flush | B-062 | S-M |
| P3 | drive_counter sync gap | B-064 | S |

Total: 3M + 2S = ~8 size-points. CIO 2026-05-10 confirmed 9 is OK; this leaves ~1 point of headroom for any mid-sprint surprises.

**No feature work in V0.27.X**. mod_state / drive_annotations / weather API / connection_log re-profile all wait for stable + V0.28 feature sprint.

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

## CIO answers (2026-05-10)

1. **Size cap**: 9 OK. Final shape ~8 (1 point headroom).
2. **B-056 mod_state**: NEW FEATURE = defer to V0.28+ stable feature sprint.
3. **B-058 connection_log**: passive audit, not a fix, doesn't help validate close = defer.
4. **B-057 / B-055 / B-056 feature arc**: all deferred to V0.28+ post-stable-V1.0 milestone (or earliest feature sprint, whichever comes first).

## Standing rule reinforcement

V0.27.X chain = **bug fixes ONLY** until clean. Per Mike Q5 2026-05-08 patch-version pattern + Mike 2026-05-10 reinforcement: no new features until the V0.27 epoch validates and merges to a stable main. Then V0.28.0 opens for feature work.
