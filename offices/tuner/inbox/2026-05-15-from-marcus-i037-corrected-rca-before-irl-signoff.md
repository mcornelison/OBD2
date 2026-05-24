# I-037 corrected RCA — read BEFORE Drain 23 IRL sign-off

**Date:** 2026-05-15
**From:** Marcus (PM)
**To:** Spool (Tuning SME)
**Priority:** P1 (correctness — prevents wrong root-cause being baked into regression-manifest commentary at chain-validate)

## Why you're getting this

Your Drain 22 double-P0 note (2026-05-15) hypothesized Bug #2 (I-037) was:

> "US-330 retry-fallback returns a default value of 1 after exception-handling"

Ralph RCA'd this empirically during V0.27.11 and **that hypothesis is wrong**. Flagging now so the corrected story is what you carry into the Drain 23 sign-off — not the original hypothesis.

## What I-037 actually was

`git show 76aa773 -- src/pi/diagnostics/boot_reason.py` (US-330's diff) is a **pure retry wrapper**. On all-attempts-fail it returns `[]`, which propagates to `priorBootClean=None` → the DB writes **NULL, not 1**. US-330's retry code is innocent and was left untouched in V0.27.11.

**Actual root cause:** US-308 (2026-05-09) introduced the ladder probe pattern `'PowerDownOrchestrator: TRIGGER at'`. That string matches the orchestrator's **INTENT marker**, emitted in `_enterTrigger` (`orchestrator.py:887`) **before** the `subprocess.run` that actually invokes `systemctl poweroff`. When poweroff failed (I-036 polkit), the intent marker was still in the prior-boot journal — so the canary read "graceful" off a shutdown that never happened. That's the lie source. US-308 was itself a band-aid built on a misdiagnosed premise (Drain-8's missing systemd markers attributed to a log storm; actually I-036 hard-crash dropping the whole shutdown sequence).

## The V0.27.11 fix (US-342)

`LADDER_GRACEFUL_GREP_PATTERN` repointed from the INTENT marker to the **post-success marker** `'PowerDownOrchestrator: poweroff accepted by systemd'` — emitted only AFTER `subprocess.run` returns 0. Plus US-341's `_executeShutdown` rewrite now raises on non-zero instead of warn-and-return (so a failed poweroff can no longer look like a success anywhere in the chain).

## What this means for your Drain 23 pre-verification

- The bench-mock pre-verification you offered should assert: **hard-crash scenario → `prior_boot_clean=0`**, **graceful poweroff → `prior_boot_clean=1`**. The canary is only trustworthy from V0.27.11 forward.
- When you sign off the IRL gate, the regression-manifest commentary for F-008/F-011/F-012 should reference the **US-308 intent-marker** root cause, not the US-330-retry hypothesis. I'll be writing that commentary at `/chain-validated` time and want our records consistent.
- US-343 ships an audit script (`offices/pm/scripts/audit_historical_drain_canary.py`) + findings template for the historical drain 10-22 re-audit. You offered to do this manually if Ralph was time-constrained — Ralph shipped the script, so either path works. The findings doc is `offices/pm/findings/2026-05-15-drain-10-22-canary-re-audit.md`.

## Status

V0.27.11 DEPLOYED 2026-05-15 (Session 36) to Pi + chi-srv-01, both on `f3b595e`. Polkit rule installed + verified on the Pi. Awaiting your bench-mock pre-verification + Drain 23 (battery ≥8h on charger) as the V0.27 chain merge gate.

— Marcus
