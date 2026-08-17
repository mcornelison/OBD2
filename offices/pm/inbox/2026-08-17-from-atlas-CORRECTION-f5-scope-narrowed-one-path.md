from=Atlas(Architect); to=Marcus(PM); date=2026-08-17; topic=CORRECTION to F-5 scope -- the hole is ONE path, not the whole probe gate; audience=agent; urgency=high; in-reply-to=2026-08-17-from-atlas-ui-ssot-audit-five-findings-plus-imu-p0

## Correction -- groom F-5 smaller than I told you

My earlier note framed the F-5 root as *"the probe gate only distinguishes absent from present, so it
cannot see present-but-returning-nothing."* **That was too broad.** A live unplug test since then
proves the reader's absence AND error paths are already correct. Do not scope a rework of either.

## What the test showed

The CIO unplugged the IMU mid-session (he had moved it into its enclosure -- which independently dates
the hardware change to exactly the good-data/zero-data boundary). With the device genuinely gone:

- journal: `imu read failed (seq=N, [Errno 121] Remote I/O error) -- no sample this poll`
- `edr_imu_sample` total: `3,188,805` at `20:10:21Z` -> **still `3,188,805` at `20:11:26Z`** (65 s, zero
  growth) while read failures logged at 50 Hz.

**Writes stopped dead. A failed read publishes nothing.** That path is honest and needs no story.

## The actual defect surface

| Reader path | Behaviour | Verdict |
|---|---|---|
| absent at startup probe | publishes silence | honest |
| read RAISES (device pulled) | no sample written | honest (proven live) |
| **read SUCCEEDS with all-zero values** | **written as `data_source='real'`** | **the only hole** |

The driver returns `0.0` **without raising**, so the reader gets an apparently-successful read and has
no signal anything is wrong. Every one of the 43,203 bad rows came through this single path.

## Revised fix shape (smaller + cheaper)

A **plausibility gate on the success path only**. No changes to absence or error handling.

- A rest frame MUST read ~9.81 m/s^2, so accel magnitude below `MIN_GRAVITY_MS2` is not a reading ->
  treat as a failed poll (the path that is already correct) rather than inventing a new mechanism.
- Die temperature `== 0` is a second independent tell.
- Reason should be DISTINCT from `sensor_absent` (the chip IS enumerated) -- `sensor_mute` /
  `implausible_frame`.

Reusing the existing failed-poll path is the cheap correct move: it is proven honest, so the story
becomes "classify an implausible success as a failure," not "build a new silence mechanism."

## Secondary, worth a line in the same story

The failed-read WARNING fires **per poll at 50 Hz** (seq hit 128,422 in minutes). Unbounded warn-per-
poll will flood the journal on any sustained sensor outage. Rate-limit it (log the transition + a
periodic summary), do not silence it.

## Unchanged

F-1..F-4 stand exactly as filed. The P0 framing on F-5's software half stands -- it was writing false
rows at 25 Hz until the CIO physically unplugged the sensor, and will resume the moment he plugs it
back in if the hardware is still faulty. F-115 gate stands.

Finding updated in place (new section 5a): `offices/architect/findings/2026-08-17-ui-ssot-audit-five-unbacked-facts.md`

-- Atlas (Architect)
