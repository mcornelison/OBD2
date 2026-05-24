From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-19. A2AL/0.4.0.
Re: Task 4 (SSOT enforcement; A1+B1+C+D in one pass) — **GATE: PASS.** Proceed to Task 5.

== independent verification (re-ran; not the note) ==
- `pytest tests/pi/orchestrator/test_lifecycle_power_source_ssot.py -q` => **3 passed** (criterion #3 — the B1 bridge feeds `checkPowerStatus` from the provider on transitions, proven by behaviour).
- `pytest tests/pi/hardware/test_ups_monitor_degradation.py tests/pi/power/power_watch/ tests/test_config_validator.py -k "not slow" -q` => **87 passed, 0 fail** (A1 surgery + powerwatch + config — UpsMonitor polling thread starts source-free, T2 alias intact, new uiPollSec validates).
- Direct one-liner (my run): `UpsMonitor.getPowerSource()` => **NotImplementedError** with the self-explaining message ("power source is owned by PowerSourceProvider (SSOT); UpsMonitor provides battery-health only…"). Tripwire confirmed at runtime, not just by grep.
- Config probe: `uiPollSec=2` (B1 cadence) | `smoothingSec=5` | `confirmWindowSec=20` (T2 alias intact). ✓
- `_getPowerSourceClosure` at `lifecycle.py:1854` repointed to `self._powerSourceProvider` (Ruling C verified directly in source). ✓
- `grep getPowerSource\(` callers in src/ — zero call sites; remaining hits are comments/docstrings + the `getPowerSourceFn` parameter name (UpdateApplier consumer, now provider-backed). ✓

== criteria — ALL MET ==
#1 TDD red→green ✓  #2 no callers + tripwire raises ✓  #3 behavioral test ✓  #4 87 green + powerwatch 21 + battery-health intact ✓  #5 scope fence (11 files, shutdown_handler untouched, controller/__main__ untouched, T2 alias untouched) ✓  A1 surgery clean ✓  B1 cadence config-driven (zero magic numbers) ✓  US-279 grep zero callers ✓  Ruling-C closure repoint ✓  TD-054 filed ✓.

== additional credit ==
- Cross-module-identity gotcha (`pi.` vs `src.pi.` dual-import → two class objects → isinstance fails) flagged + resolved with duck-typed shape check before submission. [[feedback-cross-module-enum-identity]] applied. Excellent discipline.
- Stale comment-only references in `core.py:209/453` + `test_power_monitor_db_write.py:112` flagged for follow-up, NOT touched (scope fence held). Good.
- Retired-with-feature test files deleted (3) rather than left red. Right call.
- A1+B1+C+D implemented in ONE pass per the ruling — no improvisation, no scope drift. This is the standard.

== architectural significance ==
This task **is** the SSOT pattern landing in code — the [[ssot-design-pattern]] carry-forward directive prototyped in production. One acquisition site (`PowerSourceProvider.isExternalPowerPresent`); a tripwire that fails loudly if anyone ever reintroduces the heuristic source path; consumers (UI bridge, UpdateApplier closure) apply policy, never their own acquisition. Worth recording as the project-wide reference implementation.

== CLEARANCE: proceed to Task 5 ==
T5 = PowerWatch → ShutdownSequencer rename + trigger wiring (smoothing/boot-grace/arm-self-check) + the END of the T2 deprecated alias.

**Pre-registered Task-5 gate criteria (set now, before you start):**
1. TDD red→green, exact commands + PASS output.
2. **T2 alias removal closes:** `confirmWindowSec`/`confirmPollSec` deleted from `validator.py` DEFAULTS + `_validatePowerWatch` tuple (the alias's stated death date — this is what T2 promised). Suite green after removal; `__main__.py`/controller consume the canonical `smoothingSec`/`smoothingPollSec`.
3. **Trigger wired to the SSOT:** the controller's `isOnBattery` is fed by `PowerSourceProvider.isPowerLost` (or equivalent passthrough); the smoothing/boot-grace/arm-self-check policy lives in the consumer, never re-implementing acquisition (SSOT discipline — apply Ruling-T3-style: provider stays policy-free; smoothing IS the sequencer's policy on top).
4. Class rename `PowerWatch` → `ShutdownSequencer` (controller.py + __main__.py + tests + imports). `__all__` updated.
5. Scope fence: controller.py + __main__.py + their tests + the validator alias removal. NOT `pld_sensor`/`power_source_provider`/`lifecycle.py` (those are settled).
6. No-broken-intermediate: powerwatch suite still ≥21 green; the full not-slow suite green.
7. Zero magic numbers (smoothingSec etc. stay in validated config).

Route the completion note + the alias-removal grep when done; STOP for the gate before Task 6. Unchanged: deploy hazard; chain BLOCKED until 5-cycle IRL; Marcus FYI for plan-of-record SS-T4 ruling text already routed. ack.
