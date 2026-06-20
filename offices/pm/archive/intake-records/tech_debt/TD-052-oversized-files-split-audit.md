# TD-052: Oversized files — split into focused modules

| Field        | Value         |
|--------------|---------------|
| Priority     | Low (P3)      |
| Status       | Open          |
| Category     | code hygiene / maintainability |
| Source       | B-019 (archived 2026-05-14) — converted from ongoing-hygiene ask into a concrete file-list |
| Created      | 2026-05-14    |
| Owner        | TBD           |

## Description

The Pi tier has 14 Python files over 500 LOC; six over 1,000 LOC; one (`orchestrator/lifecycle.py`) over **2,500 LOC**. Long files hurt code review focus, increase merge-conflict risk during multi-agent work, and make grep-and-skim navigation harder. Split each into focused submodules grouped by responsibility.

## Audit snapshot (2026-05-14)

`find src -name '*.py' | xargs wc -l | sort -rn | head -15`:

| LOC | File | Likely split direction |
|----:|---|---|
| **2,505** | `src/pi/obdii/orchestrator/lifecycle.py` | Boot / shutdown / signal-handling / watchdog / connect / reconnect — each its own module |
| **1,372** | `src/pi/obdii/orchestrator/core.py` | Main loop / interval-sync / health-check / drive-detection-glue — split per responsibility |
| **1,288** | `src/pi/obdii/drive/detector.py` | Drive-start / drive-end / engine-on / warm-restart detection — one detector per file |
| **1,258** | `src/server/services/analysis.py` | Ollama plumbing / DB writers / drive_summary roll-up / DTC analyzer — split |
| **1,160** | `src/pi/power/orchestrator.py` | Drain ladder state machine / threshold logic / DB writer / stage handlers |
| **1,132** | `src/pi/hardware/hardware_manager.py` | Display / battery / GPIO / I2C bus — one component per file |
| **1,117** | `src/pi/hardware/ups_monitor.py` | MAX17048 driver / VCELL-trend logic / SOC fallback / flap debounce |
|     998 | `src/pi/update/update_applier.py` | Cooldown / safety preconditions / fetch / apply / rollback |
|     959 | `src/pi/sync/client.py` | Delta-cursor / pushDelta / pull / retention prune / sync_history writes |
|     843 | `src/pi/obdii/obd_parameters.py` | Default-poll list / PID metadata / unit conversion (mostly data; may be fine as-is) |
|     836 | `src/pi/hardware/status_display.py` | Layout / renderer / dim / restore — already partially split |
|     810 | `src/pi/power/power.py` | PowerMonitor / source detection / power-saving mode / callbacks |
|     791 | `src/server/db/models.py` | SQLAlchemy models — fine to leave as-is unless table count grows further |
|     786 | `src/pi/obdii/drive_summary.py` | Writer / 12-field contract / cold-start metadata defer / start-batter capture |

## Approach (per file)

1. Pre-flight: `git log --follow` the target file to identify clean responsibility boundaries (commit clusters often map to natural split lines)
2. Extract by responsibility into sibling modules at the same package level
3. Re-export at the package's `__init__.py` so callers don't change imports
4. Preserve test coverage during the split (no behavior changes; tests rename only if file paths change)
5. One PR per top file; do NOT batch multiple file splits in a single sprint

## Acceptance Criteria

- [ ] All listed files at or below 600 LOC (or documented as data-only / SQLAlchemy-models exemption)
- [ ] Zero behavior change (test suite green throughout)
- [ ] Original import paths preserved via re-exports in package __init__
- [ ] Each split commits clean diff (no incidental refactors mixed in)

## Cross-references

- B-019 (archived 2026-05-14 — superseded by this TD)
- This is hygiene work; should not block sprint goals. Land opportunistically when Ralph or another agent has a slot between feature/fix work.

## Notes

`orchestrator/lifecycle.py` at 2,505 LOC is the standout — splitting it alone would be a significant maintainability win. Consider that as a first targeted slice.
