################################################################################
# File Name: test_carousel_altitude_typed_na_recorded_pass.py
# Purpose/Description: US-642 -- RECORD THE PASS for the states/imu ALTITUDE
#   contract: the field is a typed NULL carrying reason "no_source" (no
#   barometer is fitted), and the panel paints it as NA WITH that reason --
#   never 0 m, never a derived guess.
#
#   WHY THIS FILE EXISTS WHEN THE BEHAVIOUR ALREADY HAD TESTS. The two halves
#   were each covered and NOTHING JOINED THEM -- the US-494/495/498 shape this
#   project keeps shipping:
#     * PRODUCER: test_imu_state_bridge.py:309 pins `buildImuState` as a PURE
#       FUNCTION. It never runs the bridge and never opens the file the panel
#       actually reads, so a bridge that post-processed the payload on its way
#       to disk would stay green.
#     * RENDERER: every altitude assertion in tests/ui/ is made on the VIEW
#       OBJECT `liveCardView(...)["altitude"]` over a HAND-WRITTEN dict
#       (test_carousel_imu_card.py:240, test_carousel_imu_always_on.py:292,
#       test_carousel_live_home_card.py:565). A hand-written
#       `{"reasons": {"altitude": "no_source"}}` is satisfied by a fixture that
#       agrees with itself; rename the producer's key tomorrow and not one of
#       them goes red.
#     * PLACEMENT: the only assertion that the tile is PAINTED AT ALL
#       (test_carousel_live_home_card.py:747) is a STRING GREP over carousel.js
#       for `appendTile(gradeTileBox, view.altitude)`. A grep cannot witness a
#       pixel. Before this file, `"ALTITUDE"` appeared in exactly ONE assertion
#       in the whole repository and it was reading a JS object property.
#   Everything below runs the REAL ImuStateBridge over REAL bus samples -> the
#   state file it actually writes -> the SHIPPED carousel.js over the SHIPPED
#   markup + stylesheet at 480x320.
#
#   THE NEGATIVE CASE IS MEASURED, NOT ARGUED. "Never a derived guess" is cheap
#   to assert when no altitude number exists anywhere in the process. One does:
#   `AltitudeAnchor` (US-518) holds the home elevation, and its own header says
#   publishing home-elevation-forever would be "a confident wrong number". So
#   the anchor is BUILT AND ANCHORED to a real metre value in these tests, and
#   the panel is then asserted to carry no digit of it -- the guess exists and
#   is demonstrably refused, rather than merely being unavailable.
#
#   VERIFY OUTCOME: PASS. Atlas's punch-list 1.3 is correct, on the state file
#   he read AND on the panel. Findings, if any, are recorded -- never fixed
#   here (the story forbids a verify story quietly becoming a fix story).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-642 recorded pass: typed-NA
#               |              | altitude end to end, real bridge to painted
#               |              | tile, with the home-elevation anchor as the
#               |              | live counter-example.
# ================================================================================
################################################################################

"""US-642: ALTITUDE renders typed-NA with its reason -- record the pass."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "src",
    ),
)

import render_harness as rh  # noqa: E402

from pi.bus.sample import Sample  # noqa: E402
from pi.location.altitude_anchor import AltitudeAnchor  # noqa: E402
from pi.sensors.imu_state_bridge import (  # noqa: E402
    IMU_STATE_FILENAME,
    REASON_NO_SOURCE,
    STANDARD_GRAVITY_MS2,
    STATE_IMU_PRESENCE,
    TOPIC_IMU_ACCEL,
    TOPIC_IMU_MAG,
    ImuStateBridge,
)

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The shipped panel, not the harness default.
PANEL = (480, 320)

_REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
_CAROUSEL_JS = os.path.join(_REPO, "src", "pi", "ui", "dashboard", "carousel.js")
_SRC_DIR = os.path.join(_REPO, "src")

G = STANDARD_GRAVITY_MS2

# A fixed instant + the canonical second-resolution ISO the producer stamps.
# The harness clock (US-641 `nowMs`) is pinned one second past it, so every
# payload below is unambiguously INSIDE carousel.js's 2 s IMU freshness window
# -- an altitude that read NA because the whole card had gone stale would prove
# nothing about the altitude field.
_T0_ISO = "2026-08-31T12:00:00Z"
_T0_MS = 1787227200000  # 2026-08-31T12:00:00Z in epoch ms
_NOW_MS = _T0_MS + 1000

# Chicagoland home elevation, in metres. The number is not a vehicle fact and is
# not being validated here -- it is the COUNTER-EXAMPLE: a real, plausible,
# in-process altitude that the panel must refuse to print. 209 m is the figure
# altitude_anchor.py's own docstring names as the error a zero default would
# make, so it is the exact wrong answer this contract exists to prevent.
_HOME_ELEVATION_M = 209.0


# ------------------------------------------------------------------- producer


def _accel(value: tuple[float, float, float], *, seq: int = 1, capture: float = 0.0):
    """One raw.imu.accel burst sample (m/s^2, device frame)."""
    return Sample(
        topic=TOPIC_IMU_ACCEL,
        source="imu",
        value=value,
        unit="m/s^2",
        tsUtc=_T0_ISO,
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _mag(value: tuple[float, float, float], *, seq: int = 1, capture: float = 0.0):
    """One raw.imu.mag burst sample (uT, device frame)."""
    return Sample(
        topic=TOPIC_IMU_MAG,
        source="imu",
        value=value,
        unit="uT",
        tsUtc=_T0_ISO,
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _presence(present: bool, *, seq: int = 1, capture: float = 0.0):
    """The retained IMU presence STATE the reader publishes on an unplug.

    The topic is imported from the producer, not spelled here. Spelling it out
    cost this file a green run during authoring: a wrong topic string is
    IGNORED by ``handleSample`` and the previous payload simply stays on disk,
    so the test reads a LIVE file while believing it has unplugged the sensor.
    """
    return Sample(
        topic=STATE_IMU_PRESENCE,
        source="imu",
        value=1.0 if present else 0.0,
        unit="bool",
        tsUtc=_T0_ISO,
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _producedImuState(tmpPath: Path, samples: list[Any]) -> dict[str, Any]:
    """Run the REAL bridge over ``samples`` and return the bytes it wrote.

    Every payload served to the panel below is the producer's OWN output. A
    producer change that renamed ``reasons.altitude`` or started emitting a
    number fails HERE, rather than being masked by a hand-written fixture that
    was written to agree with the renderer in the first place.
    """
    bridge = ImuStateBridge(None, str(tmpPath))
    for sample in samples:
        bridge.handleSample(sample)
    return json.loads((tmpPath / IMU_STATE_FILENAME).read_text(encoding="utf-8"))


def _liveState(tmpPath: Path) -> dict[str, Any]:
    """A LIVE states/imu payload straight from the bridge.

    A level board with a north-pointing magnetometer: gravity resolves, so the
    g-meter and the heading are real readings sitting BESIDE the absent
    altitude. That pairing is the point -- it is what makes "the altitude is
    NA" a statement about the altitude rather than about a dead card.
    """
    return _producedImuState(
        tmpPath,
        [_mag((0.0, 20.0, -40.0)), _accel((0.0, 0.0, G))],
    )


# --------------------------------------------------------------------- render


def _run(imu: Any, *, nowMs: int = _NOW_MS) -> dict[str, Any]:
    """Boot the SHIPPED carousel over the SHIPPED markup at the panel size.

    ``imu`` is served at /imu; pass None to model the state file being ABSENT
    (an unlisted route 404s -- nothing is invented on the test's behalf).
    """
    routes: dict[str, Any] = {}
    if imu is not None:
        routes["/imu"] = imu
    return rh.runDashboard(
        routes=routes,
        steps=[{"flush": 4}],
        viewport=PANEL,
        nowMs=nowMs,
    )["tree"]


def _findAttr(node: Any, attr: str, value: str) -> dict[str, Any] | None:
    if isinstance(node, dict) and node.get("attrs", {}).get(attr) == value:
        return node
    for child in (node or {}).get("children", []) or []:
        found = _findAttr(child, attr, value)
        if found is not None:
            return found
    return None


def _text(node: dict[str, Any] | None) -> str:
    if node is None:
        return ""
    if "text" in node:
        return str(node["text"])
    return " ".join(_text(c) for c in node.get("children", []) or []).strip()


def _homeCard(tree: dict[str, Any]) -> dict[str, Any]:
    card = _findAttr(tree, "id", "home-card")
    assert card is not None, "the Home card is not in the rendered tree"
    return card


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for child in node.get("children", []) or []:
            yield from _walk(child)


def _classOf(node: dict[str, Any]) -> str:
    return str(node.get("attrs", {}).get("class") or "")


def _childText(tile: dict[str, Any], cls: str) -> str:
    for node in _walk(tile):
        if _classOf(node) == cls:
            return _text(node)
    return ""


def _tiles(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every PAINTED tile on the Home card, keyed by its rendered label."""
    out: dict[str, dict[str, Any]] = {}
    for node in _walk(_homeCard(tree)):
        if _classOf(node) != "tile":
            continue
        label = _childText(node, "tile-label")
        if label:
            out[label] = node
    return out


def _tile(tree: dict[str, Any], label: str) -> dict[str, Any]:
    tiles = _tiles(tree)
    assert label in tiles, (
        f"no {label} tile was painted on the Home card -- found {sorted(tiles)}"
    )
    return tiles[label]


def _value(tile: dict[str, Any]) -> str:
    return _childText(tile, "tile-value")


def _detail(tile: dict[str, Any]) -> str:
    return _childText(tile, "tile-detail")


def _level(tile: dict[str, Any]) -> str:
    return str(tile.get("attrs", {}).get("data-level") or "")


def _srcFilesContaining(needle: str) -> set[str]:
    """Every src/ Python file whose text contains ``needle``, repo-relative.

    A sweep rather than a hand grep: a hand grep is a claim about the tree ON
    THE DAY IT WAS RUN, and this file's whole subject is that an unrecorded
    check is indistinguishable from an unmade one.
    """
    found: set[str] = set()
    for root, _dirs, files in os.walk(_SRC_DIR):
        if "__pycache__" in root:
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            if needle in Path(path).read_text(encoding="utf-8", errors="ignore"):
                found.add(os.path.relpath(path, _REPO).replace("\\", "/"))
    return found


# =============================================================================
# 1. THE RECORDED PASS -- the real producer, through to a painted tile.
# =============================================================================


def test_realBridge_writesAltitudeAsTypedNullWithNoSourceReason(tmp_path):
    """
    Given: the REAL ImuStateBridge draining a live accel + mag burst
    When: the state file it writes is read back off disk
    Then: `altitude` is JSON null and `reasons.altitude` is "no_source"

    The pure-function pin already existed; the FILE did not. The panel reads the
    file, so this is the byte-level SSOT the story names.
    """
    state = _liveState(tmp_path)

    assert state["altitude"] is None
    assert state["reasons"]["altitude"] == REASON_NO_SOURCE
    # Typed NULL, not an omitted key: a missing field and a refused one are
    # different facts, and only one of them can carry a reason.
    assert "altitude" in state


def test_liveFaceActuallyPainted_control(tmp_path):
    """
    Given: that same live payload on the shipped panel
    When: the Home card is inspected
    Then: it is on the LIVE face and carries REAL readings beside the absence

    THE CONTROL FOR EVERY ABSENCE CLAIM BELOW. US-638 established the hazard by
    walking into it: a harness that throws renders an empty card body, and an
    empty body satisfies "no altitude number is painted" while proving nothing.
    A face that demonstrably paints a heading and a g reading cannot be that.
    """
    tree = _run(_liveState(tmp_path))

    assert _homeCard(tree).get("attrs", {}).get("data-face") == "live"
    tiles = _tiles(tree)
    assert "HEADING" in tiles and "G-FORCE" in tiles and "ALTITUDE" in tiles
    assert re.search(r"\d", _value(tiles["HEADING"])), _value(tiles["HEADING"])
    assert re.search(r"\d", _value(tiles["G-FORCE"])), _value(tiles["G-FORCE"])


def test_shippedPanel_altitudeTileReadsNaWithTheProducersReason(tmp_path):
    """
    Given: the producer's own payload served at /imu
    When: the shipped carousel paints the Home card at 480x320
    Then: the ALTITUDE tile reads NA and its detail carries the reason

    This is the story's END STATE, measured on the panel rather than on the view
    object every prior test stopped at.
    """
    tile = _tile(_run(_liveState(tmp_path)), "ALTITUDE")

    assert _value(tile) == "NA"
    assert _detail(tile) == "no source"


def test_shippedPanel_altitudeTileCarriesTheUnavailableLevel(tmp_path):
    """
    Given: the painted ALTITUDE tile
    When: its [data-level] is read
    Then: it is `unavailable` -- the stylesheet's absence presentation

    The word NA alone is a string; the level is what makes the tile LOOK absent.
    Both halves are asserted because either one alone can be right while the
    tile still reads as a settled value.
    """
    assert _level(_tile(_run(_liveState(tmp_path)), "ALTITUDE")) == "unavailable"


def test_shippedPanel_altitudeIsPaintedInTheGradeBox_notMerelyComputed(tmp_path):
    """
    Given: the locked live-face layout (grade % + a PROMINENT altitude together)
    When: the rendered tree is walked
    Then: the ALTITUDE tile is a child of `.live-grade-tiles`, beside GRADE

    Replaces the string grep at test_carousel_live_home_card.py:747, which
    matches the source text whether or not the call ever runs.
    """
    box = None
    for node in _walk(_homeCard(_run(_liveState(tmp_path)))):
        if "live-grade-tiles" in _classOf(node):
            box = node
            break
    assert box is not None, "the grade tile box was never built"

    labels = [
        _childText(t, "tile-label") for t in _walk(box) if _classOf(t) == "tile"
    ]
    assert labels == ["GRADE", "ALTITUDE"], labels


# =============================================================================
# 2. THE NEGATIVE CASE -- never 0 m, never a derived guess.
# =============================================================================


def test_altitudeTile_carriesNoDigitAnywhere(tmp_path):
    """
    Given: the painted ALTITUDE tile
    When: its value AND its detail are searched for a digit
    Then: there is none

    Asserted as "no digit" rather than "not the string '0 m'" deliberately. A
    zeroed altitude renders as sea level -- a confident lie -- and it can wear
    many costumes (0, 0.0, 0 m, 0 ft, -0). The absence of any digit rules out
    every one of them, including the ones nobody thought to enumerate.
    """
    tile = _tile(_run(_liveState(tmp_path)), "ALTITUDE")

    assert not re.search(r"\d", _value(tile)), _value(tile)
    assert not re.search(r"\d", _detail(tile)), _detail(tile)


def test_altitudeTile_isNotAZeroInAnyCostume(tmp_path):
    """
    Given: the painted ALTITUDE tile
    When: its value is compared against the plausible sea-level renderings
    Then: it matches none of them

    Redundant with the digit sweep ON PURPOSE: this one names the defect, so a
    future reader sees WHAT the digit sweep is protecting against rather than
    reading it as a stylistic rule about tiles not containing numbers.
    """
    value = _value(_tile(_run(_liveState(tmp_path)), "ALTITUDE"))

    assert value not in {"0", "0 m", "0.0 m", "0.0", "0 ft", "-0 m", "0m"}


def test_homeElevationAnchorHoldingARealMetreValue_neverReachesThePanel(tmp_path):
    """
    Given: the REAL AltitudeAnchor re-anchored to a real home elevation, so a
           plausible altitude number genuinely EXISTS in the process
    When: the bridge publishes and the panel paints
    Then: the state file still says null/no_source and no digit of that number
          appears anywhere on the Home card

    THE STORY'S "never a derived guess", MEASURED. Without the anchor this claim
    is free -- you cannot leak a number that does not exist. altitude_anchor.py's
    own header says publishing home-elevation-forever would be "a confident wrong
    number, strictly worse than the honest 'no source' shown today"; this is the
    test that holds that sentence to account.
    """

    class _HomeProvider:
        def getHomeElevationM(self) -> float:
            return _HOME_ELEVATION_M

    anchor = AltitudeAnchor(_HomeProvider())
    assert anchor.reanchorToHome() is True
    assert anchor.getAltitudeM() == pytest.approx(_HOME_ELEVATION_M)

    state = _liveState(tmp_path)
    assert state["altitude"] is None, "the anchor's value leaked into states/imu"

    cardText = _text(_homeCard(_run(state)))
    assert "209" not in cardText, cardText


def test_altitudeTile_isVisuallyDistinctFromTheLiveReadingsBesideIt(tmp_path):
    """
    Given: the ALTITUDE tile painted next to a live HEADING on the same card
    When: their [data-level]s are compared
    Then: they differ -- absence does not present as a measurement

    "Unknown is not clear" at the level of the stylesheet. A typed NA that
    painted at the same level as a real bearing would be an honest string in a
    confident costume, which is the punch list's 2.1 defect class.
    """
    tiles = _tiles(_run(_liveState(tmp_path)))

    assert _level(tiles["ALTITUDE"]) == "unavailable"
    assert _level(tiles["HEADING"]) != "unavailable"


def test_absentImuState_paintsNoAltitudeNumberEither(tmp_path):
    """
    Given: no states/imu file at all -- the shipped Pi today, where
           pi.sensors.imu.enabled defaults false
    When: the Home card paints
    Then: it falls back off the live face and prints no altitude number

    The story's absence case at the OTHER end of the chain. The tile is gone
    with the face it lived on, which is honest -- what must not happen is a
    fallback face that fills the gap with a plausible metre reading.
    """
    tree = _run(None)

    assert _homeCard(tree).get("attrs", {}).get("data-face") != "live"
    assert "ALTITUDE" not in _tiles(tree)
    assert "209" not in _text(_homeCard(tree))


def test_unpluggedSensor_altitudeStaysNoSource_notSensorAbsent(tmp_path):
    """
    Given: the reader reports the IMU absent (the retained presence STATE)
    When: the bridge writes the unavailable payload
    Then: every other derived field takes the blanket `sensor_absent` reason,
          but altitude STILL reads `no_source`

    A permanently-unsourced field and a temporarily-unreadable one are different
    facts, and the bridge keeps them apart even when the whole instrument is
    down. Fitting a barometer would fix one and not the other; collapsing them
    would hide that.
    """
    state = _producedImuState(tmp_path, [_accel((0.0, 0.0, G)), _presence(False)])

    assert state["available"] is False
    assert state["reasons"]["altitude"] == REASON_NO_SOURCE
    assert state["reasons"]["gLat"] != REASON_NO_SOURCE


# =============================================================================
# 3. THE REASON IS CARRIED -- NA alone is a shrug.
# =============================================================================


def test_producersReasonWord_isOneTheShippedRendererCanActuallySpell(tmp_path):
    """
    Given: the reason word the REAL producer wrote
    When: it is looked up in the vocabulary read OUT OF the shipped carousel.js
    Then: it is present, and its rendered text is what the panel painted

    THE JOIN, stated as a join. Both sides could be internally consistent and
    still disagree: rename the producer's constant and the tile silently starts
    printing the raw code instead of the operator-facing words. The vocabulary
    is parsed from the shipped file rather than hardcoded here, so this test
    cannot pass by remembering what the map used to say.
    """
    js = Path(_CAROUSEL_JS).read_text(encoding="utf-8")
    block = re.search(r"var IMU_REASON_TEXT = \{(.*?)\};", js, re.S)
    assert block, "IMU_REASON_TEXT is no longer declared in carousel.js"
    vocabulary = dict(re.findall(r"(\w+):\s*\"([^\"]*)\"", block.group(1)))

    state = _liveState(tmp_path)
    code = state["reasons"]["altitude"]
    assert code in vocabulary, (
        f"the producer writes {code!r}, which carousel.js cannot spell: "
        f"{sorted(vocabulary)}"
    )

    tile = _tile(_run(state), "ALTITUDE")
    assert _detail(tile) == vocabulary[code]


def test_missingReasonsMap_stillReadsNaWithTheGenericUnavailable(tmp_path):
    """
    Given: a payload whose `reasons` map has been lost entirely
    When: the ALTITUDE tile paints
    Then: it reads NA with the generic "unavailable" -- and still no number

    The degradation is toward LESS information, never toward a fabricated one.
    A renderer that fell back to a value instead of a word would be the exact
    failure the typed null exists to prevent.
    """
    state = _liveState(tmp_path)
    state.pop("reasons")

    tile = _tile(_run(state), "ALTITUDE")

    assert _value(tile) == "NA"
    assert _detail(tile) == "unavailable"
    assert not re.search(r"\d", _detail(tile))


def test_unknownReasonCode_passesThroughRatherThanBeingSwallowed(tmp_path):
    """
    Given: a reason word the panel has not been taught (the shape a future
           barometer's own failure would arrive in)
    When: the tile paints
    Then: the raw code reaches the operator instead of a generic word

    A reason the card has not been taught is still information someone can act
    on. Pinned because the tempting "tidy" change is to map anything unknown to
    "unavailable", which would delete the only clue on the panel.
    """
    state = _liveState(tmp_path)
    state["reasons"]["altitude"] = "baro_i2c_nak"

    tile = _tile(_run(state), "ALTITUDE")

    assert _value(tile) == "NA"
    assert _detail(tile) == "baro_i2c_nak"


def test_twoAbsencesOnOneCard_reportDifferentReasonsSideBySide(tmp_path):
    """
    Given: a dead magnetometer beside the permanently-unsourced altitude
    When: both tiles paint
    Then: both read NA, and their DETAILS differ

    Two absences on one card that mean different things. If the panel collapsed
    them to a shared "unavailable" the operator would have no way to tell "this
    reading will come back" from "no such instrument is fitted" -- and only one
    of those ever resolves.

    THE PAIR THIS TEST ORIGINALLY USED WAS WRONG, and the correction is worth
    keeping: I first paired altitude with GRADE, expecting `pitch_unseeded`
    because no gyro sample is fed. It renders "+0.0 %" -- PitchFusion seeds off
    the ACCELEROMETER, so a level parked board has a genuinely known, genuinely
    flat attitude. The test name would have lied about a field that was working.
    """
    tiles = _tiles(_run(_producedImuState(tmp_path, [_accel((0.0, 0.0, G))])))

    assert _value(tiles["ALTITUDE"]) == "NA"
    assert _value(tiles["HEADING"]) == "NA"
    assert _detail(tiles["ALTITUDE"]) != _detail(tiles["HEADING"])
    # The control: a THIRD field on the same card is live, so "everything reads
    # NA" cannot satisfy this.
    assert _value(tiles["GRADE"]) == "+0.0 %"


# =============================================================================
# 4. THE ABSENCE IS PERMANENT AND MUST NEVER BLOCK THE INSTRUMENT.
# =============================================================================


def test_deadMagnetometer_altitudeUnchanged_andTheGMeterStaysLive(tmp_path):
    """
    Given: no magnetometer paired with the burst (a dead compass)
    When: the card paints
    Then: HEADING grays with its OWN reason, ALTITUDE is untouched, and the
          g-meter is still a live reading

    Failures are independent. A card where one absent field recruited the others
    would turn a dead compass into a dead instrument.
    """
    state = _producedImuState(tmp_path, [_accel((0.0, 0.0, G))])
    tiles = _tiles(_run(state))

    assert _value(tiles["HEADING"]) == "NA"
    assert _detail(tiles["HEADING"]) == "no compass reading"
    assert _value(tiles["ALTITUDE"]) == "NA"
    assert _detail(tiles["ALTITUDE"]) == "no source"
    assert re.search(r"\d", _value(tiles["G-FORCE"])), _value(tiles["G-FORCE"])


def test_permanentlyAbsentAltitude_neverBlocksTheLiveFace(tmp_path):
    """
    Given: the altitude absent on EVERY tick, which is its shipped state
    When: the panel runs on for several poll rounds
    Then: the Home card is still on the live face

    The tempting simplification is to drop a tile that is always NA. It stays --
    the locked layout reserves the space so a future source lands in its place,
    and a card that went idle over a field that is absent by design would be
    permanently idle.
    """
    tree = rh.runDashboard(
        routes={"/imu": _liveState(tmp_path)},
        steps=[{"flush": 12}],
        viewport=PANEL,
        nowMs=_NOW_MS,
    )["tree"]

    assert _homeCard(tree).get("attrs", {}).get("data-face") == "live"
    assert _value(_tile(tree, "ALTITUDE")) == "NA"


def test_altitudeStaysNaEvenWhenTheProducerIsToldToPublishOne(tmp_path):
    """
    Given: a payload carrying a REAL altitude number beside its no_source reason
           -- what a future producer that forgot to blank the field would write
    When: the tile paints
    Then: it STILL reads NA

    CHARACTERISATION of an override, not a wish. The renderer ignores the value
    outright because the tile is typed-NA unconditionally today (AC-2). Whoever
    lands US-519's integrator will fail this test ON PURPOSE -- and should
    RE-RECORD it against the new contract rather than relax it, because the day
    the renderer starts honouring a number is the day it needs a reason gate.
    """
    state = _liveState(tmp_path)
    state["altitude"] = 209.0

    tile = _tile(_run(state), "ALTITUDE")

    assert _value(tile) == "NA"
    assert not re.search(r"\d", _value(tile))


# =============================================================================
# 5. ONE ACQUISITION PATH (ssot-design-pattern rule B).
# =============================================================================


def test_thePanelAcquiresAltitudeExactlyOnce(tmp_path):
    """
    Given: the shipped carousel.js
    When: it is searched for altitude acquisitions
    Then: there is exactly ONE (`imuView`), consumed by exactly one painter

    A second acquisition is how this project got a latched magnetometer. It is
    also the obvious wrong fix here: reaching for another source to fill a tile
    that is honestly empty is precisely what the story forbids.
    """
    js = Path(_CAROUSEL_JS).read_text(encoding="utf-8")

    assert len(re.findall(r'imuReason\(\s*\w+\s*,\s*"altitude"\s*\)', js)) == 1
    assert len(re.findall(r"\bview\.altitude\b", js)) == 1


def test_theHomeElevationAnchorHasNoWireToStatesImu():
    """
    Given: the whole src/ tree
    When: the modules that write states/imu and the modules that read the
          altitude anchor are compared
    Then: they are disjoint sets

    Swept rather than grepped by hand, so it stays true. `AltitudeAnchor` lives
    in the orchestrator's sync path and holds a number the panel must not show;
    the day some tidy-up passes it to the bridge, this goes red.
    """
    writers = _srcFilesContaining("buildImuState(")
    anchorReaders = _srcFilesContaining("AltitudeAnchor") - {
        "src/pi/location/altitude_anchor.py"
    }

    assert writers, "nothing writes states/imu any more -- the sweep is inert"
    assert anchorReaders, "nothing reads the altitude anchor -- the sweep is inert"
    assert writers & anchorReaders == set(), writers & anchorReaders


def test_theOnlyStatesImuWriterIsTheBridge():
    """
    Given: the src/ sweep above
    When: the set of states/imu writers is named
    Then: it is exactly the IMU state bridge

    The story's SSOT clause. Naming the file rather than counting it means a
    second producer appearing under a different name cannot pass by keeping the
    count the same.
    """
    writers = _srcFilesContaining("buildImuState(")

    assert writers == {"src/pi/sensors/imu_state_bridge.py"}, sorted(writers)


def test_theTypedNullIsAssembledOnceInTheProducerToo(tmp_path):
    """
    Given: two DIFFERENT producer paths -- a live burst and an unplug
    When: both payloads are compared on the altitude field
    Then: both carry null + no_source

    The bridge has several write sites (the live cadence, the presence unplug,
    the channel gate). One of them forgetting the field is the producer-side
    version of the same defect, and only a payload from each path can see it.
    """
    live = _liveState(tmp_path)
    absent = _producedImuState(tmp_path, [_presence(False, seq=2)])

    for state in (live, absent):
        assert state["altitude"] is None
        assert state["reasons"]["altitude"] == REASON_NO_SOURCE
