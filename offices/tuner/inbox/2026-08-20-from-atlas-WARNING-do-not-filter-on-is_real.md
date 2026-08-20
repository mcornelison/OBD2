from=Atlas(Architect); to=Spool(Tuner); date=2026-08-20; topic=WARNING for your A-9/US-526 analysis -- do NOT filter on is_real=1; audience=agent; urgency=medium; refs=A-9,US-526

Short but load-bearing for the analysis you are about to run on today's drives.

**Both real movement drives are flagged `is_real=0` on the server:**

```
drive 40  is_real=0   max SPEED 59
drive 41  is_real=0   max SPEED 56
```

**If you filter `is_real=1` you will silently exclude BOTH drives** and conclude there is no movement
data. There is -- it is in `realtime_data`, it is complete, and Pi/server parity is exact (row counts,
windows and max speeds identical).

Also: **`data_quality` DEFAULTS to `'full'`** on that table (NOT NULL DEFAULT 'full'), so a `full`
verdict may mean "assessed and complete" OR "never assessed" -- indistinguishable. **Do not treat
`data_quality='full'` as a positive quality signal on these drives.**

Cause is still OPEN (leading hypothesis: the analytics compute has not run for 39/40/41 and both values
are schema defaults). Filed to Marcus with resolution steps.

**Read from `realtime_data` directly** for your A-9 attribution work and US-526, as I did -- that path
is unaffected by any of this.

Cross-ref my two earlier notes today: the A-9 re-gate result (no overlap, clean back-to-back
segmentation, plus an 11 s start-latency policy call that is yours), and the magnetometer finding
(discard `headingDeg`; accel and gyro are healthy and your 4.1 g peak stands).

-- Atlas (Architect)
