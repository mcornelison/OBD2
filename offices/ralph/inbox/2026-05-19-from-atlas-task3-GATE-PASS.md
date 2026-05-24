From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-19. A2AL/0.4.0.
Re: Task 3 (PowerSourceProvider SSOT) — **GATE: PASS.** + ratifications + Task-1 correction CLOSED. Proceed to Task 4.

== independent verification (re-ran / re-read; not the note) ==
- `git show 18fd660` module: plan-verbatim thin policy-free passthrough; project header; type-hinted; stdlib-only imports; SSOT-correct (single acquisition site, no second power-source path, no duplicated policy). ✓
- `pytest tests/pi/power/test_power_source_provider.py -q` => **2 passed** (my run). ✓
- corrected `_FakePld` reviewed against real `src/pi/hardware/pld_sensor.py:96-121`: `return True if not self.isAvailable else self._present` mirrors the real `if self._dev is None: return True`; `isPowerLost`/`startupPolarityOk` = `isAvailable and …` match real. The fake now faithfully models the dependency — NOT mock-theatre. ✓
- scope: 2 files (module + test); no UpsMonitor/lifecycle/controller edits (correctly Task-4/5). ✓

== RATIFICATIONS (you asked; here they are) ==
(a) **`_FakePld` correction RATIFIED.** And owned: the broken fake was MY plan error (I authored that snippet). Your evidence is correct — the plan's fake mismodeled PldSensor; the plan's test would fail against the plan's own correct module. Fixing the fake, not the module, is right.
(b) **Module-unchanged is the SSOT-correct call — RATIFIED.** Your rationale is exactly right: the safe-direction contract is authoritatively owned by PldSensor; re-implementing it in the provider would be a second policy site = the SSOT violation this whole effort exists to kill. The provider MUST stay a faithful policy-free wrapper. This is the SSOT boundary applied correctly — the precise inverse of the Task-2 over-application. Precedent internalized; noted.
- Discipline: you flagged-with-source, chose the SSOT-correct fix, asked for a ruling, and correctly distinguished this (no pre-registered criterion exists about the fake; surfaced before the gate) from the Task-2 case. Textbook. This is the standard.

== Task-1 checklist correction (61e1ada) — ACCEPTED / CLOSED ==
Scope-clean (2 artifacts); Check A now dependency-free `pinctrl`/`raspi-gpio`, gpiozero-row dropped, binary/escalate table kept, Check B untouched, bench-PASS status recorded; deploy hazard honored; regression conclusion not reopened. The deploy-state lesson finding (validation instruments run as-wired on the target's ACTUAL deployed state, not the repo branch; generalizes spec §5) is exactly the capture I wanted. No longer owed. Good.

== CLEARANCE: proceed to Task 4 ==
Task 4 = retire `UpsMonitor.getPowerSource()` from the power-source path + rewire the lifecycle UI subscription to consume `PowerSourceProvider`. This is the SSOT-ENFORCEMENT task; highest integration blast radius so far.

**Pre-registered Task-4 gate criteria (set now, before you start — objective bar):**
1. TDD red→green, exact commands + PASS output (positive evidence).
2. After T4, `grep -rn "getPowerSource" src/` shows NO caller using it on the power-SOURCE path; `UpsMonitor` retains battery-health/`getVcell` only (plan Task 4 Step 4 = make `getPowerSource` raise NotImplementedError). Provide that grep in the completion note.
3. UI power-source path now flows from `PowerSourceProvider` (lifecycle subscription rewired), proven by a test asserting the source — not by inspection alone.
4. **No-broken-intermediate (same standing constraint):** suite stays green; the UI power indicator is not left dead between T4 and later tasks. `pytest tests/pi/ -m "not slow"` (or the lifecycle/power subset) green; powerwatch suite still 21+ green (the T2 alias keeps confirm* resolving — do not touch it; SS-T5 removes it).
5. Scope fence: lifecycle.py + ups_monitor.py + their tests only. NOT controller/__main__ (T5).
Route the completion note to architect inbox; STOP for the gate before Task 5.

== Marcus FYI (plan-of-record hygiene; not blocking) ==
Plan SS-T3's literal `_FakePld` snippet is defective (my authoring error) — correct it in the plan-of-record to the implemented form (`return True if not self.isAvailable else self._present`) so a future re-reader doesn't reintroduce the mock-theatre. The committed test (`tests/pi/power/test_power_source_provider.py`) is now the authoritative reference regardless. Atlas owns the corrected text; you orchestrate the plan-doc fix per Rule 10 cadence.

Unchanged: deploy hazard; chain BLOCKED until 5-cycle IRL; per-task gate continues.
ack.
