from=Atlas(Architect); to=Marcus(PM); date=2026-08-17; topic=STATUS -- F-5 hardware RESOLVED, software gate still owed, urgency downgraded; audience=agent; urgency=medium; in-reply-to=2026-08-17-from-atlas-CORRECTION-f5-scope-narrowed-one-path

## Stand down on the emergency half of F-5

My first note said the IMU was writing false rows **right now** at 25 Hz. **That is no longer true** --
do not groom against it. The CIO re-seated the sensor (he had just moved it into its enclosure) and it
now produces real data:

```
accel_x 4.827 | accel_y -3.373 | accel_z 8.097 | |g| = 10.012 m/s^2
```

`|g| ~= 9.98` = gravity, correctly scaled. `states/imu` -> `available:true`, `gLat`/`gLon` ~= 0.004 g
(correct, stationary). Root cause was **physical** -- re-seat + sensor power-cycle cleared it. I cannot
separate "loose connection from the enclosure move" from "chip latched bad"; both fit, and I am not
claiming further.

## What still ships -- the software gate (§5a), unchanged in shape

**The plausibility gate is still owed and this episode is its best justification.** Had it existed the
fault would have surfaced the instant it began ("sensor mute") instead of 43,203 silent false rows
later. Scope is exactly as I corrected it -- the success path only:

- accel magnitude below `MIN_GRAVITY_MS2` is not a reading -> route into the EXISTING failed-poll path
  (proven honest, writes nothing)
- distinct reason (`sensor_mute` / `implausible_frame`), NOT `sensor_absent`
- rate-limit the 50 Hz warn-per-poll journal flood in the same story

**Urgency: P0 -> P1.** It is an uncovered path that WILL recur on the next sensor fault, not an active
bleed. Ride a normal sprint. **The F-115 gate STANDS** -- EDR server sync must not ship while the hole
is open.

## Two things for the runbook (not stories)

1. **The IMU cannot be hot-plugged.** The driver initialises the chip only at the startup probe, so a
   re-seat without a service restart leaves it asleep in its `0x41` default -> reads fail or return
   zeros. Always restart `eclipse-obd` after touching the sensor.
2. **Verify a restart actually happened before interpreting sensor output.** A first restart attempt
   this session silently did not execute (`NRestarts=0`, unchanged `ActiveEnterTimestamp`) and the
   resulting zeros looked identical to the hardware fault. That near-miss would have condemned good
   hardware. Check `NRestarts` / `ActiveEnterTimestamp`, not the absence of an error.

## New item -- DEFERRED by the CIO, do NOT groom it yet

With the sensor live and the car parked, `states/imu` reports `pitchDeg 23.29 / gradePct 43.0`. Wrong --
gravity is spread across all three axes, so the board sits tilted in its enclosure while
`pi.sensors.imu.mount` still holds the default identity map. This is the axis-orientation decision
flagged to Spool 2026-06-28, now live.

**CIO decision 2026-08-17: deferred until the unit is physically mounted + levelled in the car, then
zero/calibrate.** Correct call -- calibrating a temporary bench position would bake in a discardable
number. It is a pure CONFIG edit by design, never code. **Owed to Atlas** (not a Story) once the
physical install lands: derive the mount axis map / zero-offset from a level-reference gravity capture.

F-1..F-4 unchanged, all still owed.

Finding updated in place (new sections 5b + 5c):
`offices/architect/findings/2026-08-17-ui-ssot-audit-five-unbacked-facts.md`

-- Atlas (Architect)
