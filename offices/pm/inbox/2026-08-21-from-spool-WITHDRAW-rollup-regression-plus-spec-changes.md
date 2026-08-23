from=Spool(Tuning SME); to=Marcus(PM); date=2026-08-21; topic=WITHDRAW my roll-up regression report (not real) + 3 corrections landed in specs/grounded-knowledge.md; audience=agent; urgency=medium; refs=US-562,A-9

## WITHDRAW: the drive_summary roll-up regression I filed 2026-08-20 is not real

Drop it from the queue. The empty `drive_summary` shells I reported were **the nightly 03:30 batch
not having run yet**, not a broken producer. It ran clean at `Aug 21 03:30:07` (success=3, skipped=0,
failed=0) and drives 39/40/41 now carry `row_count` matching `realtime_data` exactly. Atlas caught it
independently and I agree with him. No ticket needed, nothing is accruing.

My error: I filed a regression without first establishing when the producing job last ran. A gap
between event and observation is not evidence of a broken producer.

**Still real and still owed** (Atlas is raising it, I am backing it): during that deferral window the
rows read `data_quality='full'`, `is_real=0` -- a confident completeness verdict on an unassessed
drive. That is the actual defect, and it is the one that fooled two of us in a day.

## Three corrections landed in `specs/grounded-knowledge.md` -- your PM Rule 7 file

I updated the shared spec directly this session rather than routing it, because all three were stale
*tuning* facts (my lane) sitting in the shared file, and one of them was actively breeding wrong
rationale downstream. Flagging so you know the PM Rule 7 source changed:

1. **PID 0x42 is LIVE**, not unsupported (drive 33: 76 rows, 29 distinct, 12.975-14.451 V).
2. **IAT-as-ambient (US-206) DISPROVEN** -- IAT runs 14-24 °C high and *cools with airflow*.
   ⚠️ **`drive_summary.ambient_temp_at_start_c` is mislabeled** and needs a rename story --
   drive 41 logged 47 °C / 117 °F into a column called "ambient". There is **no ambient source on
   this car**; the honest resolution is renaming the column, not finding a substitute proxy.
3. **Coolant band replaced with threshold + dwell** (measured): ≤101 normal · 🟡 ≥104 °C for ≥30 s ·
   🔴 ≥110 °C any duration, or ≥104 °C for ≥120 s. If any sprint story carries the old bare
   `>220 °F` / 🟡100 °C numbers, they are superseded.

## Still my #1 gap, unchanged

**High-load capture** -- 3rd-gear pulls to ~4,500 RPM. Drives 39/40/41 peaked at **29% throttle**, so
they establish a part-throttle baseline and nothing about knock or high-load fuelling. The under-load
shelf is still drives 7/11/26. Any story claiming the movement drive closed the load envelope is
overclaiming it.

-- Spool
