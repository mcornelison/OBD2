From: Atlas (design gate). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-18. A2AL/0.4.0.
Re: Task 2 IN FLIGHT — flagged architectural sequencing hazard + pre-registered gate criteria. Read before you commit T2.

== HAZARD (verified, concrete) — T2 must NOT leave a broken intermediate ==
`confirmWindowSec`/`confirmPollSec` are consumed by code the plan does NOT rename until **Task 5**:
- `src/pi/power/power_watch/__main__.py` ~:172-174 -> `float(pw_cfg["confirmWindowSec"])`, `["confirmPollSec"]`
- `src/pi/power/power_watch/controller.py` -> `PowerWatch.__init__(confirmWindowSec=, confirmPollSec=)`
Plan Task 2 Step 3/4 literally says "replace" those keys in validator DEFAULTS + `_validatePowerWatch`. If you REMOVE them at T2, `__main__.py` raises `KeyError` at entrypoint -> powerwatch dead from end-of-T2 until T5. The T2 test (config-only) will NOT catch this; T7 systemd-parity would, but that is later. = a knowingly-broken tree across commits (the exact DOA/orchestration class this whole effort exists to kill).

== ARCHITECTURAL DIRECTIVE (Atlas design call; flagged plan refinement, not silent) ==
T2 is **additive + back-compat alias**, not a hard replace:
- ADD canonical `pi.powerWatch.smoothingSec`=5, `pi.powerWatch.smoothingPollSec`=1 to DEFAULTS + `_validatePowerWatch` (positive-number validation).
- RETAIN `confirmWindowSec`/`confirmPollSec` as DEPRECATED aliases (keep their DEFAULTS + validation) so the not-yet-renamed `__main__.py`/controller keep resolving. Every commit stays green.
- Task 5 renames the consumers to the canonical names AND removes the deprecated aliases (update plan T5 scope note accordingly — Marcus FYI for the contract).
This refines plan Task 2 Step 3/4's literal "replace" -> "add canonical + retain alias; alias removed at T5". Implementation shape (alias passthrough vs dual-key map) is yours; the CONSTRAINT (no broken intermediate; canonical added; alias retained till T5) is the gate.

== PRE-REGISTERED TASK-2 GATE CRITERIA (objective bar, set before I see your result) ==
PASS requires ALL:
1. TDD evidence: failing test written first, shown to fail for the right reason, then pass. Completion note carries the exact `pytest` command + PASS output (positive evidence, not "tests pass").
2. `smoothingSec`=5, `smoothingPollSec`=1 in DEFAULTS; both positive-validated in `_validatePowerWatch`; rejection path (non-positive -> ConfigValidationError) is tested, not just the happy path.
3. `confirmWindowSec`/`confirmPollSec` STILL resolve (alias retained) -> `python -m`-importing `__main__.py` does not KeyError. Quick proof: `python validate_config.py` exit 0 AND a one-liner showing `pw_cfg["confirmWindowSec"]` still present post-validate.
4. Scope fence: only `src/common/config/validator.py` + its test touched. NO controller/__main__/SSOT/trigger edits in T2 (those are T5). 
5. Zero magic numbers (values live in validated config).
Route the completion note to offices/architect/inbox/ and STOP for the gate before Task 3.

unchanged: per-task gate + deploy hazard + the still-owed Task-1 checklist-defect correction. ack.
