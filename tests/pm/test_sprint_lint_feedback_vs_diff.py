################################################################################
# File Name: test_sprint_lint_feedback_vs_diff.py
# Purpose/Description: TDD coverage for the US-282 / AI-002 sprint_lint.py
#     extension that walks every story.feedback.filesActuallyTouched entry,
#     gathers the union of changed files in commits between sprintBaseRef
#     and HEAD, and emits an error for each claim that does not appear in
#     any commit's tree-diff.  Closes the commit-but-not-stage pattern that
#     surfaced in Sprint 22 (rescue commit 096dade) and Sprint 23 (rescue
#     commit 6d8af99) -- two consecutive sprints needing PM-side recovery.
#
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-03    | Rex (US-282) | Initial -- TDD synthesis of the four spec-
#               |              | mandated cases (claim-present-OK, claim-
#               |              | missing-error, empty-feedback-OK,
#               |              | parenthetical-stripping) plus mixed-claim
#               |              | + invalid-feedback edge cases plus a
#               |              | TestLintStoryWiring class that exercises
#               |              | the --check-feedback opt-in flag through
#               |              | lintStory() with a real tmp_path git repo.
# ================================================================================
################################################################################

"""TDD tests for US-282: sprint_lint.py commit-vs-claim verifier.

The spec asks for 4+ parametrized cases that all FAIL pre-fix because
``lintFeedbackVsTreeDiff`` does not exist on the pre-fix module surface.
Post-fix, the function walks ``git log <sprintBaseRef>..HEAD`` (collected
via subprocess inside ``repoRoot``), unions the per-commit name-only
diffs into a single set of changed paths, then asserts every entry in
``story.feedback.filesActuallyTouched`` (after stripping the parenthetical
annotation via the existing US-274 ``parseFilesToTouchEntry`` helper)
appears in that union.  Missing claims emit one error per missing path
shaped ``"feedback claim missing from commits: '<path>'"``.

Cases covered (spec acceptance #3 mandates the first four):
    1. **claim-present-OK** -- feedback path appears in a commit's tree-diff
       between sprint-base and HEAD => 0 errors.
    2. **claim-missing-error** -- feedback path does NOT appear in any
       commit's tree-diff => 1 error mentioning the path.
    3. **empty-feedback-OK** -- ``filesActuallyTouched`` is empty (story
       not yet shipped) => 0 errors.
    4. **parenthetical-stripping** -- annotation contains nested parens;
       the path is parsed off the *first* ``" ("`` separator (mirrors
       US-274's parseFilesToTouchEntry contract) so the inner ``)`` never
       fools the lookup.
    5. **mixed-claims** -- two claims, one present, one missing => exactly
       one error and it names only the missing path.
    6. **invalid-feedback** -- story without ``feedback`` or with non-dict
       ``feedback`` is handled gracefully (no error, no crash).

A separate ``TestLintStoryWiringCheckFeedback`` class proves the function
is wired through ``lintStory()`` only when the new ``--check-feedback``
opt-in is on -- pre-ship lint runs (where ``filesActuallyTouched`` is
empty by design) MUST NOT spurious-fail.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

# ================================================================================
# Module loader (offices/pm/scripts/ is not a package; mirrors US-274 + schema_diff)
# ================================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / "offices" / "pm" / "scripts" / "sprint_lint.py"


def _loadSprintLint():  # noqa: ANN202 -- test helper
    """Load offices/pm/scripts/sprint_lint.py as a module.

    The script lives outside the importable ``src/`` tree so we use
    ``importlib.util`` to load it by absolute path -- same pattern as
    ``tests/pm/test_sprint_lint_filestotouch.py`` and
    ``tests/scripts/test_schema_diff.py``.
    """
    spec = importlib.util.spec_from_file_location("sprint_lint", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sprint_lint"] = mod
    spec.loader.exec_module(mod)
    return mod


sl = _loadSprintLint()


# ================================================================================
# Fixtures: synthetic git repo with a known base ref and committed paths
# ================================================================================


def _runGit(args: list[str], cwd: Path) -> str:
    """Tiny subprocess wrapper that fails loudly + returns stripped stdout.

    Tests use this for fixture setup; the production code under test has
    its own subprocess calls.  Keeping the fixture wrapper minimal makes
    the failure mode obvious if a Windows MINGW64 quirk surfaces (per
    US-282 stopCondition #1).
    """
    result = subprocess.run(  # noqa: S603 -- explicit args, hermetic tmp_path
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def gitRepo(tmp_path: Path) -> tuple[Path, str]:
    """Init a tmp git repo with one initial commit; return (path, baseRef).

    The initial commit becomes the synthetic ``sprintBaseRef`` -- tests
    add further commits on top to simulate sprint-branch work, then ask
    the lint function whether feedback claims appear in commits between
    the base and the new HEAD.
    """
    _runGit(["init", "-q", "-b", "main"], tmp_path)
    _runGit(["config", "user.email", "test@example.invalid"], tmp_path)
    _runGit(["config", "user.name", "Test User"], tmp_path)
    _runGit(["config", "commit.gpgsign", "false"], tmp_path)
    (tmp_path / "README.md").write_text("init\n", encoding="utf-8")
    _runGit(["add", "README.md"], tmp_path)
    _runGit(["commit", "-q", "-m", "init"], tmp_path)
    baseRef = _runGit(["rev-parse", "HEAD"], tmp_path)
    return tmp_path, baseRef


def _addCommit(repo: Path, relPath: str, content: str = "# stub\n", message: str = "add file") -> None:
    """Create + commit a single file under repo at the given relative path."""
    target = repo / relPath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _runGit(["add", relPath], repo)
    _runGit(["commit", "-q", "-m", message], repo)


# ================================================================================
# Spec-mandated cases per US-282 acceptance #3
# ================================================================================


class TestLintFeedbackVsTreeDiff:
    """Pure-function tests for the new commit-vs-claim verifier.

    All cases would FAIL pre-fix because ``lintFeedbackVsTreeDiff`` does
    not exist on the pre-fix module surface (AttributeError at the call
    site).  Post-fix, each case asserts the documented error / no-error
    behavior.
    """

    def test_claimPresentInCommit_returnsNoError(
        self, gitRepo: tuple[Path, str],
    ) -> None:
        """Case 1: feedback path appears in a commit tree-diff -> 0 errors."""
        repo, baseRef = gitRepo
        _addCommit(repo, "src/foo.py", message="add foo for story")
        story = {
            "feedback": {
                "filesActuallyTouched": [
                    "src/foo.py (UPDATE -- claim shipped)",
                ],
            },
        }

        errs = sl.lintFeedbackVsTreeDiff(story, repo, baseRef)

        assert errs == [], (
            f"present claim must not error; got {errs}"
        )

    def test_claimMissingFromCommits_returnsOneError(
        self, gitRepo: tuple[Path, str],
    ) -> None:
        """Case 2: feedback path NOT in any commit tree-diff -> 1 error.

        The literal Sprint 22/Sprint 23 rescue-pattern shape: feedback
        list claims a path that is never staged/committed.
        """
        repo, baseRef = gitRepo
        # Commit a DIFFERENT file than what the feedback claims.
        _addCommit(repo, "src/bar.py", message="add bar (unrelated)")
        story = {
            "feedback": {
                "filesActuallyTouched": [
                    "src/foo.py (UPDATE -- this claim never landed in any commit)",
                ],
            },
        }

        errs = sl.lintFeedbackVsTreeDiff(story, repo, baseRef)

        assert len(errs) == 1, f"expected exactly 1 error; got {errs}"
        assert "src/foo.py" in errs[0]
        assert "feedback claim missing from commits" in errs[0].lower()
        # Belt-and-braces: error must NOT spuriously name the unrelated file.
        assert "src/bar.py" not in errs[0]

    def test_emptyFeedback_returnsNoError(
        self, gitRepo: tuple[Path, str],
    ) -> None:
        """Case 3: empty filesActuallyTouched (story not yet shipped) -> 0 errors.

        The opt-in flag default-off plus this case together guarantee
        pre-ship lint runs (where every story has ``feedback``: ``{
        filesActuallyTouched: [], grounding: ""}``) DO NOT spurious-fail.
        """
        repo, baseRef = gitRepo
        story = {
            "feedback": {
                "filesActuallyTouched": [],
                "grounding": "",
            },
        }

        errs = sl.lintFeedbackVsTreeDiff(story, repo, baseRef)

        assert errs == [], f"empty feedback must be a no-op; got {errs}"

    def test_parentheticalStripping_pathParsedCorrectly(
        self, gitRepo: tuple[Path, str],
    ) -> None:
        """Case 4: annotation with nested parens -> path parsed off first ' ('.

        Mirrors US-274's parseFilesToTouchEntry contract: the parser must
        split on the *first* ``" ("`` so an inner ``")"`` inside the
        annotation never confuses the path boundary.  If the parser were
        wrong, the lookup would search for the literal entry string
        (containing ``" (UPDATE -- ..."``) which would never match and
        spurious-fail this case.
        """
        repo, baseRef = gitRepo
        _addCommit(repo, "src/foo.py", message="add foo")
        story = {
            "feedback": {
                "filesActuallyTouched": [
                    "src/foo.py (UPDATE -- adds (helper) and validate())",
                ],
            },
        }

        errs = sl.lintFeedbackVsTreeDiff(story, repo, baseRef)

        assert errs == [], (
            f"nested-paren annotation must not break path lookup; got {errs}"
        )

    def test_mixedClaims_emitsErrorOnlyForMissing(
        self, gitRepo: tuple[Path, str],
    ) -> None:
        """Case 5: two claims, one present, one missing -> exactly 1 error."""
        repo, baseRef = gitRepo
        _addCommit(repo, "src/present.py", message="add present (shipped)")
        story = {
            "feedback": {
                "filesActuallyTouched": [
                    "src/present.py (UPDATE -- this one shipped)",
                    "src/missing.py (UPDATE -- this one did NOT)",
                ],
            },
        }

        errs = sl.lintFeedbackVsTreeDiff(story, repo, baseRef)

        assert len(errs) == 1, f"expected exactly 1 error; got {errs}"
        assert "src/missing.py" in errs[0]
        # Belt-and-braces: error must NOT name the present file.
        assert "src/present.py" not in errs[0]

    def test_missingFeedbackKey_returnsNoError(
        self, gitRepo: tuple[Path, str],
    ) -> None:
        """Case 6a: story without 'feedback' at all -> graceful no-op."""
        repo, baseRef = gitRepo
        story: dict = {}

        errs = sl.lintFeedbackVsTreeDiff(story, repo, baseRef)

        assert errs == []

    def test_nonDictFeedback_returnsNoError(
        self, gitRepo: tuple[Path, str],
    ) -> None:
        """Case 6b: feedback is None / wrong type -> graceful no-op.

        The structural-shape warning belongs to the existing lintStory()
        feedback check, not to this verifier.  This function must never
        crash on malformed input.
        """
        repo, baseRef = gitRepo
        story = {"feedback": None}

        errs = sl.lintFeedbackVsTreeDiff(story, repo, baseRef)

        assert errs == []


# ================================================================================
# Wiring test: lintStory() respects the --check-feedback opt-in
# ================================================================================


class TestLintStoryWiringCheckFeedback:
    """Acceptance #2 of US-282: lintStory must surface feedback errors only when checkFeedback=True.

    Default off so pre-ship lint runs (where ``filesActuallyTouched`` is
    empty by design) DO NOT spurious-fail.  When the opt-in is on, the
    new check fires alongside the existing checks and contributes its
    own error class to the lintStory() error list.
    """

    def _makeStory(self, filesActuallyTouched: list[str]) -> dict:
        """Minimal valid story dict with feedback populated."""
        return {
            "id": "US-999",
            "title": "test fixture story",
            "size": "S",
            "intent": "fixture",
            "priority": "high",
            "dependencies": [],
            "scope": {"filesToTouch": [], "filesToRead": []},
            "groundingRefs": [],
            "acceptance": ["Pre-flight audit: noop"],
            "verification": [],
            "invariants": [],
            "feedback": {
                "filesActuallyTouched": filesActuallyTouched,
                "grounding": "test",
            },
            "passes": False,
        }

    def test_lintStory_checkFeedbackOff_skipsCheck(
        self, gitRepo: tuple[Path, str],
    ) -> None:
        """Default off -- a missing claim must NOT spurious-fail."""
        repo, baseRef = gitRepo
        story = self._makeStory(
            ["src/never_committed.py (UPDATE -- claim)"],
        )

        # checkFeedback default-off means no feedback-vs-diff errors are
        # produced even when feedback claims a missing file.
        errs, _warns = sl.lintStory(story, repoRoot=repo)

        feedbackErrs = [e for e in errs if "feedback claim" in e.lower()]
        assert feedbackErrs == [], (
            f"checkFeedback default-off must skip the check; got {errs}"
        )

    def test_lintStory_checkFeedbackOn_missingClaim_emitsError(
        self, gitRepo: tuple[Path, str],
    ) -> None:
        """checkFeedback=True -- missing claim contributes a feedback error."""
        repo, baseRef = gitRepo
        # Add a different file so HEAD has at least one commit beyond base.
        _addCommit(repo, "src/something_else.py", message="unrelated")
        story = self._makeStory(
            ["src/never_committed.py (UPDATE -- the bug-class)"],
        )

        errs, _warns = sl.lintStory(
            story,
            repoRoot=repo,
            checkFeedback=True,
            sprintBaseRef=baseRef,
        )

        feedbackErrs = [e for e in errs if "feedback claim" in e.lower()]
        assert len(feedbackErrs) >= 1, (
            f"checkFeedback=True must surface feedback errors; got errs={errs}"
        )
        assert any("src/never_committed.py" in e for e in feedbackErrs), (
            f"feedback error must name the missing path; got {feedbackErrs}"
        )
