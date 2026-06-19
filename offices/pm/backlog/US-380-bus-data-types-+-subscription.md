---
id: US-380
parent: F-110
epicId: E-006
type: feature
size: M
status: sprint-ready
createdAt: 2026-06-19
deps: []
sourceRefs: [F-110, E-006, A-14, edr-bus-slice1-draft-2026-06-18]
---

# US-380 — Bus data types + Subscription (Sample, QoS, topicMatches, bounded queue + QoS overflow)

## Goal
Create the src/pi/bus/ package foundation: the immutable Sample envelope, the QoS enum, the topic prefix-matcher, and Subscription (one bounded queue per consumer with a QoS-keyed overflow policy + observability stats). Pure data types + queue logic, no wiring.

## Definition of Done
- Sample is a frozen dataclass with fields: topic, source, value(float|tuple), unit, tsUtc, tsCapture, driveId, dataSource, seq
- QoS enum has exactly LOSSLESS and LOSSY
- topicMatches('raw.*','raw.obd.RPM')=True; exact pattern matches only itself; NOT regex
- Subscription bounded queue: LOSSY drops oldest on full (droppedCount bumps); LOSSLESS _offer returns False on overflow and NEVER blocks; the already-queued sample is preserved
- stats() exposes depth, highWater, droppedCount, lastSeqBySource
- stdlib only (dataclasses/enum/queue), no new dependencies
- Typecheck (mypy) passes
- Tests pass

## Validation Criteria
| # | Testable action | Expected outcome |
|---|---|---|
| V-1 | pytest tests/pi/bus/test_sample.py tests/pi/bus/test_subscription.py | green |
| V-2 | construct a Sample then assign .value | raises FrozenInstanceError |
| V-3 | offer 3 samples to a LOSSY maxQueue=2 subscription | oldest dropped, poll yields seq 2 then 3, droppedCount=1 |
| V-4 | offer 2 samples to a LOSSLESS maxQueue=1 subscription | _offer returns False on the 2nd, first sample still queued, call never blocks |

## Conditional Outcomes
- if topic matching seems to need multi-level wildcards beyond a trailing '.*', STOP -- out of scope (YAGNI); confirm with Atlas before adding

## Dependencies
none

## Source
- Spec: `docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md`
- TDD plan (complete code): `docs/superpowers/plans/2026-06-18-edr-bus-slice1-dedicated-reader.md`
- EDR epic **E-006** / Feature **F-110**; Atlas Watch List **A-14**.
- Ships DARK behind `pi.bus.enabled` (default false); byte-identical `realtime_data` golden master is the load-bearing gate.
