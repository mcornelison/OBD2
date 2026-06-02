from=Marcus(PM); to=Argus(QA/Tester); date=2026-06-01; topic=V0.28.2 pre-drill baseline — schema+data verified GREEN on prod; audience=agent; refs=US-364,US-377,US-378,F-005,F-007

# Pre-drill baseline for your V0.28.2 drill runsheet — all schema/data checks GREEN

Ran the pre-drill checks against chi-srv-01 prod `obd2db` (via the new
`offices/pm/scripts/prod_db_query.sh`). Everything code/schema/data is verified;
only the **drive-27 IRL** remains. Use this as the verified starting baseline.

## Verified GREEN (prod, V0.28.2 / cb54311)
| Check | Result |
|---|---|
| Migrations applied | **0001–0012 all present** in `schema_migrations` |
| `data_quality` width (US-377) | `varchar(20)` on `drive_summary` + `drive_statistics` |
| US-364 recompute | drives 23+24 `attribution_anomaly`, 25 `full`; idempotent |
| data_quality distribution | **only 23,24 anomaly**; 17 other drives all `full` (no false positives) |
| `ecu` shape | id PK, `(ecu_signature,cal_signature)` VARCHAR(32) NOT NULL pair, no lineage cols |
| `vehicle_info` | `ecu_id` INT NOT NULL FK→ecu.id; transitional `ecu_signature` TEXT NOT NULL / `cal_signature` TEXT NULL |
| `speed_pid_calibration` | `ecu_id` NOT NULL **UNIQUE** FK→ecu.id; `ecu_signature` column ABSENT (re-keyed) |
| `dtc_freeze_frame` | 10 cols incl. `dtc_log_id` FK, `vehicle_info_id` FK, `pid_responses_json`, synced-capture set |
| Coherence (clause 13) | `vehicle_info` text cols == joined `ecu` row (zero drift) |
| Correction-factor JOIN | **MD346675→1.0**, **MD326328→0.5** (A-13 corrected ECU; factor + FK preserved) |
| ECU P/N (A-13) | prod `ecu` id=2 = `MD326328`; `grep MD335287 src/ tests/` = none |

## What the drive-27 drill still must prove (your runsheet)
1. **Single-attribution** — drive-27 → ONE clean `drive_summary` (no 23/24-style overlap); the F-107 fix payoff.
2. **Full Pi→server sync round-trip** — capture → sync → drive_summary + drive_statistics + realtime_data on chi-srv-01 → releases F-005/F-007.
3. **Tripwire no-false-positive** — clean drive stays `data_quality='full'`.
4. **ECU lineage** — drive-27 attributes to the active ECU (`MD326328`). NOTE: `vehicle_info` currently holds ONLY the `PRE_TRACKING_UNKNOWN` placeholder (US-367 ECU backfill deferred), so real per-drive ECU attribution lands when US-367 ships — flag in the runsheet whether drive-27 needs the backfill first or validates against the placeholder.

On drill GREEN → I run `/sprint-validated` (43/44/45) → `/chain-validated`. — Marcus
