# US-507 done — but its on-Pi validationCriteria says "4 cards" and US-507 alone lands at 5

from=Rex(Dev); to=Marcus(PM); date=2026-07-31; topic=US-507 validation-criteria card count; audience=mixed

## The finding

US-507 is complete and committed (`7c02b16`). Its acceptance bullets are all met.
But its `validationCriteria` outcome reads:

> 4 cards total (Home/System Status/Health/Alerts)

**After US-507 alone the carousel has 5 cards**: Standby (home) · System Status ·
Health · **Motion** · Alerts.

That is not a shortfall in this story. US-507's own acceptance says *"drop the 2
now-merged standalone cards"* — Battery Health and Light (plus the hidden LTFT
Trend slot), which is exactly what shipped: 3 sources merged into 1 card, net −2.

The missing 5th → 4th step is **US-508's**, whose acceptance says the home slot
shows *"the idle card when parked and the live instrument when driving — one
slot, two faces (**not a separate always-present card**)"*. Absorbing the Motion
card into the home slot is what reaches the locked 4.

## Why I did not just delete the Motion card

Scope Fence. Removing it here would (a) do US-508's work in US-507, and (b) delete
US-497's shipped card during the window before US-508 re-issues it to the locked
spec — a real regression window on the Pi if the sprint is validated between the
two stories.

## What I need from you

Nothing blocking — this is a **validation-gate** correction, not a code one:

1. Either re-word US-507's validationCriteria to the state US-507 actually
   produces (*"5 cards; the 3 standalone reference cards are gone, replaced by one
   Health card"*), **or** mark that outcome as jointly discharged by US-507+US-508.
2. `validation.bigDefinitionOfDone` carries the same "4 cards total" line copied
   from US-507 — same fix.

As written, an on-Pi validator checking US-507 in isolation would count 5 and
record a FAIL against a story that met every one of its acceptance criteria.

## State of the story

`passes: true`. Green in-loop (synchronous): tests/ui + tests/deploy/test_dashboard_kit.py
= 414 passed exit 0; tests/pi/splash = 180 passed / 1 skipped; ruff clean.
Architecture design-gate DoD met in-sprint.

**Still owed on-Pi (A-16, cannot be discharged from this box):** bench + engine
off → the Health card shows a real battery reading and a real lux reading, and
the Fuel Trim section reads **"no engine data"** — not a fabricated 0%. Watch
specifically that a dead UPS grays the **Battery section only** and leaves the
Light reading beside it live; merging three cards must not merge their failures.

— Rex
