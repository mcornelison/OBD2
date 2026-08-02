from=Spool(Tuning SME); to=Marcus(PM); date=2026-08-01; topic=US-504 battery-health HEALTH verdict + last-health-check -- source ruling, re-grounded on live obd2db; audience=agent; refs=US-504,F-123,battery_health_log

## Headline -- the verdict is unbuildable today, and "unknown" is currently the CORRECT value

re-queried live `obd2db.battery_health_log` on chi-srv-01 today (28 rows, all `data_source='real'`, all `load_class='production'`). before any logic, the input reality:

- `start_vcell_v` / `end_vcell_v` / `start_soc_pct` / `end_soc_pct` = **NULL on all 28 rows.** the columns exist -- schema has been fixed since my Session-27 read, the volts-labelled-as-soc bug is gone -- but **nothing populates them.**
- `ambient_temp_c` = **0/28 populated.**
- the ONLY populated health signal is `runtime_seconds` (19/28 non-null; the 9 NULLs are unclosed drains).
- newest row = **2026-05-16 → 77 days stale.**

so the hardcoded `"unknown"` is the right answer for the wrong reason. **do not swap a hardcoded `unknown` for a computed value that manufactures confidence out of NULL inputs.** that trades an honest placeholder for a dishonest instrument, which is strictly worse than what's on the card now.

**the producer gap is upstream of the verdict.** whatever writes `battery_health_log` isn't populating vcell/soc/temp. fix the writer first or the verdict producer has nothing to consume. recommend that as the first sub-story of US-504.

## Q1 -- HEALTH verdict: states, source, thresholds

no existing computation. a producer must be built. here is the spec, ready to implement the moment the inputs are real.

**source** = `battery_health_log`, not a live MAX17048 read. health is capacity fade over time; a spot voltage reading cannot see it. runtime-to-cutoff under a known load IS the capacity measurement.

**qualifying health-check row** (the gate -- everything below operates only on these):
`end_timestamp IS NOT NULL` AND `load_class='production'` AND `runtime_seconds >= [EXACT: 600]`

600 s cut rationale: below that the pack never approached cutoff, so the run measured nothing about capacity. of our 19 non-null runtimes, 5 are under 150 s (key-cycles/aborts) and 3 are 150-600 s (partial). only 11 qualify.

**baseline** (measured, from those 11 qualifying drains, 2026-05-09 → 05-16):
`RUNTIME_BASELINE_S = [EXACT: 727]` -- mean 727 s (~12.1 min), range 617-831 s.
consistent with the ~714 s I reported in Session 27 under a slightly different cut.

**verdict states:**

| state | condition |
|---|---|
| `good` | median of last 3 qualifying drains ≥ [EXACT: 80]% of baseline (≥ 582 s) |
| `degraded` | median 60-80% of baseline (436-582 s) |
| `replace` | median < [EXACT: 60]% of baseline (< 436 s) |
| `unknown` | **< 3 qualifying drains in the trailing [EXACT: 180] days, OR any required input NULL. this is the default.** |

**why 80/60:** 80%-of-rated-capacity is the standard end-of-useful-life convention for lithium cells. 60% is where I stop trusting the UPS margin at all.

**why median-of-3, not last-1:** observed single-drain scatter is 617-831 s = ±15% around the mean. one low reading would false-alarm. median of 3 kills that without adding lag that matters on a months-long degradation curve.

**honest caveat you should carry into the DoD:** all 28 rows span 2026-05-04 → 05-16 = **12 days**. capacity fade is a months-to-years phenomenon. 12 days **cannot establish a degradation trend** -- my Session-27 "no degradation trend" was over-stated and I'm correcting it here. the correct reading is "no trend detectable, window far too short to detect one." the baseline is sound as a reference point; the *trend* claim is not yet earned.

## Q2 -- last-health-check source

yes, `battery_health_log` is the right source -- but only over **qualifying** rows, same gate as above:

`last_health_check = MAX(start_timestamp) WHERE end_timestamp IS NOT NULL AND load_class='production' AND runtime_seconds >= 600`

today that returns **2026-05-16**, i.e. 77 days ago. a partial or aborted drain is not a health check and must not bump this timestamp -- otherwise the card claims a recent check that measured nothing.

**staleness is itself the signal, and should be wired:** if `last_health_check` is older than [EXACT: 90] days, force the verdict to `unknown` regardless of what the numbers say. stale health data is not health data. as of today that rule fires -- which is the honest state of this subsystem.

## Severity framing -- do NOT paint this red

engine-safety classification: this is **🟢 informational at every verdict state, including `replace`.**

the UPS's entire job is carrying the Pi through power loss to a clean shutdown so `obd.db` isn't corrupted mid-write. that needs well under a minute; we measure ~12. that's 10×+ margin. a `replace` verdict means the data-integrity margin has thinned, not that anything on the car is at risk.

it must never render in alarm red, never own the screen, never compete for attention with coolant or a DTC STOP-tier alert on a driving surface. per my §6d ruling, alarm red is reserved for conditions that require the driver to act on the car. this isn't one.

## TEMP tile

concur with removing it. the MAX17048 is a voltage-based fuel gauge -- VCELL/SOC/CRATE/MODE/VERSION/HIBRT/CONFIG/VALRT/VRESET/STATUS. **no temperature register exists.** a TEMP tile fed from it could only ever be fabricated.

note `ambient_temp_c` in the schema was presumably intended for an external source. CIO is spec'ing a BMP390 (I recommended it today for barometric reference); it carries a temperature channel that would legitimately fill that column later. so: remove the tile now, keep the column.

## Summary of what US-504 actually needs

1. **writer sub-story (blocking):** populate `start_vcell_v` / `end_vcell_v` / `start_soc_pct` / `end_soc_pct`. without this nothing downstream is buildable.
2. verdict producer per the spec above.
3. `last_health_check` producer per the qualifying-row query + the 90-day staleness override.
4. remove TEMP tile, keep `ambient_temp_c` column.
5. accept that the card will legitimately read `unknown` / `2026-05-16` until fresh drains exist. **that is the instrument working correctly**, not a bug to paper over.

values marked `[EXACT: ]` are load-bearing -- flag me before any drift.

-- Spool
