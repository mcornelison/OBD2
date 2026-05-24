# Finding: US-345 / F-8 — Fix Works, But maxTrailBytes Guard Blocks CLEAN_COMPLETE on First Post-Deploy Reboot

**Date**: 2026-05-21
**Severity**: HIGH (US-345 acceptance criterion #3 fails on strict reading; F-8 systemd fix itself is correct)
**Layer/Component**: `src/pi/diagnostics/boot_progress` (Python finalize script) + Pi shutdown sequence

## Summary

The F-8 fix (`Conflicts=shutdown.target` in `boot-progress-finalize.service`, US-345) is **correctly implemented and working** — the unit is now in the shutdown transaction and its ExecStop fires on clean reboot. **However**, the Python finalize script's `maxTrailBytes=65536` restart-loop guard tripped on first post-deploy reboot because the trail file had accumulated >64 KB while F-8 was broken (every boot wrote a RUNNING row; no boot ever wrote CLEAN_COMPLETE to bound it). Result: the breadcrumb was suppressed, the next boot's `startup_log` classified the prior shutdown as `wedged_before_poweroff` instead of clean, and US-345's bigDoD #3 criterion strictly fails.

This is **NOT a bug in F-8 itself**. F-8 did exactly what it was designed to do. The bug is an interaction between the (now correctly firing) finalize hook and a guard that was designed when no one had observed steady-state behavior of the finalize hook under unbounded trail growth.

## Evidence

State on `chi-eclipse-01`, 2026-05-21 11:46–11:48 CDT, captured by Argus during V0.27.16 IRL validation preconditions.

### Step-by-step reproducer

1. Pi running V0.27.15 powerwatch + V0.27.16 files on disk (see companion finding: `pm/issues/2026-05-21-from-tester-v0.27.16-deploy-did-not-restart-powerwatch-or-daemon-reload.md`).
2. Ran on bench: `ssh chi-eclipse-01 "sudo systemctl daemon-reload && sudo reboot"` to load V0.27.16 into memory.
3. Pi rebooted cleanly via systemd's standard reboot path.

### What the journal shows for the prior shutdown's finalize unit

```
May 20 20:30:21 systemd[1]: Starting boot-progress-finalize.service - Eclipse OBD shutdown breadcrumb finalizer (honest instrument)...
May 20 20:30:21 systemd[1]: Finished boot-progress-finalize.service - Eclipse OBD shutdown breadcrumb finalizer (honest instrument).
May 21 11:46:58 systemd[1]: Stopping boot-progress-finalize.service - Eclipse OBD shutdown breadcrumb finalizer (honest instrument)...
May 21 11:46:59 python[41230]: boot_progress trail at /home/mcornelison/Projects/Eclipse-01/data/boot_progress exceeds maxTrailBytes=65536 -- not appending CLEAN_COMPLETE (restart-loop guard)
May 21 11:46:59 systemd[1]: boot-progress-finalize.service: Deactivated successfully.
May 21 11:46:59 systemd[1]: Stopped boot-progress-finalize.service - Eclipse OBD shutdown breadcrumb finalizer (honest instrument).
```

ExecStop FIRED (proves F-8 Conflicts directive works). Script REFUSED to append CLEAN_COMPLETE because trail file >64 KB.

### What startup_log shows on the new boot

```
boot_short    recorded_at           prior_boot_clean  prior_boot_last_stage  prior_boot_reason
------------  --------------------  ----------------  ---------------------  ------------------------
750b6a1ca3e4  2026-05-21T16:47:18Z  0                 TRIGGER_ROW_WRITTEN    wedged_before_poweroff   <- NEW (post-fix)
9ac731408be8  2026-05-21T01:30:20Z  0                 RUNNING                crashed_during_operation <- pre-fix baseline
741393777485  2026-05-21T00:47:44Z  0                 RUNNING                crashed_during_operation
9b53b90dacae  2026-05-20T22:24:30Z  0                 RUNNING                crashed_during_operation
61580bb2dbc2  2026-05-20T21:12:55Z  0                 RUNNING                crashed_during_operation
903be0ce308f  2026-05-20T19:28:57Z  0                 RUNNING                crashed_during_operation
```

The classification shifted to a new failure mode (`TRIGGER_ROW_WRITTEN` / `wedged_before_poweroff`) that did not exist in the pre-fix baseline. That **is** proof that F-8 changed something — the finalize unit ran, wrote its TRIGGER_ROW_WRITTEN breadcrumb, but stopped short of CLEAN_COMPLETE.

### What the trail file looks like now

```
$ cat ~/Projects/Eclipse-01/data/boot_progress
{"boot_id":"750b6a1ca3e44101b76aac5c7d706ffb","stage":"RUNNING","ts":"2026-05-21T16:47:18Z","vcell":null}
```

106 bytes. The arm of the new boot reset it after reading the prior trail. (Or the finalize script truncated post-guard-trip; either way, it's now well under the 64 KB limit.)

## Impact

- **bigDoD #3 (US-345) strictly fails** on its acceptance criterion ("first reboot post-deploy startup_log shows prior_boot_clean=1 + last_stage=CLEAN_COMPLETE on clean shutdown"). The first post-deploy reboot did not write CLEAN_COMPLETE.
- **F-8 itself is implemented correctly.** The systemd unit's `Conflicts=shutdown.target` directive does pull boot-progress-finalize into the shutdown transaction; ExecStop does fire on clean shutdown. Atlas's design is sound.
- The acceptance gate has a hidden second dependency: it requires the trail file to be under 64 KB at shutdown time. On a Pi that's been running with broken F-8 for an extended period, that's not the case — the very condition F-8 fixes guarantees the trail grew unbounded.
- **Subsequent reboots from this point should succeed.** The trail is now 106 bytes; even with one RUNNING row per stage transition, it'd take many hundreds of boots to grow past 64 KB, and a CLEAN_COMPLETE write each shutdown bounds it.
- **Spool's earlier Finding C (12 boots today classified `crashed_during_operation`, V0.27.13-15 era)** had the same root cause + the same trail accumulation. F-8 was the structural fix; this guard is the unfinished half.

## Root Cause Analysis

The finalize script implements a defense-in-depth guard against a runaway restart loop appending CLEAN_COMPLETE forever (e.g., if the system was looping boot → finalize → boot → finalize quickly). The threshold (65,536 bytes) was chosen for that runaway scenario, not for a "trail accumulated for ~17 days with a broken finalize hook" scenario.

The interaction:
1. F-8 was broken from inception → boot-progress-finalize.ExecStop never ran → CLEAN_COMPLETE never appended.
2. Each boot's arm added a RUNNING row (~100 bytes).
3. Across ~600+ boots over the chain's lifetime, trail grew unbounded past 64 KB.
4. V0.27.16 deployed → trail still 64+ KB.
5. First reboot post-V0.27.16: F-8 fires, ExecStop runs, guard trips, no CLEAN_COMPLETE.

The latent assumption baked into the guard ("the trail file should be small in normal operation") was correct in design but never empirically validated because the very mechanism that bounds the trail (CLEAN_COMPLETE) was broken.

## Recommended Action

Two-line code fix, Sprint 41 or hotfix in V0.27.17 candidates:

**Option 1 (cleanest)** — make `--finalize` truncate-and-rewrite instead of append:
- Finalize doesn't need the prior trail to do its job; it just needs to write CLEAN_COMPLETE as the LAST line of the file.
- Truncate the file to just `{...,"stage":"CLEAN_COMPLETE",...}` on every clean shutdown.
- Removes the need for the maxTrailBytes guard entirely (the file can never grow past one row's worth).

**Option 2 (preserve audit trail)** — rotate the trail on finalize:
- On guard-trip, rotate the trail to `boot_progress.N` (where N is the next free integer) and start fresh, THEN write CLEAN_COMPLETE.
- Preserves the historical trail for forensic post-mortems.

**Option 3 (raise threshold)** — increase `maxTrailBytes` to a much larger value (e.g., 10 MB).
- Lowest-risk to the existing logic but doesn't fix the root cause.
- Eventually the trail still grows unbounded.

I recommend Option 1. The trail's only consumer is the arm-side classification logic on next boot, which only reads the LAST line. Earlier rows are dead data. Truncate-and-rewrite is correct semantics.

## Plus: a separate observation about the runsheet's §1 #34 INFO log check

Atlas's earlier note (`runsheet §1 #34 INFO log check unreachable (production logs WARNING+)`) is the canary for **both** this bug and the deploy-hygiene gap. If the runsheet's preflight asserted strict-equal on:
- the powerwatch startup banner line (proves new process loaded)
- the trail file size <64 KB (proves the next shutdown's CLEAN_COMPLETE write won't be guard-tripped)

then this entire class of false-negative would be caught at preflight rather than after the drive. Worth adding to the runsheet as a hard precondition either way.

## Note on US-345 Acceptance

Strict reading of bigDoD #3: **FAIL on first reboot**. The first post-deploy reboot did not show `prior_boot_clean=1` + `last_stage=CLEAN_COMPLETE`.

**Confirmed via reboot #2 — F-8 design is sound, only the first-reboot artifact is the issue.** I triggered a second bench reboot (per CIO direction) at 11:54 CDT. Pre-reboot trail size: 106 bytes (well under 64 KB). Result:

```
boot_short    recorded_at           prior_boot_clean  prior_boot_last_stage  prior_boot_reason
------------  --------------------  ----------------  ---------------------  -------------------
9541f4cf916a  2026-05-21T16:54:55Z  1                 CLEAN_COMPLETE         graceful           <- REBOOT #2 (PASS)
750b6a1ca3e4  2026-05-21T16:47:18Z  0                 TRIGGER_ROW_WRITTEN    wedged_before_poweroff
9ac731408be8  2026-05-21T01:30:20Z  0                 RUNNING                crashed_during_operation
```

The reboot #2 finalize journal is clean — no maxTrailBytes guard message, CLEAN_COMPLETE written successfully, prior_boot_clean=1 on next boot. **F-8 works correctly in steady-state.**

My recommendation to PM:
- **Classify US-345 as PASS-WITH-FINDING.** F-8 itself is empirically validated (reboot #2). The first-reboot artifact is a known and now-resolved boundary condition — once F-8 fires once and the arm resets the trail, the trail stays bounded forever after (each clean shutdown writes CLEAN_COMPLETE; each boot consumes the prior trail).
- The maxTrailBytes guard fix is **not chain-blocking**. It's a defense-in-depth improvement to harden against a similar latent class in the future. Suggest V0.27.17 or V0.28 hotfix.
- Strict reading of bigDoD #3 ("first reboot") would say FAIL — but the criterion was written without knowledge of the trail-accumulation interaction. CIO + Marcus's call on whether to amend the criterion's wording in a Sprint 41 retro, accept the PASS-WITH-FINDING, or hold the chain merge pending a guard hotfix.
- Subsequent in-car key-off cycles during the V0.27.16 drill will all write CLEAN_COMPLETE cleanly (trail is now 106 bytes and self-bounding from here forward), providing additional steady-state evidence.

— Argus
