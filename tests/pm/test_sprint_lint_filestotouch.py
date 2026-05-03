################################################################################
# File Name: test_sprint_lint_filestotouch.py
# Purpose/Description: TDD coverage for the US-274 / AI-001 sprint_lint.py
#     extension that walks every story.scope.filesToTouch entry and verifies
#     UPDATE-annotated paths exist on disk (NEW paths exempt).  Closes the
#     phantom-path drift pattern that has surfaced ~once per sprint across
#     Sprints 14-22 (9-session history).
#
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-03    | Rex (US-274) | Initial -- TDD synthesis of the 5 parametrized
#               |              | path-existence cases mandated by the spec
#               |              | (NEW-missing-OK, UPDATE-missing-error,
#               |              | UPDATE-present-OK, no-annotation-missing-error,
#               |              | sub-parenthetical-stripped) plus an integration
#               |              | test that exercises the wiring through
#               |              | lintStory() against a synthetic story dict.
# ================================================================================
################################################################################

"""TDD tests for US-274: sprint_lint.py path-existence check.

The spec asks for 5 parametrized cases that all FAIL pre-fix (because
``lintFilesToTouchPaths`` does not exist on the pre-fix module surface).
Post-fix, the function classifies each ``scope.filesToTouch`` entry by
parenthetical annotation and emits errors for missing UPDATE / no-annotation
paths only -- NEW paths are exempt because they are explicitly marked as
files the story is creating.

Cases parametrized below:
    1. NEW-missing-OK -- ``(NEW -- ...)`` annotation + missing on disk = no error.
    2. UPDATE-missing-error -- ``(UPDATE -- ...)`` + missing = one error.
    3. UPDATE-present-OK -- ``(UPDATE -- ...)`` + present = no error.
    4. no-annotation-missing-error -- bare path string + missing = one error.
    5. sub-parenthetical-stripped -- annotation contains nested parens; path
       is parsed off the *first* ``" ("`` separator, never confused.

A separate ``TestLintStoryWiring`` class confirms the function is wired
into ``lintStory`` so the main script catches phantom paths in real
sprint.json files.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ================================================================================
# Module loader (offices/pm/scripts/ is not a package; mirrors test_schema_diff)
# ================================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / "offices" / "pm" / "scripts" / "sprint_lint.py"


def _loadSprintLint():  # noqa: ANN202 -- test helper
    """Load offices/pm/scripts/sprint_lint.py as a module.

    The script lives outside the importable ``src/`` tree so we use
    importlib.util to load it by absolute path -- same pattern as
    tests/scripts/test_schema_diff.py.
    """
    spec = importlib.util.spec_from_file_location("sprint_lint", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sprint_lint"] = mod
    spec.loader.exec_module(mod)
    return mod


sl = _loadSprintLint()


# ================================================================================
# Fixtures: synthetic repo root with one real file on disk
# ================================================================================


@pytest.fixture
def syntheticRepo(tmp_path: Path) -> Path:
    """A scratch repo root with one known-existing file at 'real/exists.py'.

    Tests that need to assert "path-present" use this fixture's known file;
    tests asserting "path-missing" name a different path that is never
    created.  Using a tmp_path keeps tests hermetic from the real repo.
    """
    realDir = tmp_path / "real"
    realDir.mkdir()
    (realDir / "exists.py").write_text("# present\n", encoding="utf-8")
    return tmp_path


# ================================================================================
# 5 parametrized cases mandated by US-274 acceptance #3
# ================================================================================


class TestLintFilesToTouchPaths:
    """Parametrized matrix per spec acceptance #3.

    All 5 cases would FAIL pre-fix because ``lintFilesToTouchPaths`` does
    not exist on the pre-fix module surface (AttributeError on lookup).
    Post-fix, each case asserts the documented error / no-error behavior.
    """

    @pytest.mark.parametrize(
        ("entry", "expectedErrorCount", "caseLabel"),
        [
            # 1. NEW-missing-OK: NEW annotation + missing on disk -> no error.
            (
                "missing/new_module.py (NEW -- to be created by this story)",
                0,
                "NEW-missing-OK",
            ),
            # 2. UPDATE-missing-error: UPDATE annotation + missing -> one error.
            (
                "missing/phantom.py (UPDATE -- expected to exist but does not)",
                1,
                "UPDATE-missing-error",
            ),
            # 3. UPDATE-present-OK: UPDATE annotation + file exists -> no error.
            (
                "real/exists.py (UPDATE -- patch existing file)",
                0,
                "UPDATE-present-OK",
            ),
            # 4. no-annotation-missing-error: bare path with no parens -> error.
            (
                "missing/bare_path.py",
                1,
                "no-annotation-missing-error",
            ),
            # 5. sub-parenthetical-stripped: nested parens in annotation -> path
            #    is parsed off the FIRST " (" so the inner ")" never fools the
            #    parser; the entry below names a missing UPDATE path so the
            #    correctness of parsing is what's exercised (one error).
            (
                "missing/nested.py (UPDATE -- adds (helper) and validate())",
                1,
                "sub-parenthetical-stripped",
            ),
        ],
    )
    def test_lintFilesToTouchPaths_classifyPath_matchesSpec(
        self,
        entry: str,
        expectedErrorCount: int,
        caseLabel: str,
        syntheticRepo: Path,
    ) -> None:
        """Each spec-listed case yields the documented error count."""
        story = {"scope": {"filesToTouch": [entry]}}

        errs = sl.lintFilesToTouchPaths(story, syntheticRepo)

        assert len(errs) == expectedErrorCount, (
            f"case {caseLabel!r}: expected {expectedErrorCount} error(s), "
            f"got {len(errs)}: {errs}"
        )

    def test_lintFilesToTouchPaths_subParenthetical_pathStrippedCleanly(
        self, syntheticRepo: Path,
    ) -> None:
        """Case 5 strict: error message names the bare path, not the entry.

        Belt-and-braces against a parser that splits on the *last* ")"
        instead of the *first* " (".  Such a parser would produce an error
        message that includes the annotation tail in the path string.
        """
        entry = "missing/nested.py (UPDATE -- adds (helper) and validate())"
        story = {"scope": {"filesToTouch": [entry]}}

        errs = sl.lintFilesToTouchPaths(story, syntheticRepo)

        assert len(errs) == 1
        # Path is the bare prefix; the annotation tail must not leak into it.
        assert "missing/nested.py" in errs[0]
        assert "(helper)" not in errs[0]
        assert "validate()" not in errs[0]


# ================================================================================
# Wiring test: lintStory() emits path-existence errors when wired
# ================================================================================


class TestLintStoryWiring:
    """Acceptance #4 of US-274: lintStory must surface path-existence errors.

    The standalone function above is necessary but not sufficient: the
    main script flow runs lintStory() per story, so the new check must be
    wired in there (or the main loop must call it separately).  This test
    proves the wiring by feeding lintStory() a synthetic story whose
    UPDATE path is missing on disk and asserting the error appears.
    """

    def _makeStory(self, filesToTouch: list[str]) -> dict:
        """Minimal valid story dict; only scope.filesToTouch matters here."""
        return {
            "id": "US-999",
            "title": "test fixture story",
            "size": "S",
            "intent": "fixture",
            "priority": "high",
            "dependencies": [],
            "scope": {"filesToTouch": filesToTouch, "filesToRead": []},
            "groundingRefs": [],
            "acceptance": ["Pre-flight audit: noop"],
            "verification": [],
            "invariants": [],
            "feedback": {"filesActuallyTouched": [], "grounding": ""},
            "passes": False,
        }

    def test_lintStory_missingUpdatePath_surfacesError(self) -> None:
        """A phantom UPDATE path in a synthetic story trips lintStory()."""
        story = self._makeStory(
            ["definitely/does/not/exist/phantom.py (UPDATE -- nope)"],
        )

        errs, _warns = sl.lintStory(story)

        # The new path-existence check must contribute >=1 error.
        pathErrs = [e for e in errs if "phantom.py" in e]
        assert len(pathErrs) >= 1, (
            f"expected lintStory to surface phantom.py path error; got errs={errs}"
        )

    def test_lintStory_newPathMissing_doesNotError(self) -> None:
        """A NEW path that doesn't exist on disk is exempt from the check."""
        story = self._makeStory(
            ["definitely/does/not/exist/brand_new.py (NEW -- about to create)"],
        )

        errs, _warns = sl.lintStory(story)

        pathErrs = [e for e in errs if "brand_new.py" in e]
        assert pathErrs == [], (
            f"NEW paths must be exempt from existence check; got errs={errs}"
        )
