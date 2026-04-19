# Pi OBD-II Physics Simulator — DEPRECATED FOR TESTING

## Status: Deprecated for Testing

**As of Sprint 13 (B-045 / US-191), the physics-based simulator in this
directory is no longer the canonical way to produce test data for the
Pi → Server sync pipeline.**

Use the flat-file replay harness instead:

- Generate fixtures: `python scripts/seed_pi_fixture.py --all --output-dir data/regression/pi-inputs`
- Run the validator:  `bash scripts/replay_pi_fixture.sh cold_start`
- Full docs:          `docs/testing.md` — "Flat-File Replay Validation (B-045)"

### Why deprecated

Session 21's sprint-exit drill surfaced two failure modes of this simulator:

1. **Non-deterministic output.** `SensorSimulator(noiseEnabled=True)` plus
   the scenario randomness means two runs of the same scenario produce
   different row counts. That's incompatible with exact-delta assertions
   — tests had to settle for "delta > 0" which hides real sync bugs.
2. **Tier-isolation violation.** The validation script launched a second
   `python src/pi/main.py --simulate` process while `eclipse-obd.service`
   was already running one. Two producers writing to one SQLite file is
   a design smell that shouldn't be required for testing.

The CIO directive (B-045) says: **until real OBD-II data is flowing from
the OBDLink LX, "simulate" means flat-file replay, not physics-based
generation.** Deterministic fixtures check into git, replay via SCP +
`sync_now.py`, and the server receives EXACTLY the row count present in
the fixture.

### What stays supported

- The simulator code itself is **not deleted**. It's working code and may
  be useful for:
  - Generating new fixture data programmatically (run the simulator once,
    capture the output as a new fixture).
  - Stress-testing drive-detection state machines against scripted
    scenarios with known inputs.
  - CIO demos and development debugging (`python src/pi/main.py --simulate`).
- `seed_scenarios.py` in `/scripts/` is the server-side fixture builder
  (see `data/regression/inputs/`). It still uses this simulator and is
  NOT impacted by this deprecation — it predates B-045 and serves a
  different slice of the regression harness.

### Canonical replacement at a glance

| Old                                                   | New                                                   |
|-------------------------------------------------------|-------------------------------------------------------|
| `python src/pi/main.py --simulate` (for testing)      | `bash scripts/replay_pi_fixture.sh <fixture>`         |
| "assert delta > 0 after sim run"                      | "assert delta == fixture row count EXACTLY"           |
| Non-deterministic scenario + noise                    | Deterministic SQLite fixtures in `data/regression/pi-inputs/` |
| Physics sim (`noise_enabled=True`)                    | Pure arithmetic (`scripts/seed_pi_fixture.py`)        |

### File map

- `sensor_simulator.py`, `drive_scenario.py`, `scenario_runner.py`,
  `scenario_builtins.py`, `failure_injector.py`, etc. — physics simulator
  (RETAINED as working code; NOT the canonical testing path).
- `data/regression/pi-inputs/*.db` — canonical deterministic fixtures
  used by the replay harness. Check into git; regenerate only on schema
  change.
- `scripts/seed_pi_fixture.py` — canonical Pi-fixture builder (B-045).
- `scripts/replay_pi_fixture.sh` — canonical Pi→Server validation
  driver (B-045).

### See also

- `offices/pm/backlog/B-045-flat-file-replay-simulator.md`
- `docs/testing.md` — "Flat-File Replay Validation (B-045)"
- `specs/architecture.md` — Tier boundaries and test-data flow
