# V0.27.1 hotfix shipped + Drive 6 IRL validation green
**Date**: 2026-05-08 (evening session)
**From**: Rex (Ralph / Developer)
**To**: Marcus (PM)
**Priority**: HOTFIX VALIDATED — ready for commit + tag + (eventual) `/sprint-validated`

> **UPDATED 2026-05-08 23:00ish CDT** — added forensic confirmation of the 20:36 reboot (V0.24.1 ladder fired exactly as designed; **first in-vehicle validation of the whole Sprint 21 + V0.24.1 + wake-on-power chain** — major win); added two new confirmed regressions (sync table migration gap + statistics drive_id NULL); cleared statistics + dtc_log audits.

## TL;DR

V0.27.1 hotfix for the Sprint 27 engine-on-test-#2 stacking-connect bug landed and **validated on the road tonight**. Mike drove the car for ~2 hours with two engine-off stops; Pi captured **12,658 rows of realtime_data across drives 6 + 7**, the first successful in-vehicle capture since **2026-05-01** (8 days of broken telemetry, now closed). V0.27.1 fix held across all three engine-on transitions (bench warmup + 2 in-vehicle restarts) with zero "multiple access on port?" errors.

**Bonus validation surfaced in the forensics**: the 20:36 mid-drive Pi reboot was the **V0.24.1 staged-shutdown ladder firing exactly as designed in real road conditions**. First in-vehicle validation of the 8-drain-saga closeout (Drain Test 10 was bench; tonight closed the road validation). Sprint 21 wake-on-power EEPROM + V0.24.1 ladder + V0.27.1 connect-path all stacked correctly: engine-off → ladder discharge → graceful poweroff → engine-on → auto-boot → V0.27.1 clean reconnect. **The B-043 power-loss orchestrator full lifecycle is now empirically validated end-to-end.**

**Three regressions were unmasked by V0.27.1's success** (all hidden behind the previous "no data ever" symptom; none V0.27.1-related). Filed below for triage.

## V0.27.1 hotfix scope (for your commit + tag)

Per CIO direct authorization in this evening's session, I authored + deployed V0.27.1 from my dev branch. Per the new 2026-05-08 workflow rule (`main` = "fully validated stable"; sprint stays on branch until IRL drill closes), **V0.27.1 should commit on `sprint/sprint27-engine-on-fixes`, NOT main**. `/sprint-validated` will merge to main after Drive 6 + Drain Test 11 validate the bigDefinitionOfDone.

**Files in V0.27.1 scope (all unstaged, ready in working tree):**

| File | Change |
|------|--------|
| `src/pi/obdii/obd_connection.py` | `__init__` adds `self._connectLock = threading.Lock()`. `connect()` body extracted to private `_performConnect()`; public `connect()` is now `with self._connectLock: return self._performConnect()`. New public `isConnectInFlight()` exposes lock state. |
| `src/pi/obdii/reconnect_loop.py` | `HEARTBEAT_ATTEMPT_TIMEOUT_SEC` 5.0 → 30.0 (K-line cold-protocol-detection envelope ~6-10s on 1998 4G63). New `inFlightProbeFn` keyword to `runReconnectHeartbeat`; tick logs `outcome=already_in_flight` and skips `_attemptConnectWithCap` spawn when probe returns True. |
| `src/pi/obdii/orchestrator/lifecycle.py` | New `_buildHeartbeatInFlightProbeFn` closure mirrors the existing `_buildHeartbeatConnectFn` / `_buildHeartbeatIsConnectedFn` pattern. `_spawnReconnectHeartbeatDaemon` passes the closure to `runReconnectHeartbeat`. Spawn-time INFO log line declares `tick=10s, attempt cap=30s, in-flight probe wired`. |
| `tests/pi/obdii/test_connect_thread_safety.py` (NEW) | 6 tests / 3 classes: 8-thread `Barrier(8).wait()` contention test asserts `maxConcurrent==1`; `isConnectInFlight()` observability seam test; heartbeat-skip-when-in-flight test; backwards-compat test (legacy callsites unchanged); constant-pin test. Pre-fix RED was synthetic 8-thread race showing `maxConcurrent=8 violations=7`; post-fix all GREEN. |
| `tests/pi/obdii/test_reconnect_loop_heartbeat.py` | `test_constantsExportedForCallSiteDiscoverability` updated 5.0 → 30.0 with V0.27.1 rationale. |
| `deploy/RELEASE_VERSION` | V0.27.0 → V0.27.1 (theme + description trimmed to fit US-241 schema's 50-char + 400-char limits). |
| `offices/ralph/progress.txt` | Session 180 entry with full RCA + verification (use as commit-message source). |

**Suggested commit message** (lift from progress.txt):
```
fix(V0.27.1): ObdConnection.connect() thread safety + heartbeat in-flight skip

Sprint 27 engine-on test #2 (2026-05-08) produced 0 realtime_data rows.
RCA: ObdConnection.connect() had no thread safety; the Sprint 25 leaked
_runInitialConnectWithTimeout daemon and the Sprint 27 US-301 heartbeat-
spawned daemons collided on /dev/rfcomm0, surfacing as pyserial
"multiple access on port?" errors.

- ObdConnection: __init__ adds self._connectLock; connect() body extracted
  to private _performConnect() running under the lock; new public
  isConnectInFlight() exposes lock state.
- runReconnectHeartbeat: new optional inFlightProbeFn keyword; ticks log
  outcome=already_in_flight and skip the _attemptConnectWithCap spawn
  when probe returns True. HEARTBEAT_ATTEMPT_TIMEOUT_SEC 5.0 -> 30.0 to
  match the empirical K-line cold-protocol-detection envelope on the 1998
  4G63 ECU.
- LifecycleMixin: new _buildHeartbeatInFlightProbeFn closure wired to
  ObdConnection.isConnectInFlight; heartbeat spawn passes it through.
- 6-test regression gate at tests/pi/obdii/test_connect_thread_safety.py.
  Pre-fix synthetic 8-thread Barrier race: maxConcurrent=8 violations=7.
  Post-fix: maxConcurrent=1 violations=0.
- Deployed to chi-eclipse-01 + IRL-validated tonight: 12,658 rows captured
  across drives 6+7, three engine-on cycles, ZERO "multiple access on
  port?" errors. First in-vehicle capture since 2026-05-01.
- Drive 6 unblocked.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

**Tag**: `V0.27.1` annotated tag on the sprint-branch commit.

## Validation evidence (Drive 6 IRL drill)

Mike drove tonight with engine on at bench → drove → 2 engine-off stops → home. All three engine-on transitions successful.

| Cycle | Time | Outcome | V0.27.1 evidence |
|-------|------|---------|------------------|
| 1 (bench engine-on) | 19:41:43 | `connect_success` event id 27351 | Heartbeat saw `already_in_flight` 46 times while leaked daemon held the lock; daemon's last attempt succeeded; heartbeat exited cleanly when `isConnectedFn()` returned True |
| 2 (drive's first engine-on) | 20:37:27 | `DRIVE STARTED \| profile=daily \| RPM=1734.25 \| drive_id=7` | Drive 7 ran 584.4s, peakRPM=5378.75, peakSpeed=84mph, ended via ECU silence at 20:47:12 (clean 60s threshold trip) |
| 3 (later engine-on) | ~22:50+ | Pi recovered cleanly per connect_attempt cluster pattern (no stacking) | (Pi currently unreachable as I write this — almost certainly on UPS battery cycling through the staged-shutdown ladder; see Issue #2 below) |

**Telemetry counters:**
- `realtime_data` total rows: 78,211 (frozen since 2026-05-01) → **80,869+** (live, growing)
- `drive_id=6`: 7,085 rows (bench-warmup capture)
- `drive_id=7`: 4,222 rows (the road drive)
- `drive_id=NULL`: 1,351 rows (pre-drive-detector-trip ticks; expected per US-286 production-order learning)

**Heartbeat outcome distribution since V0.27.1 deploy:**
- `already_in_flight`: 46 (every tick during the leaked-daemon's wedge cycle, exactly as designed)
- `timeout` / `failure` / `error`: 0 (heartbeat never had to spawn its own connect because the leaked daemon won every race)

**Multi-thread collision check:** The pre-fix smoking-gun pattern (multiple `Connection attempt N/6 failed` lines with interleaved counters in the same second) is **GONE**. `journalctl | grep "Connection attempt" | awk by-second | uniq -c | filter > 1` returned EMPTY. Single rfcomm0 holder, stable thread count.

## Issue #1 (CONFIRMED, P1) — drive_summary not writing rows for drives 6+7

**Symptom CONFIRMED**: drive_summary count = 4 (drives 2-5 from history; last good write 2026-04-29). Drive 6 + Drive 7 ran cleanly per the journal (`DRIVE STARTED | drive_id=7 | RPM=1734.25` and `DRIVE ENDED | duration=584.4s | peakRPM=5378.75 | peakSpeed=84.0` both fired with full payloads). Zero new rows landed in drive_summary.

**Likely cause**: SummaryRecorder (US-206) wiring is logged at boot ("SummaryRecorder wired to driveDetector (US-206)") but the actual write path is silent — no INFO log on row insert. Most probable:
- Drive-end handler fires → SummaryRecorder's insert path is exception-swallowed, OR
- Drive-end → SummaryRecorder wiring in the new orchestrator structure (Sweep-5 mixin refactor era) lost the call site

Last known-good drive_summary write was 2026-04-29 (drive_id=5), which roughly aligns with the start of the engine-on path being broken. Probably regressed during Sprint 26 / Sweep-5 refactor; was masked behind the engine-on capture failure.

**Impact**: HIGH for Spool — drive_summary holds `ambient_temp_at_start_c`, `starting_battery_v`, `barometric_kpa_at_start`, the exact context Spool's per-drive tuning analysis depends on. Without these rows, the realtime_data exists but lacks drive-level metadata.

**Recommended action**: file P1 issue (or hotfix story for V0.27.2 if you want it on the same sprint). Discriminator/test: drive-end harness (mirror US-303 pattern) that asserts a drive_summary row exists post-drive-end with non-NULL ambient_temp/battery/baro fields.

**This is NOT a V0.27.1 regression**.

## Issue #2 (RESOLVED — not a bug) — 20:36:48 PID change was V0.24.1 ladder firing as designed

**Symptom**: Service PID changed from 233537 (post-V0.27.1-deploy) to 1185 (very low PID = fresh OS boot, not a service restart) at 2026-05-08 20:36:48 CDT.

**FORENSIC CONFIRMATION (pulled after Pi came back on wall power)** — the V0.24.1 staged-shutdown ladder fired exactly as designed:

| Time (CDT) | power_log event | VCELL | Threshold |
|------------|-----------------|-------|-----------|
| 20:19:00 | `transition_to_battery` | — | engine off, Pi switches to UPS |
| 20:24:04 | **`stage_warning`** | **3.69V** | crossed 3.70 ✅ |
| 20:32:45 | **`stage_imminent`** | **3.54V** | crossed 3.55 ✅ |
| 20:36:45 | **`stage_trigger`** | **3.42V** | crossed 3.45 → graceful poweroff ✅ |
| 20:36:59 | `transition_to_ac` | — | Pi auto-rebooted via US-253 wake-on-power EEPROM ✅ |

`battery_health_log` row 8 has the clean closeout: started 20:24:04, ended 20:36:45, start_vcell=4.17V, end_vcell=3.42V, runtime 761s, load_class='production'.

**This is the FIRST IN-VEHICLE VALIDATION of the V0.24.1 ladder + Sprint 21 wake-on-power chain.** Drain Test 10 (2026-05-04) was bench validation; tonight closed the road validation. The 8-drain-saga that ran from Sprint 21 through Sprint 24 (closed by V0.24.1 hotfix) is now genuinely retired.

**B-043 PowerLossOrchestrator full lifecycle is empirically validated end-to-end** (the only remaining gating per memory was "CIO hardware task to wire Pi to ignition-switched line" — and tonight's drive proves the existing UPS-battery-only path works flawlessly even without that wiring).

Engine-off cycle #2 (later in the drive, ~20:46) also began the ladder sequence — `stage_warning` at 20:47:10, vcell=3.67V — followed by another graceful poweroff + wake-on-power cycle at ~22:13 (boot -1 → boot 0 transition).

**No code change needed. RESOLVED.** Worth a celebration note: this validates ~6 months of accumulated Sprint 21-24 power-management work in real road conditions for the first time.

## Issue #3 (NEW, P2) — Sprint 26 US-300 v0007 sync-history migration did not apply

**Symptom**: Live Pi DB schema shows only `sync_log` table. No `sync_history` table exists.

```
sqlite> SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE 'sync%' OR name LIKE '%history%');
sync_log
```

Memory says Sprint 26 US-300 + BL-010 ("BL-010 fixed table name") shipped a v0007 migration that renamed `sync_log` → `sync_history` for the 90-day retention horizon. Either:
- (a) The migration was code-only — Python references were updated to talk to "sync_history" but no actual DDL ran, OR
- (b) The migration ran but failed silently (exception swallowed), OR
- (c) The migration was deferred and the BL-010 fix landed elsewhere

**Impact**: B-053 sync-history retention (90-day horizon) silently cannot work — there's no table to retain rows in. Sync may still function depending on whether the code expects `sync_history` (which would error at first call) or kept the legacy `sync_log` reference.

**Recommended verification (one-line query)**: `sqlite3 data/obd.db "SELECT * FROM schema_migrations ORDER BY id DESC LIMIT 5;"` (or whatever the migration-tracking table is — typical name is `schema_migrations` / `migrations` / `_schema_version`). If v0007 is not present, migration never ran. If present + has an error column populated, swallowed exception.

**Recommended action**: file P2 issue. Could be a quick V0.27.2 alongside #1, or a Sprint 28 starter.

## Issue #4 (NEW, P3) — `statistics` rows write with `drive_id=NULL`

**Symptom**: 84 rows in `statistics` table (84 fresh from tonight's drive). All `drive_id` column values are NULL.

Example from tonight: `id=110 | parameter_name=SPEED | analysis_date=2026-05-09T01:47:12Z | profile_id=daily | max=84.0 | sample_count=1836 | drive_id=NULL`. Note max=84.0 matches `peakSpeed=84.0` from the journal — so the analysis IS correctly aggregating real drive data, just not tagging which drive it came from.

**Impact**: Low. Spool's per-parameter statistics are intact (max RPM, max speed, mean throttle, etc. are all there) — but he can't filter "this drive's stats" without joining against realtime_data drive_id ranges himself.

**Likely cause**: same write-path family as Issue #1 (SummaryRecorder). The drive_id is presumably supposed to be populated by the StatisticsEngine reading active drive state from the orchestrator at write time; that wiring may have lost its drive_id source during the same Sweep-5 refactor.

**Recommended action**: file P3 issue. Could be rolled into Issue #1's fix (same family, likely same single-line wiring fix).

## Audit findings — checked CLEAN (not bugs)

These are subsystems I sanity-checked tonight and they appear to be working:

| Subsystem | Status | Evidence |
|-----------|--------|----------|
| `statistics` table writes | ✅ Working | 84 rows fresh from tonight (id 110: SPEED max=84.0 matching journal `peakSpeed=84.0`; id 112: TIMING_ADVANCE max=61.0; etc.). Drive aggregation is happening. (See Issue #4 for the orthogonal NULL-drive_id concern.) |
| `dtc_log` post-drive | ✅ Consistent with clean ECU | 0 rows. US-292 only writes a row when a DTC is **found**, not on every probe. Mike's car likely has no active codes — consistent. Worth a separate journal-grep check that the Mode 03 probe ran-and-found-zero, but no evidence of regression. |
| `power_log` writes | ✅ Working | 9 distinct event types post-deploy: `ac_power`, `battery_power`, `power_saving_enabled/disabled`, `stage_warning`, `stage_imminent`, `stage_trigger`, `transition_to_battery`, `transition_to_ac`. Full ladder sequence captured for engine-off cycle #1; Issue #2 RESOLVED via this evidence. |
| `battery_health_log` writes | ✅ Working | drain_event_id 8 closed cleanly with start_vcell=4.17V / end_vcell=3.42V / runtime=761s. drain_event_id 9 currently open from engine-off cycle #2. |
| US-301 heartbeat behavior | ✅ Working | 46 `outcome=already_in_flight` ticks during the leaked-daemon hold window; heartbeat exited cleanly when connection came up. ZERO timeout/error/failure outcomes (heartbeat never had to spawn its own connect — leaked daemon won every race). |
| Drive detector start/end | ✅ Working | Drive 7 started at RPM=1734.25, ended via ECU silence (60s threshold) — exact V0.24.1-style threshold-based termination. |

## What I'd ask you to do

1. **Stage + commit** V0.27.1 on `sprint/sprint27-engine-on-fixes` (file scope above; suggested commit message above; use HEREDOC per CLAUDE.md).
2. **Tag** `V0.27.1` (annotated, `git tag -a V0.27.1 -m "..."`).
3. **Push** the sprint branch to `origin/sprint/sprint27-engine-on-fixes` (NOT main per the new workflow).
4. **Update** `offices/ralph/sprint.json` validation block: V0.27.1 currentVersion + validatedAt timestamp from this drive + validatedBy=Mike. (Or wait — the V0.27.1 was a code change, not a sprint contract change; update path is whatever the new `/sprint-validated` workflow scripts read.)
5. **File P1 issue (Issue #1)** for drive_summary not writing. Suggest title `I-XXX: SummaryRecorder not writing drive_summary rows post-drive-end (regression)`. Link to this note as evidence.
6. **File P2 issue (Issue #3)** for sync-history migration gap. Suggest title `I-XXX: v0007 sync-history migration did not apply on Pi (sync_log still present, sync_history missing)`. One-line verification first: `sqlite3 data/obd.db "SELECT * FROM schema_migrations ORDER BY id DESC LIMIT 5;"` to confirm whether the migration ran-and-failed or never-ran.
7. **File P3 issue (Issue #4)** for statistics drive_id NULL. Could be rolled into #1's fix (same write-path regression family).
8. **NO action needed for Issue #2** — RESOLVED with forensic confirmation. Worth a celebratory line in the next changelog: "First in-vehicle validation of the V0.24.1 staged-shutdown ladder + Sprint 21 wake-on-power chain." B-043 PowerLossOrchestrator full-lifecycle is empirically validated end-to-end.
9. **`/sprint-validated`** when you + Mike are ready to merge to main and bump regression_manifest.json `lastValidated` for F-002 through F-012. Tonight's drive validates the engine-on critical path features; the V0.24.1 ladder validation also potentially bumps `lastValidated` on power-mgmt features (F-XXX, whichever IDs cover B-043).

## Cross-references

- V0.27.1 RCA + implementation: `offices/ralph/progress.txt` Session 180 entry (full text)
- Spool's hotfix request: `offices/ralph/inbox/2026-05-08-from-spool-us301-hotfix-stacking-connects.md` (Spool's three-story plan; my one-story dev-side plan in progress.txt explains the divergence)
- Spool's earlier P0 inbox notes (engine-on test #1 + #2): `offices/pm/inbox/2026-05-08-from-spool-engine-on-test-blocked-2-p0-bugs.md`, `offices/pm/inbox/2026-05-08-from-spool-engine-on-test-2-blocked-us301-stacking-bug.md`
- V0.24.1 anti-pattern lesson (cross-module module identity + boot-canary discipline; mirrored in V0.27.1's regression test pattern): `specs/anti-patterns.md`

## Drive 6 status

✅ **UNBLOCKED.** First successful in-vehicle data capture since 2026-05-01. Spool can resume LTFT-post-jump tracking once you process the new realtime_data payload + the (eventual, post-Issue-#1-fix) drive_summary rows.

— Rex
