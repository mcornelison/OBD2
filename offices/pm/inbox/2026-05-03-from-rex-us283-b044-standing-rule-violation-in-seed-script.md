# US-283 Sprint-Adjacent Drift — B-044 Standing-Rule Lint Failing on Sprint Branch

**Date**: 2026-05-03
**From**: Rex (Ralph, Agent 1)
**To**: Marcus (PM)
**Priority**: Low — does NOT block US-283 ship; flagged per CIO Q1 rule (drift filed immediately, not log-and-forget)

## TL;DR

The B-044 standing-rule lint test (`tests/lint/test_no_hardcoded_addresses.py::TestAuditRepositoryStandingRule::test_auditRepository_cleanRepository_zeroFindings`) is **failing on the current sprint branch** (`sprint/sprint24-ladder-fix`). The failure is **pre-existing**, dating to commit `35e1374` (2026-05-01 11:59 CDT, `fix(seed): add Eclipse VIN row to Pi sqlite + chi-srv-01 vehicle_info`), and has been on disk since before Sprint 23 close. NOT a US-283 regression. Filing per CIO Q1 rule for sprint-adjacent drift observation.

## The 3 Violations

```
scripts/seed_eclipse_vin.py:80   [hostname] ECLIPSE_DEVICE_ID = "chi-eclipse-01"
scripts/seed_eclipse_vin.py:332  [ip]       default=os.environ.get("SERVER_BASE_URL", "http://10.27.27.10:8000"),
scripts/seed_eclipse_vin.py:333  [hostname] help="Server base URL (default: production chi-srv-01).",
```

All 3 are in `scripts/seed_eclipse_vin.py`, a one-off seeder. None is in any sprint scope and none is in `src/`.

## Why It Slipped Past Sprint 23 Close

Sprint 24 testBaseline note in sprint.json says *"Verify exact count at sprint start"* but the discriminator was deferred. The three violations have been failing the lint test since 2026-05-01 evening — Sprint 22 close, Sprint 23 close, and Sprint 24 grooming all let it through. Today's US-283 fast-suite run is the first to surface it explicitly.

## Verification

- `git log -1 --format="%h %ai" -- scripts/seed_eclipse_vin.py` → `35e1374 2026-05-01 11:59:19 -0500` (single commit, unchanged since)
- `git status --short scripts/seed_eclipse_vin.py` → no modifications in working tree
- US-283 working-tree diff touches only `tests/pi/diagnostics/test_boot_reason.py` + sprint.json/ralph_agents.json/progress.txt — zero overlap with `scripts/`
- `pytest tests/pi/diagnostics/test_boot_reason.py -v` → 47 passed (44 baseline + 3 US-283 new); my work is clean

## Recommended Disposition

Three options for Marcus's call (not for me to pick — outside Sprint 24 scope):

1. **Add `# b044-exempt: <reason>` markers** to the 3 lines (the seeder is a one-off Eclipse-specific script; "frozen here as version-controlled truth" per file comment). 5-minute fix; 1-line per violation; lowest-friction path. Could even land as a chore commit on the sprint branch before merge to keep the branch's fast suite green.
2. **Wrap into a Sprint 25 story** ("Move Eclipse seeder constants behind config.json") — heavier; may not be worth the engineering for a one-off seeder.
3. **Accept as TD** — file `TD-047-seed-script-b044-exempt-needed.md` with severity Low, audit-only; close in a future cleanup sprint.

My read: Option 1 is the cheapest correct fix and keeps the standing-rule contract honest. The seeder genuinely IS Eclipse-specific (per the file's "Canonical Eclipse VIN record -- frozen here as version-controlled truth" header comment); B-044 exemption markers exist exactly for this case.

## US-283 Ship Decision

I am proceeding to ship US-283 (`passes: true`, schema-assertion test added per US-273 closure-in-fact-pre-existed pattern) despite the standing-rule failure, because:

- The failure is unambiguously pre-existing (git log + working-tree confirms zero US-283 overlap)
- US-283 itself ships clean: 47/47 boot_reason tests pass, ruff clean, sprint_lint clean
- Per `feedback_strict_story_focus`: I MUST NOT fix `scripts/seed_eclipse_vin.py` from inside US-283 — that's scope creep
- Per CIO Q1 rule: flagging via this inbox note IS the correct disciplined response

If Marcus prefers I block US-283 until the seeder is exempt-marked, send a counter-note and I'll roll back the `passes:true` flip.

---

**Forensic artifact**: full pytest output at session task `b7ylcrvu1.output` shows `1 failed, 3932 passed, 17 skipped, 19 deselected in 1047.66s (0:17:27)`. The 3932 passed = 3850 baseline + 82 from Sprint 24 work (US-279/280/281/282 ancillary tests + US-283's +3). Single failure is the B-044 lint as documented above.

---

## P.S. — Sprint 24 Rescue Scope Has Grown Beyond Session 156's Note

Session 156 (Rex) filed `2026-05-03-from-rex-us282-first-catch-us280-uncommitted-test-file.md` flagging that US-280's `tests/pi/power/test_orchestrator_state_file.py` was uncommitted. Running `sprint_lint.py --check-feedback` from this Session 157 reveals **the rescue scope is actually 5 files across 3 stories**, not 1 file under 1 story:

```
$ python offices/pm/scripts/sprint_lint.py --check-feedback
  US-279   OK
  US-280
    ERROR   feedback claim missing from commits: 'tests/pi/power/test_orchestrator_state_file.py'
  US-281
    ERROR   feedback claim missing from commits: 'specs/anti-patterns.md'
    ERROR   feedback claim missing from commits: 'offices/pm/tech_debt/TD-046-stale-state-cross-component.md'
  US-282
    ERROR   feedback claim missing from commits: 'offices/pm/scripts/sprint_lint.py'
    ERROR   feedback claim missing from commits: 'tests/pm/test_sprint_lint_feedback_vs_diff.py'
  US-283
    ERROR   feedback claim missing from commits: 'tests/pi/diagnostics/test_boot_reason.py'

Summary: 6 error(s), 0 warning(s) across 5 stories
```

(The 6th error is my own US-283 work — resolves the moment my Session 157 commit lands. The other 5 errors are the actual rescue scope.)

**Recommended retroactive rescue commit on `sprint/sprint24-ladder-fix` before merge** — same shape as `096dade` (Sprint 22 US-262) and `6d8af99` (Sprint 23 US-275/276/277):

```bash
git add tests/pi/power/test_orchestrator_state_file.py \
        src/pi/power/orchestrator.py \
        specs/anti-patterns.md \
        offices/pm/tech_debt/TD-046-stale-state-cross-component.md \
        offices/pm/scripts/sprint_lint.py \
        offices/pm/action-items.md \
        tests/pm/test_sprint_lint_feedback_vs_diff.py
git commit -m "feat: [US-280 + US-281 + US-282] rescue Sprint 24 work uncommitted on disk"
```

After that commit, `python offices/pm/scripts/sprint_lint.py --check-feedback` should report 0 errors across all 5 Sprint 24 stories (assuming my US-283 commit also lands).

**Why Session 156's note didn't see this**: Session 156 ran `--check-feedback` after committing US-281's anti-patterns.md and TD-046 to the working tree but before committing them to git, AND it shipped US-282 but didn't commit US-282's own files either — so the only first-catch the lint reported at Session 156 wall-clock was the US-280 path that was already there from a prior session. The lint correctly reported what existed at that moment; the moment expanded as Session 156 added more work without committing.

**Why this is the third strike of AI-002 in the same sprint that supposedly closed AI-002**: US-282 itself shipped the detector but its own implementation didn't get committed. The detector works (it caught itself); the staging-discipline gap that AI-002 was meant to plug is bigger than the detector alone can close. Per Session 156's recommendation #3 (carryforward TD on Ralph's commit-vs-stage workflow): worth elevating to a Sprint 25 P0 candidate, since the detector CAN catch the bug but it ran under `--check-feedback` opt-in (not default-on) and ralph-side didn't run it before claiming `passes:true`. **Default-on `--check-feedback` would have surfaced this in Session 156** — but flipping a default mid-sprint is a Marcus call.

I am **not** taking a rescue action from US-283 because (a) per Strict Story Focus rule, US-280/281/282 are not in my scope; (b) per memory `feedback_ralph_no_git_commands.md`, Ralph CAN commit on the sprint branch but the rescue commit's message would have to attribute work to stories I didn't ship — that feels like the kind of branch-topology decision the same memory says PM (Marcus) owns. If Marcus prefers I do the rescue commit on the sprint branch instead of doing it himself, send a counter-note and I'll execute.
