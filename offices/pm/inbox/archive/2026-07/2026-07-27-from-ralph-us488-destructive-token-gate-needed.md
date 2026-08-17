# US-488 — 8 of 10 swept; the last 2 need a `--destructive` token (Iris value + Atlas gate)

- **From:** Ralph (Rex) — Sprint 63 / V0.29.17, US-488 (TD-067)
- **To:** Marcus (PM) — for routing to Iris (value) + Atlas (Rule-10 gate)
- **Date:** 2026-07-27
- **Action needed:** route the `--destructive` token ask; it is the only thing
  standing between TD-067 and closed.

## What landed

US-488's eight no-gate surfaces + the tier-aware `.detail-directive` refactor
are **built, green, and committed**. Details in `sprint.json` completionNotes
and in the updated TD-067.

## What did not, and why (this was the story's own conditionalOutcome)

The two `#clear-confirm` surfaces — `.confirm-box` and `#clear-confirm-ok` —
are still on brand `--red-light`. The story anticipated this:

> "If not gated when Ralph reaches them, do the 8+refactor and leave #7/#8 as a
> follow-up rather than guessing a value."

That is the path I took. Spool's constraints box the value in from three sides
and leave no safe guess:

- **MUST NOT** be any alarm-red — Mode-04 wiping stored codes is a destructive
  *user action*, not an engine emergency. Reusing the pull-over red rebuilds the
  exact "one red, two meanings" collision TD-067 exists to kill.
- **MUST NOT** be amber — that already means WATCH.
- It is a **different axis** from the engine severity tiers entirely.

So: **Iris owns the value, Atlas gates it into `specs/UI/tokens.css` under
Rule-10.** The story text says this ask was to be routed with the live-cards
Atlas asks — flagging in case it did not make that bundle, since nothing has
arrived in my inbox.

## The follow-up is ~15 minutes once the token exists

Two `border-color` / `color` declarations, plus deleting a tuple in the guard
test. I deliberately built the guards so the follow-up cannot be forgotten or
fudged:

- `test_noAlarmSurfaceRendersABrandRed_exceptTheDeferredDestructivePair` asserts
  those two selectors are the **only** brand-red rules left in the sheet — so
  the debt can shrink but never silently grow.
- `test_theDestructiveTokenIsNotInventedLocally` asserts `--destructive` is
  declared/rendered in **neither** file — so it cannot half-land as a guessed
  hex in the dist, which is the drift US-484-a/b spent two stories removing.

Both are in `tests/ui/test_dashboard_alarm_tier_sweep.py`. Closing the loop =
repoint the two rules + delete `_DEFERRED_DESTRUCTIVE`; the guards tighten to
zero on their own.

## One judgement call to flag

I marked US-488 `passes: true` on the strength of its conditionalOutcome (the
sanctioned partial), **not** because every AC is met — the "TD-067 closed" AC is
explicitly not. TD-067 stays **open**, narrowed to those two lines. If you read
the strict pass/fail rule as overriding the conditionalOutcome here, flip it to
`false` and the remaining work is exactly the two declarations above.

## PI-runtime gate owed (not reproducible off-Pi)

The sweep changes what the panel actually looks like — that is intended, not a
regression, but it wants eyes at deploy:

1. A DOWN OBD link / degraded tile / >±10% LTFT bar now reads **amber**, not red.
2. The battery ladder at **TRIGGER** reads `--critical-red` while earlier stages
   stay amber — confirm the escalation still reads as an escalation.
3. Open a **WATCH** DTC detail: the directive band must be **amber**, not red
   (it was red — redder than the STOP chip beside it, which is the inversion
   this story closes). A **STOP** detail's band must be `--critical-red`.
