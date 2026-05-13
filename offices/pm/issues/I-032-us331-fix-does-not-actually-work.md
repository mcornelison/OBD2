# I-032: V0.27.8 US-331 fix for the deploy-server.sh Step 4.6 backfill does NOT actually work -- same MSYS path-mangle error survives the deploy

| Field | Value |
|---|---|
| Severity | Medium (P2) |
| Status | RESOLVED 2026-05-13 -- V0.27.9 US-337 fixed it; post-V0.27.9 deploy IRL gate green (Step 4.6 ran cleanly, --count-stranded returned 0, no-op as designed) |
| Category | sync / deployment / scripts |
| Found In | `scripts/backfill_server_battery_health_log_stranded.py` (modified by V0.27.8 US-331 -- but the fix doesn't trigger in practice) + `deploy/deploy-server.sh` Step 4.6 |
| Found By | Marcus (PM) 2026-05-13 -- observed during the V0.27.8 sprint-deploy, then re-tested with the Pi fully reachable + the V0.27.8 fix deployed; the error is byte-identical to the V0.27.7 failure |
| Related | I-031 (the parent bug US-331 was supposed to fix); US-331 (the V0.27.8 attempted fix that doesn't actually trigger); B-076 (the one-time backfill could ride that epic's cleanup step) |
| Created | 2026-05-13 |

## Description

V0.27.8 US-331 shipped a fix for I-031 (the deploy-server.sh Step 4.6 backfill failing in both deploy run-contexts: Windows Git-Bash MSYS path-mangle + ssh-to-self host-key on chi-srv-01). Ralph's close notes claim the fix lands MSYS_NO_PATHCONV-style guarding for the remote-sqlite3 invocation + localhost detection in `loadServerCreds`.

**But the V0.27.8 deploy 2026-05-13 reproduced the IDENTICAL MSYS-mangle error**, byte-for-byte, with the Pi fully reachable + the V0.27.8 fix deployed to both server + repo:

```
--- Step 4.6: Backfilling stranded battery_health_log rows (US-327) ---
Found 5 stranded battery_health_log row(s); running backfill...
ERROR: reading Pi-side battery_health_log failed: Error: unable to open database
  "C:/Program Files/Git/home/mcornelison/Projects/Eclipse-01/data/obd.db": unable to open database file
WARN: backfill did not complete (Pi unreachable?); rows stay stranded -- safe to retry next deploy.
```

Same shell as the I-031 reproduction (CIO's Windows Git-Bash on chi-nas-01 Z: mount). Same git repo state as V0.27.8 (commit `c7bdd20`). Same Pi target, this time fully reachable (SSH worked moments earlier; `deploy-pi.sh` succeeded against the same address). **Step 4.6 still fails in exactly the same way.**

This means one of:
- **(a)** The MSYS_NO_PATHCONV guard Ralph added doesn't actually trigger in practice (e.g., the guard wraps the wrong subprocess invocation, or the env var doesn't propagate to the SSH'd remote, or the guarding mechanism doesn't apply to the code path that constructs `$HOME/Projects/Eclipse-01/data/obd.db`).
- **(b)** There's a separate code path that constructs the mangled path BEFORE the guarded path is reached (a pre-check, a path-validation, etc.).
- **(c)** The deployed `scripts/backfill_server_battery_health_log_stranded.py` is actually a different file than the one Ralph modified (deploy hidden-bug pattern -- e.g., the script the deploy invokes is the unfixed version on chi-srv-01, not the freshly-deployed one).

Hypothesis (c) is unlikely: `deploy-server.sh` ran `git pull` (Step 1 "Already up to date" means the Pi-side script content matches the repo's V0.27.8 content), and the script invocation in Step 4.6 references the repo path locally. But pre-flight should verify which version of the script the failing invocation actually ran.

## Impact

- Server-side `battery_health_log` rows 11-15 remain `end_timestamp` NULL (unchanged from I-031 -- the V0.27.8 bigDoD clause for US-331 ("rows 11-15 populated") is NOT met).
- The deploy is otherwise clean (5/5 stories shipped, both targets on V0.27.8, server healthy), so this is NOT a deploy blocker -- the script is best-effort by design.
- The V0.27.8 IRL validation gate for US-331 has FAILED on its first attempt. The story claimed `passes:true` based on synthetic tests; the real-world gate disproves them.

## Workaround until fixed

Same as I-031: run the backfill from a Linux box (the Pi or a WSL shell with both hosts in `known_hosts` + no MSYS path-mangling). Or let the one-time backfill ride the B-076 server-schema-normalization epic's cleanup step.

## Acceptance Criteria (when groomed)

- [ ] Pre-flight: verify which version of `scripts/backfill_server_battery_health_log_stranded.py` actually ran during the failing Step 4.6 (rule out hypothesis (c)); trace the exact code path that produces the mangled `C:/Program Files/Git/home/...` argument to `sqlite3 -readonly`; identify whether Ralph's V0.27.8 MSYS guard is on the right call path
- [ ] Fix: the remote `sqlite3 -readonly $HOME/Projects/Eclipse-01/data/obd.db` argument is no longer MSYS-mangled when the script runs under Git Bash on Windows; one good test: invoke the failing function in isolation from a Git-Bash shell and assert no `C:/Program Files/Git/` substring appears in the constructed command string
- [ ] Re-run `bash deploy/deploy-server.sh` from the CIO's Windows Git-Bash post-fix -> Step 4.6 completes; server rows 11-15 populated; a 2nd deploy is a no-op (the same gate as I-031)
- [ ] Regression test that would have caught the V0.27.8 false-pass: assert the constructed remote-command string has no Windows-drive-prefixed `/home/...` paths when run under MSYS-style path translation

## Why US-331 false-passed

The story shipped a test file `tests/scripts/test_backfill_deploy_contexts.py` that Ralph reported PASSED post-fix. That test presumably exercised the MSYS guard via Python-level mocks -- but it didn't reproduce the actual Git-Bash subprocess interaction that triggers the path-mangle (which happens at the *shell-to-subprocess* boundary, not inside Python). The synthetic test was insufficient to gate the real-world behaviour. Lesson for I-032's regression test: cover the shell-to-subprocess path translation, not just the in-Python command-string construction.

## Source

- PM 2026-05-13 V0.27.8 sprint-deploy output (Step 4.6 reproduced the I-031 error identically with the V0.27.8 fix deployed)
- Parent: I-031 + US-331 (the V0.27.8 fix that didn't work)
- Cross-reference: the same gate is the V0.27.8 bigDoD clause #1 for US-331; that clause is now KNOWN-RED, not pending.
