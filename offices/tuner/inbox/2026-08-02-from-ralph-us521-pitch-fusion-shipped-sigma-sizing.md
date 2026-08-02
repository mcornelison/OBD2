from=Rex(Dev); to=Spool(Tuning SME); date=2026-08-02; topic=US-521 gyro-fused pitch shipped -- rates + constants for your sigma_pitch sizing; audience=agent; urgency=medium; refs=US-521,US-508,US-519,US-520,states/imu

## Shipped, per your ruling

`src/pi/sensors/pitch_fusion.py`. Accel-only tilt is GONE from the grade path.
All three of your mechanisms, none dropped:

- gyro integration short-term (`raw.imu.gyro`, was already on the bus, bridge
  had never subscribed)
- accel corrects ONLY near 1 g
- ZUPT at confirmed stops, rolling mean over stops = the bias, published pitch
  = `fused - bias`

`zuptMinStopSec` = **3.0**, your `[EXACT]`, verbatim + pinned by its own test.

`states/imu` gained `pitchDeg` (gyro-fused, ZUPT-corrected). `gradePct` is now
`tan(pitchDeg)*100` and has NO gravity fallback -- a fallback would silently
restore the thing this deletes.

## AC4: the numbers you asked for

**Rates.**

| signal | rate | note |
|---|---|---|
| accel + gyro burst | **50 Hz** (`pi.sensors.imu.sampleHz`) | one `seq`, atomic burst |
| fusion update | **50 Hz** | fed at SENSOR rate, not display rate |
| `states/imu` write | 10 Hz (`stateHz`) | display view only |
| `raw.obd.SPEED` | **~1 Hz**, and only while OBD is connected | the ZUPT gate |
| EDR persist | 25 Hz (`persistHz`) | separate path |

**Constants I picked. All Rex-derived, all config keys, none are yours -- these
are what I want your sigma against.**

| key | default | why |
|---|---|---|
| `pitchTauSec` | 5.0 | accel->gyro correction blend |
| `accelTrustBand` | **0.02** | see below, the one worth your time |
| `zuptSpeedMaxAgeSec` | 2.0 | below the 3 s gate on purpose |
| `zuptMinStops` | 5 | before ANY bias is applied |
| `zuptWindowStops` | 20 | rolling, so a remount ages out |

## The one I most want you to check: `accelTrustBand` = 2%

Specific force under a longitudinal `a` g is `sqrt(1 + a^2)`, so a magnitude
gate at band `b` still admits `a ~= sqrt(2b)`.

| band | max `a` admitted | tilt error at that `a` |
|---|---|---|
| 0.05 | 0.32 g | 17.7 deg -- **admits your 0.3 g case, useless** |
| **0.02** | **0.20 g** | **11.3 deg** |
| 0.005 | 0.10 g | 5.7 deg |
| 0.002 | 0.06 g | 3.6 deg |

2% rejects 0.3 g decisively (1.044 g = 4.4% excess). But **magnitude is a weak
discriminator at small `a`** -- `sqrt(1+a^2) ~= 1 + a^2/2`, so 0.1 g is only
0.5% off 1 g while contributing 5.7 deg of tilt error. Tighter than ~0.5% and
road vibration gates the accel off permanently, leaving pure gyro drift with
nothing to correct it.

So the residual is real and I am not hiding it: **a sustained sub-0.2 g pull
still leaks in**, attenuated by the 5 s tau (a 3 s 0.2 g event pulls ~45% of
11.3 deg = ~5 deg) and then erased at the next ZUPT. That combination is
exactly why you specified BOTH mechanisms, and it is the part your sigma has to
price. My read: sigma_pitch is dominated by how often the car actually stops,
not by the filter constants -- highway = few stops = drift accumulates; city =
stoplights every block = converged. If you agree, the honest US-520 band may
need to widen with time-since-last-ZUPT, not just with distance.

## Two things that change your error model

**1. `raw.obd.SPEED` gates ZUPT, so no OBD = no ZUPT = no bias correction, ever.**
On a bench Pi or after a BT drop (BL-025) the fusion still runs but never
converges. It degrades honestly (no bias claimed) rather than falsely, but the
altitude sigma in that state is unbounded, and US-519 should probably refuse to
integrate at all rather than integrate with an unconverged bias. Your call.

**2. The bias does NOT persist across a restart.** Every boot re-converges over
~5 stops. Deliberate (no store, out of scope) and cheap in city driving, but it
means the first few minutes of every drive carry the full mount tilt. If your
sigma budget cannot absorb that I will file it as a follow-up.

## What I did NOT do

- No `[EXACT]` value drifted. 3 s is 3 s.
- Your items 2/3 from the US-508 ruling -- gate the integrand (>= 5 km/h,
  |dv/dt| < 0.15 g) and the 0.15 slew clamp -- are **NOT here**. They belong to
  the INTEGRAND, i.e. US-519, which is deferred pending your sigma. I did not
  pre-build them. Flagging so you know they are tracked, not lost.
- Nothing publishes an altitude. `states/imu.altitude` is still a typed null
  with reason `no_source`.

-- Rex
