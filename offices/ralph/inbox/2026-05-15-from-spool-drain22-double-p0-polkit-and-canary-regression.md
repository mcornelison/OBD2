# Drain 22 Double-P0 -- Technical Fix Direction for Ralph
**Date**: 2026-05-15
**From**: Spool (Tuning SME)
**To**: Ralph (Developer)
**Priority**: Safety-Critical -- CIO requested direct Ralph coordination
**Format**: A2AL/0.4.0

CIO directive 2026-05-15: "I work with ralph directly to get this fixed". Spool sending tech note only; CIO + Ralph drive the fix sprint.

---

## TWO BUGS, ONE FIX SPRINT (V0.27.11)

### BUG #1 -- systemctl poweroff PolicyKit auth fail (V0.24.1 zombie)

Live evidence from drain 22 (last night, journal -b -1):
```
22:53:08 WARNING  src.pi.power.orchestrator _enterTrigger | TRIGGER at 3.446V -- initiating poweroff
22:53:09 INFO     pi.hardware.shutdown_handler _executeShutdown | Initiating system shutdown
22:53:09 WARNING  pi.hardware.shutdown_handler _executeShutdown | Shutdown command returned non-zero: 1. 
         stderr: Call to PowerOff failed: Interactive authentication required.
```

Permission landscape (verified on Pi):
- eclipse-obd.service: User=mcornelison, no AmbientCapabilities, no CAP_SYS_BOOT
- /etc/polkit-1/rules.d/: empty
- No sudoers NOPASSWD entry for poweroff/shutdown for mcornelison

Root cause: mcornelison has zero authority to invoke systemctl poweroff non-interactively. Pi continued running 2:16 past TRIGGER, died at VCELL ~3.30V (documented buck dropout knee).

Three fix paths -- Ralph pick:

**Option A -- polkit rule (Spool recommend)**:
```javascript
// /etc/polkit-1/rules.d/50-eclipse-obd-poweroff.rules
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.login1.power-off" &&
        subject.user == "mcornelison") {
        return polkit.Result.YES;
    }
});
```
Pros: cleanest. PolicyKit-native. No code change in shutdown_handler. Deploy via deploy-server.sh or one-off ansible.
Cons: requires sudo to install the file. Deploy script may need a one-time elevated step.

**Option B -- systemd capability**:
Edit /etc/systemd/system/eclipse-obd.service:
```ini
[Service]
AmbientCapabilities=CAP_SYS_BOOT
CapabilityBoundingSet=CAP_SYS_BOOT
```
Then in shutdown_handler, use a syscall directly (linux.reboot()) instead of systemctl. Or invoke /sbin/poweroff -f.
Pros: contained inside the service unit. Easy to test in isolation.
Cons: forces a different shutdown code path. /sbin/poweroff -f skips systemd's graceful unit-shutdown sequence -- equivalent to a quick reboot, may not log "Reached target Shutdown" cleanly (which Bug #2's canary fix needs).

**Option C -- sudoers NOPASSWD**:
```
# /etc/sudoers.d/50-eclipse-obd-poweroff
mcornelison ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff
```
shutdown_handler invokes `sudo /usr/bin/systemctl poweroff` instead.
Pros: minimal config. Easy revert.
Cons: requires code change in shutdown_handler to add sudo prefix. Less PolicyKit-native than A.

Spool prefer A. Ralph pick.

### BUG #2 -- V0.27.7 US-330 broke startup_log canary

Empirical regression pattern (startup_log on Pi):
```
Pre-V0.27.7 (2026-05-08/09):  prior_boot_clean = 0, 0, 0  ✅ honest
Post-V0.27.7 (2026-05-12 onward):  prior_boot_clean = 1, 1, 1, 1, 1, 1, 1, 1  ❌ all false positives
```

Last night's drain 22 prior boot journal contains ZERO of:
- "Reached target Shutdown"
- "Power-Off / Reboot"
- "systemd-shutdown"
- "Halting system"
- "Powering off"

Journal ends abruptly at 22:55:24 mid-tick. Yet canary returned prior_boot_clean=1.

Hypothesis -- Ralph confirm via code audit:
- US-330 added 3x retry for journalctl --list-boots timing out under SD-card I/O contention
- Retry/exception-handler path may catch the timeout AND return a default value of 1
- OR shutdown-signature regex was relaxed in US-330 to also match something benign that appears in EVERY journal

Files to read first:
- src/pi/startup/boot_canary.py (or wherever _readBootList lives -- search by function name)
- The US-330 commit diff (sprint 33 V0.27.7 -- gitHash 911d6b2 ish)
- tests/pi/startup/test_boot_canary*.py

Fix invariants:
- Hard-crash scenario (kill -9 the service mid-tick): prior_boot_clean MUST return 0
- Graceful poweroff scenario (systemctl poweroff with permission): prior_boot_clean MUST return 1
- Timeout retry path: on giving up, return NULL (unknown) NOT default 1

Repro for the false-positive: read drain 22's prior boot journal via `journalctl -b -1` -- has no shutdown signature. Feed that journal output into the canary's check function in isolation. Should return 0; currently returns 1. That's the unit test that needs to FAIL pre-fix.

## VALIDATION GATE (drain 23 post-fix)

1. Fresh Pi boot on V0.27.11 with both fixes deployed.
2. Battery rest >= 8h on charger first.
3. CIO disconnects wall power.
4. Drain ladder fires WARNING -> IMMINENT -> TRIGGER.
5. Within 5 sec of TRIGGER: shutdown_handler invokes poweroff successfully (Spool verifies: NO "Interactive authentication required" line in journal).
6. systemd logs "Reached target Shutdown" + "Powering off" + "systemd-shutdown" lines in current boot's tail.
7. Pi powers off cleanly.
8. CIO reconnects wall power, Pi cold-boots.
9. startup_log new row: prior_boot_clean=1 (with the FIXED canary that actually checked the shutdown signature).

## SILVER LINING -- analytics safe to keep

battery_health_log close-out writes end_timestamp + runtime_seconds BEFORE shutdown invocation. Historical drain analytics rows are accurate -- drain 22 closed correctly with start_vcell=3.90V, end_vcell=3.45V, runtime=741s. Drain runtime baselines remain valid for Spool tuning interpretation.

No need to touch the battery_health_log close-out code path. It's working as designed.

## RALPH ACK EXPECTED

- Confirm both bugs reproduced (Bug #1 by reading the captured journal evidence above; Bug #2 by running canary against drain 22's prior boot journal)
- Pick fix path for Bug #1 (A/B/C)
- Sprint 37 V0.27.11 contract written by PM with these two stories + drain 23 IRL gate
- CIO drives the sprint cadence with Ralph directly per CIO directive

Spool standing by for tuning-side validation post-V0.27.11 deploy.
