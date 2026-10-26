################################################################################
# File Name: test_control_border_grammar.py
# Purpose/Description: US-758-a guard -- a coloured border is CONTROL grammar.
#   The CIO pressed the DTC detail's NEXT STEP box (GET DIAGNOSED) because it
#   wore a 1px amber border around bold amber text: the same grammar as the
#   green CLEAR button. So in dashboard.css a border naming --amber-warn,
#   --green-ok or --critical-red may appear ONLY on a real control or the STOP
#   alarm frame (Iris RULED 2026-10-26, pm/inbox/2026-10-26-from-iris-S116-
#   tidy-up-9-closures-confirmed-1-residue.md; allow-list measured at dev
#   a20af18e after US-758-a's deletions). Any other hit fails and names its
#   selector. The directive card's winning border is the neutral
#   .detail-card --text-tertiary, resolved through the render harness cascade.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-26    | Rex (US-758-a)| Initial -- control border grammar guard.
# ================================================================================
################################################################################

"""US-758-a: only controls and the STOP alarm carry a state-coloured border."""

import os
import re
from typing import Any

from tests.ui.render_harness import (
    Surface,
    declarationOf,
    matchesSelector,
    parseMarkup,
    specificity,
)

_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard")
_CSS = os.path.join(_DIST, "dashboard.css")
_HTML = os.path.join(_DIST, "dashboard.html")

# The state colours that read as "this is live / press me" when drawn as a border.
_STATE_TOKENS = ("--amber-warn", "--green-ok", "--critical-red")

# The ONLY places a state-coloured border is allowed: the STOP alarm frame (and
# its pulse) plus the four real controls.
_ALLOWED = frozenset(
    {
        '#dtc-takeover[data-severity="stop"]',
        "@keyframes stop-alarm-pulse",
        '.set-btn[aria-pressed="true"]',
        ".confirm-box",
        "#confirm-ok",
        "#dtc-clear-btn",
    }
)

# `border`, `border-color` and the per-side / per-side-colour longhands: a
# coloured top edge is the same grammar as a coloured box.
_BORDER_DECL = re.compile(r"(?:^|[;{])\s*(border(?:-[a-z]+)*)\s*:\s*([^;}]+)")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _blocks(css: str) -> list[tuple[str, str]]:
    """(prelude, body) for every top-level block, comments stripped, @media
    descended into. An @keyframes block is kept whole under its own prelude
    (render_harness.parseCss drops every @-rule but @media, which would hide
    the alarm pulse from this guard)."""
    text = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    out: list[tuple[str, str]] = []
    i = 0
    while True:
        brace = text.find("{", i)
        if brace == -1:
            return out
        prelude = text[i:brace].strip()
        depth, j = 1, brace + 1
        while j < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            j += 1
        body = text[brace + 1 : j - 1]
        if prelude.startswith("@media"):
            out.extend(_blocks(body))
        else:
            out.append((re.sub(r"\s+", " ", prelude), body))
        i = j


def stateBorderSelectors(css: str) -> set[str]:
    """Every selector (or @keyframes prelude) whose block draws a border in a
    state colour."""
    hits: set[str] = set()
    for prelude, body in _blocks(css):
        coloured = any(
            token in value
            for _, value in _BORDER_DECL.findall(body)
            for token in _STATE_TOKENS
        )
        if not coloured:
            continue
        if prelude.startswith("@"):
            hits.add(prelude)
        else:
            hits.update(s.strip() for s in prelude.split(","))
    return hits


def test_stateColouredBorders_appearOnlyOnControlsAndTheStopAlarm():
    hits = stateBorderSelectors(_read(_CSS))
    stray = sorted(hits - _ALLOWED)
    assert not stray, f"state-coloured border on a non-control: {stray}"


def test_theAllowList_isExactlyTheSixControlAndAlarmSelectors():
    """Every allowed selector still draws its border: an allow-list entry that
    no longer matches anything would let a future hit hide behind it."""
    assert stateBorderSelectors(_read(_CSS)) == _ALLOWED


def test_theGuard_flagsTheRetiredDirectiveBorder():
    """Negative: the rule US-758-a deletes is exactly what the guard catches,
    so a re-introduction fails by name."""
    css = '.detail-fix[data-mode="directive"] { border-color: var(--amber-warn); }'
    assert stateBorderSelectors(css) == {'.detail-fix[data-mode="directive"]'}


def test_theGuard_seesBordersInsideMediaAndKeyframes_andIgnoresComments():
    css = (
        "/* .x { border: 1px solid var(--green-ok); } */\n"
        "@media (min-width: 10px) { .a, .b { border-top: 2px solid var(--critical-red); } }\n"
        "@keyframes k { 0% { border-color: var(--amber-warn); } }\n"
        ".c { color: var(--amber-warn); outline: 1px solid var(--green-ok); }\n"
    )
    assert stateBorderSelectors(css) == {".a", ".b", "@keyframes k"}


def _directiveCardPath() -> list[dict[str, Any]]:
    """The real page tree with the fix card carousel.js builds for a 🔴/🟡 code
    (`detail-card detail-fix`, data-mode="directive") placed in #detail-body."""
    tree = parseMarkup(_HTML)
    card = {
        "tag": "div",
        "attrs": {"class": "detail-card detail-fix", "data-mode": "directive"},
        "children": [],
    }
    surface = Surface(tree, "")
    body = surface.pathById("detail-body")
    assert body is not None, "#detail-body is not in dashboard.html"
    body[-1]["children"].append(card)
    return body + [card]


def _winningBorderColour(css: str, path: list[dict[str, Any]]) -> str:
    """The border colour that wins the cascade, with the `border` shorthand and
    the `border-color` longhand competing in ONE cascade (Surface resolves one
    property name at a time, and the shorthand sets the colour too)."""
    best: tuple[Any, ...] | None = None
    colour = ""
    for rule in Surface({"tag": "body", "attrs": {}, "children": []}, css).rules:
        if not matchesSelector(rule.selector, path):
            continue
        for prop in ("border", "border-color"):
            found = declarationOf(rule.declarations, prop)
            if found is None:
                continue
            value, important = found
            key = (important, specificity(rule.selector), rule.order)
            if best is None or key >= best:
                best = key
                colour = value.split()[-1] if prop == "border" else value
    return colour


def test_theDirectiveCard_wearsTheNeutralDetailCardBorder():
    colour = _winningBorderColour(_read(_CSS), _directiveCardPath())
    assert colour == "var(--text-tertiary)"


def test_theDirectiveText_staysBoldAmber():
    """Severity, not a control: the words keep amber + 700 (Iris RULED)."""
    css = _read(_CSS)
    match = re.search(r"^\.dtc-fix-directive\s*\{([^}]*)\}", css, re.MULTILINE)
    assert match is not None, "no .dtc-fix-directive rule"
    assert declarationOf(match.group(1), "color") == ("var(--amber-warn)", False)
    assert declarationOf(match.group(1), "font-weight") == ("700", False)


def test_theDeadHeroRules_areRetired():
    """No emitter builds the DTC hero block (US-757 retired it); its rules go
    too. The class name is split so the story's own `git grep` for it over
    src/ and tests/ stays empty."""
    assert "dtc-" + "hero" not in _read(_CSS)
