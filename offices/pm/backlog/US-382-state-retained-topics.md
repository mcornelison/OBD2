---
id: US-382
parent: F-110
epicId: E-006
type: feature
size: S
status: sprint-ready
createdAt: 2026-06-19
deps: [US-381]
sourceRefs: [F-110, E-006, A-14, edr-bus-slice1-draft-2026-06-18]
---

# US-382 — STATE retained topics (last-value-cache) + integrity-gap markers

## Goal
Add retained STATE topics (publish(retain=True) -> last-value-cache, replayed to new subscribers) for slowly-changing data (VIN, calibration, state.config.*); and the honest-instrument integrity-gap marker -- a LOSSLESS overflow publishes event.integrity.gap rather than silently dropping.

## Definition of Done
- publish(sample, retain=True) stores the latest sample per topic
- a new subscriber matching a retained topic immediately receives the current retained value
- only the latest retained value per topic is kept; STREAM publishes are NOT retained
- a LOSSLESS subscription overflow causes the bus to publish event.integrity.gap (source='bus', unit=<subscriptionName>, seq=<lost seq>) to OTHER subscribers, not the overflowing one
- no overflow => no marker
- Typecheck passes
- Tests pass

## Validation Criteria
| # | Testable action | Expected outcome |
|---|---|---|
| V-1 | publish retained 'state.config.serverHost' then subscribe late to 'state.config.*' | retained value delivered on subscribe |
| V-2 | overflow a LOSSLESS maxQueue=1 sub while a watcher subscribes to event.integrity.gap | exactly one gap marker with correct subscription name + lost seq |
| V-3 | publish within queue capacity (no overflow) | no event.integrity.gap emitted |

## Dependencies
US-381

## Source
- Spec: `docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md`
- TDD plan (complete code): `docs/superpowers/plans/2026-06-18-edr-bus-slice1-dedicated-reader.md`
- EDR epic **E-006** / Feature **F-110**; Atlas Watch List **A-14**.
- Ships DARK behind `pi.bus.enabled` (default false); byte-identical `realtime_data` golden master is the load-bearing gate.
