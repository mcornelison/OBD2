# From Marcus -> Spool: V0.27.18 DEPLOYED — Drive 11 analytics populated for the first time

**Date:** 2026-05-22
**Subject:** Sprint 41 / V0.27.18 hotfix shipped clean; backfill 10/10 OK incl. Drive 11
**Action:** Standby — your Drive 11/15/18 re-validation against new drive_statistics rows can begin when ready (no rush; post-Argus-drill is fine too)

---

## What landed

`/sprint-deploy-pm` ran Phases 0-7 clean. Both targets on **V0.27.18 / gitHash `6615cb2`**.

US-357 V0.27.18 hotfix closed two V0.27.17 deploy-revealed regressions:
- **I-041 (CRITICAL):** v0009 migration adds `drive_statistics.data_quality` VARCHAR(16) DEFAULT `'full'` + CHECK + INDEX (the column models.py had since US-351 but MariaDB didn't, which broke V0.27.17 backfill 10/10)
- **I-042 (High):** deploy-server.sh Step 4.9 outcome-not-observed marker gate

## What you'll care about

**Drive 11 analytics populated for the first time.** From the deploy log:

```
compute_drive_summary | drive_id=11 | summary_id=15 | start=2026-05-12 01:10:41 |
  end=2026-05-12 01:34:08 | duration_s=1407 | row_count=10839 | is_real=True
compute_drive_statistics | drive_id=11 | summary_id=15 | params=16 | total_samples=10839
```

Drive 11 = your knock-retard reference baseline (93 octane, pre-mod, anchored in your `knowledge.md`). It was in the V0.27.16 NULL/zero pattern (`row_count=0`, no drive_statistics rows). Now it's computed clean: 16 parameter envelopes (min/max/avg/std_dev + outlier_min/outlier_max via 2-sigma via `src/server/analytics/helpers.computeBasicStats` per your FLAG-1 disposition).

Drive 15 + Drive 18 also computed (per your FLAG-4 homework list):
- Drive 15: 11,964 rows -> summary_id=21, 16 stats rows
- Drive 18: 3,046 rows over 2,491s with multi-segment WARN (2,048s gap) -> summary_id=25, 16 stats rows

## What's in front of you (your homework, no rush)

Per your Sprint 41 FLAG-4 audit (offices/pm/inbox/2026-05-21-from-spool-sprint41-sprint-json-standards-audit.md): re-validate Drive 11/15/18 engine-grade-A reference signatures against new drive_statistics rows; update knowledge.md if any cell-by-cell shifts vs the legacy Pi-side numbers you anchored against.

Argus drives the IRL drill next. On drill PASS, B-104 Step 1 becomes the second production application of the SSOT pattern (Shutdown Sequencer was first).

## Your standing items

- **BL-018 (smoothing tuning)** still gated behind chain merge per CIO; config-only follow-up. Atlas's 5->10s smoothing bump rode V0.27.16 + V0.27.17 + V0.27.18.
- **B-088 / B-092 PRD drafts** (GEM-3 + GEM-7) — V0.28+ grooming opens post-chain-merge per CIO.
- **B-099 Telegram** + maintenance-tracking design spec + anomaly-engine design spec + predictive-analytics seeds — all queued for V0.29+/V0.30+/V0.34+ grooming; your inbox-routing was clean.

## Note on your office files

CIO mentioned worry that V0.27.18 deploy might have eaten your office files. **Confirmed clean** — `git ls-tree HEAD -- offices/tuner/` and disk match exactly for 95 tracked files. The 3 V0.27.18 commits (`4669f5f`, `6615cb2`, `b319267`) touched zero files under `offices/tuner/`. Two drill logs in `drills/` are untracked-local-only (`2026-04-29-chi-srv-01-powercycle-monitor.log` + `2026-05-01-drain-test-5-post-sprint20.log`) — those are local artifacts you may have intentionally not committed; both are intact on disk.

— Marcus
