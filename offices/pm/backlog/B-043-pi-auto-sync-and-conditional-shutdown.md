# B-043: Pi Automatic-Sync + Conditional-Shutdown on Power Loss

**Priority**: High
**Size**: L (multi-component; at least 3 US- stories once groomed)
**Status**: Pending (needs grooming before PRD)
**Epic**: B-037 (Pi Pipeline — Run/Sprint phases)
**Related**: US-184 (UPS signal, done), US-181 (shutdown handler, done), US-149 + US-154 (sync, done), spec §2.3 (WiFi detection, deferred), spec §4.3 / US-173 (lifecycle test — spec version is **manual** sync)
**Filed**: 2026-04-18 (PM Session 21)
**Source**: CIO behavior spec

## Summary

When the car is turned off, the Pi should do one of two things automatically:

1. **If at home WiFi (DeathStarWiFi)**: connect to Chi-Srv-01, push delta sync, then shut down cleanly. Drive is closed out server-side.
2. **If not at home WiFi**: shut down cleanly without attempting sync. Drive data stays in local SQLite. It will sync on the next time at home.

When the car is powered up, the Pi boots and data logging starts locally. This continues until the car is turned off. This pattern supports intermittent drives (car on/off multiple times away from home) and a single sync-on-return when the Pi sees home WiFi again.

## Motivation

**CIO direct quote (Session 21):**
> "When Switching to battery mode: it first checks to see if we are at home and connected to our home network. If it is, it connects to the server and uploads and synchronizes any delta data. If it is not connected to the home WiFi, it gracefully shuts down closes out its Drive. On car power up, the pi should start up, all of the data logging processes should start logging data locally. And this continues until the car is shut down. This pattern accommodates intermittent drives where the car is turned on and off but not at home, and synchronizes once it's back at home."

The Run/Sprint phases already assume a manual sync step (`python scripts/sync_now.py`) after each drive. Automating this:
- Removes a CIO step per drive (huge UX improvement over the life of the project)
- Ensures sync doesn't get forgotten when the CIO is tired or in a hurry
- Preserves data integrity (no sync when not at home means no failed attempt that could leave state in a bad half-synced condition — US-149's HWM-preserve-on-failure invariant already protects this)

## Current coverage (building blocks already in place)

| Component | Status | Source |
|---|---|---|
| UPS EXTERNAL → BATTERY signal + `onPowerSourceChange` callback | ✅ Done | US-184 (Sprint 11) |
| `SyncClient.pushAllDeltas()` with HWM-preserve invariant | ✅ Done | US-149 (Sprint 11) |
| Manual sync CLI `scripts/sync_now.py` | ✅ Done | US-154 (Sprint 11) |
| `ShutdownHandler` with SIGTERM + pushbutton + graceful teardown order | ✅ Done | US-181 (Sprint 10) |
| DriveDetector RUNNING/STOPPING/STOPPED state machine | ✅ Done (pre-existing) | B-032 or earlier |
| WiFi detection (SSID / subnet / server ping) | ❌ Missing | Spec §2.3 deferred |
| Power-loss orchestrator (glue: signal → WiFi check → branch) | ❌ Missing | This backlog item |
| Grace-period debouncer (ignore cranking dips) | ❌ Missing | This backlog item |

## Scope

### Proposed component breakdown (to be groomed into US- stories)

**Component 1 — WiFi / Home-Network Detection**
- Module: `src/pi/network/home_detector.py` (or similar)
- Functions:
  - `isAtHomeWifi()` — returns `True` if Pi is connected to DeathStarWiFi
  - `isServerReachable()` — returns `True` if `GET http://<baseUrl>/api/v1/ping` succeeds with bounded timeout
  - `getHomeNetworkState()` — combined: `HomeNetworkState.AT_HOME_SERVER_REACHABLE | AT_HOME_SERVER_DOWN | AWAY`
- Detection approach options (grooming needed):
  - SSID match via `iwgetid -r` (simple, requires SSID known)
  - Subnet match on `10.27.27.0/24` (catches any home-network reconfig; simpler to test)
  - Both (SSID for the wifi check, then server ping to confirm)
- Config: SSID name + subnet in `config.json pi.homeNetwork` section
- Logged state changes (connected/disconnected transitions) to `connection_log` table

**Component 2 — Power-Loss Orchestrator**
- Module: `src/pi/power/power_loss_orchestrator.py` (or extend existing power module)
- Subscribes to `UpsMonitor.onPowerSourceChange((old, new))`
- On `EXTERNAL → BATTERY` transition:
  1. Start grace-period debouncer (default 10s — configurable). If source returns to EXTERNAL during grace, cancel (momentary dip).
  2. Still on BATTERY after grace → begin shutdown sequence.
  3. Close current drive if one is active (DriveDetector RUNNING → STOPPING → STOPPED).
  4. Check `getHomeNetworkState()`:
     - `AT_HOME_SERVER_REACHABLE`: invoke `SyncClient.pushAllDeltas()` with bounded timeout (e.g., 45s to fit inside the ~60s UPS grace window). Log result. Proceed to shutdown regardless of sync success/failure — US-149's invariant guarantees sync failure leaves HWM untouched for retry next time home.
     - `AT_HOME_SERVER_DOWN`: skip sync, log reason, proceed to shutdown.
     - `AWAY`: skip sync, log reason, proceed to shutdown.
  5. Invoke `ShutdownHandler` graceful teardown (existing US-181 path). Data flushed to SQLite, systemd clean stop.
  6. Trigger OS-level power off: `sudo systemctl poweroff` OR let systemd handle via service ExitStopPost OR signal X1209 HAT to cut power (grooming Q).

**Component 3 — Lifecycle Integration Test**
- Extends or replaces the manual-sync version of US-173.
- End-to-end test (mocked signals on Windows, live-verified on Pi):
  - Simulate BATTERY transition while on home WiFi → sync fires → shutdown.
  - Simulate BATTERY transition while away → no sync → shutdown.
  - Simulate brief power dip (2s) → grace period swallows it, no action.
  - Simulate BATTERY with server unreachable → sync skipped, shutdown proceeds.

### Invariants

- **US-149 data-integrity invariant preserved**: failed sync attempts (timeout, server down, auth) never advance the sync_log high-water mark. A shutdown mid-sync leaves the HWM at the last successful position — retry on next home arrival.
- **Grace period is configurable and default-bounded**: 10s default, minimum 2s (to avoid instant-shutdown on genuine single-poll glitches), maximum 60s (can't exceed UPS backup budget).
- **Sync timeout must fit inside UPS battery budget**: sync must start and either complete or be abandoned before the UPS battery runs flat. X1209 provides ~5–15 min on a healthy LiPo at idle Pi load per Geekworm docs — plenty.
- **Drive-close always fires before shutdown**: whether or not sync runs, the current drive is transitioned to STOPPED state and statistics are calculated. This is an existing contract from US-181 + DriveDetector; orchestrator just makes sure it happens before shutdown starts.
- **No regression on existing lifecycle**: SIGTERM, pushbutton, and double-Ctrl-C shutdown paths (US-181) continue to work. Orchestrator is an additional path, not a replacement.

## Open grooming questions

1. **Grace period duration**: 10s reasonable? Cranking usually drops voltage <1s; a longer grace gives margin but delays legitimate shutdown. CIO gut call or empirical drill.
2. **Shutdown trigger mechanism**: `sudo systemctl poweroff` from Python (needs passwordless sudo for the service user) vs. signal X1209 HAT to cut power (requires knowing X1209's shutdown command/GPIO) vs. let UPS battery naturally deplete (slow, noisy, bad practice). Recommend `systemctl poweroff` via a small `deploy/setup-sudoers.d` rule. Needs CIO decision.
3. **Sync timeout**: 45s, 60s, or config-driven? Fit inside UPS grace period. Recommend config with 45s default.
4. **Mid-drive BATTERY handling**: if the Pi goes to BATTERY mid-drive (e.g., bad alternator), what do we do? Close the drive and shut down (current proposal)? Or keep logging as long as battery holds and wait for EXTERNAL to return? Current proposal: close and shut down — mid-drive data is valuable and safer to capture clean than risk ungraceful crash.
5. **Server-unreachable-while-at-home**: if SSID says home but ping fails (e.g., server is down), do we log and skip sync (current proposal) or retry N times within the UPS budget? Current proposal: log + skip; data still syncs on next successful home-arrival.
6. **WiFi detection approach**: SSID match only, subnet only, or both? Recommend both for resilience.
7. **OS-level home-WiFi config**: Pi's `wpa_supplicant.conf` already has DeathStarWiFi credentials from crawl phase setup (implied but not verified). Story should verify this is in place or document where it lives.
8. **BT + car ignition coupling**: Run phase (B-037) assumes OBDLink LX auto-connects on Pi boot. If BT fails, does the Pi still boot + log (no OBD data but local logging active)? Should impact "On car power up" branch. Likely yes — Pi runs regardless, just no OBD readings until BT connects.

## Proposed acceptance criteria (to be finalized during grooming)

- WiFi detection module returns correct `HomeNetworkState` for: at home + server up, at home + server down, away (not on DeathStarWiFi), tested with mocked and (optionally) live Pi.
- Power-loss orchestrator subscribes to `UpsMonitor.onPowerSourceChange` at startup.
- EXTERNAL → BATTERY with grace period < configured duration + recovery → no action (grace swallowed the dip).
- EXTERNAL → BATTERY with grace period elapsed, at home, server reachable → sync fires, shutdown proceeds. Server receives expected rows.
- EXTERNAL → BATTERY with grace period elapsed, away → no sync, shutdown proceeds cleanly.
- EXTERNAL → BATTERY with grace period elapsed, at home, server down → sync skipped, shutdown proceeds cleanly.
- Sync timeout bounded to < (UPS grace window − safety margin). Bounded timeout verified under mocked slow-server.
- Drive state transitions to STOPPED before any shutdown command fires.
- Post-shutdown: SQLite integrity check returns `ok`, WAL files flushed.
- CIO live drill on `chi-eclipse-01`: ignition ON → drive → ignition OFF → observe auto-sync (if at home) or shutdown (if away) happen automatically without CIO intervention.
- No regression on SIGTERM, pushbutton, double-Ctrl-C shutdown paths.

## Risks

- **Sudo for systemctl poweroff**: giving the Pi's service user passwordless sudo for `poweroff` is a small security widening. Mitigate with a scoped sudoers.d rule (`mcornelison ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff`).
- **False-positive BATTERY reads from US-184 VCELL trend**: if the VCELL trend heuristic misclassifies, the Pi will shut down mid-drive. US-184's trend window already has hysteresis + threshold tuning; this risk is low but would become visible fast if it happened. Mitigate by running the auto-shutdown path with a config-gated kill switch (`pi.powerLossOrchestrator.enabled`) so CIO can disable remotely if it misbehaves.
- **UPS battery variance**: not every X1209 LiPo holds 60+ seconds of Pi load. Sync timeout must accommodate the worst case. Test with a low-SOC battery before declaring the feature safe.
- **Systemd race conditions**: if systemd receives the poweroff command while the orchestrator's sync is still in flight, sync gets killed mid-request (broken connection). Use Python's async-aware shutdown sequencing to ensure sync returns (or times out) BEFORE poweroff fires.

## Dependencies

**Unblocked (can start anytime):**
- US-184 (UPS signal) ✅ Sprint 11
- US-181 (shutdown handler) ✅ Sprint 10
- US-149 / US-154 (sync) ✅ Sprint 11
- DriveDetector lifecycle ✅ Pre-existing

**Required before merging to main:**
- CIO decision on grace-period duration (grooming Q #1)
- CIO decision on shutdown trigger mechanism (grooming Q #2)

**Not a hard dependency (but improves confidence):**
- US-167 Bluetooth pairing (B-037 Run phase) — lets live drills produce real OBD-II data before the auto-shutdown test
- US-173 full-lifecycle test placeholder — B-043 likely replaces the manual-sync version of US-173

## Sprint placement notes

- **Sprint 13+ candidate** — probably the same sprint as early Run-phase work (US-167 BT pairing, US-168 live idle), because B-043 wants real-drive validation and BT pairing is upstream.
- Alternatively, can land as a pure-simulator implementation in a polish-adjacent sprint if the CIO wants it in hand before car-mount work.
- **Not for Sprint 12** (`sprint/pi-polish` — US-186/187/165/183) — scope and timing mismatch.

## Proposed story split (to be finalized)

- **US-188**: WiFi / home-network detection module (components, detection strategy, state callbacks)
- **US-189**: PowerLossOrchestrator — UPS signal subscription + grace period + conditional-branch glue
- **US-190**: End-to-end auto-sync + auto-shutdown lifecycle test (mocked on Windows + live on Pi)

Story counter would bump to US-191 when these are assigned.
