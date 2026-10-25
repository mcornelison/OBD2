################################################################################
# File Name: test_shutdown_splash_render.py
# Purpose/Description: US-498 (S5, F-103) render tests for the closeout
#   (shutdown) splash: what the operator SEES on the logo, resolved from the
#   shipped CSS rather than grepped for a magic string.
#
#   US-498 measured the old trap: splash-shutdown.svg was splash.svg plus one
#   `animation-direction: reverse` override, and the reversed 6s-delayed fadeout
#   held opacity 0 for most of the grace window -- a black screen for the whole
#   shutdown. US-870-c retired both SVG timelines: the logo is inline and
#   styles.css drives it on body classes the poller sets on the animation's own
#   events (reverse spin -> dim spin -> dim-down -> the stage fade). The same
#   operator-facing promises are measured here against the PAGE CSS:
#     - the mark is fully visible the instant the stage paints, and nothing the
#       logo runs animates its opacity (no blank frame while the bar fills);
#     - every shutdown spin runs in reverse;
#     - the close-out only ever dims: hi -> low -> black, never back up.
#   The event chain itself (iteration -> dim spin -> animationend -> dim-down ->
#   animationend -> fade -> black) is driven in tests/ui/test_shutdown_spins.py.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-29    | Ralph (Rex)  | Initial -- US-498 closeout splash render.
# 2026-10-25    | Rex (US-870-c)| MOVED PIN (US-870-c): splash.svg and
#               |              | splash-shutdown.svg are retired; the SVG-timeline
#               |              | resolver (delays, grace window, the reversed
#               |              | light ramp) is rewritten against styles.css.
# ================================================================================
################################################################################

"""US-498 render tests for the F-103 closeout (shutdown) splash, on the page CSS."""

from __future__ import annotations

import copy
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

KIT_DIR = Path(rh.SPLASH_DIR)
STYLES_CSS = KIT_DIR / "styles.css"
SHUTDOWN_HTML = KIT_DIR / "shutdown.html"
INDEX_HTML = KIT_DIR / "index.html"

# The shutdown logo's parts, in the order the poller sets them.
SHUTDOWN_PARTS = ("spin-rev", "spin-dim", "dim-down")


# ---------------------------------------------------------------------------
# A miniature keyframe reader -- enough for styles.css.
# ---------------------------------------------------------------------------


def _css() -> str:
    return re.sub(r"/\*.*?\*/", "", STYLES_CSS.read_text(encoding="utf-8"), flags=re.DOTALL)


def _topLevelBlocks(css: str) -> list[tuple[str, str]]:
    """Split CSS into ``(prelude, body)`` pairs, brace-depth aware (@keyframes)."""
    blocks: list[tuple[str, str]] = []
    i, n = 0, len(css)
    while i < n:
        open_ = css.find("{", i)
        if open_ == -1:
            break
        prelude = css[i:open_].strip()
        depth, k = 1, open_ + 1
        while k < n and depth:
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
            k += 1
        blocks.append((prelude, css[open_ + 1 : k - 1]))
        i = k
    return blocks


def _decls(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for chunk in body.split(";"):
        if ":" not in chunk:
            continue
        prop, _, value = chunk.partition(":")
        out[prop.strip()] = value.strip()
    return out


def _rootProps(css: str) -> dict[str, str]:
    for prelude, body in _topLevelBlocks(css):
        if prelude == ":root":
            return {p: v for p, v in _decls(body).items() if p.startswith("--")}
    raise AssertionError("styles.css has no :root block")


def _keyframes(css: str, name: str) -> list[tuple[float, dict[str, str]]]:
    """``(progress, declarations)`` stops for ``@keyframes <name>``."""
    for prelude, body in _topLevelBlocks(css):
        if prelude.startswith("@keyframes") and prelude.split()[-1] == name:
            stops = []
            for marker, stopBody in _topLevelBlocks(body):
                progress = {"from": 0.0, "to": 1.0}.get(marker)
                if progress is None:
                    progress = float(marker.rstrip("%")) / 100.0
                stops.append((progress, _decls(stopBody)))
            return sorted(stops, key=lambda s: s[0])
    raise AssertionError(f"no @keyframes {name} in styles.css")


def _brightness(value: str, props: dict[str, str]) -> float:
    """``brightness(var(--x))`` / ``brightness(0.25)`` -> the number."""
    resolved = re.sub(r"var\((--[\w-]+)\)", lambda m: props[m.group(1)], value)
    match = re.fullmatch(r"brightness\(\s*(-?\d+(?:\.\d+)?)\s*\)", resolved.strip())
    assert match is not None, f"not a brightness(): {value}"
    return float(match.group(1))


def _decl(html: Path, classes: str, elementId: str, prop: str) -> str | None:
    """The winning declaration of ``prop`` on ``#elementId`` with body.<classes>."""
    body: dict[str, Any] = copy.deepcopy(rh.parseMarkup(str(html)))
    body.setdefault("attrs", {})["class"] = classes
    surface = rh.splashSurface(body, reducedMotion=False)
    path = surface.pathById(elementId)
    assert path is not None, f"no #{elementId} in {html.name}"
    winner = surface.winningDeclaration(path, prop)
    return None if winner is None else winner[0]


def _animationName(classes: str) -> str:
    animation = _decl(SHUTDOWN_HTML, classes, "logo", "animation")
    assert animation is not None, f"no animation on #logo with body.{classes}"
    return animation.split()[0]


# ---------------------------------------------------------------------------
# The blank-screen trap (US-498's headline defect), on the page
# ---------------------------------------------------------------------------


def test_shutdownSplash_markIsVisibleTheInstantTheStageIsRevealed():
    """
    Given: shutdown-state-poll.js paints the stage (body.animating, spin-rev)
    When: the operator first sees the surface
    Then: the mark is at FULL opacity with no fade-in -- not the boot page's
          cross-fade start (opacity 0), not mid-transition
    """
    assert _decl(SHUTDOWN_HTML, "animating spin-rev", "mark", "opacity") == "1"
    assert _decl(SHUTDOWN_HTML, "animating spin-rev", "mark", "transition") == "none"


def test_shutdownSplash_nothingTheLogoRunsAnimatesOpacity():
    """
    Given: every animation the shutdown logo runs
    Then: none of its keyframes touches opacity

    The old trap was an opacity keyframe held by `fill-mode: both` on a delay.
    With no opacity keyframe on the logo there is nothing to hold at 0: the only
    thing that takes the screen to black is the stage fade, after the dim-down.
    """
    css = _css()
    for part in SHUTDOWN_PARTS:
        name = _animationName(f"animating {part}")
        for _, decls in _keyframes(css, name):
            assert "opacity" not in decls, f"@keyframes {name} animates opacity ({part})"


# ---------------------------------------------------------------------------
# The reversal contract -- the shutdown spins the other way
# ---------------------------------------------------------------------------


def test_shutdownSplash_everySpinRunsInReverse():
    """Both shutdown spins carry `reverse`; the boot spins never do (control)."""
    for part in ("spin-rev", "spin-dim"):
        animation = _decl(SHUTDOWN_HTML, f"animating {part}", "logo", "animation")
        assert animation is not None and "reverse" in animation.split(), part

    for spin in (1, 2, 3):
        animation = _decl(INDEX_HTML, f"logo-up phase-1 spin-{spin}", "logo", "animation")
        assert animation is not None and "reverse" not in animation.split(), spin


def test_shutdownSplash_dimsDownRatherThanUp():
    """
    Given: the close-out's three logo parts, in order
    Then: the brightness only falls -- --bright-hi, --bright-low, then the
          dim-down from --bright-low to 0 -- and ends black

    The old reversed SVG light ramp opened at --bright-max: a flash UP after the
    last dim spin. Each part's level is resolved from the shipped :root.
    """
    css = _css()
    props = _rootProps(css)
    levels: list[float] = []
    for part in ("spin-rev", "spin-dim"):
        level = _decl(SHUTDOWN_HTML, f"animating {part}", "logo", "filter")
        assert level is not None, part
        levels.append(_brightness(level, props))
    for _, decls in _keyframes(css, _animationName("animating dim-down")):
        levels.append(_brightness(decls["filter"], props))

    assert levels == sorted(levels, reverse=True), f"the close-out brightens: {levels}"
    assert levels[0] == pytest.approx(float(props["--bright-hi"]))
    assert levels[1] == pytest.approx(float(props["--bright-low"]))
    assert levels[2] == pytest.approx(float(props["--bright-low"]))
    assert levels[-1] == pytest.approx(0.0)
