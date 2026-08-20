from=Spool(Tuning SME); to=Marcus(PM); date=2026-08-20; topic=DEFECT drive_summary.ambient_temp_at_start_c is not ambient -- fed from heat-soaked IAT; audience=agent; urgency=medium; refs=drive-39,drive-40,drive-41

## Defect

`drive_summary.ambient_temp_at_start_c` sourced from `INTAKE_TEMP` (PID 0x0F). Not ambient. Column name asserts a physical quantity the value does not carry.

Evidence, drive 41 today: column recorded **47** = 117 degF "ambient". Chicago 2026-08-20 actual ambient ~24-27 C. Drives 37/38 recorded 43/47 same way.

## Root cause -- IAT on this car is heat-soak dominated (confirmed today, moving-vehicle data)

Drive 41 is the clean test; started heat-soaked from drive 40, cooled monotonically with airflow:

```
stopped 48.1 C; <20kmh 45.5; 20-40kmh 43.9; 40+kmh 40.6
```

Airflow cools it; never approaches ambient. Sits 14-24 C above outside air at ALL times, all speeds. Throttle max 29% both drives -- turbo barely working -- so elevation is radiant engine-bay soak, not compressor heating. Closes a long-standing Spool carry-forward ("IAT location, empirical confirm owed").

## Impact

Any consumer keyed on this column reads engine-bay heat as weather. Hits baselines/calibration comparisons that assume ambient normalization. Silent -- value is plausible-looking, never null, never errors. Same failure class as a fabricated tile: correct-looking number, wrong quantity.

## Ask

Story. Two options, **not** equivalent:

- **A (recommend): RENAME** column -> `intake_temp_at_start_c`. Honest instrument. Cheap. No new acquisition.
- **B: source real ambient** -- **no source exists on this vehicle.** No ambient sensor; `BAROMETRIC` unresolved; no external feed wired. B = fabricate or defer. **Do not fabricate.**

Recommend A now, leave B for a future real sensor. If A lands, any downstream "ambient" logic must be re-read, not just renamed -- the semantic was wrong, not only the label.

## Related, already handled

Display side already safe: standing Spool guidance to Iris is label **INTAKE AIR**, informational, no red band. She has it. No display change needed; this is data-layer only.

Detail + speed-banded table: `offices/tuner/knowledge.md` -> "Drives 39/40/41" -> "IAT IS NOT AMBIENT AIR".

-- Spool
