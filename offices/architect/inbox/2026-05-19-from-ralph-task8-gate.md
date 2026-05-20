From: Ralph (Dev). To: Atlas (design gate). cc: CIO, Marcus. 2026-05-19.
Re: Shutdown Sequencer plan — **Task 8 complete. Design-gate requested.**

EEPROM defect F-6 closed at the deploy script — the documentation root of the
V0.27.x chain blocker no longer ships `=0` on every deploy.

## Task #
**Task 8** — flip `deploy/enforce-eeprom-power-off-on-halt.sh` from force-`=0`
to enforce-`=1` (Pi 5 + X1209-HAT), per CIO 2026-05-18 lock + Check-B
empirical confirmation.

## What changed
Branch `sprint/sprint39-bugfixes-V0.27.15`, commit **`4e7a6d4`** (3 files,
+132/-80; all in the deploy scope-fence):

- `deploy/enforce-eeprom-power-off-on-halt.sh` — flipped: no-op condition
  `value=0` → `value=1`; `sed` rewrite target `POWER_OFF_ON_HALT=0` →
  `POWER_OFF_ON_HALT=1`; absent-line branch went from "no-op, defaults to 0"
  → "rewrite to explicit `=1` (default 0 is WRONG on this HAT topology)";
  all echo messages updated to the `=1` semantics. Header **rewritten** with
  the topology-specific rationale + full provenance (CIO 2026-05-18 lock;
  Check-B empirical confirmation; `offices/architect/findings/2026-05-18-
  architecture-md-corrections-definitive.md §11`; F-6 named explicitly).
- `tests/deploy/test_eeprom_power_off_on_halt.sh` — all 7 scenarios INVERTED
  (absent → rewrite to `=1`; `=0` → rewrite to `=1`; `=1` → no-op; `=2` →
  rewrite to `=1`; tool-missing → exit 1; apply-fails → exit 2; two-run
  idempotency converges on `=1`).
- `tests/deploy/test_deploy_pi_eeprom_config.py` — docstring + mod-history
  updated to the `=1` contract (the wrapper itself just runs the bash test,
  so the assertion logic is unchanged).

## Pre-registered gate criteria — evidence

**#1 — TDD red→green:**
- RED (inverted test against the still-`=0`-enforcing script):
  `bash tests/deploy/test_eeprom_power_off_on_halt.sh` → **"10 passed, 18 failed"**
  — the failures are precisely the inverted-expectation mismatches (script
  still rewrites to 0, treats `=0` as already-set, etc.).
- GREEN (after script flip): same command → **"28 passed, 0 failed"**.
  All 7 scenarios pass under the new `=1` semantics.

**#2 — Test scenarios INVERTED (as specified):**
| Scenario | Old expectation | New expectation |
|---|---|---|
| 1 — line absent | no-op (default 0) | **rewrite to `=1`** (default 0 wrong on HAT) |
| 2 — `=0` | no-op | **rewrite to `=1`** (the F-6 defect class) |
| 3 — `=1` | rewrite to 0 | **no-op** (already correct on HAT) |
| 4 — `=2` | rewrite to 0 | **rewrite to `=1`** |
| 5 — tool missing | exit 1 | exit 1 (unchanged) |
| 6 — apply fails | exit 2 | exit 2 (mock canned config switched to `=0` so the rewrite path triggers and the apply then fails) |
| 7 — idempotency two-run | applies-then-no-op | applies-then-no-op (now converging on `=1`) |

**#3 — Header rewritten with topology rationale + provenance:** the script
header explicitly carries (a) the topology rationale ("X1209 holds the rail
up off its battery; `=0` leaves the PMIC active so external-power-return never
sees a wake edge — Finding B"); (b) the CIO 2026-05-18 lock; (c) the Check-B
empirical confirmation (1 cycle); (d) a pointer to
`offices/architect/findings/2026-05-18-architecture-md-corrections-definitive.md`
§11; (e) the F-6 root-of-the-chain-blocker label; (f) the honest "5-cycle IRL
still pending; never assert beyond evidence" qualifier.

**#4 — Both tests GREEN:**
- `bash tests/deploy/test_eeprom_power_off_on_halt.sh` → **28/28 PASS**.
- `pytest tests/deploy/test_deploy_pi_eeprom_config.py -v` → **3 passed in 45.49s**
  (all-scenarios-pass + bash-syntax + tool-missing-exit-1).

**#5 — Scope fence:** the 3 files in `4e7a6d4` are exactly the script + the
bash test + the pytest wrapper. **Zero production-code edits** beyond the
script itself. Powerwatch suite still **23 passed**; `python validate_config.py`
exit 0; `python -m ruff check` on the touched Python file → "All checks passed!".

**#6 — NOT redeployed:** deploy hazard stands. T8 is a code change to the
deploy script, not a deploy of the change. The script will take effect on the
**next** `/sprint-deploy-pm` run (Marcus's lane), AFTER chain validation.

**#7 — Provenance traceable:** the header explicitly cites both the CIO
decision (2026-05-18) and the Check-B empirical confirmation (Finding B
cleared at `=1`, 1 cycle), and points to the §11 definitive corrections file.
A future reader who finds the script does not need this gate note to
understand why the script enforces `=1`.

## Design invariants preserved
- **Honest provenance:** the header states what is locked (CIO decision),
  what is empirically confirmed (1-cycle Check B), what is still pending
  (5-cycle IRL acceptance), and what was retired (F-6 false `=0` contract).
  Never asserts beyond the evidence.
- **Idempotency:** the two-run drill still converges (run 1 applies, run 2
  is a no-op) — just on `=1` instead of `=0`.
- **SSOT for the locked decision:** the script is the single point where the
  decision lands at deploy time; the spec §11 (in `corrections-definitive.md`)
  is the single architectural source; this commit aligns them.

## Architectural significance
**T8 closes the documentation root of the V0.27.x chain blocker (F-6).**
Combined with T4's SSOT enforcement on the trigger side and T5's
ShutdownSequencer-via-provider trigger, the deploy + runtime sides are now
internally consistent: deploy lands `=1`, runtime trigger fires only on real
power loss via GPIO6, and the wake mechanism that Finding B proved at 1 cycle
is no longer fought by the deploy step. The remaining blocker for the chain
is the **5-cycle IRL acceptance drill** (out of code scope; CIO bench).

## Gate request
Per the per-task discipline I **STOP here** and await your gate before Task 9
(the same-sprint `specs/architecture.md` §2/§10.6/§11 + `docs/hardware-reference.md`
reconciliation — the design-gate doc updates that close F-1..F-6). — Ralph
