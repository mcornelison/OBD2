################################################################################
# File Name: test_boot_spins.py
# Purpose/Description: US-869-f -- the boot logo spins on the page, each step on
#   the previous step's own event: spin 1 once at --bright-mid, spin 2 loops at
#   --bright-hi, spin 3 once at --bright-max, then the fade and window.close().
#   Drives the SHIPPED boot-state-poll.js + motion-gate.js through
#   tests/ui/splash_probe.js (the probe is the browser's half: it dispatches
#   #logo's animationend / animationiteration one rotation apart, on virtual
#   time), and resolves the SHIPPED styles.css over the result.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-24    | Ralph (Rex)  | Initial -- US-869-f page-driven spins.
# ================================================================================
################################################################################

"""US-869-f: spin 1 once, spin 2 loops, spin 3 once, hand-off on the fade's end."""

from __future__ import annotations

import copy
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
POLL_JS = SPLASH_DIR / "boot-state-poll.js"
STYLES_CSS = SPLASH_DIR / "styles.css"
INDEX_HTML = SPLASH_DIR / "index.html"

_POLL_MS = 250
_EMIT_MS = 500
_ROTATION_MS = 3_000  # what the probe computes from #logo's 3s animationDuration

_WAITING = {"healthy": False, "degraded": False}
_HEALTHY = {"healthy": True, "degraded": False}

# What the browser computes with styles.css present: the stage fade, the
# cross-fade, and -- while a body.spin-N class is on -- #logo's spin animation.
_SPINS_LIVE: dict[str, dict[str, str]] = {
    "splash-stage": {"transitionDuration": "0.5s"},
    "mark": {"transitionDuration": "0.5s"},
    "logo": {"animationName": "spin", "animationDuration": "3s"},
}


def _healthyAt(ms: int, before: dict[str, Any] = _WAITING) -> list[dict[str, Any]]:
    """Boot-states written every 500 ms: `before` until `ms`, healthy from then."""
    return [before] * (ms // _EMIT_MS) + [_HEALTHY]


def _spins(result: dict[str, Any]) -> list[tuple[int, int]]:
    return [(entry["spin"], entry["atMs"]) for entry in result["spinLog"]]


def _events(result: dict[str, Any]) -> list[tuple[str, int, int]]:
    return [(e["type"], e["spin"], e["atMs"]) for e in result["animationEvents"]]


def _stripJsComments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def _stripCssComments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def _bodyWith(classes: str) -> dict[str, Any]:
    body = copy.deepcopy(rh.parseMarkup(str(INDEX_HTML)))
    body.setdefault("attrs", {})["class"] = classes
    return body


def _logoDecl(classes: str, prop: str, reducedMotion: bool = False) -> str | None:
    surface = rh.splashSurface(_bodyWith(classes), reducedMotion=reducedMotion)
    path = surface.pathById("logo")
    assert path is not None, "no #logo group in index.html"
    winner = surface.winningDeclaration(path, prop)
    return None if winner is None else winner[0]


# --- the shipped page, driven ------------------------------------------------


@_NODE_ONLY
class TestSpinSequence:
    """Validation: the healthy sequences, every step on its own event."""

    def test_healthyAt4s_spin1Spin2IterationSpin3FadeClose(self):
        """
        Given: the spins live, 0b over at 0 ms, boot-state healthy at virtual 4 s
        When: the probe dispatches each rotation's event
        Then: spin 1 0-3 s, spin 2 3-6 s, spin 3 on the 6 s iteration, the fade at
              9 s on spin 3's animationend, and window.close() on its transitionend
        """
        result = rh.runSplash(_healthyAt(4_000), computedStyles=_SPINS_LIVE, rounds=60)

        assert _spins(result) == [(1, 0), (2, 3_000), (3, 6_000)]
        assert _events(result) == [
            ("animationend", 1, 3_000),
            ("animationiteration", 2, 6_000),
            ("animationend", 3, 9_000),
        ]
        assert result["fadeStartedAtMs"] == 9_000
        assert result["transitionEndDispatched"]
        assert result["handoff"]
        assert result["handoffAtMs"] == 9_000
        assert result["closeCalls"] == 1
        assert result["spinAtHandoff"] == 3
        assert not result["degraded"]

    def test_healthyBeforeSpin1Ends_atLeastOneSpin2Rotation(self):
        """
        Given: healthy on the very first poll, before spin 1's animationend
        Then: spin 2 still turns once -- an animationiteration -- before spin 3
        """
        result = rh.runSplash([_HEALTHY], computedStyles=_SPINS_LIVE, rounds=60)

        events = _events(result)
        spin3At = dict((spin, at) for spin, at in _spins(result))[3]
        iterations = [e for e in events if e[0] == "animationiteration" and e[2] <= spin3At]
        assert len(iterations) >= 1
        assert _spins(result) == [(1, 0), (2, 3_000), (3, 6_000)]
        assert result["handoff"] and result["closeCalls"] == 1

    def test_healthyMidSpin2_spin3WaitsForTheNextIteration_noSnap(self):
        """
        Given: healthy at 6.25 s -- just after spin 2's first iteration at 6 s
        Then: spin 2 finishes the rotation it is in; spin 3 starts at 9 s, not 6.25 s
        """
        result = rh.runSplash(_healthyAt(6_250), computedStyles=_SPINS_LIVE, rounds=80)

        assert _spins(result) == [(1, 0), (2, 3_000), (3, 9_000)]
        assert ("animationiteration", 2, 6_000) in _events(result)
        assert result["handoffAtMs"] == 12_000

    def test_neverHealthy_spin2LoopsAndNothingCloses(self):
        """Waiting is spin 2 looping: one iteration per rotation, no spin 3, no close."""
        result = rh.runSplash([_WAITING], computedStyles=_SPINS_LIVE, rounds=60)

        assert _spins(result) == [(1, 0), (2, 3_000)]
        iterations = [e for e in _events(result) if e[0] == "animationiteration"]
        times = [at for _, _, at in iterations]
        assert times[:3] == [6_000, 9_000, 12_000]
        assert all(b - a == _ROTATION_MS for a, b in zip(times, times[1:]))
        assert not result["handoff"]

    def test_liveSpinWithNoEvent_waitsForItsOwnEvent(self):
        """The control: spins live but the browser fires nothing -> no step, no close."""
        result = rh.runSplash(
            [_HEALTHY], computedStyles=_SPINS_LIVE, dispatchSpinEvents=False, rounds=60
        )

        assert _spins(result) == [(1, 0)]
        assert not result["handoff"]
        assert result["closeCalls"] == 0

    def test_stubbedAnimationEndAtZeroElapsed_handsOff(self):
        """Spec AC 6a: the hand-off fires on the events alone, no elapsed time."""
        result = rh.runSplash([_HEALTHY], computedStyles=_SPINS_LIVE, spinEventMs=0, rounds=4)

        assert [spin for spin, _ in _spins(result)] == [1, 2, 3]
        assert [e[0] for e in _events(result)] == [
            "animationend",
            "animationiteration",
            "animationend",
        ]
        assert result["handoff"]
        assert result["handoffAtMs"] == 0
        assert result["closeCalls"] == 1

    def test_spinsWaitForTheCrossFadesEnd(self):
        """Spin 1 starts on the cross-fade's transitionend (US-785), not before."""
        held = rh.runSplash(
            [_HEALTHY], computedStyles=_SPINS_LIVE, dispatchCrossFadeEnd=False, rounds=40
        )
        released = rh.runSplash(
            [_HEALTHY], computedStyles=_SPINS_LIVE, fontsReadyMs=1_000, rounds=60
        )

        assert held["spinLog"] == []
        assert not held["handoff"]
        assert _spins(released)[0] == (1, 1_000)


@_NODE_ONLY
class TestNoEventWillFire:
    """Atlas G2 / C-Atlas-6: a wait that cannot end is never entered."""

    def test_reducedMotion_closesOnTheHealthyRead_noAnimationRuns(self):
        """
        Given: prefers-reduced-motion, healthy at 4 s
        Then: window.close() at 4 s; no spin was live and no animation event fired
        """
        result = rh.runSplash(
            _healthyAt(4_000),
            computedStyles=_SPINS_LIVE,
            reducedMotion=True,
            dispatchTransitionEnd=False,
            rounds=40,
        )

        # The 4 s read's answer lands within that poll round.
        assert result["handoff"]
        assert 4_000 <= result["handoffAtMs"] <= 4_000 + _POLL_MS
        assert result["closeCalls"] == 1
        assert result["animationEvents"] == []
        assert all(not entry["live"] for entry in result["spinLog"])
        assert result["animationLiveAtHandoff"] is False

    def test_reducedMotion_waitingHoldsOnSpin2_static(self):
        """Before the healthy read the page rests in spin 2 with nothing animating."""
        result = rh.runSplash([_WAITING], computedStyles=_SPINS_LIVE, reducedMotion=True, rounds=20)

        assert [spin for spin, _ in _spins(result)] == [1, 2]
        assert result["animationEvents"] == []
        assert not result["handoff"]

    def test_durationsZero_healthy_noEvent_closesExactlyOnce(self):
        """styles.css missing: every duration computes 0 -> each step advances at once."""
        result = rh.runSplash(
            _healthyAt(4_000),
            computedStyles={},
            dispatchTransitionEnd=False,
            dispatchSpinEvents=False,
            dispatchCrossFadeEnd=False,
            rounds=40,
        )

        assert [spin for spin, _ in _spins(result)] == [1, 2, 3]
        assert 4_000 <= result["fadeStartedAtMs"] <= 4_000 + _POLL_MS
        assert result["handoff"]
        assert result["closeCalls"] == 1

    def test_durationsZero_strayEventsStillCloseOnce(self):
        result = rh.runSplash(_healthyAt(1_000), computedStyles={}, rounds=40)

        assert result["closeCalls"] == 1


@_NODE_ONLY
class TestDegradedFreezesTheLogo:
    """F-103 degraded, unchanged meaning: the logo pauses, the reason prints verbatim."""

    def test_degradedMidSpin2_pausesAndPersists(self):
        failed = {
            "healthy": False,
            "degraded": True,
            "degradedReason": "eclipse-powerwatch: failed to start",
        }
        result = rh.runSplash([_WAITING] * 8 + [failed], computedStyles=_SPINS_LIVE, rounds=40)

        body = result["tree"]
        classes = (body.get("attrs", {}).get("class") or "").split()
        assert result["degraded"]
        assert result["degradedMsg"] == "eclipse-powerwatch: failed to start"
        assert not result["handoff"]
        assert "spin-2" in classes and "degraded" in classes

        surface = rh.splashSurface(body)
        logo = surface.pathById("logo")
        assert surface.winningDeclaration(logo, "animation-play-state")[0] == "paused"


# --- the stylesheet ------------------------------------------------------------


class TestSpinStyles:
    """styles.css owns the motion: one rotation is var(--t-spin), declared once."""

    @pytest.mark.parametrize(
        ("spin", "brightness", "count"),
        [(1, "--bright-mid", "1"), (2, "--bright-hi", "infinite"), (3, "--bright-max", "1")],
    )
    def test_eachSpin_rotationLevelAndCount(self, spin, brightness, count):
        animation = _logoDecl(f"logo-up phase-1 spin-{spin}", "animation")
        assert animation is not None
        parts = animation.split()
        assert parts[0] == "spin" and parts[1] == "var(--t-spin)", animation
        assert count in parts, animation
        assert _logoDecl(f"logo-up phase-1 spin-{spin}", "filter") == (
            f"brightness(var({brightness}))"
        )

    def test_spinKeyframesAreSplashSvgs_thirdsEaseInOutToMinus360(self):
        css = _stripCssComments(STYLES_CSS.read_text(encoding="utf-8"))
        block = re.search(r"@keyframes\s+spin\s*\{(.*?)\n\}", css, re.S)

        assert block is not None, "no @keyframes spin in styles.css"
        stops = re.findall(r"([\d.]+%)\s*\{\s*transform:\s*rotate\(([-\d]+deg)\)", block.group(1))
        assert stops == [
            ("0%", "0deg"),
            ("33.33%", "-120deg"),
            ("66.67%", "-240deg"),
            ("100%", "-360deg"),
        ]
        assert block.group(1).count("animation-timing-function: ease-in-out") == 3
        assert len(re.findall(r"@keyframes\s+spin\b", css)) == 1

    def test_theRotationLengthIsDeclaredOnce_asTheToken(self):
        css = _stripCssComments(STYLES_CSS.read_text(encoding="utf-8"))

        spinRules = re.findall(r"body\.spin-[123] #logo\s*\{([^}]*)\}", css)

        assert len(re.findall(r"--t-spin\s*:", css)) == 1
        assert len(spinRules) == 3
        for rule in spinRules:
            assert "var(--t-spin)" in rule
            assert not re.search(r"\b\d+(\.\d+)?m?s\b", rule), rule

    def test_theBloomIntroIsNotCarried(self):
        """Iris C-Iris-3: no dot, no s-top / s-side bloom on the page."""
        css = _stripCssComments(STYLES_CSS.read_text(encoding="utf-8"))
        html = INDEX_HTML.read_text(encoding="utf-8")

        assert "bloom" not in css
        assert ".s-top" not in css and ".s-side" not in css and ".dot" not in css
        assert 'class="dot"' not in html

    def test_beforeSpin1_theLogoRestsAtTheSpin1Level_noAnimation(self):
        assert _logoDecl("logo-up phase-1", "animation") is None
        assert _logoDecl("logo-up phase-1", "filter") == "brightness(var(--bright-mid))"

    def test_degradedRuleFollowsEverySpinRule(self):
        for spin in (1, 2, 3):
            assert _logoDecl(f"spin-{spin} degraded", "animation-play-state") == "paused"

    @pytest.mark.parametrize("spin", [1, 2, 3])
    def test_reducedMotion_noAnimation_staticAtBrightMid(self, spin):
        classes = f"logo-up phase-1 spin-{spin}"
        assert _logoDecl(classes, "animation", reducedMotion=True) == "none"
        assert _logoDecl(classes, "filter", reducedMotion=True) == "brightness(var(--bright-mid))"

    def test_reducedMotion_noTransitionRuns_evenTheInlineFade(self):
        body = _bodyWith("logo-up phase-1 spin-3")
        stage = next(c for c in body["children"] if c.get("attrs", {}).get("id") == "splash-stage")
        stage["style"] = {"transition": "opacity var(--t-fade)", "opacity": "0"}
        reduced = rh.splashSurface(body, reducedMotion=True)
        normal = rh.splashSurface(body)

        for elementId in ("splash-stage", "mark", "warning"):
            path = reduced.pathById(elementId)
            assert reduced.winningDeclaration(path, "transition")[0] == "none", elementId
        assert normal.winningDeclaration(normal.pathById("splash-stage"), "transition")[0] == (
            "opacity var(--t-fade)"
        )


class TestPollJsHasNoRotationTwin:
    """Validation: grep boot-state-poll.js -- no rotation duration, one setTimeout."""

    def test_noRotationDuration(self):
        code = _stripJsComments(POLL_JS.read_text(encoding="utf-8"))

        assert not re.search(r"\b\d+(\.\d+)?m?s\b", code), "a CSS time literal in the poller"
        assert not re.search(r"\b\d{4,}\b", code), "a millisecond-scale number in the poller"
        assert "t-spin" not in code

    def test_onlyThePollTickIsASetTimeout(self):
        code = _stripJsComments(POLL_JS.read_text(encoding="utf-8"))

        assert re.findall(r"setTimeout\s*\(([^)]*)\)", code) == ["tick, POLL_MS"]
        assert "setInterval" not in code
        assert "requestAnimationFrame(tick" not in code

    def test_everySpinWaitAsksMotionGateFirst(self):
        code = _stripJsComments(POLL_JS.read_text(encoding="utf-8"))

        assert 'willFire(logo, "animation")' in code
        assert 'addEventListener("animationend"' in code
        assert 'addEventListener("animationiteration"' in code
