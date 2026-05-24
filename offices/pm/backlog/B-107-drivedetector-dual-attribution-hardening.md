# B-107: DriveDetector Dual-Attribution + Pi-Side Drive Lifecycle Hardening (V0.28.0 TOP PRIORITY)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | **HIGH (V0.28.0 TOP PRIORITY)** -- CIO-ratified 2026-05-22 ~13:30 CDT per Atlas disposition; filed pre-chain-merge so `main` carries the known-scoped-exception in commit history, not by silent omission |
| Status       | Pending (V0.28.0 sprint 1 candidate; tripwire ships in same sprint per Atlas pre-condition 3) |
| Category     | pi / lifecycle / data-integrity |
| Size         | M (RCA + fix + regression tests on both Pi + server sides + server-side tripwire) |
| Related PRD  | None yet; primary architectural finding at `offices/architect/findings/2026-05-22-drive-detector-dual-attribution.md`; supporting evidence in Spool's 2026-05-22 dual-attribution + capability-probe notes |
| Dependencies | V0.27.18 / `/chain-validated` to main lands first (this item ships in V0.28.0); no software dependencies but coordinates with B-076 V0.28 schema-normalization epic + Spool's drive_summary.drive_id NULL + drive_statistics.drive_id=summary_id smell |
| Created      | 2026-05-22 (CIO directive following V0.27.18 IRL drill 2026-05-22) |

## Description

**Bug class: NEW** (not the V0.27.7/16/17 false-pass family that B-104 Step 1 closed). Drives 23+24 from V0.27.18 IRL drill recorded as **two parallel emitter streams of the same physical leg**, not segmentation of a single stream:

- Start times 3 seconds apart (14:43:40 + 14:43:43)
- Overlap window: 14:43:40-14:50:14 (~6m 30s)
- Per-second RPM samples differ by 1500-2000 between drive_ids at identical/adjacent seconds (single engine impossible)
- Combined RPM sample rate during overlap = ~1 sample / 1.55s = **2× normal Pi cadence**

**Locus**: `src/pi/obdii/drive/detector.py` + `src/pi/obdii/orchestrator/lifecycle.py`. Last touch was Sprint 41 US-351's revert to pre-US-349 shape — first IRL exposure under V0.27.18.

**Scope: BOUNDED.** Independent server-side + Pi-side scans both confirm exactly ONE overlap pair across all 14 attributed drives in history (drives 11-25 from Pi). **Drive 25 (current idle, witnessed live 2026-05-22 ~18:35 UTC) is single-attribution clean** — confirms bounded artifact in historical data, not an ongoing emission defect. CIO confirmed Drive 25 telemetry showed no ghost / duplicate RPM signals.

**Bug locus is UPSTREAM of B-104 Step 1.** Server compute path correctly attributes whatever drive_ids the Pi assigns; both drive 23 + drive 24 segments have valid analytics on their respective data. Architecturally orthogonal to the V0.27.7/16/17 false-pass class B-104 Step 1 structurally closed.

## Why this item exists pre-chain-merge (instead of being filed post-merge)

Per CIO-ratified Atlas disposition: `main` becomes "fully validated stable AS DESIGNED, with a **logged scoped exception**." The chain-merge commit documents this defect, points to Atlas's architectural finding, and names B-107 as the V0.28.0 top-priority remediation. **No silent merge of a known data-integrity issue.** Honest commit-message = main is fully validated stable with a logged exception, not by omission. This filing carries the audit trail.

## Acceptance Criteria

### Step 1 -- Reproduce

- [ ] DriveDetector + lifecycle unit-test harness exercises rapid drive-end → drive-start transitions with multi-thread emission paths
- [ ] If unit-test reproducer fails to surface the defect: schedule an in-car drill with explicit instrumentation (logging thread-id + emission seam + timestamp on every realtime_data row) to capture the trigger condition
- [ ] Drive 23/24 evidence (RPM/timestamp delta, parallel emission cadence) reproduced in test fixture

### Step 2 -- RCA

- [ ] `git diff` US-351 revert against commit-prior-to-US-348 documents whether the revert was byte-identical to pre-US-349 OR left a residual race
- [ ] If revert was clean: explain why pre-US-349 code was emission-safe but V0.27.18's iteration of it isn't (possible vectors: orchestrator thread interaction differences, V0.27.16-introduced upstream timing changes, lifecycle ordering shift)
- [ ] RCA documented in fix commit message + cross-referenced in Atlas's finding doc

### Step 3 -- Fix

- [ ] Root-cause fix to DriveDetector / lifecycle preventing dual-emission
- [ ] No regression in B-104 Step 1 compute path (server-side analytics still consume whatever Pi emits cleanly)
- [ ] Pi-side `drive_statistics` table stays retired per US-351 (no resurrection)

### Step 4 -- Regression test (BOTH tiers)

- [ ] Pi-side: DriveDetector unit test asserting single-attribution for a synthetic rapid-transition scenario
- [ ] Server-side: `detect_overlapping_drives(session, drive_id) -> list[int]` exists in compute path
- [ ] Server-side: regression test fixture seeds drives 23+24 historical overlap; tripwire fires + flags `data_quality='attribution_anomaly'` on both rows (Atlas-preferred option (a) per disposition)
- [ ] Server-side tripwire: pipeline continues producing rows so downstream consumers can self-filter on `data_quality`

### Step 5 -- Tripwire (PRE-CONDITION 3, Atlas disposition)

- [ ] V0.28.0 sprint 1 ships server-side tripwire ALONGSIDE Steps 1-4 (not after; Atlas pre-condition explicit)
- [ ] Even if Steps 1-4 are clean, the tripwire ensures any recurrence is observable in the data, not silent
- [ ] `compute_drive_summary` / `compute_drive_statistics` invoke `detect_overlapping_drives`; non-empty result triggers carve-out

### Step 6 -- Backfill historical anomaly

- [ ] Drives 23+24 in chi-srv-01 `obd2db` get retroactive `data_quality='attribution_anomaly'` set
- [ ] Drive 25+ on new ECU re-checked for anomaly absence (Spool's witnessed-live read; codify the check)

## Validation Script Requirements

- **Input**: Production database state with drives 11-25 ingested; new V0.28.0 deploy lands B-107 fix + tripwire
- **Expected Output**: After v0010+ migration runs, `SELECT drive_id, data_quality FROM drive_summary WHERE drive_id IN (23, 24)` returns both with `data_quality='attribution_anomaly'`; same for `drive_statistics` rows where applicable. All other drives keep their existing `data_quality` value.
- **Database State**: `attribution_anomaly` becomes a valid `data_quality` enum value (CHECK constraint update via v0010+ migration); compute path's tripwire writes it idempotently
- **Test Program**: `python -m server.cli.recompute_drive_analytics --drive-id 23` produces the anomaly flag; idempotent re-run identical (per US-350 idempotency pattern)
- **Reference**: Drive 25 single-attribution clean state remains `data_quality='full'` post-recompute

## Cross-references

| Item | Relationship |
|---|---|
| **Atlas's finding doc** `offices/architect/findings/2026-05-22-drive-detector-dual-attribution.md` | Primary architectural source; cited in chain-merge commit footer |
| **Spool's 2026-05-22 dual-attribution note** (filed to Atlas + PM inboxes) | Evidence anchor (per-second RPM + cadence math); not the RCA per Spool's 2026-05-15 hypothesis-discipline lesson |
| **B-076 V0.28 schema normalization epic** | One coherent V0.28 schema pass touches B-076 + B-107 + Spool's `drive_summary.drive_id NULL + drive_statistics.drive_id=summary_id` smell + ECU-lineage `vehicle_info.ecu_signature` field. Same surface area. |
| **B-104 Step 1** (server compute path) | Architecturally orthogonal; B-107 tripwire calls into compute path but does not modify the core compute logic |
| **TD-055** | US-355's deferred-work item (harness-vs-applied-migrations); 4th-cycle bug class defense-in-depth. If TD-055 also lands in V0.28.0, B-107's tripwire gets the defense-in-depth-(3) coverage |
| **TI-009 (Argus)** | Argus's tester-side gap entry naming this same defect; B-107 closes it on V0.28.0 land |

## Notes

- **CIO Drive 25 observation 2026-05-22**: "no ghost or duplicate RPM signals" — supports the "bounded artifact in historical data" framing, not an ongoing emission defect. Backfill of drives 23+24 is the immediate data-integrity remediation; root-cause fix prevents recurrence.
- **PM Rule 10 design-gate territory** — touches Pi-side lifecycle (load-bearing subsystem); `specs/architecture.md` update owed in-sprint per the design-gate DoD pattern that landed §10.6 (Sprint 39) + §10.7 (Sprint 41).
- **Honest scope per Atlas disposition**: this is an active production bug, not future tech debt (TD-). Filed as B- (backlog) not TD-.
- **Sprint 41 US-351 contributed locus** (revert chain to pre-US-349 shape). B-107 RCA must trace whether the revert itself was byte-identical or introduced a residual race. Per Atlas: `git diff sprint/sprint41-bugfixes-V0.27.17:src/pi/obdii/drive/detector.py <commit-prior-to-US-348>:src/pi/obdii/drive/detector.py` is the anchor diff.
- **Filed per CIO 2026-05-22 directive in PM Session 42** as pre-chain-merge pre-condition #1. Story drafting belongs in V0.28.0 PRD grooming; the B-item captures the high-level scope.
