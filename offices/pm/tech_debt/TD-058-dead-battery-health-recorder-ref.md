# TD-058: Dead `batteryHealthRecorder` reference in hardware_manager

| Field | Value |
|---|---|
| Status | open (addressed in-sprint by US-427) |
| Priority | P3 (dead code; no runtime effect) |
| Category | cleanup / power |
| Size | S |
| Created | 2026-07-01 |
| Source | Atlas BL-015 ruling `offices/architect/reports/2026-07-01-bl014-bl015-power-mode-soc-rulings.md` |

## Problem

`hardware_manager` constructs + stores `self._batteryHealthRecorder` (`src/pi/hardware/hardware_manager.py:233`) and it is passed in via `lifecycle.py`, but it is **never called** — a dead reference since the SS-T5 redesign (2026-05-19) deleted `PowerDownOrchestrator`, the only production caller that opened/closed drain events. `grep -rn "startDrainEvent\|endDrainEvent" src/` → 0 callers.

## Resolution

Removal is folded into **US-427** (Sprint 52 SoC%-wiring story) DoD — the wiring work touches this exact code area, so the cleanup lands with it. Verify no live caller before removing (there are none as of 2026-07-01).
