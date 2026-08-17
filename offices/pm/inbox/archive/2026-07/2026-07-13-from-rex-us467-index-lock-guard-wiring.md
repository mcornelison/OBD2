# US-467 shipped — guarded stale `.git/index.lock` clearer (TD-057) — wiring hand-off

from=Rex(Dev); to=Marcus(PM); date=2026-07-13; topic=US-467 index.lock guard wiring

## What shipped

`offices/pm/scripts/index_lock.py` — a **guarded** stale-lock clearer that encodes
the exact heuristic you validated by hand in TD-057. It removes `.git/index.lock`
**only** when the lock is verified-orphaned, and refuses (never deletes) otherwise.

Three conditions, checked in this fixed order (the order *is* the safety guarantee):

1. **No live `git` process** — checked FIRST, so no later condition can ever lead
   to deleting a lock a running git owns (handbook §13 Rule-4). The default
   detector uses exact process-name match (`git` / `git.exe`) — no substring, so
   it can't false-trip on names like "Logitech" (your TD-057 note). If the probe
   itself fails, it **assumes live** and refuses (uncertainty never authorizes a delete).
2. **Aged past a threshold** (default 120s) — a fresh lock may be a commit still
   finishing on the slow share.
3. **Empty (0 bytes)** — a live commit writes the new index *into* index.lock
   before the atomic rename, so 0 bytes = nothing pending; non-empty = refused.

`clearStaleIndexLockWithBackoff` retries on the `[1,2,4,8,16]` ladder to wait out
a genuinely-live commit (the lock vanishes on its own) rather than force-clear.

## Usage

```bash
python -m offices.pm.scripts.index_lock --repo .          # clear if verified-stale
python -m offices.pm.scripts.index_lock --repo . --check  # dry-run: decide only
```

Exit 0 = safe to proceed (no lock, or cleared). Exit 2 = refused (live process /
too-fresh / non-empty) — escalate. Fully importable too:
`from offices.pm.scripts.index_lock import clearStaleIndexLockWithBackoff`.

## Wiring — needs your hand (PM-owned, lane discipline)

Acceptance #3 says "wired where PM commits happen if practical" and TD-057
acceptance wants it documented in **handbook §13** as the supersede-path for the
"escalate every time" step. Those are PM/shared-doc edits, so I left them for you:

- **`/closeout-pm` + `/sprint-deploy-pm`** commit steps — call the CLI (exit 0 =
  proceed, exit 2 = escalate) *before* the `git add`/`commit` on a lock-blocked run.
- **Ralph's lock-blocked path** (TD-057 acceptance) — run the guarded clearer
  before emitting `HUMAN_INTERVENTION_REQUIRED`. Note `ralph.sh`'s git allow-list
  does **not** permit `rm`; the CLI's `unlink` of a *verified-orphaned* lock is the
  safe substitute, but confirm the harness permits invoking it.
- **handbook §13 Rule-4** — annotate: the guarded clearer is the sanctioned
  safe-clear for the verified-orphaned case (still never force under a live process).

## Verification (in-loop)

- 17 targeted tests pass — `pytest tests/pm/test_index_lock.py` — incl. a **real-git**
  end-to-end: plant a stale lock → commit blocked → guard clears → commit succeeds
  (validationCriterion #1), and a persistently-live case proving the lock is NEVER
  deleted across the full backoff schedule (validationCriterion #2).
- `ruff check` clean on both files.
- PM/integration gate (not run in-loop): full `pytest tests/` + mypy strict.

TD-057 can move to **resolved** once the wiring above lands.
