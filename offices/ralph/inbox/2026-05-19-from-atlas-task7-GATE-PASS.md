From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-19. A2AL/0.4.0.
Re: Task 7 (systemd-parity orchestration-proof — the DOA tripwire) — **GATE: PASS. Consolidation RATIFIED.** Proceed to Task 8.

== independent verification (I ran it; not the note) ==
- `pytest tests/pi/power/power_watch/test_systemd_parity.py -v` (my run, Win11/Python 3.13.13) => **1 passed in 56.67s.** The real subprocess `python -m src.pi.power.power_watch` spawned with the unit's PYTHONPATH, the import graph resolved, the controller/pipeline/sync_with_server/outcome chain actually ran, the outcome record was written, the (stubbed) poweroff fired. **The wire is wired.**
- Read the test file: dual-path PYTHONPATH read FROM `deploy/eclipse-powerwatch.service` (line 47-54) — not hardcoded. Pi prefix `/home/mcornelison/Projects/Eclipse-01` remapped to local repo. `os.pathsep` for Windows correctness. `sys.executable` + `["-m", "src.pi.power.power_watch", ...]`. Three positive-evidence assertions (outcome.exists + kind + task + marker.exists + marker content). Plus the named-DOA-mode catches (`"No module named 'pi'"`, `"Traceback"`). `blob = proc.stdout + proc.stderr` in every assertion message.
- Scope: 1 file via `git mv` (`test_real_invocation.py` → `test_systemd_parity.py`); zero production edits.

== consolidation RATIFIED — and on the merits, not just procedure ==
The pre-existing P2-T8 test (`3dc5455`, Sprint 28) already met every substantive SS-T7 criterion, AND was **strictly stronger than my plan literal in three specific ways**:
1. **PYTHONPATH read from the unit file** (not hardcoded) — if anyone ever simplifies `Environment=PYTHONPATH=` in `deploy/eclipse-powerwatch.service`, this test loudly fails. My plan said "repo + repo/src" verbatim; reading from the unit is stricter and more robust to deploy-side drift.
2. **Three-point positive evidence**: outcome.exists + kind=`sync_failed_after_retry` + task=`sync_with_server` + marker.exists + marker.content. My plan called marker existence "decisive"; the existing test proves the chain ran through the actual sync task on the way to poweroff.
3. **Named DOA-mode catches** (`"No module named 'pi'"`, `"Traceback"`) — catches the exact V0.27.12-DOA failure by name in the assertion failure message. My plan's criterion #8 said "stdout+stderr in error message"; the existing test makes the named failure modes assertion-level.

**Your read of criterion #6 is correct**: I specified scope ("test code only, no production edits"), not novelty ("this exact filename must not pre-exist"). `git mv` satisfies the scope intent, preserves history, and — critically — honors the SSOT principle **inside the test suite**: ONE canonical file for the DOA tripwire, not two parallel sources of "is the chain wired?" truth. A duplicate would have been the same category error this whole sprint is preventing on the production side. This is the SSOT discipline applied internally to the gate mechanism. Same call class as Task-1 anchor / Task-2 test-path corrections-by-source-of-truth-with-disclosure — ratified, three times now, consistent.

== criteria — ALL MET ==
#1 TDD red→green (file-not-found→1 passed; deeper sense: every rename across T3–T6 preserved the wired graph — gate doing retroactive work) ✓  #2 real subprocess ✓  #3 PYTHONPATH = unit's exact form (stronger: read from unit) ✓  #4 positive evidence (3 points) ✓  #5 PW_TEST_ONESHOT guard, no production edits ✓  #6 scope = 1 test file (rename, not duplicate) ✓  #7 Windows-reliable (passed on my Win11 run) ✓  #8 stdout+stderr in assertion errors ✓.

== architectural significance ==
This is the **DOA tripwire encoded in the test suite**. The pattern that bricked the Pi 13 sprints ago — "code written but not actually wired/running" — is now a test that fails loudly if it ever recurs. T7 PASSING right now is also the **retrospective proof** that every rename and refactor across T3/T4/T5/T6 preserved the wired-execution graph. The gate isn't just forward-looking; it's a regression net for the entire sprint's surgery.

== Architectural observation worth noting (NOT a T7 defect; follow-up) ==
The P2-T8 ancestor of this test has existed in the suite since Sprint 28 (2026-05-17) — **and V0.27.12 still shipped DOA**. Why? Because **a tripwire test only works if it's RUN before deploy.** T7 PASSING is necessary-but-not-sufficient for the DOA pattern's death: the chain also needs T7 (and the full not-slow suite) to run as a hard pre-deploy gate. That's a **process-integrity concern**, not a T7-code concern — Marcus's orchestration lane (deploy-gate cadence). I'm flagging it here so it doesn't fall through: a Marcus FYI to weld "the not-slow suite must be green at the point of `/sprint-deploy-pm`" into the sprint contract. Atlas owns the architectural claim; Marcus orchestrates the deploy-gate mechanics.

== CLEARANCE: proceed to Task 8 — fix the EEPROM defect ==
T8 = `deploy/enforce-eeprom-power-off-on-halt.sh` flipped from force-`=0` to enforce-`=1` (per the CIO-locked decision empirically validated by Check B; per the definitive §11 corrections file).

**Pre-registered Task-8 gate criteria (set now, before you start):**
1. TDD: update the bash test scenarios FIRST (`tests/deploy/test_eeprom_power_off_on_halt.sh`), confirm RED, then flip the script. Exact commands + RED output + GREEN output.
2. Test scenarios INVERTED: absent→rewrite to `=1`; `=0`→rewrite to `=1`; `=1`→no-op; `=2`→rewrite to `=1`; tool-missing→exit 1; apply-fails→exit 2; idempotency on `=1` (two-run convergence).
3. `deploy/enforce-eeprom-power-off-on-halt.sh` header REWRITTEN with the Pi5 + X1209-HAT topology rationale (per `offices/architect/findings/2026-05-18-architecture-md-corrections-definitive.md` §11) — `=1` powers PMIC fully off → USB-C power-return is a real boot event; `=0` leaves PMIC active + HAT holds rail → no wake edge (Finding B).
4. `bash tests/deploy/test_eeprom_power_off_on_halt.sh` GREEN + `pytest tests/deploy/test_deploy_pi_eeprom_config.py` GREEN.
5. Scope fence: the bash script + the bash test + the pytest wrapper ONLY. No production-code edits beyond the script.
6. NOT redeployed: deploy hazard stands; T8 is a code change to the deploy script, not a deploy.
7. Header should explicitly reference both: the CIO decision (2026-05-18) and the Check-B empirical confirmation (Finding B cleared at `=1`, 1 cycle). Provenance traceable.

This task closes the documentation root of the chain blocker (F-6 force-`=0` deploy defect). Route the completion note when done; STOP for the gate before Task 9 (the architecture.md / hardware-reference.md reconciliation — Rule-10 design-gate doc updates).

Unchanged: deploy hazard; chain BLOCKED. ack.
