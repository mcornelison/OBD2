# State of the System — Sprint 32 Grooming Brief

**Date**: 2026-05-11
**Author**: Tester agent (evidence-based; live Pi + chi-srv-01 + DB inspection this session)
**Purpose**: One-page-ish snapshot for Sprint 32 (V0.27.6) grooming/execution and V0.27.7+ planning. Consolidates: `2026-05-11-v0.27-chain-validation-status.md`, `2026-05-11-regression-manifest-rewalk.md`, `2026-05-11-drive-11-validation-checklist.md`, and the gap/PM files of the same date.

---

## 1. Executive summary

The system is **healthy and deployed at V0.27.5** on both nodes. The V0.27 chain (Sprints 28-31 / V0.27.2-.5) is sound on everything that can be checked from code, tests, and the live system — but it has **one un-IRL-validated headline regression (F-005: `drive_summary` writer not firing on `drive_end`)** and a cluster of fixes that are *deployed but never exercised by a real drive*. The single thing standing between "deployed-awaiting-validation" and "merge the chain to main" is **B-063** (the Pi's undersized stereo-USB-C power feed) → one clean car-coupled drive ("Drive 11"). B-063 is **not yet done** (power-source flicker still visible in the logs today); CIO says the fix is imminent. Sprint 32 (V0.27.6) is correctly scoped at the data-hygiene + tooling backlog Spool surfaced 2026-05-11; none of it is drive-blocked. Two small bugs the Tester found are ticketed; nothing requires re-work of shipped V0.27 stories.

**For grooming:** Sprint 32 as scoped is good. Watch-items for V0.27.7+ planning: (a) the contingency if Drive 11 shows F-005 still broken; (b) B-066 (self-update IRL drill) should be queued near B-063; (c) two small Tester-found bugs (`chain_validate_aggregate.py` double-count; `pytest tests/` 2 Windows failures + `make lint` red) — minor, slot when convenient.

---

## 2. The one critical path

```
B-063 (CIO: fuse-box buck converter, replaces stereo-USB-C feed)
   └─> Drive 11 (first clean car-coupled drive on stable power)
         ├─> validates F-005 (drive_summary INSERT on drive_end + 12-field metadata) — US-304/US-310
         ├─> validates F-007 (sync round-trip post-V0.27.4) — US-314/US-315/US-317
         ├─> validates US-311 (DriveDetector warm-restart, I-019)
         ├─> produces the full FORENSIC journal trail — US-319
         └─> if all green → /sprint-validated on Sprints 28-30 → /chain-validated → V0.27 merges to main
   └─> also unblocks the original "every key-on = Pi power-on" model
         └─> B-066 (B-047 self-update IRL drill) becomes both possible AND urgent (power-on update trigger fires every car start; safety preconditions load-bearing) — validates F-013/F-014
```

Run `2026-05-11-drive-11-validation-checklist.md` the moment Drive 11 lands. **If F-005 is still broken after Drive 11, that's a V0.27.7 bug-fix sprint** (the V0.27.2/.3 drive_summary fixes didn't hold) — worth pre-acknowledging in grooming as a possible branch.

---

## 3. System health (verified live 2026-05-11)

| Item | State |
|---|---|
| Pi (chi-eclipse-01, 10.27.27.28) | UP, `eclipse-obd.service` active since 07:32 CDT, deployed **V0.27.5** (`bb744d1`). Reconnect heartbeat alive; FORENSIC instrumentation emitting; OBD connect failing as expected (engine off). Hostname still `Chi-Eclips-Tuner`. |
| chi-srv-01 (10.27.27.10) | UP, `obd-server.service` active since 07:24 CDT, running the V0.27.5 NAS checkout (`/mnt/projects/O/OBD2v2` = this repo). MariaDB `obd2db` (11.8.6) reachable. |
| `pytest tests/` (Windows dev box) | ~4147 pass, **2 fail** — both `@slow @integration` simulator tests, neither a feature regression (boot_id ERROR on a non-Linux platform; simulator second-resolution timestamps). |
| `make lint` (ruff) | **RED — 16 errors, all auto-fixable** (debt outside the files Ralph touches each iteration). `ruff check … --fix` clears it. |
| `validate_config.py` | green |
| B-063 power feed | **still active/unfixed** — Pi `power_log` shows power-source flicker (`transition_to_ac`/`transition_to_battery`) ~70/day on 2026-05-10, ~23 already on 2026-05-11, vs ~10-15/day on calm days |

---

## 4. Feature status (the 14-feature regression manifest, re-walked)

`pm_regression_status.py` today: **10 OK / 0 STALE / 4 NEVER.** With Tester corrections:

| Status | Features | Notes |
|---|---|---|
| **Working, fresh, no action** | F-001 (Pi boot), F-009 (reconnect) | re-confirmed live this session |
| **Working, 3 days old, re-confirmed on Drive 11** | F-002 (OBD handshake), F-003 (RPM flow), F-004 (drive_start), F-006 (realtime_data), F-010 (DTC retrieval) | not stale; last real evidence Drives 6+7 (2026-05-08) |
| **Working — UNDER-RATED in the manifest** | F-008 (staged shutdown), F-011 (stage latching), F-012 (vcell columns) | fresher evidence exists: Drain Test 16 (2026-05-10), not Drain 8 (2026-05-08). Recommended manifest bumps filed for PM. |
| **Mechanism works; fix-validation pending** | F-007 (sync delta-push) | Pi pushed a `connection_log` delta to the server live; `battery_health_log` row 16 UPDATE-synced; dual-cursor populated. The fresh-drive round-trip + V0.27.4 drive_summary/drive_counter UPDATE fixes still pending Drive 11 (partly blocked by F-005). Leave `null`, refresh wording. |
| **REGRESSED — live, deployed-not-exercised** | F-005 (drive_summary on drive_end) | Pi `drive_summary` has drives 2-5 only; 6-10 missing; metadata NULL. V0.27.2/.3 fixes deployed, never hit a real `drive_end`. **The headline.** |
| **NEVER — synthetic only, gated on B-066** | F-013 (Pi self-update), F-014 (auto-rollback) | accurate. Recommend B-066 near B-063. |

---

## 5. Open work, by bucket

### Already in Sprint 32 / V0.27.6 (no grooming action needed — confirmed it matches reality)
Sprint 32 absorbs Spool's 2026-05-11 audit. Tester corroborated every underlying DB fact:
- **US-320** add `pymysql` to `requirements-server.txt` (I-022) — **already shipped (`passed`)**. Closes the calibration-CLI crash.
- **US-321** remove the phantom `sqlite:///data/server_crawl.db` fallback in `scripts/report.py` (I-023) — pending. (CIO Option A recommended by Spool: make `--db-url`/`DATABASE_URL` required.)
- **US-322** Pi `realtime_data` NULL-`drive_id` orphan cleanup (B-072) — pending. (61,293 orphan rows confirmed Pi-side; noise not poison — analytics filter `drive_id IS NOT NULL` already.)
- **US-323** server `battery_health_log` backfill of stranded rows 11-15 (B-073) — pending. (Confirmed: server rows 11-15 have `end_timestamp=NULL`; Pi has the closed values. One-off `UPDATE`.)
- **US-324** build the production `drive_statistics` writer (I-024) — pending. (Confirmed: server `drive_statistics`=0; nothing fires for it; `proposeCalibration()` joins through it, so calibration needs this + ≥5 real drives. Also: server has 3 ghost `drive_summary` shells id 12/13/14 — low-pri cleanup, Spool said *not* for V0.27.6.)

### Blocked on CIO hardware — not sprint-able
- **B-063** fuse-box buck converter → Drive 11. Everything in §2 hangs off this.
- **B-066** B-047 self-update IRL drill (CIO + PM cooperative). Validates F-013/F-014. Recommend queuing right after B-063.

### Tester-found, not yet ticketed (minor — slot when convenient)
- `chain_validate_aggregate.py` double-counts the active sprint when `sprint.json`'s `currentVersion` matches an archived sprint's (the post-deploy/pre-groom window — exactly when `/chain-validated` runs). ~3-line fix + 1 test. Gap: `gaps/2026-05-11-chain-validate-aggregate-double-count.md`. Worth fixing before the first real `/chain-validated` (i.e. before the V0.27 chain merge).
- `pytest tests/` 2 Windows failures (boot_reason ERROR-level log on non-Linux; simulator timestamp granularity) + `make lint` RED (16 auto-fixable). Gap: `gaps/2026-05-11-windows-simulator-test-failures.md`. Could be a single XS "test/lint hygiene" item, or folded into a future bug-fix sprint.

### Watch-item for V0.27.7+ (contingency)
- If Drive 11 shows `drive_summary` still not writing on `drive_end` → the V0.27.2/.3 fixes didn't hold → V0.27.7 dedicated to F-005. Same bug class as Sprint 19 US-237 and the original B-059. Pre-acknowledge so it's not a surprise.

---

## 6. Grooming recommendations

1. **Sprint 32 as scoped is good** — it's the right backlog (data hygiene + the calibration-CLI tooling chain), and it's all non-drive-blocked, so Ralph can keep moving while B-063 sits with CIO. No re-grooming needed.
2. **Don't expand Sprint 32** to chase Drive-11-blocked work — there's nothing useful to add there until the hardware lands.
3. **Pencil in V0.27.7** as the contingency landing zone for: (a) F-005 if Drive 11 fails it, (b) the `chain_validate_aggregate.py` double-count, (c) the test/lint hygiene. If Drive 11 passes F-005, V0.27.7 can be light (just b + c) or skipped.
4. **Ask CIO** to slot B-066 (self-update IRL drill) on the calendar near B-063 — they're synergistic (post-fuse-box, the power-on update trigger fires on every car start, so F-013/F-014 go from "synthetic only" to "exercised every drive, needs to be right").
5. **When B-063 + Drive 11 land** → Tester runs the Drive-11 checklist, reports pass/fail per `bigDefinitionOfDone` clause; if green, PM runs `/sprint-validated` on Sprints 28-30 then `/chain-validated` (after the aggregate dedup fix). The Drive-11 checklist already maps every FORENSIC token / DB row to the clause it closes.
6. **Manifest edits** (filed in `pm/issues/2026-05-11-from-tester-regression-manifest-rewalk.md`): bump F-008/F-011/F-012 to 2026-05-10 / Drain Test 16, refresh F-007 wording, optionally bump F-001 to V0.27.5. Low priority but keeps the freshness alarms honest.

---

## Appendix — key live numbers (2026-05-11)

| | Pi (`obd.db`) | Server (`obd2db`) |
|---|---|---|
| `drive_summary` | 4 rows (drives 2/3/4/5; metadata NULL) | 3 rows (ghost shells id 12/13/14, NULL `drive_id`, `is_real=0`) |
| `drive_statistics` | (no such table) | 0 |
| `baselines` | — | 0 (never calibrated) |
| `realtime_data` | 102,816 (drives 2-10 = 41,523; 61,293 NULL-`drive_id` orphans) | 41,682 (drives 3-10 + ~2k recent NULLs) |
| `drive_counter.last_drive_id` | 10 | 3 (stale; advances on next sync round-trip) |
| `battery_health_log` | 16 rows; 11-16 closed with runtime_seconds + vcell columns; rows 1 & 9 known-OPEN | 16 rows; rows 11-15 stranded (`end_timestamp=NULL`); row 16 closed via US-315 UPDATE-sync |
| `startup_log` | 11 rows; latest 2026-05-11 07:27 boot `prior_boot_clean=1`; mix of 0/1 historically (graceful-detection discriminates) | (Pi-only table) |
| `connection_log` | 32,340 rows; `connect_success`=13, `disconnect`=2,793; syncing live | 3,668+ rows; `drive_start`=9 / `drive_end`=8 |
| `sync_log` / `sync_history` | `connection_log` last synced 2026-05-11T16:06Z; `battery_health_log` `last_synced_modified_at` populated (dual-cursor) | `sync_history`=17,097 rows |
| `power_log` | `stage_warning`=16 / `stage_imminent`=14 / `stage_trigger`=12 (one each per drain, monotonic); power-source flicker ~70/day 2026-05-10 (B-063) | (Pi-only table) |
