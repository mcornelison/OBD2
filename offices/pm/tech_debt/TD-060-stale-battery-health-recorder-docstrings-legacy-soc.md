# TD-060: Stale `BatteryHealthRecorder` docstrings reference the dropped legacy `start_soc`/`end_soc` dual-write

| Field | Value |
|---|---|
| Status | open |
| Priority | P3 (docstring-only drift; no runtime effect) |
| Category | cleanup / power / docs |
| Size | S |
| Created | 2026-07-02 |
| Source | Rex, spotted during US-430 Sprint 52 doc-sync (drift outside the doc-sync spec scope — source file, not a spec doc) |

## Problem

US-426 (Sprint 52 / V0.29.6) dropped the legacy misnamed `start_soc`/`end_soc`
columns and added dedicated `start_soc_pct`/`end_soc_pct`, but the
`BatteryHealthRecorder` method docstrings in `src/pi/power/battery_health.py`
still describe the retired **legacy `start_soc` dual-write contract**:

- `startDrainEvent` docstring (~lines 496–516): "the same value is also written
  to the legacy `start_soc` column (US-289 dual-write contract)" and
  "`startSocPct` … lands in the legacy `start_soc` column (overriding the
  dual-write VCELL fallback)". Post-US-426 there is no `start_soc` column;
  `startSocPct` now lands in `start_soc_pct` and `startSoc` (volts) lands in
  `start_vcell_v` only. The prose is contradicted by the module's own
  `SCHEMA_BATTERY_HEALTH_LOG` and the US-426 rebuild helper.
- `endDrainEvent` docstring likely carries the mirrored stale `end_soc` wording
  (verify at fix time).

The runtime code is correct (it writes `*_vcell_v` + `*_soc_pct`); only the
docstrings are stale, so this is P3 doc-drift, not a behavior bug.

## Resolution

Rewrite the `startDrainEvent` / `endDrainEvent` docstrings to match the
post-US-426 schema: `startSoc`/`endSoc` (volts) → `*_vcell_v` (sole voltage
home); `startSocPct`/`endSocPct` (register SoC%) → `*_soc_pct`; drop all
references to the legacy `start_soc`/`end_soc` columns and the US-289 dual-write
contract. Source-file edit — wrap into a future power/cleanup story (not the
US-430 doc-sync scope, which is spec docs + `CLAUDE.md` + `regression_manifest.json`).
