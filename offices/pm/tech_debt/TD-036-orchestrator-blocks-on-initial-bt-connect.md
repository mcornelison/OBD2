# TD-036: Orchestrator blocks on initial BT connect, prevents `runLoop` (and US-226 auto-sync) from starting when engine is off

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Medium                    |
| Status       | Open                      |
| Category     | code / lifecycle          |
| Affected     | `src/pi/obdii/orchestrator/lifecycle.py::_initializeConnection` + caller flow |
| Filed By     | Marcus (PM), Sprint 18 post-deploy 2026-04-27 |
| Surfaced In  | After Sprint 18 deploy of US-226 (auto-sync wiring) the Pi still did not auto-sync Drive 3. Diagnosis: `eclipse-obd.service` was running, but stuck in the initial-connect retry loop in `_initializeConnection` because the engine was off (adapter responds, ECU silent). The orchestrator never reached `runLoop`, where US-226's `_maybeTriggerIntervalSync` is invoked. With car off, sync simply cannot fire — by design, but unintentionally. |
| Filed        | 2026-04-27                |

## Symptom

After Pi deploy with US-226 auto-sync wiring, journal shows:
```
INFO  | _initializeConnection | Starting connection...
INFO  | obd_connection.connect | Connecting to OBD-II dongle | mac=00:04:3E:85:0D:FB
WARN  | obd_connection.connect | Connection attempt 1/6 failed | error=...
INFO  | obd_connection.connect | Retrying in 1s...
WARN  | obd_connection.connect | Connection attempt 2/6 failed
INFO  | obd_connection.connect | Retrying in 2s...
ERROR | obd.elm327 | Adapter connected, but the ignition is off
WARN  | obd_connection.connect | Connection attempt 3/6 failed
INFO  | obd_connection.connect | Retrying in 4s...
[loop continues; runLoop never starts]
```

The collector never advances past `_initializeConnection`, so:
- `runLoop` never runs
- `_maybeTriggerIntervalSync` (US-226) never fires
- Auto-sync silently fails to fire — no error, no warning, just a quiet "sync hasn't fired" state

## Root cause

`_initializeConnection` blocks on the first successful `ObdConnection.connect()` before returning control to the orchestrator's main `runLoop`. With ignition off (or any sustained ECU silence), the connect retry loop ticks indefinitely (US-211 + US-221 + US-232 work make it gracefully retry without crashing — but never *resolves*). So the orchestrator is forever in the "starting up" phase.

US-211's resilience work was scoped to **mid-drive** BT flaps (after `runLoop` is established). It does not address the **initial** connection-failure case where the orchestrator hasn't yet entered its main loop.

US-226 (auto-sync) lives in `runLoop`, so it inherits this initialization gap.

## Impact

- **Drive 3 + future drives**: any sync after a Pi reboot when the car is off will not fire automatically until the engine is started + adapter handshake completes. CIO must invoke `scripts/sync_now.py` manually, OR start the engine before relying on auto-sync.
- **Spool's review ritual**: blocked until either (a) engine started briefly to clear initialization, or (b) manual sync.
- **US-216 power-down orchestrator path**: also potentially affected — if the Pi reboots on AC-restore mid-drain, the orchestrator's first action should be sync the queued events, but it would block on BT-connect first.

## Options

1. **Make `_initializeConnection` non-blocking on first-connect failure.** Return a "degraded" connection state and let `runLoop` start. Sync, drive-detection, and other components run; OBD polling stays gated until first successful connect. This matches how a healthy car-off-Pi-on state should behave.
2. **Plumb sync into a separate background task** that runs independently of `runLoop` (and therefore independent of OBD-connect state). Deeper restructure.
3. **Add a short timeout** on the initial-connect retry loop that, on expiry, transitions to a degraded state that still enters `runLoop`.

**Recommended**: Option 1. Smallest change that preserves the design intent while fixing the operational gap. `_initializeConnection` returns immediately with a not-yet-connected state; the existing US-211/US-221 reconnect-loop machinery (which already runs from `runLoop`) handles the "still trying to connect" case post-init.

## Related

- US-211 (reconnect classifier + loop, Sprint 16) — solves mid-drive BT flap, not initial-connect.
- US-221 (US-211 integration into capture loop, Sprint 17) — same scope.
- US-226 (auto-sync wiring, Sprint 18) — directly affected by this bug.
- US-232 / TD-035 (SIGTERM responsiveness) — adjacent lifecycle territory.
- TD-035 fixed `time.sleep` → `Event.wait` in retry loops; if Option 3 chosen, the timeout-then-degraded transition can reuse the same event mechanism.

## Workaround used 2026-04-27

For BL-007 closure, bridged via:
1. SQL cursor-skip on Pi `sync_log.realtime_data.last_synced_id` from 492,844 → 3,433,871 (skipping the 2.9M `drive_id=1` pollution rows that US-227 will delete anyway).
2. Manual `sync_now.py` loop, 13 invocations × 500-row batches, drained Drive 3's 6,089 rows.
3. Final cursor at 3,439,960 (Drive 3 max id).

This is operational-only; the underlying TD-036 bug remains for Sprint 19+ to address.
