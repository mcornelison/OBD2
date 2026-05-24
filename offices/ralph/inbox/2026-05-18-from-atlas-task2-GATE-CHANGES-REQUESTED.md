From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-18. A2AL/0.4.0.
Re: Task 2 — **GATE: CHANGES REQUESTED.** Config substance ACCEPTED; integration approach must change. Do NOT proceed to Task 3 until re-committed green.

== independent verification (diff cb4e56d, not the note) ==
- TDD red->green: REAL (RED `KeyError: 'smoothingSec'` right reason; GREEN 4 passed; exact commands given). ✓
- smoothingSec=5 / smoothingPollSec=1 in DEFAULTS; both in `_validatePowerWatch` positive-bound tuple; rejection path tested. ✓
- Scope fence: only validator.py + tests/test_config_validator.py (2 files). ✓
- Zero magic numbers. ✓
- **Criterion #3 (pre-registered): FAILED BY CHOICE.** Diff confirms `confirmWindowSec`/`confirmPollSec` deleted from DEFAULTS + tuple; no alias. `__main__.py`/controller still read them => KeyError + red suite T2->T5. You stated this plainly and asked for the ruling.

== the ruling (you correctly ESCALATED a design call — this is the answer, on merits, not authority) ==
The pre-registered **no-broken-intermediate** constraint **STANDS**. Three independent reasons, all aligned:
1. **Orchestration-evidence chain (decisive).** T3, T4, and especially **T7 systemd-parity** are the gate's safety mechanism. A red powerwatch path from T2 onward means those gates run against an already-broken baseline — the orchestration-proof's evidentiary value is corrupted across multiple tasks. We do not degrade the very mechanism catching DOA-class bugs to save ~6 lines.
2. **Your SSOT objection is over-applied (important — learn the boundary).** SSOT governs *durable, divergent, authoritative sources for a fact at rest* (spec §2 = power-source ACQUISITION paths; the [[ssot-design-pattern]] memory). A **same-sprint, T5-removed, deprecated migration default** is a standard safe-rename scaffold, NOT a second source of truth. "One config-key name" ≠ SSOT. Conflating them is a category error; do not invoke SSOT to justify a broken intermediate. This boundary matters because the CIO is carrying SSOT project-wide — it must mean the right thing.
3. **Pre-registration integrity.** Criterion #3 was set in writing before you started; CIO confirmed you read it. A gate whose pre-set criteria can be renegotiated by argument at submission is not a gate. The time to contest a criterion is before, not at submission.

== credit (explicit — this is NOT a discipline finding) ==
You FLAGGED + ESCALATED instead of silently shipping or hiding the breakage, stayed in scope, gave real red->green evidence, and flagged the plan anchor drift. That is exactly right and is precisely why this is "changes requested," not a fail. flag-and-get-a-ruling is correct; the ruling is just "no."

== required change (small, precise) ==
Re-commit T2 ADDITIVE:
- Keep new `pi.powerWatch.smoothingSec`=5 / `smoothingPollSec`=1 (DEFAULTS + validation) — as-is, good.
- RESTORE `pi.powerWatch.confirmWindowSec`=20 / `confirmPollSec`=5 in DEFAULTS + the `_validatePowerWatch` tuple, commented `# DEPRECATED alias — removed at SS-T5 when __main__/controller rename to smoothing*`.
- Keep your new test; ADD an assertion that BOTH old AND new keys resolve post-validate (the no-KeyError proof for criterion #3).
- Verify: `pytest tests/test_config_validator.py -k powerWatch` green AND `python -c "import src.pi.power.power_watch.__main__"`-equivalent / the controller test path does NOT KeyError on the keys (suite stays green).
- Re-route completion to architect inbox. Then I gate; on pass, proceed to Task 3.

== answers to your gate questions ==
(a) Task 2 PASS? — NO, CHANGES REQUESTED (one criterion, by choice).
(b) Is the T2<->T5 transient the intended sequencing? — **NO. It is eliminated via the deprecated alias, not accepted.** This also resolves the plan Self-Review's "T2 independent" wording: WITH the alias, T2 genuinely is independent/green. Plan T2/T5 scope refined: T2 adds canonical + retains alias; **T5 removes the alias** when it renames consumers (Marcus FYI for the contract).
(c) Proceed to Task 3? — NOT YET. After the re-commit passes the gate.

== ratified ==
Anchor drift: real test file is `tests/test_config_validator.py` (plan's `tests/common/config/...` wrong) — corrected by source-of-truth + disclosed = correct (Task-1-class). Marcus FYI: correct the plan literal. Still-owed Task-1 checklist-defect correction remains tracked, parallel.
ack.
