# TD-074: US-504b battery-health verdict can only ever return good/unknown (band remap owed with US-504a)

| Field      | Value                                                  |
|------------|--------------------------------------------------------|
| Type       | tech-debt                                              |
| Severity   | Medium (latent today; correctness trap when a writer exists) |
| Status     | Open — rides US-504a into V0.29.25                     |
| Parent     | F-123                                                  |
| Filed      | 2026-08-02 (Marcus, from Spool close-clearance note)  |
| Refs       | US-504b, US-504a, BL-028                                |

## What

US-504b (battery-health verdict producer) shipped `passes:true` in Sprint 69,
built **verbatim** against Spool's `runtime_seconds >= 600` qualifying gate.
Hours after 504b landed, Spool **retired that gate** (it sat above the 582 s
good/degraded boundary, making `degraded`/`replace` unreachable) and moved to a
**depth gate: `end_vcell_v <= 3.50 V` + 60 s floor**.

**Consequence:** US-504b as shipped can only ever return `good` or `unknown` —
`degraded` and `replace` are unreachable through the real pipeline. A health
verdict that cannot degrade fails toward reassurance, the one direction it must
never fail.

## Why it is only tech-debt (not a live bug) today

Entirely latent: there is **no production writer** (US-504a is carried), the
newest `battery_health_log` row is 2026-05-16, and Spool's 90-day staleness
override fires — so the card correctly reads `unknown` regardless of the gate.
Behaviour on the Pi right now is correct. The defect only becomes live the day
a production writer (US-504a) starts producing fresh qualifying rows.

## Fix

Ride the depth-gate band remap **with US-504a in V0.29.25**. Ralph already
isolated the band mapping in a public `verdictForMedianRuntime()`, so the change
is contained. Do **not** book US-504b as done-done independently — if it closes
out alone, this defect goes invisible until a writer exists.

## Resolution

[Open — grouped into V0.29.25 grooming alongside US-504a.]
