---
id: F-056
parent: E-002
status: pending
renamedFrom: B-056
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-056: mod_state enum for drive tagging (cross-mod-comparison safety)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | High                   |
| Status       | Pending                |
| Category     | database / analytics   |
| Size         | S                      |
| Related PRD  | None                   |
| Dependencies | None (precedes B-057 drive_annotations table)  |
| Created      | 2026-05-09             |

## Description

Spool 2026-05-09 spec (relaying CIO's mod plan): every drive captured with the car in a specific modification state. **Same engine in different mod states behaves differently enough that comparing across states without tagging is dangerous.** A WOT pull on premod baseline + a WOT pull on `ecmlink_e85_blend` should NEVER be averaged together.

Required enum values + transitions (cumulative, additive over time):

| Value | Definition | Tuning impact vs prior state |
|---|---|---|
| `premod` | Stock turbo (TD04-13G) + modified EPROM + current bolt-ons (CAI / BOV / FPR / AN-6 fuel / oil catch can / clutch / suspension) | Project baseline. All drives 3-7 are this state. |
| `walbro_installed` | + Walbro GSS342G fuel pump | Negligible at stock turbo + 91 (capacity headroom only). |
| `flex_sensor_idle` | + GM flex fuel sensor wired (not yet active) | Sensor sits idle until ECMLink reads it. |
| `exhaust_installed` | + 3" downpipe + 2.5-3" cat-back | **Significant**: better exhaust flow, possibly higher boost on stock wastegate, faster spool. |
| `ecmlink_pump_gas_base` | + ECMLink V3, base pump-gas tune, stock injectors | **Major**: ECU swap. Tune evolves through this state. |
| `ecmlink_pump_gas_wideband` | + AEM 30-0300 wideband to ECMLink | Tune is now data-driven (real AFR vs target). |
| `ecmlink_pump_gas_id550` | + ID550 (550cc) injectors, rescaled | Pump gas tune redone. |
| `ecmlink_e85_blend` | + E85 map enabled, flex sensor active | **Major**: different fuel map per ethanol content. |
| `big_turbo_16g` | + 16G turbo (placeholder) | Different boost behavior + MAF saturation. |
| `big_turbo_20g` | + 20G turbo (placeholder) | More aggressive variant of 16G family. |

## Acceptance Criteria

- [ ] `mod_state VARCHAR(32)` column added to `drive_summary` (and B-057 `drive_annotations` when that ships)
- [ ] All 5 existing drives (3, 4, 5, 6, 7) backfill to `mod_state='premod'`
- [ ] `mod_state_history` reference table (mod_state VARCHAR, installed_at DATE, notes TEXT) tracks transition dates
- [ ] Pi reads CURRENT mod_state from `config.json` at drive-start (or server reads at sync-time); one-line config change when mod ships
- [ ] Adding a new `mod_state` value requires only config update + reference-table row, NOT a code change
- [ ] Spool's grading queries can `WHERE mod_state = ?` to constrain comparisons to a single bucket

## Validation Script Requirements

- **Input**: completed drive with config `mod_state=premod`
- **Expected Output**: drive_summary row has `mod_state='premod'` populated
- **Database State**: SELECT DISTINCT mod_state FROM drive_summary -- enumerates only seen states
- **Test Program**: integration test sets config `mod_state=walbro_installed`, captures a drive, asserts new row carries that value while pre-existing premod rows untouched

## Notes

**Transition trigger**: `mod_state` advances the moment a mod is installed AND the car is driven for the first time post-install. Pre-install and post-install drives must NOT share a value.

**Schema choice**: VARCHAR(32) NOT NULL DEFAULT 'premod' until migration date is set, then drop the default. Spec rationale: enum-as-string for human readability + easy extension.

**Sequencing**: should ship Sprint 28 if there's room (post-V0.27.2 bug-fix work) OR Sprint 29. Spool wants this BEFORE B-057 drive_annotations because B-057 has mod_state as an FK column.

**Source**: `offices/pm/inbox/archive/2026-05/2026-05-09-from-spool-three-specs-mod-state-drive-annotations-drive-summary-contract.md` Spec 1
