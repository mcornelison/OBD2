# BL-029: stale `.git/index.lock` blocks every Ralph commit on the shared checkout

| Field      | Value                                                          |
|------------|----------------------------------------------------------------|
| Type       | blocker (environment / shared-checkout)                        |
| Severity   | HIGH — work is complete and green but CANNOT be committed       |
| Status     | Open — needs CIO action                                        |
| Found      | 2026-08-03 (US-525, Sprint 70 / V0.29.25)                      |
| Owner      | CIO (only they can clear it / grant the permission)            |
| Refs       | US-525, handbook §13 rule 4, TD-059                            |

## The blocker

`Z:\o\OBD2v2\.git\index.lock` exists and is **not clearing**:

```
-rw-r--r-- 1 mcorn 197609 0 Aug  3 08:26 .git/index.lock
```

- **0 bytes**, created **08:26**, still present at **08:39+** — ~13 minutes.
- Every `git add` fails: `fatal: Unable to create '.../.git/index.lock': File exists.`
- Retried 4 times across ~13 minutes. It has not cleared.

Handbook §13 rule 4 describes the transient case ("clears in seconds; wait +
retry"). This is not that case — 13 minutes with a 0-byte lock means the holding
process is gone, not busy.

## Why I did not clear it myself

Rule 4's second half: **never delete it while a `git` process is running.** I
could not establish that no git process is running — both process-listing routes
are permission-blocked in this harness (`ps -W`, `tasklist /FI "IMAGENAME eq
git.exe"`, `Get-Process git`).

I then tried the **reversible** alternative — `mv .git/index.lock
.git/index.lock.stale-...`, which preserves the artifact and, on Windows, fails
if a live process holds the file (so success would itself have been evidence of
staleness). The harness blocks writes to `.git/index.lock` as a sensitive path.

So: correct guardrails, and I stopped rather than routing around them. This
needs the CIO.

## Impact — sprint-wide, not story-scoped

This is **not** specific to US-525:

- US-525's work is **complete and gate-green** (28 targeted tests pass;
  `tests/ui` + `tests/pi/splash` = 794 passed with only the 2 known I-041 reds
  that US-528 owns) but sits **UNCOMMITTED** in the working tree.
- Every remaining story (US-526/527/528/529) would hit the same wall at
  Workflow step 6. Ralph would do the work and be unable to preserve it.
- Uncommitted work is exactly what handbook §13 says disappears on a branch
  switch. **Do not switch branches until this is cleared and US-525 is
  committed.**

## Requested CIO action (one of)

1. Confirm no git process is live, then remove `Z:\o\OBD2v2\.git\index.lock`
   (preferably `mv` it aside rather than `rm`, so the artifact survives for
   diagnosis — the US-513 preserve-forensics lesson); **or**
2. Grant the harness permission to move/remove `.git/index.lock` so Ralph can
   clear a proven-stale lock itself; **or**
3. Clear it and commit the staged US-525 fileset yourself:

```
specs/UI/dist/splash-pi/boot-state-poll.js
specs/architecture.md
tests/ui/render_harness.py
tests/ui/splash_probe.js
tests/pi/splash/test_splash_launcher_route_contract.py
tests/ui/test_splash_min_visible_floor.py
offices/pm/issues/I-043-shutdown-splash-terminal-reason-not-observable.md
offices/pm/issues/I-044-kiosk-units-xdg-runtime-dir-percent-U-expands-to-zero.md
offices/ralph/sprint.json
offices/ralph/ralph_agents.json
offices/ralph/progress.txt
offices/pm/blockers/BL-029-stale-git-index-lock-blocks-all-ralph-commits.md
```

Suggested message: `fix: [US-525] anchor the boot-splash visible floor to the
brand paint + pin the launcher route contract`

## Do NOT include in that commit (other lanes)

These are dirty in the same tree and are **not** US-525's:

- `.deploy-version` — deploy artifact (PM lane; currently reads V0.29.24)
- `offices/uidevloper/proposals/2026-07-27-pi-live-instrument-card.md` — Iris's lane

## Note on the lock's origin

Unknown, and I am not guessing. It appeared at 08:26, which overlaps this
session's first read-only `git status`/`git log` calls (those succeeded). A
concurrent agent on the shared checkout is equally plausible. If the CIO wants
this rooted out rather than cleared, preserve the file before removing it.

## Resolution

**CLEARED by PM (Marcus) 2026-08-03 09:08.** By the time PM picked this up the
08:26 0-byte lock had already cleared (Ralph committed US-522/523/524 + the keyring
docs); a NEW lock was present -- 363 KB, 08:56, ~12 min old, **no git process
running** (`ps` clean). That is a stale interrupted-write lock (size = how far the
killed op got), safe to remove per handbook §13 rule 4. Removed it and committed
Ralph's US-525 fileset on his behalf (PM-as-integrator) at `c799a0c` with his
suggested message; excluded `.deploy-version` + Iris's proposal (other lanes).
**US-525 preserved; sprint now 5/8.** Ralph can resume US-526/527/528/529 (+ the
reopened US-522 keyring flag) on the next `ralph.sh`.

**Recurring-cause note:** this is the 5th+ stale-lock hit this session (same class
as BL-stale-index-lock-*). The durable fix is option 2 from above -- grant Ralph
(and PM) harness permission to `mv` a proven-stale `.git/index.lock` aside -- so a
0-byte/idle lock does not stop the sprint each time. Routed to CIO as a standing
ask; tracked under the existing stale-lock debt (US-467 helper exists but cannot
run while the harness blocks the sensitive path).

Status -> Resolved (this instance); durable-fix ask open with CIO.
