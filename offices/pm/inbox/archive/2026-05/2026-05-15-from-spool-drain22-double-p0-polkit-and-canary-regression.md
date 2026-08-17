# Drain 22 Post-Mortem: Double P0 -- PolicyKit Auth + Canary False-Positive Regression
**Date**: 2026-05-15
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Safety-Critical -- chain-blocking
**Format**: A2AL/0.4.0

---

## CHAIN STATUS

V0.27 chain merge gate -> RED on drain side. Drain 22 (last night) hard-crashed despite TRIGGER firing correctly. Two P0 bugs in the same chain; one masked the other for 11 days.

## BUG #1 -- I-036 (proposed) -- systemctl poweroff PolicyKit auth fail

Empirical evidence captured live from drain 22 journal:
- 22:53:08 _enterTrigger | PowerDownOrchestrator: TRIGGER at 3.446V -- initiating poweroff
- 22:53:09 _executeShutdown | Initiating system shutdown
- 22:53:09 _executeShutdown | Shutdown command returned non-zero: 1. stderr: Call to PowerOff failed: Interactive authentication required.

eclipse-obd.service runs as User=mcornelison. NO AmbientCapabilities=CAP_SYS_BOOT in unit file. /etc/polkit-1/rules.d/ empty. NO sudoers NOPASSWD for poweroff. mcornelison has zero authority to invoke systemctl poweroff non-interactively.

Pi continued running 2:16 past TRIGGER on residual battery. Died at VCELL ~3.30V (buck dropout) -- documented hard-crash signature from drain-7-baseline. Journal ends abruptly at 22:55:24 mid-tick. No shutdown record of any kind.

**This bug has existed since at least V0.24.1 deploy (2026-05-04).** All drains 10-22 likely hard-crashed; we declared success because Pi went offline + canary lied to us about cleanliness.

## BUG #2 -- I-037 (proposed) -- V0.27.7 US-330 introduced canary false-positive regression

startup_log empirical pattern:
- Pre-V0.27.7 (2026-05-08/09): prior_boot_clean = 0, 0, 0 -- canary was HONEST
- Post-V0.27.7 (2026-05-12 onward): prior_boot_clean = 1 in every record -- canary LIES

The US-330 race-guard fix (3x retry for journalctl --list-boots timing out under SD-card I/O contention) apparently broke the canary's heuristic. It now returns 1 unconditionally even when prior-boot journal contains zero shutdown signature.

Tonight's smoking gun: drain 22 prior boot journal ends mid-tick with no "Reached target Shutdown", no "Power-Off", no "systemd-shutdown", no "Halting", no "Powering off" -- yet startup_log shows prior_boot_clean=1.

**This bug has existed since V0.27.7 deploy (~2026-05-12).** Every "drain validated" claim post-V0.27.7 was unverified.

## INTERACTION -- WHY THIS WENT UNDETECTED 11 DAYS

Bug #2 was the enabler. With canary lying, every drain looked "clean" by automated check. Bug #1's PolicyKit denial only became visible last night because Spool grep'd the actual journal for shutdown signature lines AND captured the live "Interactive authentication required" stderr from the prior boot before Pi went offline.

## SILVER LINING -- analytics not corrupted

battery_health_log close-out writes end_timestamp + runtime_seconds BEFORE shutdown invocation. So drain_event_id=22 closed correctly (end_timestamp=03:53:08Z, runtime_seconds=741) despite shutdown later failing. Historical drain runtime baselines remain valid for tuning analytics. Drain 22 specifically: start_vcell 3.90V, end_vcell 3.45V, WARNING->TRIGGER 12:21 -- within historical envelope.

## PROPOSED V0.27.11 SCOPE

Two stories minimum:

US-341 -- I-036 -- Fix systemctl poweroff permission for eclipse-obd.service
- Option A (Spool recommend): polkit rule /etc/polkit-1/rules.d/50-eclipse-obd-poweroff.rules allowing user mcornelison to power-off without interactive auth. JS rule recognizes user + org.freedesktop.login1.power-off action -> polkit.Result.YES.
- Option B: AmbientCapabilities=CAP_SYS_BOOT on eclipse-obd.service unit + Pi-side python invokes /sbin/reboot via direct syscall.
- Option C: sudoers NOPASSWD for /sbin/poweroff -f for mcornelison + handler invokes via sudo.
- Real-world gate: drain 23 post-fix. Pi powers off within 5s of TRIGGER. Prior boot journal contains "Reached target Shutdown" or "Powering off" line.

US-342 -- I-037 -- Fix startup_log canary false-positive
- Audit US-330 race-guard logic. Determine why _readBootList retry path returns prior_boot_clean=1 when no shutdown signature found.
- Hypothesis (pending Ralph diagnosis): retry path catches the timeout exception + returns default value of 1 OR shutdown-signature regex was changed in US-330 to match too permissively.
- Real-world gate: drain 23 post-fix. Hard-crash scenario (forcibly kill -9 the service) MUST return prior_boot_clean=0. Graceful poweroff MUST return 1.

US-343 (optional) -- Backfill audit of historical drain canary records
- Re-examine startup_log + journalctl boot-archive for drains 10-22.
- For each: did prior boot journal contain shutdown signature, or end mid-tick?
- Output: corrected interpretation of which drains were ACTUALLY graceful vs hard-crash since 2026-05-04.
- Spool willing to do this manually if Ralph time-constrained -- not blocking.

## CHAIN MERGE GATE IMPACT

V0.27 chain CANNOT merge to main until V0.27.11 fixes BOTH bugs and drain 23 validates green with the corrected canary.

Re-running drain 23 needs:
- Battery rest >= 8h on charger AND
- V0.27.11 deployed AND
- Spool verifies polkit rule + canary heuristic via bench mock before real drain

## CIO COORDINATION NOTE

CIO directive 2026-05-15 morning: "I work with ralph directly to get this fixed". Spool filing parallel technical note to Ralph with fix direction. PM tracking via this note. PM does NOT need to mediate -- CIO + Ralph will coordinate the V0.27.11 sprint contract directly.

PM action items:
1. File I-036 + I-037 as P0 issues; both reference this Spool note as source.
2. Create V0.27.11 sprint shell with placeholders for US-341 + US-342 (+ optional US-343).
3. Update V0.27 chain status: chain merge BLOCKED pending V0.27.11.
4. Notify tester re: any "drain validated" smoke tests in test harness MAY be passing on false-positive canary -- need test re-audit.
