# Finding: Drive 23/24 Dual-Attribution — DriveDetector Pi-Side Defect

**Date**: 2026-05-22
**Author**: Atlas (Architect)
**Severity**: High (data-integrity in just-deployed pipeline)
**Chain-blocking**: **No** (CIO-ratified 2026-05-22)
**Disposition**: V0.28.0 top-priority issue; chain-merge proceeds with documented carve-out + tripwire pre-condition
**Source**: Spool's 2026-05-22 inbox note `from=Spool topic=drive 23/24 dual-attribution`; CIO-routed for Atlas verdict
**Refs**: V0.27.18 IRL drill (Argus); Sprint 41 US-351 DriveDetector + lifecycle revert; B-104 Step 1; my Watch List A-9 (now upgraded)

---

## 1. Finding (one paragraph)

V0.27.18 IRL drill 2026-05-22 produced two `drive_summary` rows (drive_id 23 + 24) that overlap in time, with **parallel emitter streams** populating both — confirmed by Spool's per-second RPM sampling showing values differing by 1500-2000 RPM between drives in the same wall-clock second (impossible for a single physical engine), and by combined sample cadence in the overlap window running at ~2× the normal Pi rate (1 sample / 1.55s vs normal 1 / 2.4s). The server compute path correctly aggregated whatever drive_id attribution the Pi emitted; the architectural defect is **upstream** of B-104 Step 1 — in Pi-side DriveDetector + lifecycle drive_id assignment, last touched by Sprint 41 US-351's revert of US-349.

This is **not** the V0.27.7 / V0.27.16 / V0.27.17 false-pass family. That class was "drive-end signal never fires"; this is "drive-start signal fires twice with overlapping windows." Different shape, different fix surface.

## 2. Evidence

### Spool's primary evidence (his note in Atlas inbox 2026-05-22)
```
14:43:44  drive 23  RPM 1339.75
14:43:45  drive 24  RPM 3140.50   (+1801 RPM in 1s — impossible)
14:43:47  drive 23  RPM  914.00
14:43:48  drive 24  RPM 2617.00   (+1703 RPM in 1s — impossible)
14:47:12  drive 23  RPM  871.00
14:47:12  drive 24  RPM 2574.00   (same second, dual rows, 1703 RPM apart)
```

Combined RPM cadence in overlap window: ~253 over 391s = 1/1.55s. Normal single-drive: 1/2.4s. **2× rate = two emitter streams**, not one stream striped.

### Atlas independent verification
- Server-side scan (chi-srv-01 / `realtime_data`):
  > `SELECT pairs of drive_ids where time ranges overlap` → **EXACTLY ONE pair: (23, 24)** across all 14 attributed drives in history (11-25). Not a pervasive condition.
- Pi-side scan (chi-eclipse-01 / Pi sqlite `realtime_data`):
  > Same query, same result: only (23, 24). Both tiers agree.
- Live engine check (CIO car idling 2026-05-22 ~18:35 UTC):
  > Drive 25 (current idle, 2404 rows, 18:35:38 → 18:42:12 UTC) is **single-attribution clean** — no dual emission currently active. Confirms the bug is **transient/edge-case**, not always-on.
- Git history of `src/pi/obdii/drive/detector.py` + `src/pi/obdii/orchestrator/lifecycle.py`:
  > Last touch is Sprint 41 US-351 (commit `d6ad871` V0.27.17 ship), which reverted Sprint 40 US-349's modifications to pre-US-349 shape. Today's drill (drives 21-24) was the **first IRL exposure** under V0.27.18's reverted DriveDetector + new B-104 Step 1 read path.

### What the evidence rules out
- ❌ DriveDetector mid-leg single-segment re-fire (would produce identical RPM values, not 1800-apart)
- ❌ Replay buffer of stale historic samples (timestamps are all 2026-05-22 14:43:40+, not earlier)
- ❌ Two physical engines (one car, one OBD link)

### What the evidence is consistent with
- DriveDetector + lifecycle race introducing a second drive_id assignment without terminating the first
- Two emitter threads/processes running concurrently on the Pi during the 23 → 24 transition window
- A buffer-flush condition that re-routes mid-flight samples to a freshly-spawned drive_id while the original drive_id stream continues

Spool flagged these three as candidate hypotheses without asserting; concur with that discipline.

## 3. System impact

- **`drive_summary` rows 30 + 31 both exist** and aggregate the same physical leg with conflicting values.
- **`drive_statistics` per-PID rows for summary_id 30 + 31** independently compute MIN/MAX/AVG/COUNT over the parallel streams — neither row is wrong by its own definition, but together they double-count the leg and disagree about the leg's character.
- Any downstream consumer that filters by `drive_id` or counts drives will double-count this leg.
- Spool's FLAG-4 re-validation against Drive 11/15/18 baselines is exposed if it touches the 23/24 pair — workaround: collapse 23+24 to one logical leg in his analysis pending the fix.

## 4. Why this is NOT chain-blocking (CIO-ratified disposition)

| Factor | Read |
|---|---|
| Server compute path correctness | **Intact** — aggregates whatever Pi attributes; B-104 Step 1 architecture sound. |
| Bug scope | **Bounded** — 1 pair across all historic data; current idle (drive 25) is clean. |
| Tier locus | **Upstream of B-104 Step 1** — Pi DriveDetector/lifecycle, not server compute. |
| Discovery path | **The discipline-loop worked** — Spool deeper than my own first read; surfaced *before* main merge. |
| Alternative cost | Holding chain = Sprint 42 hotfix = risks reasserting "drill-revealed-issue → spin a sprint" loop just escaped |
| RCA tractability | High — clear evidence + clear suspect surface (DriveDetector + US-351 revert) |

**Chain merges with the architecture validated. The defect is named in the merge commit, queued at V0.28.0 top priority, and gated by a tripwire pre-condition.** Main = fully validated stable AS DESIGNED, with a known scoped exception logged. The discipline survives only if we name what we know.

## 5. Pre-conditions on the chain-merge (Atlas to Marcus)

1. **Chain-merge commit message documents the carve-out** — names drive 23/24 dual-attribution + points to this finding + names the V0.28.0 B- item. Honest, not silent.
2. **B- item filed pre-merge** (Marcus's surface) with concrete V0.28.0 scope: (a) reproduce, (b) RCA, (c) fix DriveDetector + lifecycle, (d) regression test Pi-side AND server-side.
3. **Tripwire pre-V0.28.0-fix** (V0.28.0 sprint 1 alongside RCA): server-side compute path detects overlapping drive_ids and either flags `data_quality='attribution_anomaly'` carve-out on both rows or refuses to compute the pair. Pipeline does not silently produce double-counted analytics post-V0.28.0 deploy.
4. **Regression manifest discipline holds** — Spool's F-008/F-011/F-012 manifest HOLD stays in place; F-005 + F-007 re-validation that Argus offered also HOLDS until the V0.28.0 tripwire lands.

## 6. Separate (smaller) flag from Spool — schema-clarity smell

Spool surfaced separately (correctly factored out from dual-attribution):
- `drive_summary.drive_id` is NULL for all new-compute-path rows (drives 11-24 except drive 20).
- `drive_statistics.drive_id` is actually `summary_id` (FK to `drive_summary.id`), not natural Pi `drive_id`.

Survives B-104 Step 1 functionally because the join works via id, but the column naming will bite future authors. **V0.28 B-076 schema-normalization territory**, not chain-blocking. Worth weaving into V0.28.0 grooming as a coherent unit with the dual-attribution fix (same surface area).

## 7. Acknowledgement of my own miss

My Watch List A-9 disposition this morning ("benign segmentation glitch / V0.28+ hygiene") was **too soft**. Spool's deeper look (per-second RPM sampling + cadence analysis) refutes the "benign" framing — this is data-attribution corruption, not signal noise. A-9 upgraded to High severity + re-framed as "DriveDetector dual-emission defect."

The discipline-loop is what saved us: agents independently dig deeper when something doesn't fit; the truth surfaces before main lands. Three deeper-dives in one chain-merge cycle now — Argus on F-7, Spool on Finding C → F-8, Spool on dual-attribution. The loop is the engine. Keep it holding.

---

— Atlas
