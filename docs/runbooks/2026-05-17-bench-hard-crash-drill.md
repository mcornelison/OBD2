# Bench Hard-Crash Drill — Layer-4 IRL Trust Gate

**Date:** 2026-05-17 · **Sprint:** 38 / V0.27.12 · **Owner:** CIO (operator-run; not automatable)
**Subject:** the honest boot-progress instrument (`src/pi/diagnostics/boot_progress.py` + `boot-progress-arm.service` + `boot-progress-finalize.service`)

> ⚠️ **GATE — read this first.** The honest boot-progress instrument is **NOT TRUSTED** until **all three required cases below pass on real hardware**. Green CI is necessary but not sufficient (synthetic tests prove the author's intent; only this drill proves fdatasync-survives-a-real-yank and the systemd `ExecStop` ordering on the actual Pi). Until this gate is green, **Bug 1 (the I/O-storm shutdown failure) work does NOT begin** — that is the deliberate "truth first" sequencing this whole effort exists to restore: prove the instrument honest, then fix the machine measured against it.

This drill is a **human/CIO action**. The helper `scripts/bench_crash_drill.sh <STAGE>` only *guides* the steps and *reads back* the verdict read-only — it never induces the crash. The operator induces the crash by hand (sysrq or PSU yank).

---

## Preconditions

1. **Pi on a BENCH PSU**, not the slow UPS battery. The whole point is a fast, repeatable, deterministic loop (~2 min) — not a 20-minute battery drain.
2. **V0.27.12 deployed from the sprint branch:**
   ```
   bash deploy/deploy-pi.sh        # installs boot-progress-finalize.service + boot-progress-arm.service
   ```
3. **Both units enabled** (deploy does this; verify):
   ```
   ssh mcornelison@chi-eclipse-01 "systemctl is-enabled boot-progress-arm.service boot-progress-finalize.service"
   ```
   Expect: `enabled` / `enabled`.
4. SSH to `chi-eclipse-01` (10.27.27.28) reachable from the drill host.

**Verdict read-back command** (used after every case — newest `startup_log` row = the boot that just came up *after* the crash, carrying the verdict for the boot that crashed):
```
ssh mcornelison@chi-eclipse-01 "sqlite3 /home/mcornelison/Projects/Eclipse-01/data/obd.db \
  \"SELECT boot_id,prior_boot_clean,prior_boot_last_stage,prior_boot_reason \
    FROM startup_log ORDER BY recorded_at DESC LIMIT 1;\""
```

Expected reasons are taken verbatim from `boot_progress._VERDICT_BY_STAGE` — do not paraphrase.

---

## The 3 required acceptance cases (spec §4.6)

### Case 1 — Drain-26-shape hard crash (the regression this instrument exists to catch)

This is the exact shape that lied for 11 days under the old canary: the shutdown sequence reaches `POWEROFF_INVOKED` and the box dies *before* `CLEAN_COMPLETE` is ever written.

- **Setup:** confirm the trail is armed for the current boot (`scripts/bench_crash_drill.sh POWEROFF_INVOKED` step 1, or `ssh … "tail -n1 …/data/boot_progress"` → expect a `RUNNING` line). Drive the ladder to TRIGGER (drain ramp or a forced low-VCELL path) so the trail advances to `POWEROFF_INVOKED`.
- **Induce (operator, on the Pi, right after POWEROFF_INVOKED, before any clean completion):**
  ```
  echo b | sudo tee /proc/sysrq-trigger     # immediate reboot, NO shutdown — simulates a hard crash
  ```
- **Read back** with the command above after the Pi reboots.
- **EXPECT (PASS):** `prior_boot_clean=0`, `prior_boot_last_stage=POWEROFF_INVOKED`, `prior_boot_reason=poweroff_invoked_never_returned`.
- **FAIL** = any `prior_boot_clean=1` here. That is the I-037 false-positive resurfacing — the instrument is NOT honest; stop, do not proceed to Bug 1.

### Case 2 — Real graceful poweroff

Proves the finalizer `ExecStop` actually runs at the end of a real systemd shutdown and writes the one `CLEAN_COMPLETE` rung.

- **Setup:** confirm armed (trail has a `RUNNING` line for the current boot).
- **Induce:**
  ```
  ssh mcornelison@chi-eclipse-01 "sudo systemctl poweroff"
  ```
  Let it fully power off; then power the bench PSU back on and let the Pi cold-boot.
- **Read back.**
- **EXPECT (PASS):** `prior_boot_clean=1`, `prior_boot_last_stage=CLEAN_COMPLETE`, `prior_boot_reason=graceful`.
- **FAIL** = `prior_boot_clean=0`/`poweroff_accepted_unfinalized` (finalizer didn't run — check `boot-progress-finalize.service` ordering / PYTHONPATH) or any other non-`graceful` result. A systematic finalizer failure here is *loud and safe* (every clean shutdown looks dirty) — that's the designed-safe direction, but it still fails the gate and must be fixed.

### Case 3 — Drive-time PSU yank (no ladder)

Proves a crash during ordinary operation (engine on, no low-battery ladder) is recorded as a crash, not silently clean.

- **Setup:** Pi running normally, no drain ladder active (trail at `RUNNING` only).
- **Induce:** physically cut the bench PSU. Restore power; let the Pi cold-boot.
- **Read back.**
- **EXPECT (PASS):** `prior_boot_clean=0`, `prior_boot_last_stage=RUNNING`, `prior_boot_reason=crashed_during_operation`.
- **FAIL** = `prior_boot_clean=1`. A crash with no graceful proof must never read clean.

---

## PASS/FAIL recording table

| Case | Date | boot_id (new boot) | observed `(clean, last_stage, reason)` | PASS/FAIL | Notes |
|------|------|--------------------|----------------------------------------|-----------|-------|
| 1 — Drain-26 hard crash | | | | | expect `(0, POWEROFF_INVOKED, poweroff_invoked_never_returned)` |
| 2 — graceful poweroff | | | | | expect `(1, CLEAN_COMPLETE, graceful)` |
| 3 — drive-time PSU yank | | | | | expect `(0, RUNNING, crashed_during_operation)` |

---

## Gate decision

- **All 3 PASS** → the instrument is trusted. It becomes the measuring stick: proceed to deploy + **one real drain** to read the *verified* Bug-1 rung off `prior_boot_reason`, then begin Bug-1 design grounded in that fact.
- **Any FAIL** → the instrument is NOT trusted. Do **not** start Bug-1 work. File the failing case (observed row + which rung) and fix the instrument; re-run the full 3-case drill from scratch.

Reason strings are the single source of truth in `src/pi/diagnostics/boot_progress.py::_VERDICT_BY_STAGE` — if a future change to that dict alters them, update this runbook in lockstep (the same drift discipline this instrument enforces in code).
