################################################################################
# File Name: test_shutdown_spins.py
# Purpose/Description: US-870-c -- the shutdown logo is inline and page-driven:
#   a reverse spin at --bright-hi loops while the bar is under 100 %; the 100 %
#   read waits for its next animationiteration, then one dim spin at
#   --bright-low, whose animationend starts the dim-down, whose animationend
#   starts the stage fade, and the stage stays black. Drives the SHIPPED
#   shutdown-state-poll.js + motion-gate.js through tests/ui/shutdown_probe.js
#   (the probe is the browser's half: it dispatches #logo's events one run
#   apart on virtual time), and resolves the SHIPPED styles.css.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-25    | Ralph (Rex)  | Initial -- US-870-c shutdown spins + close-out.
# 2026-10-27    | Ralph (Rex)  | US-870-e: >= 2 reverse turns + the bar seen
#               |              | full before the dim spin; the done POST once
#               |              | on black; the bar's width transition. MOVED
#               |              | PINS: test_awayFastPath_... and
#               |              | test_fullMidRotation_... (dim after 2 turns);
#               |              | test_cancelledDuringTheDimSpin_... re-timed
#               |              | so it still cancels DURING the dim spin.
# ================================================================================
################################################################################

"""US-870-c: reverse spin under 100 %, then the dim spin, the dim-down, black."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

_NODE_ONLY = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to run the shipped JS"
)

SPLASH_DIR = Path(rh.SPLASH_DIR)
POLL_JS = SPLASH_DIR / "shutdown-state-poll.js"
STYLES_CSS = SPLASH_DIR / "styles.css"
INDEX_HTML = SPLASH_DIR / "index.html"
SHUTDOWN_HTML = SPLASH_DIR / "shutdown.html"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "states" / "shutdown"

_POLL_MS = 250
_ROTATION_MS = 3_000  # what the probe computes from the 3s animationDuration
_DIM_DOWN_MS = 500  # ... and from the dim-down's 0.5s
_MIN_REVERSE_TURNS = 2  # spec §2.1: >= 2 completed reverse turns before the dim spin
_SPLASH_DONE_ROUTE = "/shutdown-splash-done"

# What the browser computes with styles.css present: the stage fade, the bar's
# width transition (--t-bar) and, while a logo class is on, #logo's animation.
_LIVE: dict[str, Any] = {
    "splash-stage": {"transitionDuration": "0.5s"},
    "bar-fill": {"transitionDuration": "0.6s"},
    "bar-kept": {"transitionDuration": "0.6s"},
    "logo": {
        "spin-rev": {"animationName": "spin", "animationDuration": "3s"},
        "spin-dim": {"animationName": "spin", "animationDuration": "3s"},
        "dim-down": {"animationName": "dim-down", "animationDuration": "0.5s"},
    },
}


def _sequence(name: str) -> list[dict[str, Any]]:
    with open(FIXTURES / f"{name}.json", encoding="utf-8") as fh:
        return json.load(fh)["sequence"]


def _flushing(index: int, of: int, name: str) -> dict[str, Any]:
    return {
        "phase": "flushing",
        "reason": "ignition_off",
        "step": {"index": index, "of": of, "name": name},
        "sync": {"state": "away", "outcome": None, "waitingAtKeyOff": None, "confirmed": None},
    }


def _parts(result: dict[str, Any]) -> list[tuple[str, int]]:
    return [(entry["part"], entry["atMs"]) for entry in result["logoLog"]]


def _events(result: dict[str, Any]) -> list[tuple[str, str, int]]:
    return [(e["type"], e["part"], e["atMs"]) for e in result["animationEvents"]]


def _fullAtMs(result: dict[str, Any]) -> int:
    return next(e["atMs"] for e in result["progressLog"] if e["fill"] == "100%")


def _stripJsComments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def _stripCssComments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def _inlineLogo(html: str) -> str:
    """The inline <svg id="mark"> body: everything between its open and close tags."""
    match = re.search(r'<svg id="mark"[^>]*>(.*?)</svg>', html, flags=re.DOTALL)
    assert match is not None, "no inline <svg id=mark>"
    return match.group(1)


# --- the markup ----------------------------------------------------------------


class TestInlineLogo:
    """shutdown.html carries index.html's logo, inline, with no <style>."""

    def test_theShutdownLogoIsIndexHtmlsLogo_byteForByte(self):
        boot = _inlineLogo(INDEX_HTML.read_text(encoding="utf-8"))
        shutdown = _inlineLogo(SHUTDOWN_HTML.read_text(encoding="utf-8"))

        assert shutdown == boot

    def test_noObjectAndNoStyleInsideTheLogo(self):
        html = SHUTDOWN_HTML.read_text(encoding="utf-8")
        markup = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

        assert "<object" not in markup
        assert "splash-shutdown.svg" not in markup and "splash.svg" not in markup
        assert "<style" not in _inlineLogo(html)

    def test_motionGateLoadsBeforeThePoller(self):
        html = SHUTDOWN_HTML.read_text(encoding="utf-8")
        gate = html.find('<script src="motion-gate.js">')
        poller = html.find('<script src="shutdown-state-poll.js">')

        assert gate != -1 and poller != -1
        assert gate < poller


# --- the shipped page, driven ------------------------------------------------


@_NODE_ONLY
class TestCloseOut:
    """Validation: each close-out part starts on the previous part's own event."""

    def test_awayFastPath_loopIterationDimSpinDimDownFadeBlack(self):
        """
        Given: the VCELL fast path (shed, custody, poweroff 3/3), every part live
        When: the probe dispatches each run's event
        Then: the reverse spin loops; the 100 % read lands in turn 1, so the
              dim spin waits for turn 2's iteration (US-870-e, MOVED PIN: it
              was turn 1's); its animationend the dim-down; that animationend
              the fade; the stage's transitionend leaves it black
        """
        result = rh.runShutdownSplash(_sequence("fast-path"), computedStyles=_LIVE, rounds=60)

        paintAt = _parts(result)[0][1]
        fullAt = _fullAtMs(result)
        dimAt = paintAt + _MIN_REVERSE_TURNS * _ROTATION_MS
        assert paintAt < fullAt < paintAt + _ROTATION_MS  # 100 % lands in turn 1
        assert _parts(result) == [
            ("spin-rev", paintAt),
            ("spin-dim", dimAt),
            ("dim-down", dimAt + _ROTATION_MS),
        ]
        assert _events(result) == [
            ("animationiteration", "spin-rev", paintAt + _ROTATION_MS),
            ("animationiteration", "spin-rev", dimAt),
            ("animationend", "spin-dim", dimAt + _ROTATION_MS),
            ("animationend", "dim-down", dimAt + _ROTATION_MS + _DIM_DOWN_MS),
        ]
        fadeAt = dimAt + _ROTATION_MS + _DIM_DOWN_MS
        assert result["fadeStartedAtMs"] == fadeAt
        assert result["transitionEndDispatched"]
        assert result["blackAtMs"] == fadeAt
        assert result["stageOpacity"] == "0"
        # Black is not an exit: the page dies with the power.
        assert not result["closed"]

    def test_awayPathOfFive_sameCloseOutAfter100(self):
        result = rh.runShutdownSplash(_sequence("away"), computedStyles=_LIVE, rounds=80)

        assert [part for part, _ in _parts(result)] == ["spin-rev", "spin-dim", "dim-down"]
        # The 100 % read can land on an iteration boundary: never BEFORE it.
        assert _parts(result)[1][1] >= _fullAtMs(result)
        assert result["blackAtMs"] is not None
        assert not result["closed"]

    def test_barStandingStill_monthlyHold_spinLoopsWithNoCloseOut(self):
        """Negative: the bar held under 100 % -> iterations only, nothing dims."""
        held = [_flushing(3, 6, "monthly_test_hold")]
        result = rh.runShutdownSplash(held, computedStyles=_LIVE, rounds=80)

        assert [part for part, _ in _parts(result)] == ["spin-rev"]
        iterations = [at for kind, _, at in _events(result) if kind == "animationiteration"]
        assert len(iterations) >= 5
        assert all(b - a == _ROTATION_MS for a, b in zip(iterations, iterations[1:]))
        assert result["fadeStartedAtMs"] is None
        assert result["blackAtMs"] is None

    def test_fullMidRotation_dimSpinWaitsForTheNextIteration(self):
        """Negative: 100 % read 1 s into turn 1 -> the dim spin starts on a boundary,
        and (US-870-e, MOVED PIN) not before turn 2's: turn 1's is too few turns."""
        states = [_flushing(1, 2, "shed")] * 4 + [_flushing(2, 2, "poweroff")]
        result = rh.runShutdownSplash(states, computedStyles=_LIVE, rounds=60)

        paintAt = _parts(result)[0][1]
        fullAt = _fullAtMs(result)
        assert fullAt - paintAt < _ROTATION_MS
        assert _parts(result)[1] == ("spin-dim", paintAt + _MIN_REVERSE_TURNS * _ROTATION_MS)

    def test_cancelledMidSpin_exitsAtOnce_noCloseOut(self):
        """Negative: key back on mid-spin -> exit on that read, nothing dims."""
        states = [_flushing(1, 5, "shed")] * 3 + [
            {"phase": "cancelled", "reason": "power_restored"}
        ]
        result = rh.runShutdownSplash(states, computedStyles=_LIVE, rounds=40)

        assert result["closed"]
        assert result["terminalCause"] == "cancelled"
        assert [part for part, _ in _parts(result)] == ["spin-rev"]
        assert result["fadeStartedAtMs"] is None
        assert result["blackAtMs"] is None

    def test_cancelledDuringTheDimSpin_exitsWithNoFurtherPart(self):
        # US-870-e: the dim spin now starts after 2 reverse turns (~6.25 s), so
        # the cancel is read at 7.5 s -- inside it -- as this test intends.
        states = [_flushing(5, 5, "poweroff")] * 15 + [
            {"phase": "cancelled", "reason": "power_restored"}
        ]
        result = rh.runShutdownSplash(states, computedStyles=_LIVE, rounds=60)

        assert result["closed"] and result["terminalCause"] == "cancelled"
        assert [part for part, _ in _parts(result)] == ["spin-rev", "spin-dim"]
        assert result["blackAtMs"] is None
        assert result["posts"] == []

    def test_liveWithNoEventDispatched_waitsForItsOwnEvent(self):
        """The control: parts live but the browser fires nothing -> no step advances."""
        result = rh.runShutdownSplash(
            _sequence("fast-path"), computedStyles=_LIVE, dispatchLogoEvents=False, rounds=60
        )

        assert [part for part, _ in _parts(result)] == ["spin-rev"]
        assert result["blackAtMs"] is None


def _iterations(result: dict[str, Any]) -> list[int]:
    return [at for kind, part, at in _events(result) if kind == "animationiteration"]


def _donePosts(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in result["posts"] if p["route"] == _SPLASH_DONE_ROUTE]


@_NODE_ONLY
class TestThreeTurnsSeenFullDoneOnce:
    """US-870-e (spec §2.1, §5a): two reverse turns and the bar seen full before
    the dim spin; the done POST exactly once, on black, never on cancelled."""

    def test_nothing_to_sync_runs_two_reverse_turns_before_dim(self):
        """
        Given: at home with nothing to sync, every part live
        When: the probe dispatches the logo's, the bar's and the stage's events
        Then: 2 reverse iterations, the dim spin, the dim-down, the fade, black,
              then ONE POST /shutdown-splash-done with the token and an empty body
        """
        result = rh.runShutdownSplash(
            _sequence("nothing-to-sync"), computedStyles=_LIVE, rounds=80
        )

        paintAt = _parts(result)[0][1]
        dimAt = paintAt + _MIN_REVERSE_TURNS * _ROTATION_MS
        assert _events(result) == [
            ("animationiteration", "spin-rev", paintAt + _ROTATION_MS),
            ("animationiteration", "spin-rev", dimAt),
            ("animationend", "spin-dim", dimAt + _ROTATION_MS),
            ("animationend", "dim-down", dimAt + _ROTATION_MS + _DIM_DOWN_MS),
        ]
        assert [part for part, _ in _parts(result)] == ["spin-rev", "spin-dim", "dim-down"]
        fadeAt = dimAt + _ROTATION_MS + _DIM_DOWN_MS
        assert result["fadeStartedAtMs"] == fadeAt
        assert result["blackAtMs"] == fadeAt
        # The bar was seen full -- its 100 % transitionend -- before the dim spin.
        fullSeen = [e["atMs"] for e in result["barEvents"] if e["width"] == "100%"]
        assert fullSeen and fullSeen[0] <= dimAt
        assert result["posts"] == [
            {
                "route": _SPLASH_DONE_ROUTE,
                "method": "POST",
                "token": "test-token",
                "body": "",
                "atMs": fadeAt,
            }
        ]
        assert not result["closed"]

    def test_reducedMotion_onePost(self):
        result = rh.runShutdownSplash(
            _sequence("nothing-to-sync"),
            computedStyles=_LIVE,
            reducedMotion=True,
            dispatchTransitionEnd=False,
            rounds=60,
        )

        assert result["animationEvents"] == []
        assert result["blackAtMs"] == _fullAtMs(result)
        assert len(_donePosts(result)) == 1
        assert result["posts"][0]["atMs"] == result["blackAtMs"]

    def test_stylesMissing_onePost(self):
        result = rh.runShutdownSplash(
            _sequence("nothing-to-sync"),
            computedStyles={},
            dispatchLogoEvents=False,
            dispatchTransitionEnd=False,
            rounds=60,
        )

        assert result["blackAtMs"] == _fullAtMs(result)
        assert len(_donePosts(result)) == 1

    def test_cancelledMidSpin_zeroPosts(self):
        states = _sequence("nothing-to-sync")[:5] + [
            {"phase": "cancelled", "reason": "power_restored"}
        ]
        result = rh.runShutdownSplash(states, computedStyles=_LIVE, rounds=60)

        assert result["closed"] and result["terminalCause"] == "cancelled"
        assert result["posts"] == []

    def test_barTransitionEndWithheld_spinKeepsLooping_noDim_noPost(self):
        """Negative: the bar is drawn 100 % but its transitionend never comes:
        the bar was not SEEN full, so the reverse spin keeps looping."""
        result = rh.runShutdownSplash(
            _sequence("nothing-to-sync"),
            computedStyles=_LIVE,
            dispatchBarTransitionEnd=False,
            rounds=80,
        )

        assert result["progress"]["fill"] == "100%"
        assert len(_iterations(result)) >= 4
        assert [part for part, _ in _parts(result)] == ["spin-rev"]
        assert result["fadeStartedAtMs"] is None and result["blackAtMs"] is None
        assert result["posts"] == []

    def test_fullAfterManyTurns_dimOnTheFirstBoundaryAfterTheBarIsSeenFull(self):
        """Home drain finishing mid-turn 4: the bar glides to 100 %, its
        transitionend fires, and the dim spin starts at the next boundary."""
        states = [_flushing(1, 2, "drain")] * 20 + [_flushing(2, 2, "poweroff")]
        result = rh.runShutdownSplash(states, computedStyles=_LIVE, rounds=100)

        seenFullAt = next(e["atMs"] for e in result["barEvents"] if e["width"] == "100%")
        dimAt = _parts(result)[1][1]
        assert _parts(result)[1][0] == "spin-dim"
        assert _iterations(result)[-1] == dimAt
        assert seenFullAt <= dimAt < seenFullAt + _ROTATION_MS
        assert len([at for at in _iterations(result) if at < dimAt]) >= _MIN_REVERSE_TURNS
        assert len(_donePosts(result)) == 1


@_NODE_ONLY
class TestNoEventWillFire:
    """Atlas G2 / C-Atlas-6: a wait that cannot end is never entered."""

    def test_durationsZero_full_noEvent_advancesToBlack(self):
        """styles.css missing: every duration computes 0 -> black on the 100 % read."""
        result = rh.runShutdownSplash(
            _sequence("fast-path"),
            computedStyles={},
            dispatchLogoEvents=False,
            dispatchTransitionEnd=False,
            rounds=40,
        )

        fullAt = _fullAtMs(result)
        assert [part for part, _ in _parts(result)] == ["spin-rev", "spin-dim", "dim-down"]
        assert all(not entry["live"] for entry in result["logoLog"])
        assert result["animationEvents"] == []
        assert result["blackAtMs"] == fullAt
        assert result["stageOpacity"] == "0"

    def test_reducedMotion_blackAtOnceOn100_noAnimationRuns(self):
        result = rh.runShutdownSplash(
            _sequence("fast-path"),
            computedStyles=_LIVE,
            reducedMotion=True,
            dispatchTransitionEnd=False,
            rounds=40,
        )

        assert result["animationEvents"] == []
        assert result["blackAtMs"] == _fullAtMs(result)
        assert not result["closed"]

    def test_reducedMotion_under100_staysPainted(self):
        result = rh.runShutdownSplash(
            [_flushing(1, 5, "shed")], computedStyles=_LIVE, reducedMotion=True, rounds=20
        )

        assert result["painted"]
        assert result["blackAtMs"] is None
        assert result["stageOpacity"] is None


# --- the stylesheet ------------------------------------------------------------


def _bodyWith(classes: str) -> dict[str, Any]:
    body = copy.deepcopy(rh.parseMarkup(str(SHUTDOWN_HTML)))
    body.setdefault("attrs", {})["class"] = classes
    return body


def _decl(classes: str, elementId: str, prop: str, reducedMotion: bool = False) -> str | None:
    surface = rh.splashSurface(_bodyWith(classes), reducedMotion=reducedMotion)
    path = surface.pathById(elementId)
    assert path is not None, f"no #{elementId} in shutdown.html"
    winner = surface.winningDeclaration(path, prop)
    return None if winner is None else winner[0]


class TestShutdownLogoStyles:
    """styles.css owns the motion; the poller holds no length of its own."""

    def test_reverseSpin_loopsAtBrightHi_oneRotationIsTheToken(self):
        animation = _decl("animating spin-rev", "logo", "animation")
        assert animation is not None
        parts = animation.split()
        assert parts[:2] == ["spin", "var(--t-spin)"]
        assert "infinite" in parts and "reverse" in parts
        assert _decl("animating spin-rev", "logo", "filter") == "brightness(var(--bright-hi))"

    def test_dimSpin_onceAtBrightLow(self):
        animation = _decl("animating spin-dim", "logo", "animation")
        assert animation is not None
        parts = animation.split()
        assert parts[:2] == ["spin", "var(--t-spin)"]
        assert "1" in parts and "reverse" in parts and "infinite" not in parts
        assert _decl("animating spin-dim", "logo", "filter") == "brightness(var(--bright-low))"

    def test_dimDown_oneLinearRunOfTheFadeToken_heldBothEnds(self):
        """Iris 2026-10-25: ONE run, var(--t-fade), linear, fill-mode both."""
        animation = _decl("animating dim-down", "logo", "animation")
        assert animation is not None
        assert animation.split() == ["dim-down", "var(--t-fade)", "linear", "1", "both"]
        assert _decl("animating dim-down", "logo", "filter") == "brightness(var(--bright-low))"

    def test_dimDownKeyframes_brightLowToBlack_noRotation(self):
        """--bright-low -> 0, and no transform: the logo holds the dim spin's end pose."""
        css = _stripCssComments(STYLES_CSS.read_text(encoding="utf-8"))
        blocks = re.findall(r"@keyframes\s+dim-down\s*\{(.*?)\n\}", css, re.S)

        assert len(blocks) == 1, "@keyframes dim-down must be declared exactly once"
        stops = re.findall(r"(from|to)\s*\{\s*filter:\s*([^;]+);\s*\}", blocks[0])
        assert stops == [("from", "brightness(var(--bright-low))"), ("to", "brightness(0)")]
        assert "transform" not in blocks[0] and "rotate" not in blocks[0]

    def test_bothShutdownSpinsRunTheBootSpinKeyframes(self):
        """The spins reuse the ONE @keyframes spin (thirds, ease-in-out; pinned in
        test_boot_spins.py): no shutdown twin a re-time could miss."""
        css = _stripCssComments(STYLES_CSS.read_text(encoding="utf-8"))

        assert len(re.findall(r"@keyframes\s+spin\b", css)) == 1
        for part in ("spin-rev", "spin-dim"):
            animation = _decl(f"animating {part}", "logo", "animation")
            assert animation is not None and animation.split()[0] == "spin", part

    def test_theShutdownLogoIsVisibleTheMomentTheStagePaints(self):
        """The boot cross-fade's opacity 0 must not hide the shutdown logo."""
        assert _decl("animating spin-rev", "mark", "opacity") == "1"
        assert _decl("animating spin-rev", "mark", "transition") == "none"

    def test_noAnimationDelayAnywhere(self):
        css = _stripCssComments(STYLES_CSS.read_text(encoding="utf-8"))

        assert "animation-delay" not in css
        for rule in re.findall(r"animation\s*:\s*([^;]*);", css):
            times = re.findall(r"\b\d+(?:\.\d+)?m?s\b|var\(--t-[\w-]+\)", rule)
            assert len(times) <= 1, f"a delay in `animation: {rule}`"

    def test_reducedMotion_noAnimationOnAnyShutdownPart(self):
        for part in ("spin-rev", "spin-dim", "dim-down"):
            assert _decl(f"animating {part}", "logo", "animation", reducedMotion=True) == "none"
        # US-870-e: the bar's glide is motion too.
        for elementId in ("bar-fill", "bar-kept"):
            assert _decl("animating", elementId, "transition", reducedMotion=True) == "none"

    def test_barFillAndKept_glideOnWidth_byTheBarToken(self):
        """US-870-e (spec §2.1 / §5a Smooth): one width transition, var(--t-bar), ease-out."""
        for elementId in ("bar-fill", "bar-kept"):
            assert _decl("animating", elementId, "transition") == "width var(--t-bar) ease-out"

    def test_tBar_declaredOnceInTokensCss_andMirroredInTheSplashRoot(self):
        tokens = _stripCssComments((SPLASH_DIR.parent / "tokens.css").read_text(encoding="utf-8"))
        styles = _stripCssComments(STYLES_CSS.read_text(encoding="utf-8"))

        assert re.findall(r"--t-bar\s*:\s*([^;]+);", tokens) == ["0.6s"]
        assert re.findall(r"--t-bar\s*:\s*([^;]+);", styles) == ["0.6s"]


class TestPollJsHasNoTimer:
    """NO TIMER: the poll tick is the only setTimeout; no length lives in JS."""

    def test_onlyThePollTickIsASetTimeout(self):
        code = _stripJsComments(POLL_JS.read_text(encoding="utf-8"))

        assert re.findall(r"setTimeout\s*\(([^)]*)\)", code) == ["tick, POLL_MS"]
        assert "setInterval" not in code
        assert "requestAnimationFrame" not in code

    def test_noLengthLiteral(self):
        code = _stripJsComments(POLL_JS.read_text(encoding="utf-8"))

        assert not re.search(r"\b\d+(\.\d+)?m?s\b", code), "a CSS time literal in the poller"
        assert not re.search(r"\b\d{4,}\b", code), "a millisecond-scale number in the poller"
        assert "t-spin" not in code

    def test_everyCloseOutWaitAsksMotionGateFirst(self):
        code = _stripJsComments(POLL_JS.read_text(encoding="utf-8"))

        assert 'willFire(logo, "animation")' in code
        assert 'willFire(stage, "transition")' in code
        assert 'addEventListener("animationend"' in code
        assert 'addEventListener("animationiteration"' in code
        assert 'addEventListener("transitionend"' in code
