# BL — Stale `.git/index.lock` blocks all commits (US-404 + US-403 uncommitted)

**Date**: 2026-06-30
**From**: Ralph (Rex, Agent 1)
**To**: Marcus (PM) / CIO
**Priority**: Important — blocks sprint commit progress
**Severity**: Infra (shared-checkout race), not a code defect
**Status**: ✅ **RESOLVED 2026-06-30 (Marcus/PM)**

## Resolution (Marcus, PM — 2026-06-30)

Diagnosis confirmed Ralph's: the lock was **0 bytes, mtime 09:10:30 (~1h45m old), with no live `git` process from that era** (the only `git.exe` PIDs were seconds-old diagnostics; the rest were Logi**t**ech substring false-matches). A live `git commit` writes the new index *into* `index.lock` before renaming — a 0-byte lock has no pending data, so removal loses nothing. Guarded-removed it (only-if-still-0-byte). Then landed the blocked work, office-scoped:
- **`1383158`** — US-403 + US-404 (entangled across shared files → single landing commit, Co-Authored-By Rex)
- **`3191cba`** — PM Sprint-50 PRD groom · **`a28b71a`** — lock-blocked Atlas notes + this blocker
All pushed to `sprint/sprint49-V0.29.3`. Ralph is unblocked: **8/9 code-complete**, US-405/406/407 remain. CIO re-runs `ralph.sh` to resume.

---


## Symptom

`git add` / `git commit` fail on the shared checkout with:

```
fatal: Unable to create '//chi-nas-01/PPS-Projects/O/OBD2v2/.git/index.lock': File exists.
Another git process seems to be running in this repository, or the lock file may be stale
```

## Evidence it is STALE (not a live op)

- `.git/index.lock` mtime = **09:10:30**; observed unchanged at **10:08** and again on re-stat — **~58 minutes old, 0 bytes, timestamp not advancing**.
- git holds `index.lock` for the whole of one operation (mtime fixed at start); a 58-minute "operation" is not running — it died.
- It has blocked **two sessions**: the prior **US-403** work (`src/pi/splash/service_control.py`, `deploy/polkit-rules/51-eclipse-service-control.rules`, `states_http_server.py`, dashboard files) shows as **uncommitted/untracked** in the working tree despite `sprint.json` marking US-403 `passes:true` — its commit never landed. **US-404** is now in the same state.

## Why I did NOT force-clear it myself

1. **Harness gate** — the tool environment treats `.git/index.lock` as a sensitive file and blocks `rm`.
2. **Handbook §13 Rule 4** — "retry-on-lock, never force … never delete it while a git process is running." On the shared SMB checkout I cannot rule out a concurrent/cross-machine git process (the process-list commands are not on the headless allow-list), so forcing the delete risks corrupting another agent's in-flight commit. Retrying (done ~6×) does not clear it.

## Requested action (CIO / PM)

1. Confirm no `git` process is genuinely running (any agent/host on the share), then remove the stale lock:
   `rm -f //chi-nas-01/PPS-Projects/O/OBD2v2/.git/index.lock`
2. Commit the **already-complete + fully-green** US-404 work (PM owns commits):
   ```
   git add \
     src/pi/splash/dtc_severity_table.py src/pi/splash/dtc_emitter.py \
     src/pi/obdii/dtc_logger.py src/pi/obdii/orchestrator/event_router.py \
     specs/architecture.md \
     tests/pi/splash/test_dtc_severity_table.py tests/pi/splash/test_dtc_emitter.py \
     tests/pi/splash/test_states_http_dtc_endpoint.py \
     tests/pi/obdii/test_dtc_logger_keyon.py tests/pi/orchestrator/test_keyon_dtc_dispatch.py \
     tests/pi/obdii/test_data_logger_restart_on_restore.py \
     offices/ralph/sprint.json offices/ralph/ralph_agents.json offices/ralph/progress.txt \
     offices/pm/blockers/BL-stale-index-lock-blocks-commit.md
   git commit -m "feat: [US-404] DTC KOEO read + dtc emitter + P1xxx severity loader (drive_id=NULL explicit, A-9)"
   ```
3. Also commit (or have the relevant office commit) the still-uncommitted **US-403** artifacts so that work isn't lost on the next branch switch.
4. Until the lock is cleared, **no further Ralph iteration can commit** — `ralph.sh` will stall on the same lock.

## Status of the blocked work

US-404 is **code-complete and verified**: all 30 new/scoped tests green (severity-table 6, emitter 8, states-http /dtc 3, KOEO logger 4, KOEO dispatch 9) + 0 regressions across `tests/pi/splash` + `tests/pi/orchestrator` + the dtc logger suites; `ruff` clean; `specs/architecture.md` Rule-10 updated. The only thing outstanding is the git commit, which this blocker prevents.
