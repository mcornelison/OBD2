# TD-035: Collector BT retry loop ignores SIGTERM (forces SIGKILL on every restart)

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Medium                    |
| Status       | Open                      |
| Category     | code / lifecycle          |
| Affected     | `src/pi/obdii/obd_connection.py::connect` retry loop |
| Filed By     | Marcus (PM), Sprint 17 post-deploy debug 2026-04-23 |
| Surfaced In  | `systemctl restart eclipse-obd` during pygame fix; observed restart takes ~90s because process doesn't respond to SIGTERM during `time.sleep(N)` between BT retries. systemd ends up SIGKILLing after `TimeoutStopSec`. |
| Filed        | 2026-04-23                |

## Symptom

When the eclipse-obd service is restarted while the collector is in the BT retry loop (car off, OBD adapter unreachable), the process does NOT respond to SIGTERM. Journal shows:

```
WARNING | pi.obdii.obd_connection | connect | Connection attempt 4/6 failed
INFO    | pi.obdii.obd_connection | connect | Retrying in 8s...
[systemd sends SIGTERM]
[no reaction from process]
systemd[1]: eclipse-obd.service: State 'stop-sigterm' timed out. Killing.
systemd[1]: Killing process 65446 (python) with signal SIGKILL.
```

Service ends up in "failed" state because SIGKILL was required. Restart cycle takes ~90s (default `TimeoutStopSec`) instead of ~1s.

## Root cause (hypothesis)

The retry loop likely uses a plain `time.sleep(backoff)` between attempts. Python's `time.sleep` in the main thread CAN be interrupted by signals, but:
- If the sleep is happening in a worker/poll thread (not the signal-receiving main thread), the thread won't wake on SIGTERM.
- If signal handlers are installed in the main thread that convert SIGTERM to a flag but the retry thread doesn't check the flag until the next loop iteration (post-sleep), the sleep-window is dead time.

US-211's resilience work focused on reconnect semantics; SIGTERM responsiveness wasn't in scope. This is a gap US-211 didn't address.

## Impact

- Every `systemctl restart eclipse-obd` during car-off state takes ~90s (wait for SIGKILL).
- Service ends up in "failed" state requiring `systemctl reset-failed` before next start (cosmetic but noisy).
- Deploy-pi.sh `step_restart_service` adds ~90s delay whenever Pi isn't connected to a running car.
- Worst case: if the orchestrator's power-down TRIGGER path (US-216) sends SIGTERM then expects quick shutdown, the 90s window may overlap with actual power loss and lose data.

## Options

1. **Replace `time.sleep(backoff)` with `threading.Event.wait(timeout=backoff)`** in the retry loop; set the event from a SIGTERM handler in main(). Main thread's signal handler flips the event; worker thread wakes immediately from its `wait()`.
2. **Shorten backoff cap to match TimeoutStopSec** — keeps `time.sleep` but bounds worst-case delay. Weaker fix; still leaves poll-tier code paths with the same issue.
3. **Configure systemd `TimeoutStopSec` shorter** (~15s) — makes SIGKILL happen faster but doesn't actually fix the problem; also bad for graceful shutdown on US-216 TRIGGER.

**Recommended**: Option 1. Uses the existing Python idiom for interruptible waits; symmetric with how US-211's ReconnectLoop should also handle shutdown signals (future US-216 interaction).

## Proposed story shape (when scheduled)

Size: S.
Scope: add a `shutdownEvent: threading.Event` (or reuse orchestrator's existing one if present); plumb into `ObdConnection.connect()` retry loop AND US-211 `ReconnectLoop` backoff; replace `time.sleep` with `event.wait(timeout)`. Main thread's SIGTERM handler sets the event. Test: mock SIGTERM mid-retry, assert process exits <2s.

## Related

- US-211 shipped the reconnect classifier + backoff schedule (Sprint 16) — same class-of-bug likely applies there.
- US-216 TRIGGER stage expects fast shutdown to call `systemctl poweroff` before battery dies — this TD may become load-bearing if US-216 triggers while collector is in retry sleep.
- TD-028 (ralph.sh promise-tag) closed in Sprint 16 US-207 — adjacent lifecycle cleanup territory.
