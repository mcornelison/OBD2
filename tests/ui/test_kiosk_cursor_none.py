################################################################################
# File Name: test_kiosk_cursor_none.py
# Purpose/Description: US-652-b (F-139; CIO 2026-10-24 "hide the mouse", Iris
#   RULED the mechanism) -- the two kiosk stylesheets each carry exactly ONE
#   cursor rule, `html, html *{cursor:none !important}`, and no other cursor
#   value anywhere. Plain `html *` is specificity (0,0,1) and loses to every
#   class rule such as `.sys-tappable{cursor:pointer}`; the !important wins
#   over all of them. On a touch kiosk every other cursor declaration is dead
#   and only invites the pointer back, so none survives.
#   CSS covers Chromium's frames only; the frames labwc owns are US-652-e's
#   blank cursor theme, and the glass check is bigDoD 6.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-25    | Rex (US-652-b) | Initial -- the one-cursor-rule grep gate.
# ================================================================================
################################################################################

"""US-652-b: one `cursor:none !important` rule per kiosk sheet, nothing else."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SHEETS = (
    REPO_ROOT / "src" / "pi" / "ui" / "dashboard" / "dashboard.css",
    REPO_ROOT / "src" / "pi" / "ui" / "splash" / "styles.css",
)
THE_RULE = "html, html *{cursor:none !important}"

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _code(sheet: Path) -> str:
    """The sheet with its comments removed (a comment is not a declaration)."""
    return _COMMENT.sub("", sheet.read_text(encoding="utf-8"))


@pytest.mark.parametrize("sheet", SHEETS, ids=lambda p: p.name)
def test_sheet_hasExactlyOneCursorDeclaration_theImportantNoneRule(sheet):
    """
    Given: a kiosk stylesheet
    When:  every `cursor:` in it is counted (grep -c 'cursor:' semantics)
    Then:  there is exactly one, and it is the `html, html *` !important rule.
    """
    text = sheet.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if "cursor:" in ln]

    assert len(lines) == 1, lines
    assert lines[0].strip() == THE_RULE, lines


@pytest.mark.parametrize("sheet", SHEETS, ids=lambda p: p.name)
def test_sheet_declaresNoOtherCursorValue(sheet):
    """No `cursor` property with any value but `none !important`, comments aside."""
    values = re.findall(r"(?<![\w-])cursor\s*:\s*([^;}]*)", _code(sheet))

    assert values == ["none !important"], values


@pytest.mark.parametrize("sheet", SHEETS, ids=lambda p: p.name)
def test_theRuleSelectsTheRootAndEveryDescendant(sheet):
    """`html *` alone is (0,0,1) -- the !important is what beats a class rule,
    and `html` itself is listed so the root carries it too."""
    rules = re.findall(r"([^{}]+)\{([^{}]*cursor[^{}]*)\}", _code(sheet))

    assert len(rules) == 1, rules
    selectors = [s.strip() for s in rules[0][0].split(",")]
    assert selectors == ["html", "html *"], selectors
    assert rules[0][1].strip() == "cursor:none !important", rules
