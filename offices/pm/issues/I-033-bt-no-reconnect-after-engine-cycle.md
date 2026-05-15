# I-033: BT-no-reconnect-after-engine-cycle — leg 2 of a multi-leg trip lost when Pi stays powered through engine-off

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | High (P1)                 |
| Status       | Open (V0.27.10 or V0.28.0 candidate -- CIO/PM call) |
| Category     | obdii / connection lifecycle |
| Found In     | `src/pi/obdii/orchestrator/core.py` + `src/pi/obdii/reconnect_loop.py` (post-drop reconnect path) |
| Found By     | Spool (Tuning SME) 2026-05-13 -- Drive 12 pharmacy-run analysis (2026-05-13-from-spool-drive-12-analysis-bt-reconnect-bug.md); independently corroborated by Marcus PM same session |
| Related B-   | B-063 (fuse-box DONE -- created the standing-power scenario this bug lives in); B-047 (engine-on/off lifecycle); related-but-distinct I-025 (BT reconnect *too aggressive* when adapter absent — this bug is the OPPOSITE: no attempt at all post-drop) |
| Created      | 2026-05-13                |

## Description

Multi-leg trip pattern: engine-on → drive → engine-off (errand stop) → engine-on → drive home → engine-off. **Pi stays powered the entire time** -- this is the load-bearing condition. The Pi-stays-powered scenario can arise via two routes:

1. **B-063 fuse-box wiring** during normal car operation (Pi on switched 12V → buck converter → 5V; "power=car" throughout drives -- the routine ops scenario)
2. **Wall power during debug / deploy / validation sessions** (Pi on AC adapter at the workbench; the scenario in effect for today's pharmacy-run repro)

Today's repro was via route #2 (CIO confirms 2026-05-13: Pi has been on wall power last night and today for diagnostic + deployment). The underlying code-path bug is identical for both routes -- what matters is the Pi process keeps running across an engine-cycle.

OBDLink LX is on a SWITCHED OBD-II port (2G Mitsubishi Eclipse), so the adapter loses 12V at engine-off → BT link drops → engine-on restores adapter power → adapter becomes reachable again.

**Pi software does not initiate a fresh `connect_attempt` on the second engine-on.** The reconnect path that would normally kick after a clean drop is silent. Result: leg 2 of the trip is lost.

Distinct from V0.27.1 hotfix scope -- V0.27.1 fixed initial-connect K-line timeout (cold detection); this is post-connect-drop recovery (different code path). Distinct from I-025 — I-025 is "reconnect loop too aggressive when adapter absent"; this bug is "reconnect loop never even attempts when adapter comes back."

## Steps to Reproduce

1. Pi powered, eclipse-obd service running, OBDLink LX paired + connected (drive in progress)
2. Turn engine off; remain stationary 5-10 minutes (errand stop)
3. Turn engine back on; drive
4. Turn engine off; check Pi-side data

Observe (today's evidence -- 2026-05-13 pharmacy run):

| Time (UTC) | Event | Source |
|---|---|---|
| 19:01:59 | Drive 12 starts (leg 1 to pharmacy) | `connection_log` drive_start, `drive_summary` |
| 19:10:24 | Drive 12 ends via ECU silence (61.4 s no RPM) | journal `_checkEcuSilenceDriveEnd`, `connection_log` drive_end |
| 19:14:32 | Drain `stage_warning` @ vcell 3.700 V (pharmacy engine-off period) | `power_log`, `battery_health_log` event 20 |
| **19:16:31** | **AC blip in power_log = adapter power restored = engine-on leg 2** | `power_log` transition_to_ac |
| 19:16:43 | US-242/B-049 alternator-voltage detector fires (BATTERY_V > 13.80V × 3 samples) → escalates to active poll | journal |
| 19:16:44 | RPM probe right after: **"Parameter 'RPM' returned null response"** (adapter present but session stale; no fresh connect attempted) | journal |
| 19:26:11 | Engine off at home (transition_to_battery) | `power_log` |
| 19:28:05 | `SyncCadenceController: IDLE → ACTIVE (missed drive_start fallback)` -- the log message itself names the failure | journal |
| 19:29:08 | Drain `stage_warning` @ vcell 3.694 V (post-arrival) | `battery_health_log` event 21 |

`connection_log` for the entire day shows **only two rows** (drive_start + drive_end for drive 12). No reconnect attempt logged for the 30+ minute window after 19:10:24Z despite power_log AC blips at 19:16:31 + 19:25-19:26.

## Expected Behavior

On loss of the OBDLink BT link (event_type that already exists in connection_log / orchestrator state), Pi should kick `_performConnect` on the heartbeat tick and continue retrying until the adapter is reachable again. When the adapter comes back (post-engine-on), DriveDetector mints a new drive_id (13) and capture resumes -- the second leg becomes its own clean drive.

## Actual Behavior

After drive_end fires (ECU silence at 19:10:24Z) the orchestrator goes quiet. The voltage-escalation logic at 19:16:43 noticed engine-on and tried to inject one RPM probe (which failed because the BT session was stale, not because the adapter was missing) -- but that single probe failure did not trigger a reconnect cycle. 30+ min of silence in connection_log; 549 orphan `realtime_data` rows with `drive_id=NULL` (capture continued at the data-logger level but had no drive context).

Server side: same orphan count (~631 NULL-drive rows in that window via sync); drive 12 row exists (id=16) and got `drive_id` healed by US-326; but `start_time`, `end_time`, `row_count` all NULL/0 because no follow-up analytics trigger fired.

## Impact

- **35 % of today's drive time was telemetry-orphaned** (leg 2: ~10 min capture time × ~70% engine-on; lost).
- Every multi-leg trip pattern (errand runs, fuel stops, mid-drive shutdowns) silently loses every leg past the first whenever Pi stays powered across the engine cycle.
- Scenario coverage grew with B-063 fuse-box wiring (DONE 2026-05-12 -- routine ops where Pi stays powered via car-switched 12V) AND it occurs in every debug/deploy session where Pi is on wall power. The pre-B-063 normal-ops path (key-on = Pi cold-boot) masked this bug; under either of the now-common Pi-stays-up scenarios it is load-bearing.
- Forensic signal complication: when Pi is on wall power (debug) OR fuse-box switched 12V (routine), `power_log` no longer cleanly tracks engine state (the AC-blips today were OBDLink-port-12V transitions, not Pi-power transitions). Only the OBDLink BT-state and ELM ATRV can positively indicate engine state under those scenarios. See Spool's P3 V0.28+ backlog ask (alternator-voltage proxy via ELM ATRV) -- complementary fix.

## Validation gate impact

Drive 12 was the IRL validation gate for the V0.27.7 / V0.27.8 / V0.27.9 chain merge to main. Drive 12 itself captured cleanly; sync works; US-326 drive_id healing works. **But the broken leg-2 reveals V0.27.1 hotfix did NOT close the engine-on/off lifecycle hole** -- recommend gating `/chain-validated` on a fix or documented workaround.

## Resolution -- direction

Spool's note (2026-05-13-from-spool-drive-12-analysis-bt-reconnect-bug.md) is going to Ralph independently with fix direction. PM-side this story is for tracking + backlog selection. Likely shape (PM read; Ralph will refine):

1. On the heartbeat tick, distinguish "adapter probe returned null while session was previously OK" from "adapter unreachable" -- the former is a stale-session signal and should drop the BT connection cleanly + kick `_performConnect`.
2. Alternative: track `lastSuccessfulQueryTime` -- if elapsed > N seconds AND any subsequent query returns null, force reconnect.
3. DriveDetector reset on reconnect so a new drive_id is minted for the next start.

## Acceptance Criteria (PM-level; Ralph fills in implementation)

- [ ] Pre-flight audit: rg `_performConnect|_handleConnection|reconnect|_checkEcuSilenceDriveEnd` src/pi/obdii/ -- map post-drop reconnect logic
- [ ] On stale-session detection (RPM-null-after-prior-success or N-second query gap), force BT disconnect + fresh `_performConnect`
- [ ] DriveDetector re-arms post-reconnect so the next engine-on mints a fresh drive_id
- [ ] connection_log records a `reconnect_attempt` event per cycle (so this bug class becomes auditable from the DB next time)
- [ ] Synthetic regression test: simulated drive_end → power_log AC-blip → adapter-reachable-but-stale-session → assert reconnect kicks within N heartbeat ticks AND new drive_id minted
- [ ] Real-world validation gate: repeat today's pharmacy-run pattern (drive → engine-off → engine-on → drive → engine-off); assert drive 13 (or whatever is next) materializes with > 100 rows AND `drive_id` populated correctly

## Cross-references

- Spool note: `offices/pm/inbox/archive/2026-05-13-from-spool-drive-12-analysis-bt-reconnect-bug.md` (will be archived this session)
- Companion bug: I-034 (SQLite long-uptime disk-I/O lockup -- separate bug, surfaced same session)
- V0.28+ backlog ask (Spool, P3): alternator-voltage engine-state proxy via ELM ATRV -- complementary, not a substitute for this fix
- V0.27.1 hotfix scope (US-301/US-302) -- closed initial-connect + AC-power-restored paths, did NOT close adapter-still-present-but-session-stale path

## Source

Spool A2AL note 2026-05-13 + Marcus PM independent dataset walk same session. CIO hypothesis verbatim: "BT drops on engine-off; no force-reconnect on engine-on."
