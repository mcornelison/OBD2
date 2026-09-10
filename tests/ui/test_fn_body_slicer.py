################################################################################
# File Name: test_fn_body_slicer.py
# Purpose/Description: US-608 (TD-080) -- the gate ON the gate. `_fnBody` is the
#   single shipped-JS function slicer that ~20 carousel wiring assertions read
#   their subject through, so a defect in IT is invisible in the direction that
#   matters: an over-broad span makes `assert X in body` pass on text the
#   function never contained, and an empty span makes `assert X not in body`
#   pass on nothing at all. Both are assertions that cannot fail.
#
#   WHY THIS FILE EXISTS RATHER THAN A ONE-OFF PROOF. Nine near-copies of this
#   helper existed before US-608, four of them with mutually incompatible
#   delimiters, and MEASURED 2026-09-09 all 17 live call sites got the wrong
#   span. Nobody noticed for eight sprints because nothing tested the slicer --
#   the suites tested carousel.js THROUGH it. These are the pins that make the
#   next wrong span a red test instead of a silent pass, including the SSOT
#   predicate itself (`test_fnBody_isTheOnlySlicerUnderTests`), so a tenth copy
#   arrives as a failure rather than as drift.
#
#   Deliberately pure-Python: the slicer is source-text analysis, so these need
#   no node and no probe, and they run in milliseconds as an in-loop gate.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-09
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-09    | Ralph (Rex)  | Initial -- US-608 slicer contract + SSOT guard.
# ================================================================================
################################################################################

"""Contract tests for the `_fnBody` shipped-JS slicer (US-608 / TD-080)."""

from __future__ import annotations

import os
import re

import pytest

from tests.ui.render_harness import FunctionSliceError, _fnBody

_TESTS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_CAROUSEL = os.path.join(
    _TESTS_ROOT, "..", "src", "pi", "ui", "dashboard", "carousel.js"
)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# The SSOT predicate -- acceptance expressed as a runnable check, not a count
# in prose. This is the pin that makes a tenth copy a red test.
# ---------------------------------------------------------------------------


def test_fnBody_isTheOnlySlicerUnderTests():
    """
    Given: US-608 consolidated nine `_fnBody` near-copies into one
    When: every .py file under tests/ is scanned for a `_fnBody` DEFINITION
    Then: exactly one exists, and it is the shared helper in render_harness.

          A count in a story is a fact about one afternoon. This is the same
          fact as a permanent control: the duplication is why the shared bug
          survived eight sprints, so the guard has to outlive the cleanup.
    """
    definition = re.compile(r"^[ \t]*def[ \t]+_fnBody[ \t]*\(", re.M)
    found = []
    for root, _dirs, files in os.walk(_TESTS_ROOT):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            if definition.search(_read(path)):
                found.append(os.path.relpath(path, _TESTS_ROOT).replace("\\", "/"))
    assert found == ["ui/render_harness.py"], (
        f"expected the single US-608 SSOT slicer, found {len(found)}: {found}. "
        "A second definition is TD-080 growing back."
    )


# ---------------------------------------------------------------------------
# The raising contract -- never a partial, never an empty span.
# ---------------------------------------------------------------------------


def test_fnBody_raisesNamingTheFunctionWhenItIsMissing():
    """A slicer that returns "" for a function it cannot find makes every
    absence assertion over the result pass for free. It must fail as a test."""
    js = "  function present() {\n    return 1;\n  }\n"
    with pytest.raises(FunctionSliceError) as excinfo:
        _fnBody(js, "absent")
    assert "absent" in str(excinfo.value), "the error must name the function"


def test_fnBody_raisesRatherThanReturnAnUndelimitableBody():
    """An unbalanced body is a truncated file or a bad edit -- either way the
    honest answer is "I cannot tell you", not a span running to EOF."""
    js = "  function truncated() {\n    if (x) {\n      go();\n"
    with pytest.raises(FunctionSliceError):
        _fnBody(js, "truncated")


def test_fnBody_neverReturnsAnEmptySpanForAnyRealDeclaration():
    """The empty-span failure mode is the whole subject of this story: it is
    silent, and it flips every `not in` assertion to a vacuous pass."""
    js = _read(_CAROUSEL)
    declared = set(
        re.findall(r"^[ \t]*(?:async[ \t]+)?function[ \t]+(\w+)[ \t]*\(", js, re.M)
    )
    empties = []
    for name in sorted(declared):
        try:
            if not _fnBody(js, name).strip():
                empties.append(name)
        except FunctionSliceError:
            pass  # raising is the contract; only a silent empty span is a defect
    assert empties == [], f"empty span returned for {empties}"


# ---------------------------------------------------------------------------
# Delimiting -- exact, and not fooled by indentation.
# ---------------------------------------------------------------------------


def test_fnBody_extractsAKnownFunctionExactly():
    """The span is the declaration through its OWN closing brace: no leading
    neighbour, no trailing sibling."""
    js = (
        "  function before() {\n    return 0;\n  }\n\n"
        "  function target(a, b) {\n    return a + b;\n  }\n\n"
        "  function after() {\n    return 9;\n  }\n"
    )
    body = _fnBody(js, "target")
    assert body == "function target(a, b) {\n    return a + b;\n  }"
    assert "before" not in body
    assert "after" not in body


def test_fnBody_delimitsANestedFunctionWithoutTruncating():
    """A body containing a NESTED declaration is returned whole. The pre-US-608
    copies cut at "the next `function` at a fixed indent", which for an outer
    function is its own child -- truncating the body at its first nested helper
    and making every assertion about the rest of it vacuous."""
    js = (
        "  function outer() {\n"
        "    var n = 1;\n"
        "    function inner() {\n"
        "      return TARGET_TOKEN;\n"
        "    }\n"
        "    return inner() + n;\n"
        "  }\n"
        "  function sibling() {\n    return 0;\n  }\n"
    )
    body = _fnBody(js, "outer")
    assert "function inner()" in body, "the nested declaration was truncated away"
    assert "TARGET_TOKEN" in body
    assert "return inner() + n;" in body, "the body was cut at its nested function"
    assert "sibling" not in body, "the span ran on into the next declaration"


def test_fnBody_doesNotTruncateAtADedentLookingLine():
    """A closing brace at a SHALLOWER indent than the function's own does not
    end it. An indent-anchored slicer stops at the first line that merely looks
    like a dedent; brace matching does not."""
    js = (
        "      function deep() {\n"
        "        if (a) {\n"
        "  }\n"  # a `}` at 2 spaces -- shallower than the declaration itself
        "        return LATE_TOKEN;\n"
        "      }\n"
    )
    body = _fnBody(js, "deep")
    assert "LATE_TOKEN" in body, "truncated at a shallower-looking closing brace"


def test_fnBody_handlesASingleLineBody():
    """carousel.js:3478 declares `function two(n) { ... }` entirely on one line,
    so there is no `\\n<indent>}` to anchor on. The indent-anchored copies ran on
    to the next same-indent brace and swallowed sibling declarations."""
    js = _read(_CAROUSEL)
    body = _fnBody(js, "two")
    assert body.count("\n") == 0, f"one-liner span spread over lines: {body!r}"
    assert body.endswith("}")
    assert "function two(n)" in body


def test_fnBody_bracesInsideStringLiteralsDoNotCloseTheBody():
    """The shipped kit builds markup from quoted strings that contain braces
    (carousel.js has four `", { class: "` fragments). A brace counter that does
    not skip string literals closes the body early."""
    js = (
        "  function withStrings() {\n"
        '    var a = "{";\n'
        "    var b = '}';\n"
        "    var c = `a } b {`;\n"
        "    return LAST_TOKEN;\n"
        "  }\n"
    )
    body = _fnBody(js, "withStrings")
    assert "LAST_TOKEN" in body, "a brace inside a string literal closed the body"


def test_fnBody_bracesInsideCommentsDoNotCloseTheBody():
    js = (
        "  function withComments() {\n"
        "    // }\n"
        "    /* } still inside */\n"
        "    return LAST_TOKEN;\n"
        "  }\n"
    )
    assert "LAST_TOKEN" in _fnBody(js, "withComments")


# ---------------------------------------------------------------------------
# Anchoring -- a commented-out declaration is not a declaration.
# ---------------------------------------------------------------------------


def test_fnBody_ignoresACommentedOutDeclaration():
    """REGRESSION PIN, and it is a real one. The old copies did a bare
    `js.index("function " + name + "(")` over the whole file, so for `imuTick`
    they resolved to the `//     async function imuTick() {` at carousel.js:186
    -- 5536 lines before the real declaration. Two live assertions in
    test_carousel_imu_card were reading a COMMENT and passing."""
    js = (
        "  //     async function target() {\n"
        "  //       return DOC_TOKEN;\n"
        "  //     }\n"
        "  async function target() {\n"
        "    return REAL_TOKEN;\n"
        "  }\n"
    )
    body = _fnBody(js, "target")
    assert "REAL_TOKEN" in body
    assert "DOC_TOKEN" not in body, "the slice anchored on the commented-out copy"


def test_fnBody_findsAsyncDeclarations():
    """`tick` and `imuTick` are both `async function`; a slicer anchored on a
    bare `function` keyword at line start would miss them entirely."""
    js = _read(_CAROUSEL)
    for name in ("tick", "imuTick"):
        assert _fnBody(js, name).lstrip().startswith("async function ")


# ---------------------------------------------------------------------------
# Ambiguity -- resolved by nesting depth, and a true tie raises.
# ---------------------------------------------------------------------------


def test_fnBody_prefersTheLeastNestedOfSeveralDeclarations():
    """carousel.js declares `render` twice: the carousel's transform renderer at
    6 spaces and a settings-row closure at 12. A caller naming the bare
    identifier means the outer one, so resolution is by DEPTH -- not by which
    happens to appear first in the file."""
    js = (
        "      function render() {\n        return OUTER_TOKEN;\n      }\n"
        "            function render(value) {\n"
        "              return INNER_TOKEN;\n"
        "            }\n"
    )
    body = _fnBody(js, "render")
    assert "OUTER_TOKEN" in body
    assert "INNER_TOKEN" not in body


def test_fnBody_raisesWhenTwoDeclarationsShareTheShallowestDepth():
    """Two at the SAME depth is a genuine coin toss, and the honest instrument
    says so instead of picking one."""
    js = (
        "  function dupe() {\n    return 1;\n  }\n"
        "  function dupe() {\n    return 2;\n  }\n"
    )
    with pytest.raises(FunctionSliceError) as excinfo:
        _fnBody(js, "dupe")
    message = str(excinfo.value)
    assert "dupe" in message
    assert "2 times" in message, f"the error should report the count: {message}"


# ---------------------------------------------------------------------------
# The shipped file -- every declaration is bounded, not just the probed ones.
# ---------------------------------------------------------------------------


def test_fnBody_boundsEveryDeclarationInTheShippedCarousel():
    """Sweeps the whole file rather than the ~17 names the suites happen to
    probe today, so the NEXT name a wiring test reaches for is already covered.
    A span that swallows a sibling declaration at its own depth is the
    over-return failure this story removes."""
    js = _read(_CAROUSEL)
    declarations = list(
        re.finditer(r"^([ \t]*)(?:async[ \t]+)?function[ \t]+(\w+)[ \t]*\(", js, re.M)
    )
    assert len(declarations) > 200, "sanity: the sweep found almost nothing to check"

    swallowed = []
    for match in declarations:
        indent, name = match.group(1), match.group(2)
        try:
            body = _fnBody(js, name)
        except FunctionSliceError:
            continue  # ambiguous-by-depth is reported, not silently sliced
        sibling = re.compile(
            r"\n" + re.escape(indent) + r"(?:async[ \t]+)?function[ \t]+\w+[ \t]*\("
        )
        if sibling.search(body):
            swallowed.append(name)
    assert swallowed == [], f"span ran on past its own body for {swallowed}"
