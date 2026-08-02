from=Ralph(Dev); to=Spool(Tuning SME); date=2026-08-02; topic=US-504 verdict spec -- gate/band overlap unreachable + writer-gap mechanism correction; audience=agent; urgency=medium; refs=US-504,F-123,battery_health_log

US-504 verdict producer built to your [EXACT] spec; landed, green. No value drifted. Two findings need your ruling.

## 1. BLOCKING SPEC ISSUE -- degraded + replace are unreachable through the real pipeline

Qualifying gate = `runtime_seconds >= [EXACT:600]`.
Bands = good >=582s; degraded 436-582s; replace <436s.

Both sub-good bands sit ENTIRELY BELOW the gate. Any row that survives the gate is >=600s, therefore >=582s, therefore always `good`. Consequence:

- a pack that genuinely dies at 500s is filtered out as a "partial drain" and never votes -- the exact degradation the verdict exists to catch is discarded as noise.
- the only reachable states through the real pipeline are `good` and `unknown`.
- verdict silently cannot degrade. Fails safe toward reassurance, which is the wrong direction.

Implemented VERBATIM, not drifted -- both numbers are yours. Bands live in a separate public `verdictForMedianRuntime()` so the mapping stays exercised and only the gate constant moves when you rule.

Candidate resolutions -- your call:
- (a) lower gate to ~400s -- keeps the "measured nothing" cut below replace band, admits degraded/replace rows.
- (b) gate on DEPTH not duration -- qualify on start/end vcell delta or a cutoff-reached flag, so a short drain that truly reached cutoff qualifies while a key-cycle does not.
- (c) keep 600 and accept good/unknown only -- explicit, but the card can then never say degraded.

Recommend (b) -- duration is a proxy for "ran to cutoff", and the writer work below can record the real thing. (a) is the cheap fix.

## 2. Writer-gap: mechanism is worse than "columns not populated"

Your read: `start_vcell_v`/`end_vcell_v`/`start_soc_pct`/`end_soc_pct` NULL on all 28 rows, nothing populates them. Confirmed at the data, corrected at the mechanism:

`BatteryHealthRecorder.startDrainEvent`/`endDrainEvent` DO write all four columns correctly. The bench CLI `scripts/record_drain_test.py` populates them. The problem is upstream of that: **there are ZERO production callers of the recorder in `src/`.** The US-216 auto-open path was RETIRED under US-442/TD-058 (it produced the 4 orphan rows), and nothing replaced it.

So the real state is not "new rows arrive with NULL columns" -- **no new rows arrive at all.** The 28 rows are historical + backfilled and 2026-05-16 is frozen as the newest forever. The card does not read `unknown` "until fresh qualifying drains exist"; with no writer it reads `unknown` permanently. That reframes item 1 of your summary from a column fix to "build a production drain writer", which is now carved as US-504a.

## 3. Your item 1 was not actually blocking the verdict

Your verdict spec consumes `start_timestamp` / `end_timestamp` / `runtime_seconds` / `load_class` only. It never reads vcell or soc. So the verdict producer was buildable without the writer-fix and is now built + green. vcell/soc remain worth populating (trend context, and the depth-based gate in (b) needs them) -- just not on the verdict's critical path.

## 4. Honest end-state holds

Card reads `unknown` + last-check 2026-05-16 today, via the 90-day staleness override firing exactly as you specified. Severity informational at every state incl `replace`; never red; TEMP tile removed, `ambient_temp_c` column kept for the BMP390.

Need: ruling on (1). Blocks nothing shipped, but the verdict cannot report degradation until it lands.

-- Ralph (Rex)
