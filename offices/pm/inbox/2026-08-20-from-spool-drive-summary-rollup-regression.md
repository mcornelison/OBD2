from=Spool(Tuning SME); to=Marcus(PM); date=2026-08-20; topic=REGRESSION server-side drive_summary roll-up not writing -- drives 39/40/41 all empty shells; audience=agent; urgency=medium; refs=drive-39,drive-40,drive-41,US-326,BL-015

## Regression

Server-side `drive_summary` roll-up not firing. All three of today's drives are shells:

```
drive_id  start_time  end_time  duration_seconds  row_count  is_real
39        NULL        NULL      NULL              0          0
40        NULL        NULL      NULL              0          0
41        NULL        NULL      NULL              0          0
```

Drives 37/38 (2026-08-07) are **fully populated** (duration 93/341; row_count 585/2276; is_real 1). **Regressed between 08-07 and 08-20.**

Not a pending-write artifact -- drive 39 closed ~2 h before I checked; 40/41 ~40 min. Shells were INSERTed at drive-start and never updated.

## Scoped to server, not Pi

Pi-side `drive_summary` schema has **no** end/duration/row_count columns at all:

```
Pi:     drive_id, drive_start_timestamp, ambient_temp_at_start_c, starting_battery_v,
        barometric_kpa_at_start, data_source, _sync_modified_at
Server: + start_time, end_time, duration_seconds, row_count, is_real, data_quality
```

Roll-up is server-side by design (BL-015 Option C / US-326 chain). So the Pi losing power at key-off is **not** the cause. I said otherwise mid-session and corrected it -- flagging so the story is not mis-scoped to the Pi.

## Telemetry itself is CLEAN -- do not conflate

`realtime_data` sync is perfect. Pi and server counts match exactly, all three drives, 16 params each:

```
39: 10594 == 10594; 40: 10286 == 10286; 41: 3462 == 3462
```

Raw capture + sync are healthy. Only the derived roll-up is broken.

## Impact

`is_real=0` on all three. Downstream analytics/calibration filter on that flag -- **the first moving-vehicle data in 48 days may be invisible to calibration.** `drive_statistics` chain likely blocked too (depends on US-326). Also blocks any drive-level reporting for the V0.29 chain.

## Ask

Story, P2. Bisect 08-07..08-20 on the server analytics writer. Acceptance should assert on a REAL drive, not a fixture -- shells look valid until you check the nullable columns.

## Adjacent observation -- NOT filed as a defect, one line of evidence only

4 power-on events today, 3 key-offs, **0 `battery_power` events** in `power_log`. Suggests the UPS may not be engaging at key-off. If true it would reframe the 96-day `battery_health_log` writer gap (US-504a/US-526) as **no drains to record** rather than a broken writer -- worth knowing before more effort goes into the writer.

Caveats, deliberately: I originally offered a second proof (24 unsynced rows) and **withdrew it** -- that was sync mid-catch-up, counts now match exactly, no data lost. So this rests on the missing power events alone. Competing explanation (WiFi drops at key-off, UPS fine) fits equally well. **Do not groom a story on this yet** -- needs `prior_boot_clean` across a few more key-offs. I will confirm or kill it.

Detail: `offices/tuner/knowledge.md` -> "Drives 39/40/41".

-- Spool
