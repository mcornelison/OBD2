################################################################################
# File Name: test_dashboard_overlay_hidden_guard.py
# Purpose/Description: US-495 (S2, F-111) guard tests for the `hidden` attribute
#   on the dashboard surface (src/pi/ui/dashboard/). Root cause (Atlas):
#   the five full-screen overlays declare `display: flex` through ID selectors,
#   and an AUTHOR declaration always outranks the user-agent `[hidden]{display:
#   none}` rule -- so the `hidden` property carousel.js sets was inert and every
#   overlay painted at once, stacked and unclickable. The JS was correct; the
#   CSS defeated it.
#
#   These tests do not grep for a magic string. They enumerate every element the
#   shipped markup ships `hidden`, resolve the winning `display` declaration
#   through a miniature cascade (importance -> specificity -> source order), and
#   assert the winner is `none`. Any overlay added later is covered the day it
#   is added, and the guard cannot be deleted without going red.
#
#   FIDELITY LIMIT (deliberate, US-499/S6 owns the rest): only compound simple
#   selectors are matched -- a rule with a combinator is skipped, as is any
#   pseudo-class this resolver cannot evaluate. A true CSS-cascade render is the
#   S6 backstop; this is the static contract S6 will exercise for real.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-29    | Ralph (Rex)  | Initial -- US-495 [hidden] guard cascade tests.
# ================================================================================
################################################################################

"""US-495 cascade tests proving the `hidden` attribute actually hides."""

import os
import re
from html.parser import HTMLParser

import pytest

_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard")
_CSS = os.path.join(_DIST, "dashboard.css")
_HTML = os.path.join(_DIST, "dashboard.html")

# The full-screen overlays from the Atlas root cause. Named explicitly (on top of
# the data-driven sweep) so deleting one from the markup fails LOUDLY rather than
# shrinking the sweep to nothing and passing.
_OVERLAY_IDS = ("dtc-takeover", "setup-menu", "confirm-modal", "dtc-detail", "clear-confirm")

# A combinator means the rule's subject is some descendant, not the element whose
# own compound we are resolving.
_COMBINATOR = re.compile(r"[\s>+~]")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _stripComments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _rules(css: str) -> list[tuple[str, str, int]]:
    """Every top-level style rule as (selector, declarations, sourceOrder).

    At-rules are skipped whole (balanced-brace scan). dashboard.css ships no
    `@media`/`@supports` today, so nothing that sets `display` hides in one --
    but skipping the block keeps a stray `@keyframes` step from being parsed as
    a style rule.
    """
    text = _stripComments(css)
    rules: list[tuple[str, str, int]] = []
    i = 0
    order = 0
    while True:
        brace = text.find("{", i)
        if brace == -1:
            return rules
        prelude = text[i:brace].strip()
        depth = 1
        j = brace + 1
        while j < len(text) and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        if not prelude.startswith("@"):
            for selector in prelude.split(","):
                rules.append((selector.strip(), text[brace + 1 : j - 1], order))
                order += 1
        i = j


def _declaration(decls: str, prop: str) -> tuple[str, bool] | None:
    """The last `prop` declaration in a block as (value, isImportant)."""
    found = None
    for match in re.finditer(rf"(?:^|;)\s*{re.escape(prop)}\s*:\s*([^;]+)", decls):
        raw = match.group(1).strip()
        important = "!important" in raw
        found = (raw.replace("!important", "").strip().lower(), important)
    return found


def _specificity(selector: str) -> tuple[int, int, int]:
    """(ids, classes+attrs+pseudo-classes, elements) for a compound selector."""
    ids = len(re.findall(r"#[\w-]+", selector))
    classes = len(re.findall(r"\.[\w-]+", selector))
    attrs = len(re.findall(r"\[[^\]]*\]", selector))
    pseudos = len(re.findall(r"(?<!:):[\w-]+", selector))
    elements = len(re.findall(r"(?:^|\))([a-zA-Z][\w-]*)", selector))
    return (ids, classes + attrs + pseudos, elements)


def _matches(selector: str, tag: str, attrs: dict[str, str | None]) -> bool:
    """True if this compound simple selector matches the element.

    Returns False (never raises) for anything this resolver cannot evaluate, so
    an unmatched exotic selector is simply not considered.
    """
    if not selector or _COMBINATOR.search(selector) or "*" in selector:
        return False
    if re.search(r"(?<!:):[\w-]+", selector):
        return False  # pseudo-class -- state we cannot resolve statically
    classes = (attrs.get("class") or "").split()
    for part in re.findall(r"\[[^\]]*\]|[#.]?[\w-]+", selector):
        if part.startswith("#"):
            if attrs.get("id") != part[1:]:
                return False
        elif part.startswith("."):
            if part[1:] not in classes:
                return False
        elif part.startswith("["):
            name = re.match(r"\[\s*([\w-]+)", part)
            if name is None or name.group(1) not in attrs:
                return False
        elif part.lower() != tag.lower():
            return False
    return True


def _winningDisplay(css: str, tag: str, attrs: dict[str, str | None]) -> tuple[str, str] | None:
    """Resolve the winning author `display` for one element: (value, selector).

    None means NO author rule declares `display`, which is the passing case --
    the UA sheet's `[hidden] { display: none }` then applies unopposed. Any
    author declaration outranks the UA sheet regardless of specificity, which is
    exactly how the bug happened.
    """
    best = None
    bestKey = None
    for selector, decls, order in _rules(css):
        if not _matches(selector, tag, attrs):
            continue
        found = _declaration(decls, "display")
        if found is None:
            continue
        value, important = found
        key = (1 if important else 0, _specificity(selector), order)
        if bestKey is None or key > bestKey:
            bestKey, best = key, (value, selector)
    return best


class _HiddenCollector(HTMLParser):
    """Every start tag in the shipped markup that carries the `hidden` attribute."""

    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrMap = dict(attrs)
        if "hidden" in attrMap:
            self.elements.append((tag, attrMap))


def _hiddenElements() -> list[tuple[str, dict[str, str | None]]]:
    parser = _HiddenCollector()
    parser.feed(_read(_HTML))
    return parser.elements


def _describe(tag: str, attrs: dict[str, str | None]) -> str:
    return f"<{tag} id={attrs.get('id')!r} class={attrs.get('class')!r}>"


# --- the guard ---------------------------------------------------------------


def test_everyHiddenElement_resolvesToDisplayNone():
    """
    Given: the shipped dashboard markup + stylesheet
    When: the cascade is resolved for every element that ships `hidden`
    Then: the winning `display` is `none` (or no author rule contests the UA one)

    This is the whole US-495 defect. Pre-fix, `#dtc-takeover` (and four more)
    win with `display: flex`, so the attribute carousel.js toggles is inert.
    """
    css = _read(_CSS)
    offenders = []
    for tag, attrs in _hiddenElements():
        winner = _winningDisplay(css, tag, attrs)
        if winner is not None and winner[0] != "none":
            offenders.append(f"{_describe(tag, attrs)} -> `{winner[1]} {{ display: {winner[0]} }}`")
    assert not offenders, (
        "these elements ship `hidden` but an author rule still gives them a box, "
        "so they paint anyway:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("overlayId", _OVERLAY_IDS)
def test_fullScreenOverlay_shipsHiddenAndResolvesToNone(overlayId):
    """
    Given: one of the five full-screen overlays from the Atlas root cause
    When: the markup + cascade are read
    Then: it ships `hidden`, and `hidden` resolves it to `display: none`

    The sweep above is data-driven, so it would quietly shrink to nothing if an
    overlay lost its attribute. This pins the five by name.
    """
    hidden = {attrs.get("id") for _, attrs in _hiddenElements()}
    assert overlayId in hidden, f"#{overlayId} must ship `hidden` so nothing paints at load"
    attrs: dict[str, str | None] = {"id": overlayId, "hidden": None}
    winner = _winningDisplay(_read(_CSS), "div", attrs)
    assert winner is None or winner[0] == "none", (
        f"#{overlayId}[hidden] resolves to `display: {winner[0]}` via `{winner[1]}` -- "
        "it will paint on top of the carousel"
    )


def test_hiddenOverlay_stillHasItsVisibleDisplayRule():
    """
    Given: the guard that hides the overlays
    Then: each overlay STILL declares its visible `display` when not hidden

    The cheap way to pass the test above is to delete `display: flex`. That
    would centre nothing and break every overlay's layout, so pin it.
    """
    css = _read(_CSS)
    for overlayId in _OVERLAY_IDS:
        winner = _winningDisplay(css, "div", {"id": overlayId})
        assert winner is not None, f"#{overlayId} lost its layout `display` declaration"
        assert winner[0].startswith("flex"), (
            f"#{overlayId} should still lay out as flex when visible, got `{winner[0]}`"
        )


def test_dtcRibbon_hiddenIsAlsoHonoured():
    """
    Given: the persistent DTC ribbon, which also ships `hidden` + `display: flex`
    Then: `hidden` resolves it to `display: none`

    Called out separately from the overlays because it is the one element that
    also runs an infinite `animation` -- an unhidden ribbon pulses a phantom
    alert band across every card at idle (F-6 no-phantom).
    """
    winner = _winningDisplay(_read(_CSS), "div", {"id": "dtc-ribbon", "hidden": None})
    assert winner is None or winner[0] == "none", (
        f"#dtc-ribbon[hidden] resolves to `display: {winner[0]}` via `{winner[1]}`"
    )
