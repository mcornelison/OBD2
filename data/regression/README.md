# Server Regression Fixtures

Checked-in fixtures for validating the server analytics pipeline without rebuilding simulated data from scratch each session. Mirrors the real-world pattern of a Pi-in-vehicle sync: one device_id per "vehicle," many drives per device.

## Layout

```
data/regression/
├── inputs/                          # seed SQLite files (portable, deterministic)
│   ├── session17_single.db          # 1 drive  — full_cycle   (device: sim-eclipse-gst)
│   ├── session17_multi.db           # 4 drives — --all        (device: sim-eclipse-gst-multi)
│   └── day1.db                      # 4 drives — realistic "day" (device: eclipse-gst-day1)
└── expected/                        # captured CLI report outputs
    ├── db_counts.txt                # post-load row totals
    ├── drive_all.txt                # report.py --drive all
    ├── drive_latest.txt             # report.py --drive latest
    ├── drive_4_cold_start.txt       # historical cold_start comparison (3σ anomaly reference)
    ├── drive_7_day1_cold_start.txt  # day1 cold_start comparison
    └── trends_default.txt           # report.py --trends (10-drive window)
```

## Fixture Provenance

The simulator (`src/pi/obd/simulator/sensor_simulator.py`) is deterministic — no RNG seed, physics-based. Re-running any of the commands below produces bit-exact SQLite output.

### Regenerating inputs/

```bash
# On chi-srv-01 (or any box with the project venv)
cd /mnt/projects/O/OBD2v2
export PYTHONPATH=$PWD
VENV=$HOME/obd2-server-venv/bin/python

$VENV scripts/seed_scenarios.py --scenario full_cycle --output data/regression/inputs/session17_single.db
$VENV scripts/seed_scenarios.py --all --output data/regression/inputs/session17_multi.db
$VENV scripts/seed_scenarios.py \
    --scenarios cold_start,city_driving,highway_cruise,city_driving \
    --gaps 1200,2400,900 \
    --output data/regression/inputs/day1.db
```

The `day1.db` shape models a realistic morning: cold start → 20 min errand → city driving → 40 min errand → highway → 15 min stop → local drive home. Under one `device_id` = one vehicle.

## Full Regression Run

Given a server with a reset MariaDB (`deploy/deploy-server.sh --init`):

```bash
export PYTHONPATH=/mnt/projects/O/OBD2v2
export DATABASE_URL='mysql+aiomysql://obd2:<password>@localhost/obd2db'
VENV=$HOME/obd2-server-venv/bin/python

# Load the 3 fixture databases under their canonical device ids
$VENV scripts/load_data.py --db-file data/regression/inputs/session17_single.db --device-id sim-eclipse-gst
$VENV scripts/load_data.py --db-file data/regression/inputs/session17_multi.db  --device-id sim-eclipse-gst-multi
$VENV scripts/load_data.py --db-file data/regression/inputs/day1.db             --device-id eclipse-gst-day1

# Expected final state: 9 drives, 26265 realtime rows, 18 connection events
```

## Diffing Against expected/

```bash
# Capture actual outputs, diff against expected
for cmd in "--drive all" "--drive latest" "--drive 4" "--drive 7" "--trends"; do
    name=$(echo "$cmd" | tr ' -' '_' | sed 's/^_*//')
    $VENV scripts/report.py $cmd > /tmp/actual_${name}.txt
    diff data/regression/expected/drive_*${name}*.txt /tmp/actual_${name}.txt 2>&1 || true
done
```

Non-empty diffs mean analytics output changed. Investigate whether that's intended (new feature, bug fix) or unintended (regression).

## When `expected/` Legitimately Changes

If the analytics engine or report formatting evolves:

1. Run the full regression load (above).
2. Regenerate expected files by piping report output into them.
3. Commit the new expected files with a message explaining what changed and why.

## Notes on Idempotency

`load_data.py` upserts keyed on `(source_device, source_id)`. Running the same input file against the same device_id twice is a no-op. **Do not** load multiple input files under the same device_id unless they were generated with continuous rowids (e.g., from a single `seed_scenarios.py` invocation). Mixing separately-seeded files under one device will silently collide on source_ids.

The `--scenarios A,B,C,...` flag exists specifically to compose multiple scenarios into one file with continuous rowids — that's the correct path for "day-of-drives" fixtures.
