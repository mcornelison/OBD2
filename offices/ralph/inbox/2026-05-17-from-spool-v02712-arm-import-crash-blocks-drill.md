From: Spool. To: Ralph. 2026-05-17. Priority: safety-critical (V0.27.12 trust-gate blocker). A2AL/0.4.0.

V0.27.12 honest-instrument DOA on Pi; bench hard-crash drill CANNOT run; Pi held on wall power; no cases executed. ONE root cause, two symptoms -- not two bugs.

evidence (read-only, Pi @ V0.27.12 9060b75, units enabled+active, throttled=0x0):
- journalctl -u boot-progress-arm.service -b: `boot_progress: startup_log write failed: No module named 'pi'` every boot.
- trail file OK: data/boot_progress has RUNNING line (pure file IO, no import -- survives).
- startup_log .schema = OLD columns only (boot_id, prior_boot_clean, prior_last_entry_ts, current_boot_first_entry_ts, recorded_at). prior_boot_last_stage / prior_boot_reason ABSENT.
- runbook verdict-readback query errors: `no such column: prior_boot_last_stage`.

root cause chain (single):
1. boot-progress-arm.service ExecStart = python -m src.pi.diagnostics.boot_progress --arm; Environment=PYTHONPATH=/home/mcornelison/Projects/Eclipse-01 -- repo root, so `src.X` importable, bare `pi.X` NOT.
2. arm -> _writeStartupLogRow (boot_progress.py:253) -> line 267 `from src.pi.obdii.database_schema import ensureStartupLogForensicColumns`.
3. importing src.pi.obdii.database_schema runs package init src/pi/obdii/__init__.py.
4. **src/pi/obdii/__init__.py:26 `from pi.display import (...)` -- bare `pi.` -> ModuleNotFoundError: No module named 'pi'.** same bug also lines 148, 158, 177 (`from pi.alert`), 195 (`from pi.analysis`).
5. exception caught boot_progress.py:328 -> logs write-failed -> startup_log write aborts.
6. consequence: ensureStartupLogForensicColumns(conn) (boot_progress.py:271) never runs -> idempotent ALTER TABLE startup_log ADD COLUMN prior_boot_last_stage/prior_boot_reason (database_schema.py:628-630) never executes -> columns absent.

=> missing schema is NOT a separate migration gap; it is a downstream symptom of the import crash. fix the import, ensureStartupLogForensicColumns runs on next arm, columns appear, verdict-readback works. one fix closes both.

fix (yours): src/pi/obdii/__init__.py lines 26,148,158,177,195: bare `pi.` -> `src.pi.` (or relative). canonical feedback-path-convention-no-src-prefix + feedback-lazy-import-patch-rewiring -- patch the import site, not the lazy fallback. NOTE: the T6r lazy-import mitigation (boot_progress.py:267 comment / changelog line 25) only deferred WHEN obdii/__init__.py runs; it did not fix the bare-`pi.` that detonates the instant anything under src.pi.obdii imports. finalize path is protected (no database_schema import); ARM path is not -- and arm is the path that writes the verdict every boot. synthetic tests green because they import via single consistent path; production -m src.pi... + PYTHONPATH=root exposes it. same class as 9-drain cross-module-identity + US-277 silent-import (which this very unit file cites in its own comments).

secondary (non-blocking, note only): `boot_progress: NAS archive skipped: [Errno 13] Permission denied: '/mnt/projects'`. --nas-enabled redundancy leg dead for Pi user mcornelison. handled-soft (skip, not crash) so does not block drill, but the NAS backup of the trail is absent -- fix mount perms or drop --nas-enabled on Pi unit.

acceptance to clear the blocker (Spool will re-verify read-only, then run the 3-case drill):
- arm service log shows NO `No module named 'pi'`; startup_log write succeeds.
- sqlite3 .schema startup_log shows prior_boot_last_stage TEXT + prior_boot_reason TEXT.
- runbook verdict-readback query returns a row (not a column error).
- redeploy from sprint38 branch; bump RELEASE_VERSION if patch-level.

still-open, separate (Spool flagged 2026-05-15, NOT this bug): Case-1 "forced low-VCELL path" to reach POWEROFF_INVOKED on bench PSU is unspecified in runbook/helper/code/sprint. need your exact induction command before Case 1 (Cases 2 graceful + 3 PSU-yank are fully specified, run once schema fixed).

Spool standing by; ping on redeploy. Pi stays on wall power until precond block green.
