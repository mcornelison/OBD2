---
id: US-385
parent: F-110
epicId: E-006
type: feature
size: M
status: sprint-ready
createdAt: 2026-06-19
deps: [US-380, US-381, US-382, US-383, US-384]
sourceRefs: [F-110, E-006, A-14, edr-bus-slice1-draft-2026-06-18]
---

# US-385 — Orchestrator wiring behind pi.bus.enabled + ships-dark integration (slice-1 cutover)

## Goal
Wire the bus into the orchestrator: when pi.bus.enabled, build a SampleBus, start a PersistenceSubscriber on raw.obd.* (LOSSLESS) bound to the logger's ObdDataLogger, and inject the bus into the logger; when off, behavior is identical to today. Slice 1 ships dark.

## Definition of Done
- _initializeDataLogger builds a SampleBus + starts a PersistenceSubscriber on ['raw.obd.*'] LOSSLESS + passes the bus to createRealtimeLoggerFromConfig, ONLY when pi.bus.enabled is true
- flag off: no bus, no subscriber, dataLogger behavior identical to today
- the PersistenceSubscriber is stopped on orchestrator shutdown
- full fast suite green with the flag OFF (zero regression -- ships dark)
- Typecheck passes; Tests pass

## Validation Criteria
| # | Testable action | Expected outcome |
|---|---|---|
| V-1 | pytest tests/pi/obdii/orchestrator/test_lifecycle_bus_wiring.py tests/pi/bus/ tests/pi/obdii/data/ | green |
| V-2 | pytest tests/ -m 'not slow' with pi.bus.enabled=false | green -- running system unchanged (ships dark) |
| V-3 | enable the flag in a harness, push one sample through the orchestrator-built bus | a realtime_data row is written by the PersistenceSubscriber |

## Conditional Outcomes
- VERIFY before coding: createRealtimeLoggerFromConfig signature (add/forward bus), and the orchestrator class + attribute names in lifecycle.py

## Dependencies
US-380, US-381, US-382, US-383, US-384

## Source
- Spec: `docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md`
- TDD plan (complete code): `docs/superpowers/plans/2026-06-18-edr-bus-slice1-dedicated-reader.md`
- EDR epic **E-006** / Feature **F-110**; Atlas Watch List **A-14**.
- Ships DARK behind `pi.bus.enabled` (default false); byte-identical `realtime_data` golden master is the load-bearing gate.
