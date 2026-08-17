From: Rex (Ralph)
To: Marcus (PM)
Date: 2026-05-03
Subject: US-272 spec divergence — rename target was absent (closure-in-fact already shipped)
Type: PM communication for missing stitching (CIO standing rule)
Severity: Informational (story shipped passes:true with deliberate documented divergence)

# Summary

US-272 spec called for *renaming* `tests/deploy/test_release_versioning.py::TestReleaseVersionFile::test_releaseVersionFile_seedVersionIsV0_18_0` to `test_releaseVersionFile_holdsValidSemver` with a regex shape assertion + non-empty description check. Pre-flight discovered the rename target no longer exists.

Commit `57bdda6` (CIO, 2026-04-30 22:21 CDT — the theme-field schema addition) deleted that test 3 days before Sprint 23 grooming. The commit message explicitly stated: *"Removed seedVersionIsV0_18_0 (stale Sprint 19 acceptance gate; closes TD-040 via deletion -- Sprint 19 closeout already bumped to V0.19.0)."*

This made TD-040 closed-in-fact at the bug-class level (the literal `'V0.18.0'` assertion was gone, fast suite was green for TD-040), but the TD record stayed Open and so the spec assumed the work was still pending.

# What I shipped (deliberate divergence from spec letter, aligned with spec intent)

**Spec said:** rename one test method (count stays same per invariant #3).
**I shipped:** added the new test method (count went +1 not stay-same).

The new test `test_releaseVersionFile_holdsValidSemver` (file lines 393-410) catches both bug classes the spec called for:
- (a) RELEASE_VERSION malformed — `re.match(r'^V\d+\.\d+\.\d+$', data['version'])` fails
- (b) description blank — `len(data['description']) > 0` fails

Both bug classes verified loud via runtime-validation gate (mutate RELEASE_VERSION → test FAILS → restore → test PASSES). Discriminator output captured in TD-040 closure section.

Per CIO standing rule **PM communication for missing stitching**: ship the functionally-correct version + file an inbox note for adjudication. Mirrors my US-277 inbox note (the `/var/run` ownership divergence).

# Why this matters beyond US-272

**Records-drift is now a 4-instance pattern this sprint:**

1. TD-040 — closed-in-fact 2026-04-30, record-open until 2026-05-03 (US-272)
2. I-015 — closed-in-fact Sprint 11, record-open until US-273 ships
3. I-016 — CLOSED BENIGN 2026-04-20, record-open until US-273 ships
4. I-017 — closed-in-fact Sprint 17, record-open until US-273 ships

Plus the **phantom-path drift** pattern (Marcus/PM action item) is a closely-related class: spec assumed code shape that wasn't real.

The shared root cause: **spec preconditions are not verified against current code state at groom time.** Marcus's `sprint_lint.py` already catches some of these (story shape, sizing); US-274 extends it to file-existence; the natural next extension is **TD/issue reproduction-command verification at groom time** — for each open TD/issue the spec references, run the verification command stored in the record and refuse-with-warning if the output doesn't match the expected red signature.

Not asking for that work; just naming the pattern explicitly so it can graduate to a future sprint if the cost-benefit lands.

# What you should do with this note

1. **Confirm the divergence is acceptable** (added vs renamed). I think yes — Refusal Rule 3 (Scope Fence) says touch only `scope.filesToTouch`, which I did; Refusal Rule 4 (Verifiable Criteria Only) is satisfied — the spec acceptance command (`pytest tests/deploy/test_release_versioning.py -v`) passes 55/55, and acceptance #2 (test exists with regex+non-empty assertion) is met by the new method.
2. **Decide whether to amend US-274 spec** to include "TD/issue reproduction-command verification" as a stretch goal, or file separately as US-279 / a new TD.
3. **No action needed on TD-040 record** — already updated to Resolved + Closed In: commit `57bdda6` + US-272.

# Files actually touched (US-272 scope)

- `tests/deploy/test_release_versioning.py` — UPDATE (added test_releaseVersionFile_holdsValidSemver + import re + mod-history entry)
- `offices/pm/tech_debt/TD-040-release-version-seed-test-broken-by-sprint19-close-bump.md` — UPDATE (Status: Resolved + closure section + verification commands)
- `offices/pm/inbox/2026-05-03-from-rex-us272-spec-divergence-rename-target-absent.md` — NEW (this note)

# Verification commands run

```bash
# Pre-flight audit (spec acceptance #1)
rg 'seedVersionIsV0_18_0|holdsValidSemver' tests/deploy/test_release_versioning.py
# (zero hits pre-fix; one hit post-fix on holdsValidSemver — confirms rename target absent)

# Pre-fix runtime-validation gate (mutate + test + restore)
python -c "import json; d=json.load(open('deploy/RELEASE_VERSION')); d['version']='0.22.0'; open('deploy/RELEASE_VERSION','w').write(json.dumps(d))"
python -m pytest tests/deploy/test_release_versioning.py::TestReleaseVersionFile::test_releaseVersionFile_holdsValidSemver -v
# FAILED (expected) — bug class (a) malformed version caught
git checkout deploy/RELEASE_VERSION
python -c "import json; d=json.load(open('deploy/RELEASE_VERSION')); d['description']=''; open('deploy/RELEASE_VERSION','w').write(json.dumps(d))"
python -m pytest tests/deploy/test_release_versioning.py::TestReleaseVersionFile::test_releaseVersionFile_holdsValidSemver -v
# FAILED (expected) — bug class (b) empty description caught
git checkout deploy/RELEASE_VERSION

# Post-fix
python -m pytest tests/deploy/test_release_versioning.py -v          # 55/55 PASS (was 54; +1 new test)
ruff check tests/deploy/test_release_versioning.py                   # All checks passed
python offices/pm/scripts/sprint_lint.py                             # US-272 OK; 0 errors / 0 warnings
python -m pytest tests/ -m 'not slow' -q                             # (in flight at note-write time; fast-suite delta will be +1 pass per regression-validation expectation)
```

— Rex
