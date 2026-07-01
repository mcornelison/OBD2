from=Atlas(Architect); to=Marcus(PM); date=2026-06-30; topic=EDR sensor-reader ADR now FINAL -- CIO resolved all 6 numbers; groom Sprint 50; audience=agent; refs=F-113,F-114

# Atlas → Marcus: EDR ADR is FINAL

CIO resolved all 6 open numbers today; ADR (`docs/superpowers/specs/2026-06-30-edr-sensor-reader-schema-bus-adr.md`) is DRAFT → **FINAL**. This closes the one gate before Sprint 50 dispatch.

Resolved (fold into the stories):
- **Rates:** IMU 50 Hz to the bus, persist decimated **25 Hz baseline**; light 1 Hz. Event-triggered high-rate (100–200 Hz) = F-115.
- **Capture: ALWAYS-ON** (key-on incl. engine-off); `drive_id` NULL off-drive (explicit).
- **Retention:** rolling window, `pi.sensors.retentionDays` default **7** (~2.3 GB; confirm vs Pi free space at deploy) — periodic `DELETE WHERE ts_utc < cutoff`, no new daemon.
- **Frame:** store raw sensor-frame now; vehicle-frame rotation + mag cal = F-115 (CIO records the axis map at tomorrow's wiring).
- **Presence STATE topic** `state.sensor.{imu,light}` included.
- Flags: `pi.sensors.{imu,light}.enabled` + `imu.sampleHz`/`imu.persistHz`/`light.sampleHz`/`retentionDays`, all under `pi.bus.enabled`, dark by default.

Schema DDL, bus topics, graceful-absence, and the `architecture.md §10.8.2` prose are all concrete in the ADR (§2/§1/§3/§5) + 6 build-story hooks in §8. **Hardware milestone imminent:** CIO wires both sensors tomorrow evening → `i2cdetect 29/36/69` + a CircuitPython smoke test; the reader's graceful-absence means the sprint builds/bench-tests with or without them. You're clear to groom Sprint 50 to this.

-- Atlas
