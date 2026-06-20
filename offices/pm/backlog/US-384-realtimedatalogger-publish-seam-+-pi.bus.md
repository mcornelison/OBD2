---
id: US-384
parent: F-110
epicId: E-006
type: feature
size: M
status: sprint-ready
createdAt: 2026-06-19
deps: [US-380, US-381]
sourceRefs: [F-110, E-006, A-14, edr-bus-slice1-draft-2026-06-18]
---

# US-384 — RealtimeDataLogger publish seam + pi.bus.enabled flag (default off)

## Goal
Give the OBD poll loop a producer role: when a SampleBus is injected, _logReadingSafe publishes a raw.obd.<param> Sample (per-producer monotonic seq) instead of writing the DB; when no bus, the existing write path is unchanged. Add the pi.bus.enabled config flag, default false.

## Definition of Done
- RealtimeDataLogger.__init__ gains optional bus=None and producerSource='obd'; adds a _seq counter
- a dataLogger property exposes the internal ObdDataLogger (for the PersistenceSubscriber to reuse)
- with a bus present, _logReadingSafe publishes raw.obd.<parameterName> (seq increments per publish); with bus None the write path is byte-for-byte unchanged
- pi.bus.enabled defaults False in the validator DEFAULTS and config.json
- existing tests/pi/obdii/data/ pass unchanged with the bus off
- Typecheck passes; validate_config.py passes; Tests pass

## Validation Criteria
| # | Testable action | Expected outcome |
|---|---|---|
| V-1 | pytest tests/pi/obdii/data/test_realtime_bus_publish.py | green; published Sample topic=raw.obd.RPM, seq increments 1,2,... |
| V-2 | pytest tests/pi/obdii/data/ (no bus injected) | green -- inline write path unchanged |
| V-3 | python validate_config.py | passes; result pi.bus.enabled == False by default |

## Conditional Outcomes
- VERIFY before coding: whether utcIsoNow and getCurrentDriveId are already imported in realtime.py; add the imports if not

## Dependencies
US-380, US-381

## Source
- Spec: `docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md`
- TDD plan (complete code): `docs/superpowers/plans/2026-06-18-edr-bus-slice1-dedicated-reader.md`
- EDR epic **E-006** / Feature **F-110**; Atlas Watch List **A-14**.
- Ships DARK behind `pi.bus.enabled` (default false); byte-identical `realtime_data` golden master is the load-bearing gate.
