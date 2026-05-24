# Calibration CLI blocked — `pymysql` missing from requirements + phantom sqlite fallback
**Date**: 2026-05-11
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important — blocks Mike's ability to actually run calibration locally; does NOT block V0.27.4 deploy itself.

## Context

Mike ran `python src/server/analytics/calibration.py --calibrate --apply` tonight as the US-316 IRL smoke test. Exit zero, no errors. That **is** a valid US-316 pass — the PYTHONPATH bootstrap Rex shipped resolves imports correctly. But the script has no `__main__` block (the CLI lives in `scripts/report.py`), so it was a no-op — args ignored, baselines untouched.

I followed up by running the actual CLI: `python scripts/report.py --calibrate --device chi-eclipse-01`. **It crashes.** Two independent issues surfaced; both are real bugs that should land in Sprint 32 / V0.27.6.

## Findings

### Bug 1 (P1) — `pymysql` is required at CLI runtime but not declared in requirements

`scripts/report.py:92-95` defines `_toSyncDriverUrl()` which rewrites the async DATABASE_URL (`mysql+aiomysql://...`) into the sync form (`mysql+pymysql://...`) for CLI use, because SQLAlchemy's sync engine can't drive aiomysql. The rewrite is correct and intentional.

But `requirements-server.txt` only declares `aiomysql>=0.2.0`. There is **no** `pymysql` entry. So on any system that follows the documented install (`pip install -r requirements-server.txt`), invoking `scripts/report.py --calibrate` blows up at engine creation:

```
File ".../sqlalchemy/dialects/mysql/pymysql.py", line 89, in import_dbapi
    return __import__("pymysql")
ModuleNotFoundError: No module named 'pymysql'
```

This affects **every CLI report path**, not just calibration — `--drive`, `--trends`, and `--calibrate` all flow through the same `_toSyncDriverUrl` path. Mike has been running drive reports manually all sprint long; either he has pymysql installed by hand and didn't realize it was undocumented, OR he hasn't actually been running these locally and the gap stayed silent.

### Bug 2 (P3, related) — `_DEFAULT_DB_URL_FALLBACK` points at a sqlite file with empty schema

`scripts/report.py:89` defines:
```python
_DEFAULT_DB_URL_FALLBACK: str = "sqlite:///data/server_crawl.db"
```

The fallback fires when `DATABASE_URL` env var is unset and `--db-url` isn't passed. I tested it tonight: `data/server_crawl.db` exists (1.1 KB or so) but has **no `drive_summary` table** — it's an empty skeleton. Any CLI command using the fallback crashes with `sqlite3.OperationalError: no such table: drive_summary`.

This isn't a hot bug (production sets DATABASE_URL), but it's a confusing "phantom fallback" — the docs imply local sqlite works for dev/testing, but it doesn't unless someone separately seeds it via `scripts/load_data.py`. Either the fallback should be removed (force explicit `--db-url`), or `scripts/load_data.py` should be a documented prerequisite, or the fallback should point at the actual test-fixture sqlite.

## Recommended Fix (Sprint 32 / V0.27.6 candidate)

### Story A — `add-pymysql-to-server-requirements` (XS, P1)

**Scope:** 1 file.
- `requirements-server.txt` — add `pymysql>=1.1.0`

**Acceptance:**
1. `grep "^pymysql" requirements-server.txt` returns a versioned line.
2. From a clean venv with only `pip install -r requirements-server.txt` run, `python scripts/report.py --calibrate --device chi-eclipse-01` no longer fails on `ModuleNotFoundError: No module named 'pymysql'` (it will get further — may or may not produce proposals depending on real-drive count, but the driver gap is closed).
3. Mod-history comment on `requirements-server.txt` cites US-XXX (V0.27.6 sprint story).

**Rationale for version pin:** pymysql 1.1.0 (Apr 2023) is the current stable. SQLAlchemy 2.x supports it. No newer breaking changes expected during Sprint 32.

**Why XS not S:** This is genuinely a one-line dependency add. No code changes. The only "investigation" is confirming the version pin matches whatever pymysql SQLAlchemy 2.x prefers (already done — 1.1.0 is the floor).

### Story B — `fix-calibration-cli-sqlite-fallback-or-remove` (S, P3)

**Scope:** 2 files (decision required).

**Decision needed from Mike (PM Option A/B/C):**

- **Option A:** Remove the sqlite fallback entirely. Make `--db-url` or `DATABASE_URL` env var required. `scripts/report.py:89` deletes `_DEFAULT_DB_URL_FALLBACK`; `_resolveDbUrl` raises `SystemExit(2)` with a clear message. Pro: no more phantom. Con: breaks any current ad-hoc test workflow that relied on the fallback (probably none).
- **Option B:** Keep the fallback but add a startup probe — if the sqlite file exists but has no `drive_summary` table, emit a friendly error suggesting `python scripts/load_data.py` first. Pro: preserves the "easy local dev" surface. Con: adds startup overhead and code path.
- **Option C:** Defer — file as TD only, no sprint slot. Mike's local workflow uses the production MariaDB anyway; this is a phantom for ad-hoc testers who don't exist yet.

**My recommendation:** Option A. The fallback is currently a footgun (crashes with an inscrutable SQL error). Mike never uses it. If a local dev workflow becomes needed later, we add it back with a real seeder.

**Acceptance (assuming Option A):**
1. `_DEFAULT_DB_URL_FALLBACK` constant removed from `scripts/report.py`.
2. Invoking `python scripts/report.py --calibrate --device chi-eclipse-01` with no DATABASE_URL env and no `--db-url` flag prints a clear error (`DATABASE_URL not set; pass --db-url or export DATABASE_URL`) and exits non-zero.
3. With DATABASE_URL set (Story A landed → pymysql works), CLI runs as expected.

## Sources

- `scripts/report.py:88-95` — driver-URL rewrite and sqlite fallback constants
- `requirements-server.txt` — current declared deps, no `pymysql` entry
- Tonight's run history (Spool session log, 2026-05-11):
  - `python src/server/analytics/calibration.py --calibrate --apply` → exit 0, no-op (US-316 narrow pass; args ignored, no `__main__`)
  - `python scripts/report.py --calibrate --device chi-eclipse-01` against MariaDB → `ModuleNotFoundError: pymysql`
  - Same against `--db-url sqlite:///data/server_crawl.db` → `OperationalError: no such table: drive_summary`

## Server DB state addendum (after Mike pointed me at the MariaDB CLI access path)

After hitting the pymysql wall, I went the documented SSH-to-chi-srv-01 + `mysql` CLI route (per `reference_chi_srv_01_obd2db_access.md`) to inspect the actual server state. **Calibration is gated on more than Story A** — there is nothing useful in the DB to calibrate from. Findings, all on chi-srv-01 / `obd2db`:

| Table | Row count | State |
|---|---|---|
| `baselines` | **0** | Never been calibrated. Empty. Consistent — no `--apply` has ever run. |
| `drive_summary` | **3** ghost rows | id=12/13/14, all from 2026-05-01 05:39:06Z. Every meaningful field NULL (`drive_id` NULL, `start_time` NULL, `duration_seconds` NULL, `is_real`=0 default, `row_count`=0). `source_id` = 3/4/5 / `source_device` = chi-eclipse-01 — these are stale pre-Session-10-cleanup shells for drives 3/4/5. |
| `drive_statistics` | **0** | Empty. (Session 10 cleanup dropped all 84 stale rows; nothing has been re-written since.) |

Pi-side spot-check (sqlite3 on chi-eclipse-01:/home/mcornelison/Projects/Eclipse-01/data/obd.db):

| Table | Row count | Detail |
|---|---|---|
| `drive_summary` | **4** | drive_id 2/3/4/5 only. **Drives 6, 7, 8, 9, 10 are missing — writer stopped firing after April 29 (drive_id=5).** Confirms the "drive_summary writer regression" filed as B-059 / fixed by US-310 in V0.27.3 (deployed 2026-05-10 but AWAITING IRL VALIDATION; B-063 fuse-box blocker means Drive 11+ hasn't happened yet). `ambient_temp_at_start_c` and `starting_battery_v` NULL on all 4 rows — the data fields were added by later user stories and never backfilled to the early drives. |

**What this means for the full picture:**

Even after Story A (pymysql) lands and the CLI works, `python scripts/report.py --calibrate --device chi-eclipse-01` will return **"Need 5 more real drives"** (`countRealDrives()` returns 0; `MIN_REAL_DRIVES=5`). Calibration is gated on:

1. **Story A** (V0.27.6) — pymysql in requirements-server.txt — unblocks the CLI
2. **B-063** — fuse-box buck converter — unblocks Drive 11+
3. **US-310 IRL validation** (V0.27.3 awaiting) — Drive 11+ has to produce a populated drive_summary row with `is_real=1`
4. **US-315 IRL validation** (V0.27.4 awaiting) — sync UPDATE has to push Pi-side row to server-side row with all fields populated
5. **drive_statistics writer** — has to fire on Drive 11+ and emit per-parameter rows (need to confirm this is wired; not clear if any current story owns this — flagging for Marcus)
6. **≥5 real drives accumulated** — Drive 11 alone won't trigger proposals; need at least 5 with `is_real=1` and populated `drive_statistics` rows tagged to each

The ghost shells (id=12/13/14) on the server-side `drive_summary` are also worth a cleanup pass at some point — they'd pollute calibration logic if `is_real` were ever flipped on them by accident. Not urgent (they're at default 0), but they're noise. Low-priority cleanup story candidate, **not for V0.27.6**.

**Question for Marcus**: is anyone tracking "drive_statistics writer fires on real drives"? I see `drive_statistics` in the schema and `proposeCalibration()` joins through it, but I don't see a sprint story owning that writer between US-310 (drive_summary 12-field) and US-315 (sync UPDATE delta). If there's no writer story, that's gap #5 above. Worth a story for V0.27.6.

## Deeper validation — narrows the regression, surfaces US-315 IRL evidence

After the addendum above I went one layer deeper on Mike's "anything else?" prompt. The picture is more positive than the headline implies, and **US-315 has early IRL validation evidence** (not from Drive 11 but from a drain).

### Realtime data writer + DriveDetector ID assignment: WORKING ✅

Pi-side `realtime_data` row counts per drive:

| drive_id | rows | matches MEMORY claim |
|---|---|---|
| 2 | 1,853 | — |
| 3 | 6,089 | idle test |
| 4 | 4,487 | idle test |
| 5 | 7,852 | idle test |
| 6 | 7,085 | ✓ Drive 6 |
| 7 | 4,222 | ✓ Drive 7 |
| 8 | **8,268** | ✓ matches MEMORY exactly (459 rows/min) |
| 9 | 1,095 | ✓ matches MEMORY exactly (36 rows/min — brownout) |
| 10 | 572 | ✓ Drive 10 garage maneuver |

**This narrows the regression significantly.** Drive 8's data integrity is verified — `knowledge.md`'s pre-mod baseline shelf claim is intact. The bug is **specifically the drive_summary roll-up writer**, NOT the broader telemetry pipeline. realtime_data writes, DriveDetector assigns IDs, drive_counter advances correctly (Pi `last_drive_id=10`). Only the per-drive summary row creation at drive_end is busted.

### NEW finding (P3): 61,293 NULL-drive_id orphan rows in Pi-side `realtime_data`

These accumulated SINCE Session 10's cleanup (which dropped ~58,885 NULL rows). Likely sources:
- Reconnect-loop polling (engine-off / no-ECU response moments)
- I-019 DriveDetector warm-restart-cranking gap (1,078 rows for the 5/9 around-the-block test alone)
- Pre-DriveDetector-start grace period rows

**Recommendation**: V0.27.6 candidate **Story C (P3, S)** — periodic cleanup task OR writer-side guard that drops engine-off polls before they hit realtime_data. Spool's tuning analytics filter on `drive_id IS NOT NULL` anyway, so the rows are noise rather than poison — P3 not P2.

### B-065 sync UPDATE gap directly observed AND US-315 (V0.27.4) shows positive IRL signal

Compared Pi-side and server-side `battery_health_log` for drain_event_ids 11-16:

| drain_event_id | Pi-side end_timestamp | Server-side end_timestamp | synced_at | Status |
|---|---|---|---|---|
| 11 (00:46Z) | ✓ 00:52:28 | NULL | 00:46:16 | **Stranded (pre-V0.27.4)** |
| 12 (01:12Z, 15s drain!) | ✓ 01:12:43 | NULL | 01:12:30 | Stranded |
| 13 (02:24Z) | ✓ 02:34:59 | NULL | 02:24:47 | Stranded |
| 14 (03:35Z, Drain Test 14) | ✓ 03:47:44 | NULL | 03:35:42 | Stranded |
| 15 (14:00Z, Drain Test 15) | ✓ 14:13:49 | NULL | 14:00:43 | Stranded |
| **16 (19:47Z)** | ✓ 20:00:46 | **✓ 20:00:46** | 19:47:17 | **CLOSED on both — US-315 working** |

The proof US-315 fixed it (not "INSERT happened to carry the close"):
- Row 16's `synced_at` is **19:47:17** — that's 2 seconds after start_timestamp, BEFORE the close at 20:00:46. So row 16 was INSERTed with end_timestamp=NULL just like rows 11-15.
- The close `end_timestamp=2026-05-10 20:00:46` was populated LATER via an UPDATE — exactly the new sync path US-315 added.
- (Implementation note: `synced_at` itself is INSERT-only — not bumped on UPDATE. Useful diagnostic for distinguishing "first arrival" from "last touch" in future audits.)

**Implication**: V0.27.4 US-315 has its FIRST IRL validation evidence — but ONLY for `battery_health_log` table. The drive_summary side of US-315 (sync UPDATE for drive_summary delta) still needs Drive 11+ for full validation. **This does NOT close US-315's bigDoD by itself** but it's strong directional signal. Update `regression_manifest.json` for F-007 only after Drive 11+ confirms drive_summary side too.

### NEW finding (P3): Historical drains 11-15 are permanently stranded on server unless backfilled

US-315 fixes the **forward** sync path. It doesn't auto-replay missed updates. So battery_health_log rows 11/12/13/14/15 will keep `end_timestamp=NULL` on the server forever unless something forces a re-sync.

**Recommendation**: V0.27.6 candidate **Story D (P3, XS)** — one-off backfill SQL run against server (`UPDATE battery_health_log SET end_timestamp = ..., end_soc = ..., runtime_seconds = ... WHERE id IN (11,12,13,14,15)` sourced from Pi-side current state). Trivial mechanical fix. OR fold into a more general "post-US-315 historical-row reconciliation" pass that also covers drive_summary once that side validates. Marcus's call.

### Real-time evidence of B-063 hardware blocker

Mid-investigation Pi went unreachable (`ssh: connect to host 10.27.27.28 port 22: Connection timed out`) and came back ~30 seconds later. That's the brownout / SSH-flake pattern B-063 is specifically about. Confirms B-063 isn't a stale concern — it's actively impacting ad-hoc work right now. The fuse-box buck converter swap remains the gate.

## What this means for V0.27.4 chain validation

US-316's bigDefinitionOfDone (per sprint.json) was narrow: "calibration.py runs to completion when invoked locally." That IS green — the bootstrap fix works. **No need to back out US-316 or amend V0.27.4.**

But the broader "Mike can actually run a calibration from his laptop" UX, which is what US-316 implies in plain English, is still broken downstream. V0.27.4 stays on the sprint branch (chain-end-merge rule); the V0.27 chain validation pass should NOT claim "calibration CLI works end-to-end" until Story A lands in V0.27.6 AND the chain validates AND ≥5 real drives accumulate on the server.

I'm logging this in `offices/tuner/sessions.md` as well. Drop me a line when Sprint 32 grooming kicks off if you want me to size these stories further or weigh in on Option A/B/C for Story B.

— Spool
