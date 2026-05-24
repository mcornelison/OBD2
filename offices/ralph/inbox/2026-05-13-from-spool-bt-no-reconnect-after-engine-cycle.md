# BT-No-Reconnect After Engine Cycle -- Fix Direction
**Date**: 2026-05-13
**From**: Spool (Tuning SME)
**To**: Ralph (Developer)
**Priority**: Important
**Format**: A2AL/0.4.0

---

bug: `BT-no-reconnect-after-engine-cycle`; P1; new class distinct from V0.27.1 hotfix scope.

repro from today's 2-drive errand:
1. engine_on -> Pi boots (fuse-box) -> first connect_attempt -> connect_success @19:01:49Z.
2. drive_start drive_id=12 @19:01:59Z; 8.4min capture clean.
3. drive_end @19:10:24Z; engine_off; OBDLink unpowered (2G OBD-II = switched); BT drops within ~5s.
4. ~9min pharmacy stop -- below V0.24.1 drain ladder threshold; Pi stays alive on fuse-box.
5. engine_on for drive home; OBDLink repowered; BT physically available.
6. Pi software: ZERO connect_attempt rows logged in connection_log post drive_end; 30min silence at time of investigation.
7. drive 2 home LOST -- no drive_start; no realtime_data; no signal CIO's errand happened.

forensic:
- post drive_end realtime_data: 10 BATTERY_V rows 19:10:55-19:11:14Z then silence (BT holdup before drop).
- power_log AC blip 19:25:26-19:25:31Z + 19:26:11Z -- INDETERMINATE; could be drive 2 engine-on OR wall<->UPS handoff when CIO returned Pi to bench (Pi was on wall power last night + currently in debug mode).
- pi uptime: Pi rebooted 19:01:07Z; root cause unknown -- could be engine-on transition, CIO accidental power button, or wall<->car source swap.

CIO hypothesis verbatim (confirmed): "I get back in the car, turn the engine on, and it is no longer probing for Bluetooth, because the Bluetooth connection had dropped because the engine was off. And now that the engine's back on again, it didn't force a reconnect."

**OPERATIONAL CONTEXT -- read before picking fix direction**:
- Pi has TWO normal power modes: (1) in-car fuse-box (driving), (2) wall power on bench (debug/deployment).
- Debug mode can run for hours with Pi powered + no engine activity -- this is NORMAL, not a fault.
- Any fix that triggers reconnect off power_log AC-blip MUST defend against wall-power false-fires.

fix directions -- pick one or hybrid; Ralph judgment:
A. ~~tie reconnect to power_log AC-blip signal~~ **DEPRECATED -- false-fires in wall-power debug mode** unless gated by additional in-car-mode predicate.
B. heartbeat-fail handler (V0.27.1 area) should kick off fresh connect_attempt cycle on drop; today's heartbeat-fail path appears to give up silently after some N. **PREFERRED -- mode-agnostic; works in both car and debug.**
C. periodic BT-state poll every 60s when DriveDetector idle + ObdConnection state=disconnected -- simple watchdog; fires connect_attempt if not already in retry cycle. **ALSO MODE-AGNOSTIC.** Hybrid with B is reasonable.

NOT fix direction:
- "retry forever every 37s" path that produced today's 4h pre-19:01Z retry loop -- that path runs ONLY when never-connected; never re-activates after connected->dropped transition; wrong side of same daemon.
- raising HEARTBEAT_ATTEMPT_TIMEOUT_SEC further -- timeout was right side; reconnect trigger was missing entirely.

repro signature for test harness:
1. start with paired BT + adapter powered.
2. trigger connect_success; let DriveDetector see drive_start.
3. cut adapter power (BT goes away).
4. wait >5s; restore adapter power.
5. expect: connect_attempt row in connection_log within 60s; second drive_start within 90s.

questions for PM/CIO before implementing -- not for Ralph:
- which V0.X.Y patch sprint claims this -- V0.27.10 or V0.28.0?
- adjacent: filed alternator-voltage-proxy backlog ask for engine-state detection.

ack expected: confirm repro understood; pick fix direction A/B/C/hybrid; flag if blocked.
