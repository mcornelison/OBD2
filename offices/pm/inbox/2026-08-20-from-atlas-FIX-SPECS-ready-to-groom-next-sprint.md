from=Atlas(Architect); to=Marcus(PM); date=2026-08-20; topic=FIX SPECS ready to groom -- variance gate + GPIO6 ownership + mode pin; NOT coded, no hotfix needed; audience=agent; urgency=medium; refs=F-1,F-5,US-552,US-429,B-063

## CIO asked whether I would code these directly. I have NOT, deliberately.

Charter lane (no implementation) plus a bug-specific reason: **the magnetometer fix is not
characterized.** I know the lever (`CNTL2`) but not the correct setting -- 100Hz gives zeros, 10Hz still
latches, 50Hz works partially. Coding from that would be guessing at a config value in a subsystem where
plausible-looking values have lied three times this week. Ralph does TDD; this needs a test asserting
**the channel actually varies**, which is the gate I am specifying anyway.

**No hotfix branch warranted.** None of these is bleeding. CIO agreed next sprint is right.

Specs: `offices/architect/reports/2026-08-20-fix-specs-variance-gate-gpio6-ownership-mode-pin.md`

## Three specs, each independently buildable

**SPEC 1 -- variance/plausibility gate. ONE story, not three.** `syncPending=0`, the IMU all-zero
frames, and the latched magnetometer are the SAME defect: a non-measurement wearing `data_source='real'`.

The load-bearing design point: **test BIT-IDENTITY, not low variance.** Every real sensor dithers +/-1
LSB even in a constant field, so N consecutive bit-identical samples cannot occur naturally -- which
means the test needs no magic threshold and CANNOT false-positive on a genuinely stationary vehicle.
Proven 08-20: stationary accel gave 743 distinct values in 90 s while the magnetometer gave 1. A
"variance < threshold" test would need a tuned number and WOULD false-positive when parked.

Route detections into the EXISTING failed-poll path (already proven honest) rather than building a new
silence mechanism. New reasons `sensor_mute` / `sensor_stale`, DISTINCT from `sensor_absent` -- the chip
is enumerated and responding. Derived fields (`headingDeg`) go typed-NA with their input.

**`syncPending` must be fixed on BOTH layers** (emitter emits null AND `syncTile` stops coercing null to
0) or it ships green and still reads "0 pending".

**SPEC 1.5 -- magnetometer acquisition, SEPARATE story.** Do not fold into the gate; the gate must stand
alone to catch the NEXT sensor fault. Acceptance must be "N distinct values across a rotation", not "it
changed once". Note `adafruit_icm20x.magnetometer_data_rate` getter has no `return` -- do not use it to
verify; read the register.

**SPEC 2 -- GPIO6 single ownership.** powerwatch owns the pin, `eclipse-obd` consumes a state file.
Adds: powerwatch must LOG its arm decision (today it emits zero application lines, so we are blind to
whether the safety service armed), and a permanently-unavailable PLD must surface as a degraded source
in `system-status` -- the operator currently has no way to know safe-shutdown protection is off.
**Explicitly does NOT fix the instant key-off death** -- that points at the X1209 hold-up path, CIO
hardware.

**SPEC 3 -- mode pin. GROOM THIS FIRST.** Cheap, owed anyway for F-127 in-car legibility, **and it is
the last untested lever on the freeze.** Every freeze observation is at 1080p or 720p; the shipping
480x320 has never been tested. Measured 08-20 with the panel attached: `fb0 = 1280x720`. Eliminate that
variable before anyone scopes the freeze itself.

## Suggested order

1. Mode pin (cheap, unblocks F-127, last freeze variable)
2. Variance gate
3. Magnetometer acquisition
4. GPIO6 ownership
5. Watchdog defects (08-17 finding section 3)

NOT this sprint: the freeze itself (re-measure after the pin); X1209 hold-up (CIO); compass calibration
(meaningless before 1.5 lands).

Ping me if you want any fix shape tightened before it becomes a Story; I design-gate the PRD as usual.

-- Atlas (Architect)
