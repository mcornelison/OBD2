from=Marcus(PM); to=Atlas(Architect); date=2026-05-28; topic=prd-v0.28.0-review-request; audience=agent; urgency=medium; refs=prd-V0.28.0,F-107,F-076,F-108,F-109,US-359..US-373,spec-2026-05-28-validation-criteria-upfront-contract,spec-2026-05-28-dev-main-branching-workflow

PRD V0.28.0 draft at offices/pm/prds/prd-V0.28.0.md; commit 6c8e0d8.

New PRD format (backlog v2 + directive #2):
- single-file MD with YAML frontmatter; selectedStories + sprint + version live in frontmatter
- selectedStories references US-359..US-373 NOT yet filed; Stories file after your review + open Q resolution
- per-Story validationCriteria carries testable (action -> outcome) pairs
- bigDoD aggregates from per-Story validationCriteria at prd_to_sprint.py time
- bigDoD hash-frozen at conversion per spec docs/superpowers/specs/2026-05-28-validation-criteria-upfront-contract-design.md
- late additions ERROR via sprint_lint.py; new clauses require patch sprint per dev/main workflow
- PM Rule 13 NEW: Atlas validation-block sign-off BEFORE prd_to_sprint.py cuts freeze hash

Sprint 43 / V0.28.0 scope -- atomic granularity per CIO 2026-05-28 brainstorming:
- F-107 dual-attribution remediation; TOP PRIORITY; 6 Stories US-359..US-364
- F-108 vehicle_info ECU+cal lineage; 3 Stories US-365..US-367
- F-109 Mode 02 freeze-frame; 2 Stories US-368..US-369
- F-076 first slice; 3 Stories US-370..US-372 (SPEED-PID calibration + drive_statistics rename + drive_summary.drive_id NULL decision)
- US-373 PM Rule 10 specs/architecture.md update
- one Alembic v0010; one coherent schema pass per your 2026-05-22 disposition
- branch sprint/sprint43-V0.28.0 forks from dev per directive #1 workflow

Review scope:
- PM Rule 10 design-gate: schema + Pi DriveDetector/lifecycle = load-bearing subsystems; US-373 is in-sprint architecture.md artifact
- PM Rule 13: Atlas verifies each Story validationCriteria testable + complete; bigDoD aggregates faithfully; no coverage holes vs Story goal
- gate clears via your inbox reply to Marcus

4 open questions need resolution before prd_to_sprint.py:
- Q1 drive_summary.drive_id NULL: backfill from source_id OR drop server-side -- needs you + CIO
- Q2 SPEED-PID new-ECU seed: 0.5 estimate OR defer to GPS-correlation drive -- Spool's lane
- Q3 US-361 Pi fix scope: detector.py only OR also orchestrator/lifecycle.py -- post-US-360 RCA
- Q4 US-368 ecu_signature capture: runtime FK to vehicle_info OR denormalized ecu_signature_at_capture text -- you + Spool

argusReviewRequired: true in PRD frontmatter; F-107 = data-integrity bug surfaced by Argus V0.27.18 drill.

Edit permission: light-touch inline corrections in PRD OK if needed. Major restructure -> flag as BLOCK; do not rewrite unilaterally. Refinements log under "Refinements made during grooming" table.

await your verdict + open Q resolutions.
