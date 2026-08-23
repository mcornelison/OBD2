# TD-083 — The Pi's local `drive_summary` still spells the IAT snapshot `ambient_temp_at_start_c`

- **Filed:** 2026-08-21 by Rex (Ralph, Agent 1) during US-563 (Sprint 75 / V0.29.30)
- **Class:** honest-instrument / mislabeled column — the *same* defect US-563 fixed, surviving on the other tier
- **Severity:** low-to-medium. No wrong number is produced and nothing is broken; the risk is that a reader of the Pi tier draws the ambient conclusion US-563 exists to prevent.
- **Scope note:** OUT of US-563's scope-fence (Refusal Rule 3). US-563's `validationCriteria` #1 is *"inspect the applied **prod** schema after migration"*, and its migration registry is the server's. Flagged, not fixed.

## State after US-563

US-563 renamed the **server** column:

```
obd2db.drive_summary.ambient_temp_at_start_c -> intake_air_temp_at_start_c
```

The **Pi's** local SQLite `drive_summary` still uses the legacy spelling:

- `src/pi/obdii/drive_summary.py:169` — `ambient_temp_at_start_c REAL,` (DDL)
- `src/pi/obdii/drive_summary.py:619, 647, 718, 754` — INSERT / UPDATE / SELECT
- `src/pi/obdii/drive/detector.py:223` — docstring
- `specs/architecture.md` (several places) still documents the Pi-sync metadata columns under the old name

## Why this was deliberately NOT done in US-563, and why nothing is broken

`src/server/api/sync.py` carries an explicit rename seam:

```python
"drive_summary": (
    DriveSummary,
    (("ambient_temp_at_start_c", "intake_air_temp_at_start_c"),),
),
```

A Pi that still sends the legacy key has its value **landed**, not dropped — the SSOT "land what you read" rule. This deliberately **decouples the two tiers' deploys**: the server rename does not require a simultaneous Pi migration, and a Pi queue holding rows captured before any Pi-side rename still syncs correctly.

That seam is the right call and should stay even after the Pi is renamed (old queued rows outlive the rename). This TD is *not* a request to remove it.

## The actual risk

The mislabel is the thing US-563 was filed about. Per Spool (2026-08-20, moving-vehicle proof, drive 41): IAT ran 48.1 → 40.6 °C by speed band, cooling with airflow, and never neared the 24-27 °C real ambient — it sits 14-24 °C high **always**. `ambient_temp_at_start_c` logged 47 °C / 117 °F.

**No ambient source exists on this vehicle** (the 2G 4G63 does not support PID 0x46), so the column can never be made to mean what its Pi-side name says. Anyone reading the Pi tier — or `specs/architecture.md` — still meets the name that misled the team once already.

## Recommendation

Small, self-contained follow-up story:

1. Pi-local schema migration renaming the column (the Pi's own migration path, not the server registry).
2. Re-point the five call sites in `src/pi/obdii/drive_summary.py` + the `detector.py` docstring.
3. Update `specs/architecture.md`'s Pi-sync metadata column lists (§ around lines 1139, 1197, 2440, 2473) — `specs/` is read-only for Ralph, so this half routes through `offices/pm/issues/`.
4. **Keep** the `sync.py` legacy-key seam regardless.

Sequencing note: because the seam maps old → new, the Pi rename can ship in **any** later sprint with no server coupling and no flag day.
