################################################################################
# File Name: test_boot_checklist.py
# Purpose/Description: US-869-g (spec specs/v030-boot-shutdown-design.md s1.1 +
#   s1.3) -- the boot page's four-feed checklist and gate R1. The dashboard
#   opens when boot-state is healthy AND IMU, LIGHT and UPS have each FINISHED
#   (ready or faulted); OBD never holds it. Drives the SHIPPED boot-state-poll.js
#   through tests/ui/splash_probe.js with capture-health and system-status
#   payloads BUILT by tests/ui/fixtures/states/boot/_generate.py, and resolves
#   the SHIPPED styles.css over the result.
#
#     - cross-language guard: the page's copies of producer vocabulary equal
#       their sources (FEED_NAMES, CAPTURE_FEEDS, STATE_FAULTED, the two reason
#       codes, LINK_UP, eclipse-obd, failed) -- no literal twins
#     - words + colours per fixture, the step latch, gate R1, Atlas G1/R3/R4
#     - the Iris R2 layout at 480x320, and the reduced-motion brightness steps
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-25    | Ralph (Rex)  | Initial -- US-869-g checklist + gate R1.
# ================================================================================
################################################################################

"""US-869-g: the four-feed checklist; the hand-off waits for IMU, LIGHT, UPS."""

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

_REPO = Path(rh.SPLASH_DIR).parents[3]
_SRC = _REPO / "src"
for _root in (str(_REPO), str(_SRC)):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from pi.obdii import capture_health as ch  # noqa: E402
from pi.splash import boot_state_emitter as bse  # noqa: E402
from pi.splash import system_status_emitter as sse  # noqa: E402

_NODE_ONLY = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to run the shipped JS"
)

SPLASH_DIR = Path(rh.SPLASH_DIR)
POLL_JS = SPLASH_DIR / "boot-state-poll.js"
INDEX_HTML = SPLASH_DIR / "index.html"
STYLES_CSS = SPLASH_DIR / "styles.css"
CAROUSEL_JS = Path(rh.DASHBOARD_DIR) / "carousel.js"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "states" / "boot"
ADVANCES = _REPO / "specs" / "assets" / "fonts" / "michroma" / "michroma-advances.json"

_GEN = rh.bootFixtureGenerator()
_EMIT_MS = 500
_POLL_MS = 250
_VIEWPORT = (480, 320)

_WAITING = {"healthy": False, "degraded": False, "services": {"eclipse-obd": "activating"}}
_HEALTHY = {"healthy": True, "degraded": False, "services": {"eclipse-obd": "active"}}
_HEALTHY_OBD_FAILED = {"healthy": True, "degraded": False, "services": {"eclipse-obd": "failed"}}

# The browser with styles.css present: both fades and -- under body.spin-N --
# #logo's 3 s rotation (test_boot_spins.py's _SPINS_LIVE).
_SPINS_LIVE: dict[str, dict[str, str]] = {
    "splash-stage": {"transitionDuration": "0.5s"},
    "mark": {"transitionDuration": "0.5s"},
    "logo": {"animationName": "spin", "animationDuration": "3s"},
}
_ROTATION_MS = 3_000

_WORD_COLOUR = {
    "w-ok": "var(--green-ok)",
    "w-warn": "var(--amber-warn)",
    "w-wait": "var(--text-secondary)",
    "w-unread": "var(--text-tertiary)",
}


# --- helpers -------------------------------------------------------------------


def _fixture(name: str) -> dict[str, Any]:
    with open(FIXTURE_DIR / f"{name}.json", encoding="utf-8") as fh:
        return json.load(fh)


def _capture(name: str) -> dict[str, Any]:
    return _fixture(name)["payloads"]["capture-health"]


def _system(name: str) -> dict[str, Any]:
    return _fixture(name)["payloads"]["system-status"]


def _run(
    bootStates: list[Any],
    capture: Any,
    system: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """runSplash with capture-health passed EXPLICITLY (Atlas R4 condition 3)."""
    return rh.runSplash(bootStates, captureHealth=capture, systemStatus=system, **kwargs)


def _walk(node: dict[str, Any]) -> list[dict[str, Any]]:
    found = [node]
    for child in node.get("children", []):
        if "tag" in child:
            found.extend(_walk(child))
    return found


def _byId(tree: dict[str, Any], elementId: str) -> dict[str, Any]:
    for node in _walk(tree):
        if node.get("attrs", {}).get("id") == elementId:
            return node
    raise AssertionError(f"no #{elementId}")


def _text(node: dict[str, Any]) -> str:
    return "".join(child.get("text", "") for child in node.get("children", []))


def _classes(node: dict[str, Any]) -> list[str]:
    return (node.get("attrs", {}).get("class") or "").split()


def _row(result: dict[str, Any], feed: str) -> tuple[str, str]:
    """(word, colour) of one checklist row, the colour resolved through styles.css."""
    node = _byId(result["tree"], f"feed-{feed}")
    surface = rh.splashSurface(result["tree"])
    path = surface.pathById(f"feed-{feed}")
    colour = surface.winningDeclaration(path, "color")
    return _text(node), (colour[0] if colour else "")


def _bodyClasses(result: dict[str, Any]) -> list[str]:
    return _classes(result["tree"])


def _stripJsComments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def _pollJs() -> str:
    return _stripJsComments(POLL_JS.read_text(encoding="utf-8"))


def _jsVar(name: str) -> Any:
    """A `var NAME = <JSON literal>;` from boot-state-poll.js, parsed."""
    match = re.search(rf"\bvar {name}\s*=\s*(.+?);", _pollJs(), flags=re.DOTALL)
    assert match is not None, f"boot-state-poll.js declares no var {name}"
    literal = re.sub(r",\s*([\]}])", r"\1", match.group(1))   # JS trailing commas
    return json.loads(literal)


def _captureFeeds() -> list[list[str]]:
    js = _stripJsComments(CAROUSEL_JS.read_text(encoding="utf-8"))
    match = re.search(r"\bvar CAPTURE_FEEDS\s*=\s*(\[.*?\]\]);", js, flags=re.DOTALL)
    assert match is not None, "carousel.js declares no CAPTURE_FEEDS"
    return json.loads(match.group(1))


def _spins(result: dict[str, Any]) -> list[tuple[int, int]]:
    return [(entry["spin"], entry["atMs"]) for entry in result["spinLog"]]


# --- the cross-language guard (no literal twins) -------------------------------


class TestVocabularyGuard:
    """Every page copy of producer vocabulary equals its source."""

    def test_feedOrderIsCarouselsCaptureFeeds_andTheSetIsFeedNames(self):
        feeds = _jsVar("FEEDS")
        assert feeds == [name for name, _label in _captureFeeds()]
        assert set(feeds) == set(ch.FEED_NAMES)

    def test_obdIsTheFeedNeverWaitedFor(self):
        assert _jsVar("NOT_WAITED_FOR") == ch.FEED_OBD

    def test_faultVocabularyIsCaptureHealths(self):
        assert _jsVar("STATE_FAULTED") == ch.STATE_FAULTED
        assert _jsVar("REASON_SENSOR_ABSENT") == ch.FEED_REASON_SENSOR_ABSENT
        assert _jsVar("REASON_READ_FAILED") == ch.FEED_REASON_READ_FAILED

    def test_linkVocabularyIsSystemStatuses(self):
        assert _jsVar("LINK_UP") == sse.LINK_UP
        assert tuple(layer for layer, _word in _jsVar("LINK_WORDS")) == sse.LINK_LAYERS

    def test_atlasG1Literals_pinnedToTheBootStateEmitter(self):
        """'eclipse-obd' is the informational unit; 'failed' its terminal state."""
        assert _jsVar("OBD_SERVICE") in bse.INFORMATIONAL_SERVICES_DEFAULT
        assert _jsVar("SERVICE_FAILED") in bse._TERMINAL_SYSTEMCTL

    def test_eachProducerLiteralAppearsOnce_noTwins(self):
        js = _pollJs()
        for literal in (
            ch.STATE_FAULTED,
            ch.FEED_REASON_SENSOR_ABSENT,
            ch.FEED_REASON_READ_FAILED,
            sse.LINK_UP,
            "eclipse-obd",
            "failed",
            *sse.LINK_LAYERS,
            ch.FEED_IMU,
            ch.FEED_LIGHT,
            ch.FEED_UPS,
        ):
            assert js.count(f'"{literal}"') == 1, literal
        # obd: once in FEEDS, once as the named NOT_WAITED_FOR -- nowhere else.
        assert js.count(f'"{ch.FEED_OBD}"') == 2

    def test_theMarkupRowsAreCaptureFeeds_inOrder_withTheirLabels(self):
        checklist = _byId(rh.parseMarkup(str(INDEX_HTML)), "checklist")
        cells = [node for node in checklist["children"] if "tag" in node]
        labels = [_text(c) for c in cells if "cl-label" in _classes(c)]
        words = [c["attrs"]["id"] for c in cells if "cl-word" in _classes(c)]
        assert [_classes(c)[0] for c in cells] == ["cl-label", "cl-word"] * 4
        assert labels == [label for _name, label in _captureFeeds()]
        assert words == [f"feed-{name}" for name, _label in _captureFeeds()]


# --- the fixtures and the harness default (Atlas R4) ---------------------------


class TestFixtures:
    """The boot fixtures are generated, never hand-edited."""

    def test_everyFixtureOnDiskIsWhatTheGeneratorBuilds(self):
        names = sorted(p.stem for p in FIXTURE_DIR.glob("*.json"))
        assert names == sorted(_GEN.FIXTURES)
        for name in names:
            text = (FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8")
            assert text == _GEN.render(_GEN.buildFixture(name)), (
                f"{name}.json is stale -- re-run tests/ui/fixtures/states/boot/_generate.py"
            )

    def test_theHarnessDefaultIsAllThreeReady_obdSilent(self):
        """Atlas R4 condition 3: the default cannot drift and change what the
        38 unedited runSplash calls prove."""
        feeds = _GEN.harnessDefaultCaptureHealth()["feeds"]
        for name in (ch.FEED_IMU, ch.FEED_LIGHT, ch.FEED_UPS):
            assert feeds[name]["firstSampleTs"] is not None, name
            assert feeds[name]["state"] != ch.STATE_FAULTED, name
        assert feeds[ch.FEED_OBD]["firstSampleTs"] is None
        assert _GEN.harnessDefaultCaptureHealth() == _capture("ecu-silent")

    @_NODE_ONLY
    def test_notPassedServesTheDefault_noneServesA404(self):
        default = rh.runSplash([_HEALTHY])
        missing = rh.runSplash([_HEALTHY], captureHealth=None, rounds=20)

        assert default["handoff"]
        assert [_row(default, f)[0] for f in ("imu", "light", "ups")] == ["ready"] * 3
        assert not missing["handoff"]
        assert {_row(missing, f)[0] for f in ch.FEED_NAMES} == {"not read"}


# --- the reads ----------------------------------------------------------------


@_NODE_ONLY
class TestReads:
    """One tick reads all three state files, each with the splash token."""

    def test_eachTickReadsBootStateCaptureHealthAndSystemStatus_tokenGated(self):
        result = _run([_WAITING], _capture("ups-silent"), _system("ecu-silent"), rounds=6)

        byTick: dict[int, list[str]] = {}
        for fetch in result["stateFetches"]:
            assert fetch["token"] == "test-token", fetch
            byTick.setdefault(fetch["atMs"], []).append(fetch["route"])
        assert len(byTick) >= 5
        for routes in byTick.values():
            assert sorted(routes) == ["/boot-state", "/capture-health", "/system-status"]


# --- words and colours (spec s1.3) --------------------------------------------


@_NODE_ONLY
class TestWords:
    """Validation criteria: each fixture's rows, word and colour."""

    def test_ecuSilent_handsOff_obdWaitingForEcu(self):
        result = _run([_HEALTHY], _capture("ecu-silent"), _system("ecu-silent"))

        assert result["handoff"]
        assert _row(result, "obd") == ("waiting for ECU", "var(--text-secondary)")
        for feed in ("imu", "light", "ups"):
            assert _row(result, feed) == ("ready", "var(--green-ok)"), feed

    def test_imuSensorAbsent_sensorNotFoundAmber_andFinished(self):
        result = _run([_HEALTHY], _capture("imu-sensor-absent"), _system("ecu-silent"))

        assert _row(result, "imu") == ("sensor not found", "var(--amber-warn)")
        assert result["handoff"], "a faulted IMU is FINISHED"
        assert not result["degraded"]

    def test_upsUnreadable_readFailedAmber(self):
        result = _run([_HEALTHY], _capture("ups-unreadable"), _system("ecu-silent"))

        assert _row(result, "ups") == ("read failed", "var(--amber-warn)")
        assert result["handoff"]

    def test_anyOtherReason_faultAmber(self):
        result = _run([_HEALTHY], _capture("imu-other-fault"), _system("ecu-silent"))

        assert _row(result, "imu") == ("fault", "var(--amber-warn)")
        assert result["handoff"]

    def test_allFourReady(self):
        result = _run([_HEALTHY], _capture("all-four-ready"), _system("all-four-ready"))

        assert {_row(result, f) for f in ch.FEED_NAMES} == {("ready", "var(--green-ok)")}

    @pytest.mark.parametrize(
        ("fixture", "word"),
        [
            ("bt-connecting", "waiting for Bluetooth"),
            ("adapter-retrying", "waiting for adapter"),
            ("ecu-silent", "waiting for ECU"),
            ("link-unread", "waiting"),
        ],
    )
    def test_obdWordIsTheFirstLinkLayerNotUp(self, fixture, word):
        result = _run([_HEALTHY], _capture(fixture), _system(fixture))

        assert _row(result, "obd") == (word, "var(--text-secondary)")
        assert result["handoff"], "OBD is never waited for"

    def test_noSystemStatus_obdReadsPlainWaiting(self):
        result = _run([_HEALTHY], _capture("ecu-silent"), None)

        assert _row(result, "obd") == ("waiting", "var(--text-secondary)")

    def test_oneFeedHeldNull_readsWaiting_andHolds(self):
        result = _run([_HEALTHY], _capture("light-silent"), _system("ecu-silent"), rounds=40)

        assert _row(result, "light") == ("waiting", "var(--text-secondary)")
        assert not result["handoff"]
        assert not result["degraded"]

    def test_feedsBlockMissing_everyRowNotRead_andHolds(self):
        result = _run([_HEALTHY], _capture("feeds-missing"), _system("ecu-silent"), rounds=40)

        assert {_row(result, f) for f in ch.FEED_NAMES} == {("not read", "var(--text-tertiary)")}
        assert not result["handoff"]
        assert not result["degraded"]

    def test_everyWordColourIsATokenRule(self):
        """Each tone class resolves to exactly the spec s1.3 token."""
        body = copy.deepcopy(rh.parseMarkup(str(INDEX_HTML)))
        for tone, colour in _WORD_COLOUR.items():
            node = _byId(body, "feed-obd")
            node["attrs"]["class"] = f"cl-word {tone}"
            surface = rh.splashSurface(body)
            path = surface.pathById("feed-obd")
            assert surface.winningDeclaration(path, "color")[0] == colour, tone


# --- gate R1 and its negative cases -------------------------------------------


@_NODE_ONLY
class TestGateR1:
    """Spin 3 waits for healthy AND IMU, LIGHT, UPS finished; never for OBD."""

    def test_upsNullFor400Polls_thenReady_spin3AtTheNextIteration(self):
        """
        Given: the spins live, healthy throughout, UPS silent for 400 polls
        When: UPS reports ready
        Then: held until then; spin 3 starts on spin 2's next animationiteration
        """
        silentMs = 400 * _POLL_MS
        captures = [_capture("ups-silent")] * (silentMs // _EMIT_MS) + [_capture("ecu-silent")]
        result = _run(
            [_HEALTHY], captures, _system("ecu-silent"), computedStyles=_SPINS_LIVE, rounds=440
        )

        spins = _spins(result)
        assert spins[:2] == [(1, 0), (2, _ROTATION_MS)]
        assert result["handoff"]
        spin3At = dict(spins)[3]
        # The first iteration boundary at or after the read that saw UPS ready
        # (the read lands at most one POLL_MS after the write).
        nextIteration = -(-silentMs // _ROTATION_MS) * _ROTATION_MS
        assert spin3At in (nextIteration, nextIteration + _ROTATION_MS)
        assert spin3At >= silentMs
        assert spin3At - silentMs <= _ROTATION_MS + _POLL_MS
        iterationsBefore = [
            e for e in result["animationEvents"]
            if e["type"] == "animationiteration" and e["atMs"] < silentMs
        ]
        assert len(iterationsBefore) >= 30, "spin 2 must have looped while UPS was silent"

    def test_upsSilentForAnyLength_holds_neverDegraded(self):
        result = _run([_HEALTHY], _capture("ups-silent"), _system("ecu-silent"), rounds=800)

        assert not result["handoff"]
        assert not result["degraded"]
        assert _row(result, "ups") == ("waiting", "var(--text-secondary)")

    def test_feedsFinished_butNotHealthy_holds(self):
        result = _run([_WAITING], _capture("ecu-silent"), _system("ecu-silent"), rounds=40)

        assert not result["handoff"]
        assert "r1-met" not in _bodyClasses(result)

    def test_captureHealthMissing_obdNotFailed_everyRowNotRead_holds(self):
        result = _run([_HEALTHY], None, _system("ecu-silent"), rounds=80)

        assert {_row(result, f)[0] for f in ch.FEED_NAMES} == {"not read"}
        assert not result["handoff"]
        assert not result["degraded"]

    def test_captureHealthMissing_eclipseObdFailed_threeFault_handsOff(self):
        """Atlas G1: the only producer of capture-health has failed for good."""
        result = _run([_HEALTHY_OBD_FAILED], None, _system("ecu-silent"))

        for feed in ("imu", "light", "ups"):
            assert _row(result, feed) == ("fault", "var(--amber-warn)"), feed
        assert _row(result, "obd")[0] == "waiting for ECU"
        assert result["handoff"]
        assert not result["degraded"]

    def test_eclipseObdFailed_handsOffAtTheNextIteration(self):
        failedAt = 6 * _EMIT_MS
        boots = [_HEALTHY] * (failedAt // _EMIT_MS) + [_HEALTHY_OBD_FAILED]
        result = _run(boots, None, _system("ecu-silent"), computedStyles=_SPINS_LIVE, rounds=60)

        spin3At = dict(_spins(result))[3]
        assert result["handoff"]
        assert spin3At == _ROTATION_MS * 2   # spin 2's first iteration after 3 s

    def test_noTimerOrTimestampGatesTheHandoff(self):
        js = _pollJs()
        assert js.count("setTimeout(") == 1, "the POLL_MS tick is the only timer"
        assert "Date" not in js
        assert "performance.now" not in js.split("first-frame")[0]


# --- the step latch (Iris C-Iris-6) and the healthy latch (Atlas R3) -----------


@_NODE_ONLY
class TestLatches:
    def test_aFinishedStepStaysFinished_theWordFollowsTheFeed(self):
        """
        Given: UPS ready on the first read, then re-armed (restart) to silent
        When: boot-state turns healthy after the re-arm
        Then: the hand-off still happens, and the UPS row reads 'waiting'
        """
        captures = [_capture("ecu-silent")] + [_capture("ups-silent")]
        boots = [_WAITING] * 4 + [_HEALTHY]
        result = _run(boots, captures, _system("ecu-silent"))

        assert result["handoff"]
        assert _row(result, "ups") == ("waiting", "var(--text-secondary)")

    def test_healthyThenDegraded_thenReady_handsOff_neverDegraded(self):
        """Atlas R3: degraded is honoured only before the first healthy read."""
        degraded = {
            "healthy": False,
            "degraded": True,
            "degradedReason": "eclipse-powerwatch: failed to start",
            "services": {"eclipse-obd": "active"},
        }
        boots = [_HEALTHY, _HEALTHY, degraded]
        captures = [_capture("ups-silent")] * 6 + [_capture("ecu-silent")]
        result = _run(boots, captures, _system("ecu-silent"), rounds=40)

        assert result["handoff"]
        assert not result["degraded"]
        assert "degraded" not in _bodyClasses(result)
        assert result["degradedMsg"] == ""

    def test_degradedBeforeHealthy_stillDegrades_andHidesTheChecklist(self):
        degraded = {
            "healthy": False,
            "degraded": True,
            "degradedReason": "dashboard assets not installed",
            "services": {},
        }
        result = _run([_WAITING, degraded], _capture("ecu-silent"), _system("ecu-silent"))

        assert result["degraded"]
        assert not result["handoff"]
        surface = rh.splashSurface(result["tree"])
        assert not surface.rendered(surface.pathById("checklist"))
        assert surface.rendered(surface.pathById("degraded-msg"))

    def test_pollingContinuesAfterHealthy_untilTheWindowCloses(self):
        result = _run(
            [_HEALTHY], [_capture("ups-silent")] * 4 + [_capture("ecu-silent")], rounds=40
        )
        readsAfterHealthy = [f for f in result["stateFetches"] if f["route"] == "/capture-health"]
        assert result["handoff"]
        assert len(readsAfterHealthy) >= 4
        assert max(f["atMs"] for f in result["stateFetches"]) <= result["handoffAtMs"]


# --- reduced motion (Atlas C-Atlas-6) ------------------------------------------


def _logoFilter(classes: str) -> str:
    body = copy.deepcopy(rh.parseMarkup(str(INDEX_HTML)))
    body.setdefault("attrs", {})["class"] = classes
    surface = rh.splashSurface(body, reducedMotion=True)
    return surface.winningDeclaration(surface.pathById("logo"), "filter")[0]


class TestReducedMotion:
    def test_brightnessStepsFollowTheFeeds(self):
        assert _logoFilter("logo-up phase-1 spin-2") == "brightness(var(--bright-mid))"
        assert _logoFilter("logo-up phase-1 spin-2 feed-finished") == (
            "brightness(var(--bright-hi))"
        )
        assert _logoFilter("logo-up phase-1 spin-3 feed-finished r1-met") == (
            "brightness(var(--bright-max))"
        )

    def test_theStepsAreInstant_noTransitionOnTheLogo(self):
        css = re.sub(r"/\*.*?\*/", "", STYLES_CSS.read_text(encoding="utf-8"), flags=re.S)
        for selector, body in re.findall(r"([^{}]*#logo[^{}]*)\{([^{}]*)\}", css):
            assert "transition" not in body, selector.strip()

    @_NODE_ONLY
    def test_oneFeedFinished_hi_thenR1_maxAndCloseWithZeroAnimations(self):
        captures = [_capture("light-silent")] * 4 + [_capture("ecu-silent")]
        held = _run(
            [_HEALTHY], _capture("light-silent"), reducedMotion=True,
            computedStyles=_SPINS_LIVE, rounds=20,
        )
        done = _run(
            [_HEALTHY], captures, reducedMotion=True, computedStyles=_SPINS_LIVE, rounds=20
        )

        assert "feed-finished" in _bodyClasses(held)
        assert "r1-met" not in _bodyClasses(held)
        assert not held["handoff"]
        assert {"feed-finished", "r1-met"} <= set(_bodyClasses(done))
        assert done["handoff"]
        assert done["animationEvents"] == []
        assert done["handoffAtMs"] - 4 * _EMIT_MS <= _POLL_MS


# --- the Iris R2 layout at 480x320 --------------------------------------------


def _surface(classes: str = "logo-up phase-1") -> rh.Surface:
    body = copy.deepcopy(rh.parseMarkup(str(INDEX_HTML)))
    body.setdefault("attrs", {})["class"] = classes
    return rh.splashSurface(body, viewport=_VIEWPORT)


def _px(surface: rh.Surface, elementId: str, prop: str) -> float:
    return surface.lengthPx(surface.pathById(elementId), prop)


def _checklistBox(surface: rh.Surface) -> tuple[float, float, float, float]:
    """(left, top, right, bottom): 4 rows of the declared line-height."""
    top, left = _px(surface, "checklist", "top"), _px(surface, "checklist", "left")
    width = _px(surface, "checklist", "width")
    rows = len(_jsVar("FEEDS"))
    return left, top, left + width, top + rows * _px(surface, "checklist", "line-height")


def _sweptDiscBottom(surface: rh.Surface) -> float:
    """The lowest y the spinning logo reaches: its tip radius at #mark's scale.

    viewBox 480x320 with `meet` -> scale = min(boxW/480, boxH/320).
    """
    mark = surface.pathById("mark")
    scale = min(surface.lengthPx(mark, "height") / 320, _VIEWPORT[0] / 480)
    points = re.findall(r"(\d+),(\d+)", INDEX_HTML.read_text(encoding="utf-8").split(
        '<g id="logo"')[1].split("</g>\n    </svg>")[0])
    radius = max(((int(x) - 240) ** 2 + (int(y) - 160) ** 2) ** 0.5 for x, y in points)
    centreY = surface.lengthPx(mark, "top") + 160 * scale
    return centreY + radius * scale


class TestLayout:
    def test_theLogoIsDrawnAt0point6_andItsSweptDiscEndsAt186(self):
        surface = _surface()
        mark = surface.pathById("mark")
        assert surface.lengthPx(mark, "top") == 24
        assert surface.lengthPx(mark, "height") == 192
        assert surface.winningDeclaration(mark, "width")[0] == "100%"
        assert surface.winningDeclaration(mark, "position")[0] == "absolute"
        assert _sweptDiscBottom(surface) == pytest.approx(186)

    def test_theChecklistBox_y194to282_clearsTheDiscAndTheChip(self):
        surface = _surface()
        left, top, right, bottom = _checklistBox(surface)
        assert (left, top, right, bottom) == (52, 194, 428, 282)
        assert top > _sweptDiscBottom(surface)
        # The chip sits bottom:12px; at --fs-meta 15 px its line box (1.2 em,
        # Iris's figure) is y ~290-308, so it starts below the last row.
        chipBottom = _px(surface, "version-chip", "bottom")
        assert _VIEWPORT[1] - chipBottom - 1.2 * 15 > bottom

    def test_theChecklistAndTheDegradedMessageNeverPaintTogether(self):
        normal = _surface()
        degraded = _surface("logo-up phase-1 spin-2 degraded")
        degradedTree = copy.deepcopy(degraded.tree)
        _byId(degradedTree, "degraded-msg")["attrs"].pop("hidden", None)
        degraded = rh.splashSurface(degradedTree, viewport=_VIEWPORT)

        assert normal.rendered(normal.pathById("checklist"))
        assert not normal.rendered(normal.pathById("degraded-msg"))
        assert degraded.displayOf(degraded.pathById("checklist"))[0] == "none"
        assert degraded.rendered(degraded.pathById("degraded-msg"))
        assert _px(degraded, "degraded-msg", "top") == 194
        assert _px(degraded, "degraded-msg", "line-height") == 22

    def test_fixedColumns_labelColumn96_wordColumn264(self):
        surface = _surface()
        checklist = surface.pathById("checklist")
        assert surface.winningDeclaration(checklist, "display")[0] == "grid"
        assert surface.winningDeclaration(checklist, "grid-template-columns")[0] == (
            "96px 264px"
        )
        assert surface.winningDeclaration(checklist, "column-gap")[0] == "16px"
        css = re.sub(r"/\*.*?\*/", "", STYLES_CSS.read_text(encoding="utf-8"), flags=re.S)
        assert "max-content" not in css

    def test_everyLabelFitsThe96pxColumn_andEveryWordThe264pxColumn(self):
        """Labels at Michroma --fs-label (20 px, the shipped advances); words at
        the mono advance (Iris: 12.04 px per character at 20 px)."""
        with open(ADVANCES, encoding="utf-8") as fh:
            advance = json.load(fh)["advanceEm"]
        for _name, label in _captureFeeds():
            assert sum(advance[c] for c in label) * 20 <= 96, label
        longest = max(
            ("ready", "sensor not found", "read failed", "fault", "waiting", "not read",
             *(word for _layer, word in _jsVar("LINK_WORDS"))),
            key=len,
        )
        assert longest == "waiting for Bluetooth"
        assert len(longest) * 12.04 <= 264

    def test_labelsRightAligned_inTheBrandFace_wordsLeftAligned_mono(self):
        surface = _surface()
        for path in surface.pathsByClass("cl-label"):
            assert surface.winningDeclaration(path, "text-align")[0] == "right"
            assert surface.winningDeclaration(path, "font-family")[0] == "var(--font-display)"
            assert surface.winningDeclaration(path, "font-size")[0] == "var(--fs-label)"
            assert surface.winningDeclaration(path, "color")[0] == "var(--text-secondary)"
        for path in surface.pathsByClass("cl-word"):
            assert surface.winningDeclaration(path, "text-align")[0] == "left"
            assert surface.winningDeclaration(path, "font-family")[0] == "var(--font-mono)"
            assert surface.winningDeclaration(path, "font-size")[0] == "var(--fs-label)"
