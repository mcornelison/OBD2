# US-363 DONE — server attribution_anomaly tripwire (3 notes for PM)

**From:** Rex (Dev) · **To:** Marcus (PM) · **Date:** 2026-05-28 · **Re:** Sprint 43 / V0.28.0 / F-107 / US-363

US-363 landed `passes: true` (server suite 852 passed / 0 failed; ruff clean on 12 files; changes unstaged per protocol). Three things you should know — none block sprint progress.

## 1. AC#1 wording vs reality: drive_summary had **no** data_quality column

AC#1 says "extend the data_quality enum / CHECK constraint to allow `attribution_anomaly` on **both** drive_summary + drive_statistics" — which reads as if both tables already had the column. They didn't: only `drive_statistics` had `data_quality` (added by v0009). `drive_summary` had **none**.

The goal statement + AC#2 ("compute_drive_summary … writes 'attribution_anomaly' / 'full'") make the intent unambiguous, so I did **not** treat it as a blocker. Implementation:
- **drive_summary** → **ADD** a new `data_quality VARCHAR(16) NOT NULL DEFAULT 'full'` column + CHECK + index (enum `{full, attribution_anomaly}` — drive_summary has no sample-count notion, so `sparse`/`below_threshold` are intentionally excluded).
- **drive_statistics** → **extend** its existing CHECK enum with `attribution_anomaly`.

Flagging so the PRD/AC phrasing can be tightened if a future audit compares AC text to the landed schema.

## 2. "Alembic v0010" is actually the explicit MigrationRunner registry

AC#1 (and the sprint/PRD generally) say "Alembic v0010 substep". The repo does **not** use Alembic — it uses the explicit `MigrationRunner` registry (TD-029 Path B; `src/server/migrations/`). I followed that existing pattern: `v0010_us363_attribution_anomaly_data_quality.py`, registered in `ALL_MIGRATIONS`. Purely a naming nuance; behavior is correct and tested (18 migration unit tests). No action needed — just so the "Alembic" label in sprint docs isn't read literally.

**v0010 is the single shared V0.28.0 migration.** Its `apply()` is structured as ordered `_applyUsNNN` substep functions with a clearly-marked insertion point so **US-365 / US-368 / US-370 / US-371 / US-372 append their substeps to the same file** (US-371→US-365 FK ordering etc. should be honored there per Atlas Refinements row 16).

## 3. Cross-agent gate still owed (cannot self-satisfy)

- **AC#7 — Atlas Rule 10 sign-off.** Owned by **US-373** (the `specs/architecture.md` §10.7 / §5.X amendment) + Atlas. Pending; gates `/sprint-deploy-pm`.
- **IRL-deferred:** the production-DB confirmation (drives 23+24 stamped `attribution_anomaly` on chi-srv-01) is **US-364**'s job and runs against chi-srv-01 — not runnable from the Windows dev box. Folds into the sprint `validationMethod` IRL drill. Note US-364's validation criteria are nearly all "against chi-srv-01", so US-364 likely needs an IRL/CIO step rather than a pure dev iteration.

— Rex
