# BL-026 — US-478 / US-497 (IMU bring-up + IMU card) are gated: no 0x69 on the bus, and the `states/imu` shape is unconfirmed

- **Filed:** 2026-07-29 by Ralph (Rex), Sprint 66 (V0.29.20), after US-498
- **Updated:** 2026-07-29 after US-499 — these two are now **the entire remaining sprint** (5/7 done)
- **Blocks:** US-478 (S4-emitter, IMU bring-up), US-497 (S4-card, consumes `states/imu`)
- **Did NOT block:** US-499 (S6 render-regression) — built and complete
- **Needs:** a CIO hardware action (AI-005) + an Atlas contract ruling. PM call at dispatch, per the story's own `conditionalOutcomes`.

## Why I did not take US-478 as the highest-priority unclaimed story

Two independent gates, either one sufficient:

1. **Hardware (AI-005).** US-478's own AC-1 records it: *"NOT yet wired -- bus shows
   only 0x29 (light) + 0x36 (UPS). Blocked on AI-005 (CIO wires the board) until
   0x69 appears."* Nothing in this sprint has changed that. AC-2/AC-3 are
   read-validation criteria against a genuine ICM-20948 that is not on the bus, so
   they cannot pass — and all three `validationCriteria` are live-hardware checks.

2. **Contract (Atlas Q-A / Q-B), the one I care about more.** The story's own
   `conditionalOutcomes` say the `states/imu` **shape is gated** on Atlas Q-A
   (the derived-field contract) and Q-B (a higher-rate transport — a compass tape
   and a 35s g-trail will not animate at the 1 Hz card poll), and instruct: *"Build
   the bridge to the blessed contract."* AC-4 lists a candidate shape marked
   *"(Iris Q-A, pending Atlas confirm)"*. I have no record of that confirmation in
   my inbox, and Q-B in particular is not a cosmetic detail — it decides whether
   the bridge writes a state file at all or needs a different transport, which is
   the whole design of the deliverable.

   Building a derived-field bridge (heading, grade, tilt-compensated lateral g)
   against an unconfirmed contract, with no hardware to validate it, would mean
   inventing the numeric contract and then testing it against my own invention.
   That is Refusal Rule 1 (ambiguity is a blocker) plus Rule 2 (ground every
   number) — so I refused rather than shipping something that looks complete.

US-497 inherits both gates: it is a pure consumer of the `states/imu` file US-478
has not defined yet, so a card built now would pin a fixture shape that the
blessed contract may contradict.

## What unblocks it

- **CIO:** wire the genuine Adafruit ICM-20948 #4554; confirm `i2cdetect` shows `69`.
- **Atlas:** rule on Q-A (the derived-field list + units, i.e. exactly what the
  reader computes so the display stays a pure consumer) and Q-B (the transport for
  the live view). Once those are in writing, the emitter is buildable.
- **PM:** the story explicitly leaves one option open — *"ship the code with
  validation deferred to a wired re-check"*. That is a legitimate call and is
  yours, not mine, but note it only unblocks gate 1. Gate 2 has to be answered
  either way, or there is nothing to build to.

## Sprint impact

**Updated 2026-07-29 (post US-499).** Sprint 66 stands at **5/7** — US-494,
US-495, US-496, US-498, US-499 all `passes: true`. US-499 (the render-regression
backstop) is built, so **US-478 and US-497 are now the only remaining stories,
and both are blocked by this file.** There is no further work Ralph can pick up
in this sprint; the next move is a CIO/Atlas/PM decision, not a dev iteration.

Note for the PM's sprint-close call: US-499 discharges its own validation
automatically (RED against the real pre-fix artifacts, GREEN after), but it does
**not** retire the on-Pi render checks owed by US-494/495/496/498. Those four
still need one deploy + bench session on the Pi before the sprint is validated.
