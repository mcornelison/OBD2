################################################################################
# File Name: test_splash_boot_no_clock.py
# Purpose/Description: US-869-d -- the boot splash decides on EVENTS, never on
#   elapsed time (CIO no-timer rule, Atlas A-tim 1-3). Drives the SHIPPED
#   boot-state-poll.js + motion-gate.js through tests/ui/splash_probe.js:
#   degraded only on the emitter's two events, a null boot-state is waiting,
#   and the hand-off closes on the fade's transitionend -- or at once when
#   motionGate says that event will not fire (Atlas G2).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-24    | Ralph (Rex)  | Initial -- US-869-d boot clocks retired.
# ================================================================================
################################################################################

"""US-869-d: the boot splash has no clock; motion-gate.js decides the hand-off."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

_NODE = shutil.which("node")
_NODE_ONLY = pytest.mark.skipif(_NODE is None, reason="node is required to run the shipped JS")

SPLASH_DIR = Path(rh.SPLASH_DIR)
POLL_JS = SPLASH_DIR / "boot-state-poll.js"
MOTION_GATE_JS = SPLASH_DIR / "motion-gate.js"

_CORE = ["eclipse-states-http", "eclipse-powerwatch", "boot-progress-finalize"]
_POLL_MS = 250
_TEN_MINUTES_ROUNDS = 10 * 60 * 1000 // _POLL_MS


def _bootState(healthy: bool, degradedReason: str | None = None, **services: str) -> dict:
    states = dict.fromkeys(_CORE, "active")
    states.update(services)
    return {
        "progress": 1.0 if healthy else 0.67,
        "healthy": healthy,
        "degraded": degradedReason is not None,
        "services": states,
        "coreServices": _CORE,
        "uiAssets": "present",
        "obdTier": "not-probed",
        "degradedReason": degradedReason,
        "ts": "2026-10-24T12:00:00Z",
    }


_HEALTHY = _bootState(True)
_ACTIVATING = _bootState(False, **{"eclipse-powerwatch": "activating"})


def _stripJsComments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


# --- the page source: no clock left to read -----------------------------------


class TestPollJsHasNoClock:
    """Validation: grep boot-state-poll.js."""

    def test_noHardCapNoMinPlayNoElapsed(self):
        code = _stripJsComments(POLL_JS.read_text(encoding="utf-8"))

        assert "HARD_CAP" not in code
        assert "MIN_PLAY" not in code
        assert "elapsed(" not in code
        assert "performance.now() - " not in code
        assert "brandReadyMs" not in code
        assert "MAX_TRANSIENT_FAILURES" not in code

    def test_exactlyOneSetTimeout_thePollTick(self):
        code = _stripJsComments(POLL_JS.read_text(encoding="utf-8"))

        calls = re.findall(r"setTimeout\s*\(([^)]*)\)", code)
        assert calls == ["tick, POLL_MS"], calls
        assert "setInterval" not in code

    def test_retiredWordsAreGone(self):
        text = POLL_JS.read_text(encoding="utf-8")

        assert "boot-progress instrument not reporting" not in text
        assert "boot did not reach healthy state" not in text

    def test_indexHtml_loadsMotionGateBeforeThePoller(self):
        html = (SPLASH_DIR / "index.html").read_text(encoding="utf-8")
        scripts = re.findall(r'<script\s+src="([^"]+)"', html)

        assert "motion-gate.js" in scripts
        assert scripts.index("motion-gate.js") < scripts.index("boot-state-poll.js")


# --- motion-gate.js: the ONE event-will-fire helper (Atlas G2) ----------------


def _willFire(computed: dict, kind: str, reducedMotion: bool = False) -> bool:
    script = """
const input = JSON.parse(process.argv[1]);
global.window = {
  getComputedStyle: function () { return input.computed; },
  matchMedia: function (q) { return { matches: input.reduced && /reduced-motion/.test(q) }; },
};
require(input.path);
process.stdout.write(JSON.stringify(window.motionGate.willFire({}, input.kind)));
"""
    payload = json.dumps(
        {"path": str(MOTION_GATE_JS), "computed": computed, "kind": kind, "reduced": reducedMotion}
    )
    out = subprocess.run(
        [_NODE, "-e", script, payload],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
    )
    return json.loads(out.stdout)


@_NODE_ONLY
class TestMotionGate:
    """willFire(el, kind) reads the computed style; false is never a stall."""

    @pytest.mark.parametrize(
        "duration, expected",
        [("0.5s", True), ("200ms", True), ("0s", False), ("0ms", False), ("0s, 0.3s", True), ("", False)],
    )
    def test_transition_firesOnlyAboveZero(self, duration, expected):
        assert _willFire({"transitionDuration": duration}, "transition") is expected

    @pytest.mark.parametrize(
        "name, duration, expected",
        [
            ("spin", "1.2s", True),
            ("none", "1.2s", False),
            ("spin", "0s", False),
            ("none", "0s", False),
        ],
    )
    def test_animation_needsANameAndADuration(self, name, duration, expected):
        computed = {"animationName": name, "animationDuration": duration}
        assert _willFire(computed, "animation") is expected

    def test_reducedMotion_isAlwaysFalse(self):
        computed = {"transitionDuration": "0.5s", "animationName": "spin", "animationDuration": "1s"}
        assert _willFire(computed, "transition", reducedMotion=True) is False
        assert _willFire(computed, "animation", reducedMotion=True) is False

    def test_unknownKind_isFalse(self):
        assert _willFire({"transitionDuration": "0.5s"}, "flourish") is False


# --- the shipped page, driven ------------------------------------------------


@_NODE_ONLY
class TestHandoffOnTheFadesOwnEvent:
    """Healthy closes the window on transitionend, or at once when none will fire."""

    def test_healthy_transitionEndDispatched_closesOnce(self):
        result = rh.runSplash([_HEALTHY])

        assert result["handoff"]
        assert result["transitionEndDispatched"]
        assert result["closeCalls"] == 1
        assert not result["degraded"]

    def test_healthy_closeWaitsForTheTransitionEnd(self):
        """With the fade live and no event, the window stays open: no timer closes it."""
        result = rh.runSplash([_HEALTHY], dispatchTransitionEnd=False, rounds=40)

        assert not result["handoff"]
        assert result["closeCalls"] == 0

    def test_healthy_allDurationsZero_noEvent_closesExactlyOnce(self):
        """Atlas G2: styles.css missing -> no transitionend will fire -> close at once."""
        result = rh.runSplash([_HEALTHY], computedStyles={}, dispatchTransitionEnd=False)

        assert result["handoff"]
        assert result["closeCalls"] == 1
        assert not result["transitionEndDispatched"]

    def test_healthy_allDurationsZero_aStrayEventStillClosesOnce(self):
        result = rh.runSplash([_HEALTHY], computedStyles={})

        assert result["closeCalls"] == 1

    def test_healthy_reducedMotion_closesAtOnce(self):
        result = rh.runSplash([_HEALTHY], dispatchTransitionEnd=False, reducedMotion=True)

        assert result["handoff"]
        assert result["closeCalls"] == 1

    def test_healthy_onlyTheTickIsEverQueued(self):
        """One setTimeout per poll round and nothing else: no 600 ms close timer."""
        result = rh.runSplash([_ACTIVATING, _HEALTHY], computedStyles={})

        assert result["handoff"]
        assert result["timeoutsQueued"] == result["polls"]


@_NODE_ONLY
class TestDegradedOnlyOnItsTwoEvents:
    """Negative cases from the acceptance, on ten minutes of driven clock."""

    def test_unitActivatingForTenMinutes_neverDegrades_keepsPolling(self):
        result = rh.runSplash([_ACTIVATING], rounds=_TEN_MINUTES_ROUNDS)

        assert not result["degraded"]
        assert not result["handoff"]
        assert result["degradedMsg"] == ""
        assert result["polls"] >= _TEN_MINUTES_ROUNDS - 1

    def test_bootState404ForTenMinutes_neverDegrades(self):
        result = rh.runSplash([None], rounds=_TEN_MINUTES_ROUNDS)

        assert not result["degraded"]
        assert not result["handoff"]
        assert result["degradedMsg"] == ""
        assert result["polls"] >= _TEN_MINUTES_ROUNDS - 1

    def test_404ThenHealthy_handsOff(self):
        """Waiting is not a verdict: the first written healthy state still hands off."""
        result = rh.runSplash([None, None, None, _HEALTHY])

        assert result["handoff"]
        assert not result["degraded"]

    def test_oneUnitFailed_degradesOnTheNextTick_namingIt(self):
        failed = _bootState(
            False, "eclipse-powerwatch: failed to start", **{"eclipse-powerwatch": "failed"}
        )
        result = rh.runSplash([_ACTIVATING, failed], rounds=40)

        assert result["degraded"]
        assert not result["handoff"]
        assert result["degradedMsg"] == "eclipse-powerwatch: failed to start"
        # Emission 1 (500 ms) is the failed one; the 500 ms poll reads it and stops.
        assert result["polls"] == 3

    def test_assetsMissing_namesIt(self):
        missing = dict(_bootState(False, "dashboard assets not installed"), uiAssets="missing")
        result = rh.runSplash([missing])

        assert result["degraded"]
        assert result["degradedMsg"] == "dashboard assets not installed"
