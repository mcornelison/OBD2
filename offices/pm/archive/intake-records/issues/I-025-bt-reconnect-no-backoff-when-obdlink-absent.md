# I-025: BT reconnect loop has no backoff when OBDLink absent for extended periods

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Medium (P2)               |
| Status       | Open (V0.27.6 candidate)  |
| Category     | obdii / connection / power efficiency |
| Found In     | `src/pi/obdii/reconnect_loop.py` (heartbeat loop) + `src/pi/obdii/obd_connection.py` (`_performConnect`) |
| Found By     | Marcus (PM) 2026-05-11 (WiFi-drop debug session) |
| Related      | Caused Pi 5 WiFi instability (combo chip + BT activity + WiFi power_save mode); OS-side mitigation applied 2026-05-11 (disable wifi.powersave) |
| Created      | 2026-05-11                |

## Description

`eclipse-obd` service runs continuously on Pi. When Pi is away from the car (OBDLink LX out of BT range OR powered off), the reconnect loop fires every ~30-60 sec FOREVER. Empirical observation from journalctl 2026-05-11:

```
11:03:46 _performConnect | Connection attempt 1/6 failed | mac=00:04:3E:85:0D:FB | error=...
11:03:52 _performConnect | Connection attempt 2/6 failed | ...
11:03:59 _performConnect | Connection attempt 3/6 failed | ...
11:04:08 _performConnect | Connection attempt 4/6 failed | ...
11:04:21 _performConnect | Connection attempt 5/6 failed | ...
11:04:43 _performConnect | Connection attempt 6/6 failed | ...
11:04:56 _performConnect | Connection attempt 1/6 failed | ...   ← starts over immediately
```

No exponential backoff. Cadence stays at ~30-60s regardless of how many failures have already happened. Pi running at desk for 3+ hours = thousands of failed connect attempts that touch `/dev/rfcomm0` constantly.

## Impact

### Primary: Pi 5 WiFi instability (the actual user-visible symptom)

Pi 5's Broadcom BCM4345/6 WiFi+BT combo chip shares radio resources internally. With WiFi `power_save = ON` (Pi 5 default) + continuous BT reconnect activity:
- Combo chip is busy with BT
- WiFi misses beacons
- WiFi power_save kicks in
- Association breaks; "associating -> disconnected -> scanning" loop
- Eventually fails to re-associate cleanly until manual click-to-reconnect

CIO observed 2 WiFi drops in 3 hours 2026-05-11. OS-side mitigation applied same day: `wifi.powersave = 2` in `/etc/NetworkManager/conf.d/disable-wifi-powersave.conf` (Pi 5 best practice; addresses chip-level issue regardless of our code).

### Secondary: Power consumption

Continuous BT activity at fixed cadence wastes power when Pi is on UPS battery (e.g., post-V0.24.1 ladder firing, Pi staying on battery briefly before AC restoration). Not safety-critical but inefficient.

### Tertiary: Journal noise

Thousands of WARNING lines per day. Real BT-fault signal is buried in noise.

## Steps to Reproduce

1. Pi running eclipse-obd service
2. OBDLink LX powered off OR out of BT range
3. Observe `journalctl -u eclipse-obd -f` for 5 minutes
4. Count "_performConnect | Connection attempt N/6 failed" lines -- should see continuous 30-60s cadence with no backoff

## Expected Behavior

After N consecutive failures (e.g., 10 attempts = ~5-10 minutes of failed reconnects), reconnect loop should back off:
- Initial cadence: ~30-60s (current)
- After 10 consecutive failures: 2 minutes
- After 30 consecutive failures: 5 minutes
- Cap at 10-15 minutes between attempts
- Reset backoff on first successful connect

OR alternatively: stop attempting connect entirely once Pi has been disconnected for >N minutes; resume on a trigger (USB power-change event, manual SSH "kick" command, etc).

## Actual Behavior

Fixed cadence regardless of failure count. Heartbeat at `HEARTBEAT_ATTEMPT_TIMEOUT_SEC = 30.0` (V0.27.1) fires every tick forever.

## Resolution (V0.27.6 candidate -- US-325)

Add exponential backoff in `runReconnectHeartbeat`. Concrete shape:

- Track consecutive failure count in heartbeat-loop state
- Compute next-attempt interval: `min(30 * (2 ** min(failures, 5)), 900)` — exponential up to 15 min cap
- Reset count to 0 on successful connect (`isConnectedFn()` returns True)
- Existing INFO heartbeat log line gains `consecutive_failures=N` + `next_attempt_in=Xs` fields

Acceptance test pattern: synthetic loop with mocked-failing `connectFn` runs 30 heartbeat ticks; assert the time interval between attempts grows per the backoff formula; assert resets to base interval after a successful connect.

## Acceptance Criteria

- [ ] Pre-flight audit: rg `HEARTBEAT_ATTEMPT_TIMEOUT_SEC|runReconnectHeartbeat|tickIntervalSec` src/pi/obdii/ -- map current cadence logic
- [ ] Exponential backoff implemented in `runReconnectHeartbeat`; formula configurable via constants (back-compat for existing tests)
- [ ] Heartbeat log line gains `consecutive_failures` + `next_attempt_in_seconds` fields
- [ ] Successful connect resets failure count; cadence returns to base interval
- [ ] Synthetic regression test: 30-tick mocked-failure run; assert intervals follow backoff formula; would FAIL pre-fix (current code uses fixed cadence)
- [ ] Real-world validation gate: post-V0.27.6 deploy, leave Pi running with OBDLink unreachable for 30 min; journal shows decreasing attempt frequency (not fixed 30-60s)

## Cross-references

- V0.27.1 hotfix US-301 (10s heartbeat + boot canary; this story adds back-off ON TOP of the heartbeat)
- V0.27.4 US-315 (sync UPDATE propagation; orthogonal but same OBDLink-disconnected-Pi scenarios)
- OS-side mitigation 2026-05-11: `/etc/NetworkManager/conf.d/disable-wifi-powersave.conf` ALREADY applied (Pi 5 wifi.powersave = 2) — Fix #1 for the WiFi-drop symptom; this story is Fix #2 (reduce BT activity at the source)
- BL-014 harness write-perm gate on `.claude/commands/` (filed Sprint 31; OS / harness territory; cross-reference for "OS-level config can fix things our code is triggering")

## Source

CIO 2026-05-11 WiFi-drop debug session. Pi in garage / car had WiFi drops; brought to desk; same pattern. Investigation revealed Pi 5 default `wifi.powersave=ON` + our continuous BT reconnect activity = combo chip starvation.
