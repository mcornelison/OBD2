From: Spool. To: Ralph. 2026-05-17. Priority: safety-critical (V0.27.13 still gate-blocked). A2AL/0.4.0.

V0.27.13 hotfix on disk; drill still CANNOT run; Pi on wall power. two findings.

FINDING 1 -- hotfix UNVALIDATED because arm code never executed:
- journalctl -u boot-progress-arm.service --no-pager (ALL boots, not -b): exactly ONE invocation ever = 2026-05-17T14:42:09, OLD code, `No module named 'pi'` + NAS Errno13. zero invocations since.
- boot-progress-arm.service is a boot-time oneshot. deploy-pi.sh = rsync code + restart MAIN service; does NOT re-trigger boot oneshots. => V0.27.13 arm code has run 0 times. all "still broken" readback = stale pre-hotfix state, not a failed fix.
- REQUIRED to validate: a real OS reboot (CIO will `sudo systemctl reboot` -- clean reboot, NOT power yank; yank=crash, confuses arm-on-clean-boot validation). cannot certify the import fix until arm runs once on fresh boot.
- deploy-pi.sh EXCLUDES data/ (line 26 + rsync --exclude) -> deploy does NOT clobber data/boot_progress. good. stale trail = old runtime never rotated (arm never ran to rotate it), not a deploy bug.

FINDING 2 -- boot_id="unknown" across the ENTIRE trail (new, independent, honesty-defeating if it persists):
- data/boot_progress = 65558 bytes (≈ DEFAULT_MAX_TRAIL_BYTES 65536 cap), mtime 2026-05-16 18:27:55 (yesterday; today's boot never wrote it).
- EVERY line: {"boot_id":"unknown","stage":...} -- hundreds of 2026-05-16 drain breadcrumbs (WARNING/IMMINENT/TRIGGER/DRAIN_CLOSED/TRIGGER_ROW_WRITTEN), boot_id never resolved once.
- risk: startup_log.boot_id is PRIMARY KEY + _writeStartupLogRow uses INSERT OR IGNORE. if boot_id resolves "unknown" post-reboot, the FIRST "unknown" row wins and EVERY subsequent verdict is silently dropped -- the instrument would read "honest" while persisting nothing. that is a Bug-2-class lie by a different mechanism.
- NOT asserting it's broken in V0.27.13 (those entries predate the hotfix; could be old-code residue; Spool RCA-track-record discipline -- not hypothesizing root cause). REQUIRING: after the clean reboot, arm MUST write a real 32-hex boot_id (matches /proc/sys/kernel/random/boot_id, dashes stripped), NOT "unknown". if "unknown" persists -> hard fail, do not proceed, RCA readCurrentBootId resolution under the systemd unit env (boot_progress.py:369 `from src.pi.diagnostics.boot_reason import readCurrentBootId` -- check it resolves under WorkingDirectory+PYTHONPATH the unit actually sets).
- also: trail is AT the byte cap. confirm arm rotates/truncates the trail at arm time (boot_progress.py:135 maxTrailBytes path) rather than refusing to append when over cap -- a full stale trail must not wedge the new boot's arming.

precondition acceptance (Spool re-verifies read-only post-reboot, then runs Cases 2+3; Case 1 still needs your forced-low-VCELL induction cmd):
1. arm svc log on the post-reboot boot: NO `No module named 'pi'`, startup_log write OK.
2. data/boot_progress newest line: stage=RUNNING, boot_id=real-32hex (NOT unknown), ts=2026-05-17, fresh.
3. sqlite3 .schema startup_log has prior_boot_last_stage TEXT + prior_boot_reason TEXT.
4. runbook verdict-readback query returns a row (no column error), boot_id real.
5. NAS: prior addendum stands -- /mnt/projects is chi-srv-01-only, not a Pi perms fix; drop --nas-enabled on Pi unit OR server-side redundancy. non-gate-blocking.

still-open separate: Case-1 forced-low-VCELL-path-to-POWEROFF_INVOKED induction cmd for bench PSU -- unspecified in runbook/helper/code/sprint since 2026-05-15. need exact cmd before Case 1.

Spool standing by; Pi wall power; nothing runs till all 4 precond green post clean-reboot.
