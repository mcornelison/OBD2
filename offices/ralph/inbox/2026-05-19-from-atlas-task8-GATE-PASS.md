From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-19. A2AL/0.4.0.
Re: Task 8 (EEPROM defect F-6 closed at deploy script) — **GATE: PASS.** Proceed to Task 9.

== independent verification (re-ran/re-read; not the note) ==
- `bash tests/deploy/test_eeprom_power_off_on_halt.sh` (my run) => **28 passed, 0 failed**. Includes the inverted scenarios (absent / `=0` / `=1` / `=2` / tool-missing / apply-fails / two-run idempotency-on-`=1`). ✓
- `pytest tests/deploy/test_deploy_pi_eeprom_config.py -q` (my run) => **3 passed**. ✓
- Script header (lines 1-23 visible) carries full provenance: topology rationale (X1209 holds 5V rail; `=0` leaves PMIC active so external-power-return never sees a wake edge — Finding B); **CIO decision 2026-05-18** locking `=1`; **Bench Check B Atlas-gated 2026-05-18** (1 cycle confirmed); pointer to `offices/architect/findings/2026-05-18-architecture-md-corrections-definitive.md`; explicit "false for this topology" callout for the prior `=0` table. Criterion #7 met with honest "5-cycle IRL still pending; never assert beyond evidence" qualifier preserved.
- Bash test inversion verified at the test source: scenario 1 = "line absent (default 0 is WRONG on HAT)" → rewrite to `=1`; scenario 2 = "`=0` → MUST rewrite to `=1`"; test header explicitly says "SS-T8: enforces =1". ✓
- Scope: 3 files = the script + the bash test + the pytest wrapper. Zero production-code edits beyond the script. ✓
- Deploy hazard honored: T8 changes the script, doesn't deploy it. Effect lands on next `/sprint-deploy-pm` (Marcus's lane, post-IRL).

== criteria — ALL MET ==
#1 TDD red→green (28-fail vs ≈10-pass under old script → 28/28 after flip) ✓  #2 scenarios inverted ✓  #3 header rewritten with topology rationale ✓  #4 bash + pytest both green ✓  #5 scope fence (3 deploy-scope files) ✓  #6 not redeployed ✓  #7 provenance traceable in-source ✓.

== architectural significance ==
**T8 closes the documentation root of the V0.27.x chain blocker (F-6) at the deploy seam.** The script no longer fights the CIO-locked decision on every deploy. Combined with T4 (SSOT trigger; tripwire) and T5 (Sequencer via provider with smoothing on top), **the deploy seam and the runtime seam are now internally consistent**: deploy lands `=1`, runtime trigger fires only on ground-truth GPIO6 power-loss, and the wake mechanism that Check B proved at 1 cycle is no longer undone by the deploy step. The remaining blocker for the chain is the **5-cycle IRL acceptance drill** (out of code scope).

The honest provenance approach in the script header (what's locked / what's empirically confirmed / what's still pending / what was retired) is the right pattern for any future "documented contract" entry that intersects empirical hardware behavior. Worth carrying forward as a project-wide convention for deploy-script docstrings — same shape as the spec §11 corrections.

== CLEARANCE: proceed to Task 9 — the design-gate doc reconciliation (Rule 10) ==
T9 = update `specs/architecture.md` §2/§10.6/§11 + `docs/hardware-reference.md` to **match `offices/architect/findings/2026-05-18-architecture-md-corrections-definitive.md` verbatim-equivalent**. This is the Rule-10 same-sprint design-gate update; Atlas sign-off REQUIRED for sprint DoD.

**Pre-registered Task-9 gate criteria (set now, before you start):**
1. **TDD substitute for a doc task:** the completion note must include BEFORE/AFTER excerpts of each updated section (§2, §10.6, §11, hardware-reference.md sections). Evidence by quoted text, not just "I updated the docs."
2. **Verbatim-equivalent to the definitive corrections file** for §2 (power-source SSOT), §10.6 (PowerDownOrchestrator deleted → ShutdownSequencer flow + bounded-window + emergency floor; retain VCELL-calibration history as explicitly-superseded), §11 (Pi5+X1209-HAT topology; `=1` locked; remove the false `=0 ✅ auto-boot` table; mark wake mechanism empirically gated; cite Check B 1-cycle + 5-cycle pending). Substance must match; small editorial adjustments OK to fit doc style, but the *content* of the corrections must be exact.
3. **F-3/F-4 closed in `docs/hardware-reference.md`:** delete the fictitious I2C power-source register section (F-3); HAT identity updated to "X1209, GPIO6 PLD vendor-confirmed (Geekworm/Suptronics) + physical-unit Bench-Check-A 2026-05-18 PASS" (F-4 now resolved, not "UNVERIFIED" — the bench-check confirmed it on this unit).
4. **Honest empirical-gated language preserved**: §11 must NOT replace the false `=0 ✅` with a new false `=1 ✅` certainty. It must state what's locked (CIO decision), what's 1-cycle confirmed (Check B), what's still pending (5-cycle IRL), and that empirical drill is the arbiter — never the doc.
5. Mod-history rows added (SS-T9, 2026-05-19) to each updated doc.
6. **Scope fence:** `specs/architecture.md` + `docs/hardware-reference.md` ONLY. No code edits. NOT touching the README (F-5 is a separate trivial follow-up; out of T9 scope per the plan).
7. Atlas reviews the diffs against the definitive corrections file before sign-off — this is the Rule-10 gate Marcus is administering as DoD.

Route the completion note with BEFORE/AFTER excerpts of each section + a `git show --stat` of the T9 commit; STOP for the gate before Task 10 (IRL acceptance runsheet).

Unchanged: deploy hazard; chain BLOCKED until 5-cycle IRL. ack.
