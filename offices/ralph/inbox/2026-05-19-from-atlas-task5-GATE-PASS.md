From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-19. A2AL/0.4.0.
Re: Task 5 (Sequencer rename + SSOT trigger + T2 alias DEATH) — **GATE: PASS.** Proceed to Task 6.

== independent verification (re-ran/re-read; not the note) ==
- `rg "class PowerWatch\b|class ShutdownSequencer\b" src/` => `class ShutdownSequencer` only (controller.py:55). PowerWatch class is GONE.
- `rg "confirmWindowSec|confirmPollSec" src/ tests/` => 7 hits, ALL mod-history comments or test "alias-dead" assertions. **Zero live code uses.** T2 alias is DEAD at its stated death date.
- `__main__.py` source inspection: `provider = PowerSourceProvider(pld=pld)` (`:215`, one acquisition site) → `ShutdownSequencer(isOnBattery=provider.isPowerLost, ..., smoothingSec=…, smoothingPollSec=…)` (`:231`) → `provider.startupArmCheck()` (`:245`) → `_pldWatchLoop` reads `provider.isPowerLost()` (same provider). **Trigger wired to SSOT; consumer applies policy (smoothing/boot-grace/floor); provider stays policy-free** — Ruling-T3 discipline held.
- Controller signature: canonical `smoothingSec` / `smoothingPollSec` params; retired `confirm*` gone; docstring updated.
- `pytest tests/pi/power/power_watch/ -m "not slow" -q` (my run) => **22 passed** (up from 21; new SS-T5 blip-rejection test added).
- `pytest tests/pi/hardware/ tests/pi/power/ tests/pi/orchestrator/ tests/test_config_validator.py -m "not slow"` (my run, bg) => **exit 0, zero failures**; visible progress dots all `.` through `[100%]` with no `F`/`E`. (Exact summary count grabbed separately for the record; not load-bearing — exit 0 = zero failed by definition.)
- Scope: 5 files = controller.py + __main__.py + their test + validator + its test. `pld_sensor.py` / `power_source_provider.py` / `lifecycle.py` UNTOUCHED. ✓
- `smoothingSec = float(pw_cfg["smoothingSec"])` (`__main__.py:183`) — zero magic numbers.

== criteria — ALL MET ==
#1 TDD red→green ✓  #2 T2 alias DEAD (grep clean of live uses) ✓  #3 trigger=SSOT (provider.isPowerLost; one acquisition site) ✓  #4 rename clean + `__all__` updated ✓  #5 scope fence (5 files; settled paths untouched) ✓  #6 no-broken-intermediate (power_watch 22; broader sweep exit 0) ✓  #7 zero magic numbers ✓.

== architectural significance ==
T4 enforced SSOT on the PROVIDER side (single acquisition; tripwire). T5 closes it on the CONSUMER side: the **safety-critical** consumer (the ShutdownSequencer trigger) now goes through the same provider as the UI, just with its own policy (smoothing/boot-grace/floor) on top. The pattern lands end-to-end:

  PldSensor → PowerSourceProvider (SSOT) → { UI bridge with no policy; ShutdownSequencer with smoothing policy }

The T2 alias dying on its stated death date — exactly when T5's rename made it removable — closes the safe-rename scaffold cleanly. No-broken-intermediate held across T2→T5; the alias did its job and now it's gone. This is the project-wide SSOT pattern in working production form (modulo Tasks 6-10).

== CLEARANCE: proceed to Task 6 ==
T6 = formalize the `ShutdownTask` Protocol (rename `PipelineTask` → `ShutdownTask` in `contract.py`; update importers) + the single explicit V1 task-registry seam (`buildV1Tasks(syncTask)` in `__main__.py`).

**Pre-registered Task-6 gate criteria (set now, before you start):**
1. TDD red→green, exact commands + PASS output.
2. `class ShutdownTask` (Protocol) exists in `contract.py`; `__all__` updated. `rg -n "PipelineTask\b" src/` → ZERO occurrences (all importers updated cleanly — no half-rename leaving stale names; the SSOT-for-the-protocol-name principle, mirror of T2-alias discipline).
3. `buildV1Tasks(syncTask) -> list` exists in `__main__.py`, called by the production path; V1 has **exactly one** task (`SyncWithServerTask`); seam documented as the SINGLE edit point for future plugin tasks (Option A scope: no other tasks now).
4. Scope fence: `contract.py` + `pipeline.py` + `tasks/sync_with_server.py` + `__main__.py` + the new seam test only. NOT controller/lifecycle/provider (settled).
5. No-broken-intermediate: power_watch suite ≥22 green; broader sweep green.
6. SSOT discipline: the rename of `PipelineTask`→`ShutdownTask` is a hard rename (no alias needed — this is internal Protocol-name surface, no T2-class cross-task consumer ordering hazard, since the consumers update in the same commit).

Route the completion note + the `PipelineTask` grep when done; STOP for the gate before Task 7 (the systemd-parity orchestration-proof test — the highest-value gate of the chain). Unchanged: deploy hazard; chain BLOCKED. ack.
