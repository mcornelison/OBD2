# DISPATCH: have Ralph correct the ECU seed `MD335287 → MD326328` across all sites (pre-deploy)

**From:** Atlas (Architect) · **To:** Marcus (PM) · **Date:** 2026-06-01
**Re:** `re: 2026-06-01-from-atlas-ecu-id-correction-md326328-pre-deploy.md` · CIO-directed this session

CIO has directed the correction proceed now (he gave the P/N directly — it's
ground-truth off the hardware, so Ralph is **not** blocked on Spool's
ratification; Spool updates his card + CALID nuance in parallel). Please dispatch
Ralph to correct the new-ECU signature **`MD335287` → `MD326328`** everywhere it's
a seed/identity value. Disposition unchanged: **at-source pre-deploy fix, NOT a
v0012** (nothing migrated; v0011 first runs at the V0.28.1 deploy). TDD.

**`E2T61683` is the mfr code, NOT a seed value** — the `ecu` table has no mfr
column this slice. Do **not** add it to `ECU_SEED_PAIRS`; it lives in Spool's card
/ `notes` only. `cal_signature` stays `UNKCAL` (this is a value correction, not a
reflash — no CALID read yet).

## Why it must be all-sites-coherent (the load-bearing reason)

v0011's `speed_pid_calibration` backfill JOINs `spc.ecu_signature = e.ecu_signature`
and re-points provenance `WHERE ecu_signature = 'MD335287'`
(`v0011_...py:264`), and v0010 **seeds that exact string**
(`v0010_...py:432`). If the `ecu` seed moves to `MD326328` but v0010's seed and
v0011's references don't, the JOIN matches nothing → **MigrationError (FAIL
LOUDLY)** on first deploy. So the ecu seed, the v0010 seed, and the v0011
references move **together** or not at all. (This is exactly why it's at-source,
not a corrective migration.)

## Code sites for Ralph (grep-verified)

| File:line | What | Action |
|---|---|---|
| `src/server/db/models.py:336` | `ECU_SEED_PAIRS` `("MD335287", UNKCAL)` | → `("MD326328", …)` — this auto-fixes v0011's ecu seed (derived from `ECU_SEED_PAIRS`) |
| `src/server/db/models.py:330` | seed comment | → `MD326328` |
| `src/server/migrations/versions/v0010_…py:432` | `speed_pid_calibration` seed `VALUES ('MD335287', 0.5, …)` | → `'MD326328'` (must match the ecu seed for the v0011 JOIN) |
| `src/server/migrations/versions/v0010_…py:420` | seed comment | → `MD326328` |
| `src/server/migrations/versions/v0011_…py:264` | provenance re-point `WHERE ecu_signature = 'MD335287'` | → `'MD326328'` |
| `src/server/cli/stamp_ecu_swap.py:36` | help-text **example** `--signature MD335287-ECMLinkV3` | cosmetic example, not a seed — Ralph's discretion to refresh |

**Tests asserting the literal (TDD — Ralph updates red→green):**
`test_ecu_model.py`, `test_migration_0011_speed_pid_rekey.py`,
`test_migration_0010_speed_pid_calibration.py`,
`test_speed_pid_calibration.py`, `test_stamp_ecu_swap.py`,
`test_vehicle_info_ecu_lineage.py`,
`test_vehicle_info_identity_immutability_enforced.py`,
`test_sync_dtc_freeze_frame.py`, `test_dtc_freeze_frame_model.py`.

**Verify after:** `pytest tests/server -m "not slow"` green; the v0010→v0011
migration still converges (the backfill JOIN matches the corrected `MD326328`
ecu row, no MigrationError).

## Other lanes (not Ralph)

- **Atlas (me):** I correct + re-gate `specs/architecture.md` §5 once Ralph's value
  lands — don't have Ralph touch it (specs/ read-only for him anyway).
- **Specs `grounded-knowledge.md` / `glossary.md` / `obd2-research.md`:** string
  references to the new-ECU P/N — assign as you prefer (Ralph as part of the change,
  or fold the vehicle-fact ones with Spool). Flagging, your call.
- **PM / governance (yours):** the frozen US-376/US-374 `validationCriteria` seed
  literal + `bigDoDHash 21971bd1` (US-370/A-11 freeze-conflict class — my read is a
  pre-deploy data-correctness defect fix, not a re-scope, but the hash/criteria
  mechanics are yours + CIO's), plus `MEMORY.md` + `prd-V0.28.1.md` + backlog refs.
- **Spool:** his ECU card — already routed.

## Suggested order
1. Ralph: code seed sites + tests → green.
2. Atlas: re-gate seed coherence + fix §5.
3. PM: frozen-criteria/MEMORY/PRD reconciliation.
4. Then `/sprint-deploy-pm` (v0011 now runs the correct `MD326328` seed).

Tracking as Watch List **A-13** until the corrected seed deploys + the drive-27
backfill resolves the FKs against the `MD326328` row.

— Atlas
