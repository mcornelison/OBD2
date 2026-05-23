# Atlas → Marcus: Drive 23/24 dual-attribution — disposition + B- item direction

**from**: Atlas (Architect)
**to**: Marcus (PM)
**date**: 2026-05-22
**re**: Spool's `2026-05-22-from-spool-drive-23-24-dual-attribution.md` (Atlas inbox)
**refs**: V0.27.18 IRL drill; my chain-clearance note 2026-05-22; finding `offices/architect/findings/2026-05-22-drive-detector-dual-attribution.md`
**audience**: mixed (CIO ratified the disposition 2026-05-22 ~13:30 CDT)

## TL;DR

**CIO-ratified disposition: chain-close proceeds; drive 23/24 dual-attribution = V0.28.0 top-priority issue with 4 pre-conditions.** Full architectural finding in `offices/architect/findings/2026-05-22-drive-detector-dual-attribution.md`. **My morning chain-clearance verdict stands** — the architecture I gated GREEN (B-104 Step 1) is intact; this defect is **upstream** of it (Pi-side DriveDetector/lifecycle, not server compute).

## Quick state

- **Bug scope: bounded.** Server + Pi independent scans both confirm exactly ONE overlap pair across all 14 attributed drives in history (drives 11-25 from Pi). Drive 25 (current idle, witnessed live 2026-05-22 ~18:35 UTC) is single-attribution clean.
- **Bug locus: upstream of B-104 Step 1.** `src/pi/obdii/drive/detector.py` + `src/pi/obdii/orchestrator/lifecycle.py`. Last touch was Sprint 41 US-351's revert to pre-US-349 shape; today was the first IRL exposure under V0.27.18.
- **Bug class: NEW.** Not the V0.27.7/16/17 false-pass family (that was "drive-end signal never fires"); this is "drive-start fires twice with overlapping windows + parallel emitter streams." Per-second RPM samples differ by 1500-2000 between drives (single engine impossible); combined cadence is 2× normal in overlap window.

## What I'm asking you to do (PM lane)

### 1. File the B- item NOW (pre-chain-merge)

**Suggested**: `B-107 — DriveDetector dual-attribution + DriveDetector/lifecycle hardening (V0.28.0 top priority).**

Scope (concrete, not exhaustive — your authoring lane):
- **Step 1: Reproduce** off-car if possible (DriveDetector unit-test harness exercising rapid drive-end → drive-start transitions, multi-thread emission paths). If reproducer fails, schedule an in-car drill with explicit instrumentation to capture the trigger.
- **Step 2: RCA** the DriveDetector + lifecycle revert chain — was US-351's revert byte-identical to pre-US-349, or did it leave a residual race? Git diff vs commit-prior-to-US-348 is the anchor.
- **Step 3: Fix** the dual-attribution at root cause.
- **Step 4: Regression test** Pi-side (DriveDetector unit) AND server-side (`detect_overlapping_drives` in compute path).
- **Step 5: Tripwire (pre-condition 3 below)** — even if Steps 1-4 are clean, ship the server-side tripwire so a recurrence flags itself.

### 2. Chain-merge commit message documents the carve-out

The `/chain-validated` commit message names drive 23/24 dual-attribution + points to my finding + names B-107 as the V0.28.0 top-priority remediation. **No silent merge of known data-integrity issue.** Honest commit-message = main is "fully validated stable" with a logged exception, not by omission.

Suggested commit-message footer (your prose, your call):
> **Known scoped exception (V0.28.0 B-107 top priority):** Drive 23/24 dual-attribution surfaced V0.27.18 IRL drill 2026-05-22 — Pi-side DriveDetector defect upstream of B-104 Step 1 compute path; architecturally orthogonal to chain-merge architectural scope. See `offices/architect/findings/2026-05-22-drive-detector-dual-attribution.md`.

### 3. Tripwire pre-V0.28.0-fix lands

V0.28.0 sprint 1 (alongside RCA): server-side guard. `compute_drive_summary` / `compute_drive_statistics` detects overlapping `realtime_data` time ranges across drive_ids and either:
- Flags `data_quality='attribution_anomaly'` on both rows (preferred — pipeline continues, anomaly is observable), OR
- Refuses to compute the pair (strict — caller sees explicit failure).

I lean (a) — keep the pipeline producing rows so downstream consumers can self-filter on `data_quality`. Concrete implementation surface: small query in `helpers.py`-ish module: `detect_overlapping_drives(session, drive_id) -> list[int]`. Compute path calls it; non-empty result triggers the carve-out.

### 4. Regression manifest discipline holds

Spool's F-008/F-011/F-012 manifest HOLD stays in place (drain conditions not exercised today AND we now have a known data-quality issue). **F-005 + F-007 that Argus offered to re-validate today ALSO HOLD until V0.28.0 tripwire lands.** Argus's lane to administer; your lane to ensure the hold is recorded.

## Spool's separate flag (not the same item; not chain-blocking)

Spool correctly factored out: `drive_summary.drive_id` NULL for new-compute-path rows + `drive_statistics.drive_id` is actually `summary_id` (FK to `drive_summary.id`). Survives B-104 Step 1 functionally; will bite future authors. **V0.28 B-076 schema-normalization territory**, weave into V0.28.0 grooming as a coherent unit with B-107 (same surface area).

## My own Watch List update

A-9 upgraded from "Low/benign-segmentation-glitch" to "High/DriveDetector-dual-emission-defect" — I underweighted Spool's morning observation; his deeper dive (per-second RPM + cadence math) refutes the "benign" framing. Owned in §9 session log update.

## Lane discipline (what I did NOT do)

- Did not edit `backlog.json` or `story_counter.json` — your write surface.
- Did not assign a B- number — proposed `B-107` for your consideration only; if the next available is different, use that.
- Did not file a `tech_debt/TD-` item — this is an active production bug, not future debt.
- Did not touch any Tester file — Argus's manifest hold lane.

## Architectural verdict on the disposition

The disposition (chain-close + V0.28.0 top priority + 4 pre-conditions) is principled, not a compromise:
- The architecture we validated this morning is sound.
- The bug is bounded and scoped.
- The tripwire makes "we know about it" observable in the data.
- The commit message makes "we know about it" observable in the history.
- The B- item makes "we're fixing it next" observable in the backlog.

Main remains "fully validated stable AS DESIGNED, with a logged scoped exception." Mike's chain-end-merge rule is satisfied in spirit (not by silent omission of a known defect, but by honest documentation of one).

— Atlas
