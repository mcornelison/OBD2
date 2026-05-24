# TD-054 — ShutdownHandler's dead source-reaction wiring (post-heuristic retirement)

**Status**: Open — tracked-not-silently-dead per Atlas SS-T4 Ruling C (2026-05-19). Do NOT fix as part of SS-T4 (out of scope, blast radius). Retire as a small follow-up after the V0.27 chain validates IRL.
**Filed**: 2026-05-19 (Sprint 39 / Shutdown Sequencer SS-T4, by Ralph at Atlas's ruling)
**Origin**: SS-T4 A1 surgery (Atlas 2026-05-19) — the `UpsMonitor.getPowerSource` VCELL-trend heuristic was retired (spec §7); the UpsMonitor monitoring thread no longer fires `onPowerSourceChange`. `ShutdownHandler`'s assignment of that callback is now inert.

## The debt

`src/pi/hardware/shutdown_handler.py` lines `:64`, `:402`, `:410`, `:425` still wire:

- `monitor.onPowerSourceChange = handler.onPowerSourceChange` (set)
- `upsMonitor.onPowerSourceChange = self.onPowerSourceChange` (set in `registerWithUpsMonitor`)
- `upsMonitor.onPowerSourceChange = None` (clear)

Post SS-T4 these assignments target an attribute that nothing in `UpsMonitor` ever invokes anymore. The wiring is **intended-dead** per spec §7 (VCELL-heuristic source path retired; the ShutdownSequencer over GPIO6 SSOT owns the shutdown trigger). The dead wiring is **inert + acceptable** — it does not crash, does not fire spuriously, does not allocate. But it is misleading to a future reader: it suggests an active reaction path that no longer exists.

## Why not fix in SS-T4

Atlas Ruling C (2026-05-19) explicitly scope-fences SS-T4 to `lifecycle.py + ups_monitor.py + their tests`. `shutdown_handler.py` is out of scope; touching it under SS-T4 risks pulling unrelated coupling into a load-bearing surgery whose gate criteria are already maximal (criterion #4: no-broken-intermediate, criterion #5: scope fence). The dead reaction is **inert**, not **broken**; deferral does not regress safety.

## Proposed cleanup (single small change, post-V0.27 chain IRL validation)

1. Delete the four `onPowerSourceChange` assignments in `shutdown_handler.py` (`:64`, `:402`, `:410`, `:425`).
2. Delete the `ShutdownHandler.onPowerSourceChange(self, old, new)` method itself if it has no other caller (grep first; it might be invoked directly by tests).
3. Update any `tests/pi/hardware/test_shutdown_handler_*.py` that asserted on the wiring.
4. Update spec § references where `ShutdownHandler` is documented as a UpsMonitor source-callback consumer.

## Acceptance

- `grep -rn "onPowerSourceChange" src/` returns ZERO results (the attribute is fully retired everywhere — currently `UpsMonitor.onPowerSourceChange` is also inert and kept only as `None` to absorb the external assignments).
- ShutdownHandler tests pass without referencing the retired wiring.
- No live shutdown path depended on the assignment.

## Linked

- Spec: `docs/superpowers/specs/2026-05-18-pi-shutdown-sequencer-design.md` §7 (Retire vs keep).
- Atlas ruling: `offices/ralph/inbox/2026-05-19-from-atlas-task4-DESIGN-RULING.md` (Ruling C).
- SS-T4 implementation: this commit's `src/pi/hardware/ups_monitor.py` + `src/pi/obdii/orchestrator/lifecycle.py`.
- Related (kept open as general rule): TD-053 (real-signal trigger validation).
