---
id: US-381
parent: F-110
epicId: E-006
type: feature
size: S
status: sprint-ready
createdAt: 2026-06-19
deps: [US-380]
sourceRefs: [F-110, E-006, A-14, edr-bus-slice1-draft-2026-06-18]
---

# US-381 — SampleBus core -- subscribe/publish fan-out (STREAM) + producer-never-blocks

## Goal
Add the SampleBus broker: subscribe() returns a Subscription; publish() fans a Sample out to every matching subscription synchronously and NEVER blocks (the queue buffer is the only async boundary). STREAM topics have no history.

## Definition of Done
- SampleBus.subscribe(topics, qos, name, maxQueue) returns a usable Subscription
- publish(sample) delivers only to subscriptions whose patterns match the topic
- STREAM: a subscriber created after a publish does NOT receive that earlier sample
- publish() returns promptly even when a subscriber never drains its queue (no blocking call in the publish path)
- Typecheck passes
- Tests pass

## Validation Criteria
| # | Testable action | Expected outcome |
|---|---|---|
| V-1 | pytest tests/pi/bus/test_bus_stream.py | green |
| V-2 | publish 1000 samples to an undrained LOSSY maxQueue=2 subscriber | all publish calls return; never hangs |
| V-3 | subscribe to 'raw.*' after a prior publish, then poll | no historical sample delivered (only post-subscribe) |

## Dependencies
US-380

## Source
- Spec: `docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md`
- TDD plan (complete code): `docs/superpowers/plans/2026-06-18-edr-bus-slice1-dedicated-reader.md`
- EDR epic **E-006** / Feature **F-110**; Atlas Watch List **A-14**.
- Ships DARK behind `pi.bus.enabled` (default false); byte-identical `realtime_data` golden master is the load-bearing gate.
