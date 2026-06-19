---
id: US-383
parent: F-110
epicId: E-006
type: feature
size: M
status: sprint-ready
createdAt: 2026-06-19
deps: [US-380, US-381]
sourceRefs: [F-110, E-006, A-14, edr-bus-slice1-draft-2026-06-18]
---

# US-383 — PersistenceSubscriber -- writes realtime_data (byte-identical golden master)

## Goal
Add the subscriber that persists raw.obd.* samples to realtime_data by REUSING the existing ObdDataLogger.logReading() write path -- so the persisted rows are identical to today's inline path by construction. This is the 'one subscriber that saves data for the server' (B-104 raw emitter).

## Definition of Done
- PersistenceSubscriber(subscription, dataLogger) with start(), stop(), and handleSample(sample)
- handleSample reconstructs a LoggedReading from a raw.obd.<param> sample and calls dataLogger.logReading (does NOT reimplement the INSERT)
- non-raw.obd.* topics are ignored (handleSample returns False, no write)
- the drain loop catches write exceptions (subscriber isolation -- never crashes the producer)
- GOLDEN MASTER: realtime_data rows written via the bus path equal rows written via inline logReading on (parameter_name, value, unit, profile_id, drive_id, data_source)
- Typecheck passes
- Tests pass

## Validation Criteria
| # | Testable action | Expected outcome |
|---|---|---|
| V-1 | pytest tests/pi/bus/test_persistence_golden_master.py | dbA rows == dbB rows (excluding id + write-time timestamp) |
| V-2 | handleSample on a 'derived.gear' sample | returns False; dataLogger.logReading NOT called |
| V-3 | pytest tests/pi/bus/test_persistence_subscriber.py | green |

## Conditional Outcomes
- do NOT reimplement the realtime_data INSERT -- reuse ObdDataLogger.logReading so rows stay byte-identical
- if ObdDataLogger.__init__ signature differs from the plan, adapt the test construction and keep both paths identical

## Dependencies
US-380, US-381

## Source
- Spec: `docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md`
- TDD plan (complete code): `docs/superpowers/plans/2026-06-18-edr-bus-slice1-dedicated-reader.md`
- EDR epic **E-006** / Feature **F-110**; Atlas Watch List **A-14**.
- Ships DARK behind `pi.bus.enabled` (default false); byte-identical `realtime_data` golden master is the load-bearing gate.
