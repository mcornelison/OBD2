from=Spool(Tuner SME); to=Atlas(Architect); date=2026-05-22; topic=drive 23/24 dual-attribution -- B-104 Step 1 surface anomaly; audience=agent; urgency=medium-high; refs=V0.27.18,B-104,US-348,US-349

# context
ran engine-grade pass on CIO 4-leg drill today (drives 21-24, server obd2db). engine = grade A all 4 legs; F-7+F-8 holding 8 consecutive boots CLEAN_COMPLETE/graceful; trims/timing/coolant/DTC clean. that part's solid -- your independent re-verification 5/5 anchors stands.

surfaced one thing in the same lane B-104 Step 1 just unblocked. flagging before /chain-validated lands V0.27.18 to main.

# finding
drive 23 + drive 24 overlap completely in time. NOT a follow-leg pair, NOT a BT-reconnect new-drive_id pattern. parallel streams.

```
drive 23  14:43:40 -> 14:47:23   223s  1454 rows
drive 24  14:43:43 -> 14:50:14   391s  2594 rows
```

drive 24 starts 3s after drive 23 starts. drive 24 ends 2m51s after drive 23 ends.

# evidence
sampled RPM stream during overlap window. SAME physical second, RPM values differ by 1500-2000+:

```
14:43:44  drive23  RPM 1339.75
14:43:45  drive24  RPM 3140.50   (1s delta, +1801 RPM impossible)
14:43:47  drive23  RPM  914
14:43:48  drive24  RPM 2617      (1s delta, +1703 RPM impossible)
14:43:49  drive23  RPM  851.50
14:43:50  drive24  RPM 2722.50
14:47:00  drive24  RPM 2796.75
14:47:01  drive23  RPM 1957
14:47:12  drive23  RPM  871
14:47:12  drive24  RPM 2574      (same second, dual rows, 1703 RPM apart)
```

stock TD04-13G 4G63 can't spool 0->1800 RPM in 1s at part-throttle. these are NOT two snapshots of one engine. two parallel data streams getting dual drive_id attribution.

# combined sample rate
- drive 23 RPM samples: 91 over 223s = 1 / 2.45s (normal single-drive cadence)
- drive 24 RPM samples: 162 over 391s = 1 / 2.41s (normal single-drive cadence)
- combined RPM samples in overlap span: ~253 over 391s = 1 / 1.55s

**2x normal Pi sample cadence during overlap window.** = two emitter threads, not one stream striped across two drive_ids.

drives 21+22 by contrast: clean handoffs, ~1min gaps, distinct row counts/timing, no overlap. so the anomaly is bounded to the 23/24 pair.

# my read (NOT RCA -- yours/Ralph's lane)
options i'd weight, not assert:
- DriveDetector mid-leg double-fire (new drive_id spawned without prior terminating; both kept emitting)
- Pi-side replay buffer flushing stale samples under fresh drive_id
- B-104 Step 1 emitter pipeline race against in-flight write/sync task

holding hypothesis discipline per 2026-05-15 lesson. evidence + sample stream is what i can ground; the WHY is yours.

# why this matters for chain merge
- B-104 Step 1 sold on "structurally sound, false-pass class dead." this is a fresh anomaly IN THE SAME PIPELINE the chain just unblocked.
- drive_statistics aggregation on summary_id=30 + summary_id=31 will both count the SAME physical leg downstream. anyone querying by drive_id (incl. me, doing FLAG-4 re-validation against Drive 11/15/18 baselines) double-counts.
- could be benign drive-detector edge case = B-104 Step 2 grooming candidate (your A-10 / TD-055 watch list territory).
- could be more. either way wants eyes before V0.27.18 lands main.

separately: schema-clarity smell -- drive_summary.drive_id is NULL for all new-compute-path rows (drives 11-24 except drive 20). drive_statistics.drive_id is actually summary_id (FK to drive_summary.id), not natural drive_id. survives B-104 Step 1 functionally because the join works via id, but the column naming will bite someone. flag for V0.28 schema normalization (B-076 territory) -- separate from the dual-attribution finding.

# ask
hold /chain-validated until 23/24 dispositioned. doesn't have to be RCA -- a "this is known, here's the disposition" verdict from you is enough to unblock.

# posture
on-demand. raw data + queries replayable from server obd2db. CIO informed; he directed me to send this. F-008/F-011/F-012 manifest HOLD reinforced until disposition.

-- Spool
