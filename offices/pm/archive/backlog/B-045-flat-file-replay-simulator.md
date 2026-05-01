# B-045: Replace Physics-Based Simulator With Flat-File Replay — CLOSED OBSOLETE

**Status**: **CLOSED OBSOLETE 2026-05-01** (CIO directive)

## Closure rationale

B-045 was filed 2026-04-18 when the project was still pre-real-OBD-data and the physics-based simulator was the only data-generation path. The standing rule from that note was: "Until we have real data, the simulator should be just reading repeatable flat files."

By Sprint 21 close (2026-05-01), the precondition for the rule is no longer in force:

- Drive 3 (2026-04-23, 9.5 min cold->warm) — first real engine data
- Drive 4 (2026-04-29, 10:47 min warm idle) — real, post-jump-start
- Drive 5 (2026-04-29, 17:39 min full cycle) — authoritative warm-idle baseline in `offices/tuner/knowledge.md`
- 5 drain tests on real Pi hardware
- Sprint 16 US-210 dropped `--simulate` from the production `eclipse-obd.service`
- Test fidelity rule (`feedback_runtime_validation_required.md`) now governs synthetic-test discipline at hardware-signal level, replacing the "use real data" intent of B-045

Real data is flowing. The motivation for the flat-file replay layer dissolved before any work landed.

The two specific complaints from B-045's "Trigger" section are also resolved by other Sprint 16/19 work:

1. **Tier-isolation violation** (validation script vs systemd both running --simulate) → eliminated when `--simulate` was dropped from eclipse-obd.service in Sprint 16 US-210
2. **Non-deterministic data** → replaced by Sprint 18+ synthetic tests that mock at hardware-signal level (`feedback_runtime_validation_required.md` rule); deterministic-replay-of-real-data is the test fidelity standard now
3. **Black-box failure** (pre-run realtime_data=0) → eliminated post-Sprint-19 — real OBD writes are observable + reliable

## What WAS preserved

The server-tier regression fixtures pattern (`data/regression/inputs/*.db` + `seed_scenarios.py` + `load_data.py`) ships and is in active use for server-side analytics tests. That portion of the B-045 idea was implemented in Session 19 pre-B-045 filing — B-045 was just the Pi-side analog, which the project no longer needs.

## Original content preserved below for historical reference

# B-045: Replace Physics-Based Simulator With Flat-File Replay

**Priority**: High
**Size**: M
**Status**: Pending (CIO directive — supersedes E-03 simulator usage in tests)
**Epic**: B-037-adjacent (test-tooling hygiene)
**Related**: E-03 (US-033 to US-043 — physics simulator), US-166 (e2e validation), B-043 (auto-sync — uses simulator), Session 19 server regression fixtures (`data/regression/`)
**Filed**: 2026-04-18 (PM Session 21, CIO directive)

## CIO directive

> "Until we have real data, the simulator should be just reading repeatable flat files. Nothing more complex than that. Just like we did when we tested the server, we ran flat files through the system to validate data flow. We don't need complicated services for testing at this stage. It will get complicated enough as soon as we turn on the Bluetooth OBD2 dongle."

## Standing rule

**Until real OBD-II data is flowing from the OBDLink LX, "simulate" means flat-file replay — never physics-based generation.** The Pi reads timestamped OBD readings from a checked-in fixture file and writes them to its SQLite as if they came from the dongle. Determinism + reproducibility + no random surprises during testing.

## Trigger

Today's `validate_pi_to_server.sh` drill exposed two problems with the physics simulator approach:

1. **Tier-isolation violation**: the validation script launched a SECOND `--simulate` instance while the systemd service already had one running. Two producers writing to one Pi SQLite. Bad design.
2. **Non-deterministic data**: the physics simulator generates different rows on each run. We can't assert "expected 247 realtime_data rows" — only "delta > 0". Server-side regression tests by contrast assert exact row counts because the input is deterministic.
3. **Black-box failure**: pre-run `realtime_data=0` after a deploy + restart suggests the systemd `--simulate` service may be failing to write any rows (or the schema is empty post-deploy). Hard to debug a non-deterministic data source.

The server side already solved this in Session 19: `data/regression/inputs/*.db` are deterministic SQLite fixtures, `seed_scenarios.py` builds them, `load_data.py` replays them, expected outputs in `data/regression/expected/` are bit-for-bit checkable. Same pattern applies to the Pi tier.

## Scope

### Phase 1 — Build the flat-file format

Pick the simplest format that supports timestamped multi-PID telemetry replay. Three options to choose from:

**Option A — CSV per PID stream**: simple, human-readable, one row per (timestamp, pid_value_set). Easy to hand-edit.
```
timestamp,rpm,coolant_temp,intake_temp,throttle,speed,...
2026-04-18T10:00:00,800,180,72,12,0,...
2026-04-18T10:00:01,820,180,72,15,2,...
```

**Option B — SQLite "tape"**: a `.db` file with the same schema as the production Pi SQLite (`realtime_data`, `connection_log`, etc.), pre-populated with fixture data. Replay = SCP file to Pi, restart sync. No replay process at all.

**Option C — JSONL stream**: one event per line, supports heterogeneous record types (realtime_data, connection_log, alert_log all in one file).

**Recommendation**: **Option B** — minimal moving parts. The Pi's pipeline doesn't even know it's a "fixture" — it just sees a populated SQLite and syncs it. Mirrors the server's `data/regression/inputs/` pattern exactly.

### Phase 2 — Build the fixtures

- Reuse `seed_scenarios.py` (Session 19) to generate Pi-shape SQLite fixtures (currently it makes server-shape ones).
- Check in `data/regression/pi-inputs/` with 3+ deterministic scenarios:
  - `cold_start.db` (engine warmup, ~5 min)
  - `local_loop.db` (idle + city, ~15 min)
  - `errand_day.db` (3 short drives with parked gaps)
- Each fixture is bit-for-bit reproducible.

### Phase 3 — Build the test harness

`scripts/replay_pi_fixture.sh` (or a Python equivalent):
```
1. SSH to Pi
2. sudo systemctl stop eclipse-obd     (no producer running during test)
3. SCP data/regression/pi-inputs/<fixture>.db to ~/Projects/Eclipse-01/data/obd.db
4. python ~/Projects/Eclipse-01/scripts/sync_now.py
5. Verify server received the expected row counts
6. (optional) restart eclipse-obd if you want the Pi back to "live" mode
```

No simulator process. No physics. Just a file copy + sync + assertion.

### Phase 4 — Rewire `validate_pi_to_server.sh` to use this

Replace step 1 (run physics sim for N seconds) with step 1 (replay `data/regression/pi-inputs/<chosen-fixture>.db`). Steps 2–7 stay the same shape. Row counts become EXACT (we know the fixture has 1000 rows, server should have +1000).

### Phase 5 — Decide systemd service default

When the Pi is on the bench (no BT dongle), the `eclipse-obd.service` currently runs `python src/pi/main.py --simulate` on boot. Three options:

- **A**: leave as-is — physics sim accumulates noise data 24/7. Bad for testing. Bad for storage. Don't recommend.
- **B**: change service to `python src/pi/main.py` (no `--simulate`) — service runs but does nothing (waits for BT to come online). Recommend this until BT pairing happens (Sprint 13). Then the service auto-connects when the dongle appears.
- **C**: disable the service from auto-starting — only enable it when the Pi is in the car or actively testing. Good middle ground.

**Recommendation**: B. The service stays alive (systemd happy) but is idle without real data. When BT pairing is added, `--simulate` is just gone. When testing, we use the replay harness.

### Phase 6 — Deprecate (don't delete) E-03 physics simulator

Mark `src/pi/obdii/simulator/` as deprecated in its README. Do NOT delete the code yet — it's working code, may have future use (e.g., generating new fixture data programmatically, or for stress-testing). But it's no longer the canonical "how do I simulate data on the Pi" answer.

## Acceptance criteria (to be finalized when entering a sprint)

- `data/regression/pi-inputs/` directory exists with 3+ deterministic SQLite fixtures
- `scripts/replay_pi_fixture.sh` runs end-to-end: copy fixture → sync → verify
- Server-side row counts match fixture-side row counts EXACTLY (not "delta > 0")
- `validate_pi_to_server.sh` rewired to use replay (or replaced by `replay_pi_fixture.sh`)
- `eclipse-obd.service` default mode decided + applied (Phase 5)
- E-03 physics simulator README marked deprecated with pointer to B-045
- Documentation updated (`docs/testing.md` describes the replay pattern as the canonical test method)

## Risks

- **Fixture maintenance**: fixtures need to evolve as schema changes. Mitigate: regenerate via `seed_scenarios.py`; any schema change adds a fixture-rebuild step to the migration.
- **B-043 dependency**: B-043 (auto-sync on power loss) wanted to test against simulated drives. With flat-file replay, the test pattern shifts: pre-load fixture → trigger UPS-loss event → verify auto-sync fires + shutdown completes. Different shape, same coverage.

## Dependencies

- `seed_scenarios.py` (Session 19) — already exists, may need `--target=pi` flag to emit Pi-shape SQLite
- US-187 obdii rename — already shipped, so paths stay stable

## Sprint placement notes

**Strong candidate for Sprint 13** (the same sprint that has the BT pairing work). Reason: today's e2e test is broken by the physics-sim hang AND the design issue. Without B-045, we can't run a clean Pi→Server validation. BT pairing (Sprint 13) needs that validation to be reliable. Bundle B-045 with the BT prep stories.

**Alternative**: file as a polish sprint after BT pairing. Risk: physics-sim continues to mislead test signals.

## Out of scope

- Physics simulator deletion (it stays as deprecated code)
- New fixture-format invention (Option B uses existing SQLite schema)
- Real BT/OBD-II integration (Sprint 13+ Run phase)
