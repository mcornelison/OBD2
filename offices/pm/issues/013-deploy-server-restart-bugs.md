# I-013: deploy-server.sh `--restart` had two latent bugs

**Severity**: Medium (caused a real outage during CIO's deploy attempt this session)
**Status**: Fixed in working tree (this session), not yet filed at the time of discovery
**Component**: `deploy/deploy-server.sh`
**Filed**: 2026-04-16 (PM Session 19)

## Symptom

CIO ran `./deploy/deploy-server.sh --restart` at 18:45:28. The script aborted
after stopping the running server but before starting the replacement, leaving
the server down. Script exit code was 255 (SSH) and there was no useful output
after "Step 5: Stopping existing server ---".

## Root Causes

### Bug 1 — pkill self-match kills its own SSH shell (Step 5)

```bash
ssh $HOST "pkill -f 'uvicorn src.server.main:app' 2>/dev/null && echo 'Stopped.' || echo 'No server was running.'"
```

The remote bash's full command line contains the literal string `uvicorn src.server.main:app`
(it's the argument to `bash -c`). `pkill -f` scans `/proc/PID/cmdline` for any
process whose full command line matches the given regex — so it matched the
bash running pkill itself and killed it. SSH lost its channel and returned 255
before the `|| echo` fallback could print anything. Under `set -e`, the script
exited immediately.

**Fix:** Use the `[u]vicorn` bracket trick. The regex matches `uvicorn`, but the
string literal in bash's cmdline is `[u]vicorn`, which the regex won't match.

### Bug 2 — SSH channel hangs on backgrounded remote (Step 6)

```bash
ssh $HOST "... nohup uvicorn ... > $LOG 2>&1 &"
```

Even with stdout/stderr redirected to a file, SSH waits for all three standard
channels of the remote session to close before returning. The remote bash
backgrounds the command with `&` but doesn't explicitly close its own fds, so
SSH holds the session open until some external event closes them — often
never. The script hangs indefinitely at Step 6, never reaching the Step 7
health check.

**Fix:** `ssh -f` + `< /dev/null` on the remote side. `-f` forks the local
ssh into background after auth (implies `-n`, no stdin). Combined with the
remote `nohup`, child fd redirects, and explicit stdin closure, SSH returns
as soon as the child is launched.

## Patch

Both fixes applied in commit that includes this file. Verified end-to-end:
`./deploy/deploy-server.sh --restart` now runs to completion in ~5 seconds,
stops the old uvicorn, starts a new one under a fresh PID, and returns
success from Step 7's health check.

## Preventable?

Yes. Both bugs are idiomatic pitfalls documented in every serious bash/ssh
reference. A deploy script review by Ralph or Marcus at creation time would
likely have caught them. The script worked on the happy path (fresh system,
nothing to kill) during Sprint 7 testing, so the bugs never surfaced until a
real restart was attempted.

## Test Hook for Future Work

A trivial integration test exists that could have caught Bug 1: run
`deploy-server.sh --restart` twice in a row against a running server. First
run should succeed and restart. Second run should also succeed and restart
again. Pre-fix, the second run would have exited 255 because `pkill` would
have matched its own shell.
