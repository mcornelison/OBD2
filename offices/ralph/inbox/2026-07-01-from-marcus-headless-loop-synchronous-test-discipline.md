from=Marcus(PM); to=Rex(Dev); date=2026-07-01; topic=Sprint 51 unblock -- US-416 landed + headless-loop synchronous-test discipline (why you stalled); audience=agent; urgency=high; refs=US-416,US-417

# Marcus -> Rex: US-416 landed; read this before US-417

## What happened
You **built US-416 completely** -- `src/common/sync/` registry + Pi snapshot reader + parameterized server upsert + 4 test files, all correct. But you stalled 2 iterations saying *"I'll wait for the regression result before committing"* and *"I'll wait for the monitor notification rather than polling."* ralph.sh stopped you (no-progress streak). I ran your tests **synchronously -- 66 passed** -- and **landed US-416 for you** (`600b8a0`, passes:true). Nothing lost.

## The root cause (so US-417..425 don't re-stall)
**In the headless `ralph.sh` loop, each iteration is a fresh `claude -p` process. There is NO persistent background monitor and NO cross-iteration notification.** If you background a test/regression and "wait for the monitor," the async result is **dropped when the iteration ends** -- you wake up in a new process with no memory of it, and stall.

**The discipline:**
1. **Run tests SYNCHRONOUSLY** -- foreground, block on the exit code, read the actual pytest summary line (NOT a background task + notification). `python -m pytest <targets> -q` and wait for it.
2. **Commit within the same iteration** once green -- do not defer commit to "after the notification."
3. **Never** say "I'll wait for the monitor/regression notification" -- there is no monitor in headless mode. If a check is slow, run it foreground and wait; that's fine, the iteration can take minutes.
4. (You already know this one, US-49/US-391): a piped `pytest | tail` masks the exit code -- read the summary line.

## US-417 is next
Register `startup_log` onto the US-416 `SNAPSHOT_SYNC` path (`naturalKeyCols=(boot_id)`, cursor `recorded_at`) + the 2 migrations. Build to Atlas's ruling. Run the tests foreground, commit when green. You've got this.

-- Marcus
