################################################################################
# File Name: test_carousel_heading_bare_bearing_recorded_pass.py
# Purpose/Description: US-656 -- RECORD THE PASS for the states/imu HEADING
#   contract under the CIO's 2026-08-31 ruling: a real-but-UNCALIBRATED reading
#   is fit to display as a BARE NUMBER, with no qualifier. The panel must paint
#   the bearing plainly when one exists, and a TYPED ABSENCE WITH A REASON when
#   one does not -- never 0 degrees, never a held previous bearing.
#
#   THE FENCE, restated here because this file is where the ruling will be read
#   back from: the rule is UNCALIBRATED vs ABSENT. A reading that EXISTS may be
#   shown plainly; a reading that DOES NOT EXIST is still a typed absence with a
#   reason (ambientTempC / altitude remain the reference implementations). This
#   file asserts BOTH halves, because the ruling is only safe as a pair.
#
#   WHY THIS FILE EXISTS WHEN THE HEADING ALREADY HAD TESTS. It had tests for
#   everything EXCEPT the thing the story asks about, and that is measurable
#   rather than rhetorical -- before this commit:
#     * The rendered heading TEXT was asserted NOWHERE. `"magnetic"` appeared in
#       zero assertions in tests/, and the only `view["heading"]["value"]`
#       assertion in the repository is `== "NA"` (test_carousel_imu_card.py:258)
#       -- the ABSENT branch. The story's positive claim ("a bare bearing
#       renders") had no coverage of any kind.
#     * Every heading assertion is on the VIEW OBJECT over a HAND-WRITTEN dict
#       (`_imu(headingDeg=247.0, ...)` at test_carousel_imu_card.py:96,
#       test_carousel_live_home_card.py:101, test_carousel_imu_always_on.py:83).
#       A fixture written to agree with the renderer cannot witness the producer.
#     * `headingCardinal` is unit-tested as a PURE FUNCTION
#       (test_carousel_imu_card.py:383) and never through a painted tile.
#   Everything below runs REAL bus samples -> the REAL ImuStateBridge -> the
#   state file it actually writes -> the SHIPPED carousel.js over the SHIPPED
#   markup + stylesheet at 480x320.
#
#   "NEVER 0 DEGREES" IS ONLY TESTABLE BECAUSE 0 IS LEGAL. Unlike altitude, a
#   zeroed heading is INDISTINGUISHABLE FROM A REAL READING: due north IS 0. So
#   "absence must not render as 0" cannot be checked by banning the digit -- it
#   is checked by rendering a genuine north bearing beside a genuine absence and
#   proving the panel tells them apart, on the text AND on the level.
#
#   "NEVER A HELD BEARING" IS MEASURED, NOT ARGUED. A stale bearing is the
#   failure this channel actually had (the fabricated compass, US-565), so every
#   absence case below is reached by publishing a REAL 90 degree bearing FIRST
#   and then taking the magnetometer away three different ways -- gate refusal,
#   pairing-window lapse, unplug. The number exists in the producer and is then
#   shown to reach no pixel.
#
#   HARNESS FIDELITY LIMIT, stated so the tape assertions are not read as more
#   than they are: mini_dom.js implements `removeChild` but NOT `firstChild`, so
#   carousel.js:3748's `while (group.firstChild) group.removeChild(...)` clear is
#   a NO-OP under this harness and tape ticks ACCUMULATE across paints. Tape
#   claims here are therefore "ticks exist" / "no tick was ever drawn" only --
#   never a count, and never "the tape cleared". Filed as TD-089.
#
#   VERIFY OUTCOME: PASS. Findings are RECORDED, never fixed here (the story
#   forbids a verify story quietly becoming a fix story). See the module-level
#   note above test_gateRefusal_* for the one finding, filed as I-us656.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-656 recorded pass: the bare
#               |              | bearing end to end, real bridge to painted
#               |              | tile, with a real north bearing as the live
#               |              | counter-example to a zeroed absence.
# ================================================================================
################################################################################

"""US-656: HEADING renders as a bare bearing, uncalibrated -- record the pass."""

from __future__ import annotations

import json
import math
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
from pi.sensors.imu_state_bridge import (  # noqa: E402
    CHANNEL_STATE_ACCEL,
    IMU_STATE_FILENAME,
    REASON_NO_MAG,
    REASON_SENSOR_ABSENT,
    STANDARD_GRAVITY_MS2,
    STATE_IMU_PRESENCE,
    TOPIC_IMU_ACCEL,
    TOPIC_IMU_MAG,
    ImuStateBridge,
    channelStateTopic,
)
from pi.sensors.plausibility_gate import REASON_SENSOR_STALE  # noqa: E402

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

# A fixed instant + the canonical second-resolution ISO the producer stamps. The
# harness clock (US-641 `nowMs`) is pinned one second past it, so every payload
# below is unambiguously INSIDE carousel.js's 2 s IMU freshness window -- a
# heading that read NA because the whole CARD had gone stale would prove nothing
# about the heading field.
_T0_ISO = "2026-08-31T12:00:00Z"
_T0_MS = 1787227200000  # 2026-08-31T12:00:00Z in epoch ms
_NOW_MS = _T0_MS + 1000

# The gate-state topic the reader publishes when the magnetometer stops
# measuring. Derived from the raw topic by the producer's own helper, never
# spelled: a wrong topic string is IGNORED by `handleSample` and the previous
# payload simply stays on disk, so a test can read a LIVE file while believing
# it has taken the compass away (the US-642 authoring hazard, one channel over).
_MAG_GATE_TOPIC = channelStateTopic(TOPIC_IMU_MAG)

# Magnetometer vectors, in the device frame, chosen for the bearing the REAL
# producer derives from them against level gravity. These are not vehicle facts
# and nothing here validates the magnetics -- they are inputs picked so the
# arithmetic lands on a bearing worth asserting. Measured, not assumed:
#
#   vector              atan2 bearing   published   painted
#   (0, 20, -40)             90.0000       90.0      "90° E"
#   (40, 0, -20)              0.0000        0.0      "0° N"
#   (30, 17, -20)            29.5388       30.0      "30° NNE"
#   (-16, -38, 5)           247.1663      247.0      "247° WSW"
_MAG_EAST = (0.0, 20.0, -40.0)
_MAG_NORTH = (40.0, 0.0, -20.0)
_MAG_FRACTIONAL = (30.0, 17.0, -20.0)

_EAST_BEARING = 90
_NORTH_BEARING = 0

# The one uncalibrated-hedge vocabulary sweep. The CIO's ruling is a rule about
# what must NOT be on the tile, so it is asserted as a vocabulary rather than as
# an equality: an equality passes the day someone appends " (approx)" to a value
# nobody re-read the assertion for.
_HEDGE_WORDS = (
    "uncalibrated",
    "calibrat",
    "approx",
    "estimate",
    "unverified",
    "unreliable",
    "untrusted",
    "roughly",
    "nominal",
    "ballpark",
    "unsure",
    "maybe",
)
_HEDGE_MARKS = ("±", "+/-", "~")


# ------------------------------------------------------------------- producer


def _sample(topic: str, value: Any, unit: str, *, seq: int = 1, capture: float = 0.0):
    """One bus sample, stamped at the pinned instant."""
    return Sample(
        topic=topic,
        source="imu",
        value=value,
        unit=unit,
        tsUtc=_T0_ISO,
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _accel(*, seq: int = 1, capture: float = 0.0):
    """One raw.imu.accel burst sample: level board, gravity on +z (m/s^2)."""
    return _sample(TOPIC_IMU_ACCEL, (0.0, 0.0, G), "m/s^2", seq=seq, capture=capture)


def _mag(value: tuple[float, float, float], *, seq: int = 1, capture: float = 0.0):
    """One raw.imu.mag burst sample (uT, device frame)."""
    return _sample(TOPIC_IMU_MAG, value, "uT", seq=seq, capture=capture)


def _magGate(reason: str, *, seq: int = 2, capture: float = 0.02):
    """The retained gate STATE the reader publishes when the mag stops measuring.

    ``value`` 0 IS the refusal (``_handleChannelGate`` reads it as
    ``gated = not bool(value)``) and the reason travels in ``unit`` -- the
    producer's own encoding, mirrored rather than reinvented.
    """
    return _sample(_MAG_GATE_TOPIC, 0.0, reason, seq=seq, capture=capture)


def _accelGate(reason: str, *, seq: int = 2, capture: float = 0.02):
    """The same refusal, on the channel that IS the gravity reference."""
    return _sample(CHANNEL_STATE_ACCEL, 0.0, reason, seq=seq, capture=capture)


def _presence(present: bool, *, seq: int = 2, capture: float = 0.5):
    """The retained IMU presence STATE the reader publishes on an unplug."""
    return _sample(
        STATE_IMU_PRESENCE, 1.0 if present else 0.0, "bool", seq=seq, capture=capture
    )


def _producedImuState(tmpPath: Path, samples: list[Any]) -> dict[str, Any]:
    """Run the REAL bridge over ``samples`` and return the bytes it wrote."""
    bridge = ImuStateBridge(None, str(tmpPath))
    for sample in samples:
        bridge.handleSample(sample)
    return json.loads((tmpPath / IMU_STATE_FILENAME).read_text(encoding="utf-8"))


def _liveState(
    tmpPath: Path, mag: tuple[float, float, float] = _MAG_EAST
) -> dict[str, Any]:
    """A LIVE states/imu payload straight from the bridge, carrying a bearing."""
    return _producedImuState(tmpPath, [_mag(mag), _accel()])


def _afterALiveBearing(tmpPath: Path, *tail: Any) -> dict[str, Any]:
    """Publish a REAL 90 degree bearing, then apply ``tail``, then read the file.

    Every "never a held bearing" claim below goes through here. The point is that
    the number is not merely unavailable -- it was genuinely resolved by the
    producer moments earlier, so a renderer or a bridge that latched it would
    have something real to latch.
    """
    return _producedImuState(tmpPath, [_mag(_MAG_EAST), _accel(), *tail])


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


def _tapeLabels(tree: dict[str, Any]) -> list[str]:
    """The rose labels actually drawn on the compass tape.

    See the fidelity limit in the header: these ACCUMULATE across paints under
    this harness, so only their presence/absence and their SET are meaningful.
    """
    return [
        _text(node)
        for node in _walk(_homeCard(tree))
        if _classOf(node) == "imu-tape-label"
    ]


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
# 1. THE RECORDED PASS -- the real producer, through to a painted bare bearing.
# =============================================================================


def test_realBridge_resolvesABearingFromRealMagAndAccelSamples(tmp_path):
    """
    Given: the REAL ImuStateBridge draining a live mag + accel burst
    When: the state file it writes is read back off disk
    Then: `headingDeg` is a real number and carries NO absence reason

    The producer half of the SSOT, at the byte level the panel actually reads.
    The pure-function pin existed; the FILE did not.
    """
    state = _liveState(tmp_path)

    assert state["headingDeg"] == pytest.approx(float(_EAST_BEARING))
    assert state["available"] is True
    # A resolved field must not ALSO carry a reason: a value plus an excuse is
    # two producers disagreeing inside one payload.
    assert "headingDeg" not in state["reasons"]


def test_liveFaceActuallyPainted_control(tmp_path):
    """
    Given: that same live payload on the shipped panel
    When: the Home card is inspected
    Then: it is on the LIVE face and carries real readings beside the heading

    THE CONTROL FOR EVERY ABSENCE CLAIM BELOW. US-638 established the hazard by
    walking into it: a harness that throws renders an empty card body, and an
    empty body satisfies "no stale bearing is painted" while proving nothing.
    """
    tree = _run(_liveState(tmp_path))

    assert _homeCard(tree).get("attrs", {}).get("data-face") == "live"
    tiles = _tiles(tree)
    assert "HEADING" in tiles and "GRADE" in tiles and "G-FORCE" in tiles
    assert re.search(r"\d", _value(tiles["GRADE"])), _value(tiles["GRADE"])
    assert re.search(r"\d", _value(tiles["G-FORCE"])), _value(tiles["G-FORCE"])


def test_shippedPanel_headingTileReadsTheBareBearing(tmp_path):
    """
    Given: the producer's own payload served at /imu
    When: the shipped carousel paints the Home card at 480x320
    Then: the HEADING tile reads the bearing plainly -- "90° E"

    THE STORY'S END STATE, and the assertion that did not exist anywhere in the
    repository before this file: no test had ever read the heading's rendered
    text on any surface.
    """
    tile = _tile(_run(_liveState(tmp_path)), "HEADING")

    assert _value(tile) == f"{_EAST_BEARING}° E"


def test_headingTile_carriesNoUncertaintyQualifier(tmp_path):
    """
    Given: the painted HEADING tile, whole tile text
    When: it is swept for uncalibrated-hedge vocabulary
    Then: there is none

    THE CIO'S RULING, as the rule it actually is. TD-087 is open and the bearing
    IS uncalibrated -- the ruling is that the panel does not say so, because at
    480x320 a qualifier on every uncertain field is clutter and precision
    happens server-side. Swept as a vocabulary rather than pinned as an equality
    so that appending " (approx)" to the value fails here too.
    """
    text = _text(_tile(_run(_liveState(tmp_path)), "HEADING")).lower()

    for word in _HEDGE_WORDS:
        assert word not in text, f"{word!r} qualifies the bearing: {text!r}"
    for mark in _HEDGE_MARKS:
        assert mark not in text, f"{mark!r} qualifies the bearing: {text!r}"


def test_headingTile_detailNamesTheReferenceFrame_notAConfidence(tmp_path):
    """
    Given: the painted HEADING tile
    When: its detail line is read
    Then: it is exactly "magnetic"

    RECORDED, because it is the one line on this tile a reader could mistake for
    the qualifier the ruling forbids, and it is not one. "magnetic" says WHAT is
    measured -- a bearing against magnetic north rather than true north, with no
    declination in the contract -- which is a fact about the quantity, the same
    class of statement as a unit. A hedge says how well it was measured. The
    sweep above bans the second; this pins the first so that deleting it is a
    deliberate act rather than a tidy-up.
    """
    assert _detail(_tile(_run(_liveState(tmp_path)), "HEADING")) == "magnetic"


def test_headingTile_isWholeDegrees_neverATenth(tmp_path):
    """
    Given: a magnetometer vector whose true bearing is 29.5388 degrees
    When: the producer publishes and the tile paints
    Then: both read a WHOLE degree -- 30, with no decimal point anywhere

    ARCH-012, held at both ends. The sensor's own standing-still scatter is
    ~11.8 degrees (specs/grounded-knowledge.md, 10 samples on the live Pi), so a
    tenth of a degree resolved the bearing ~118x finer than the instrument
    moves. That is a claim the measurement does not make -- and it is exactly the
    kind of false precision the bare-number ruling must not be read as licensing.
    """
    state = _liveState(tmp_path, _MAG_FRACTIONAL)
    rawBearing = math.degrees(math.atan2(_MAG_FRACTIONAL[1], _MAG_FRACTIONAL[0]))

    # The control: the underlying arithmetic really is fractional, so "no decimal
    # point" is a rounding claim rather than an accident of the chosen vector.
    assert rawBearing != pytest.approx(round(rawBearing))
    assert state["headingDeg"] == pytest.approx(30.0)

    value = _value(_tile(_run(state), "HEADING"))
    assert value == "30° NNE"
    assert "." not in value


def test_headingTile_presentsAsAReading_notAsAnAbsence(tmp_path):
    """
    Given: the painted HEADING tile beside the typed-NA ALTITUDE tile
    When: their [data-level]s are compared
    Then: the heading is `neutral` and the altitude is `unavailable`

    The ruling's other half at the level of the stylesheet: an uncalibrated but
    REAL reading must not be dressed in the absence presentation. Asserted
    against a tile that IS absent on the same card, so "neutral" is shown to be
    a distinction the panel actually draws rather than a string this test read.
    """
    tiles = _tiles(_run(_liveState(tmp_path)))

    assert _level(tiles["HEADING"]) == "neutral"
    assert _level(tiles["ALTITUDE"]) == "unavailable"


def test_headingTile_isPaintedInTheLiveHeadingBox_notMerelyComputed(tmp_path):
    """
    Given: the CIO-locked live-face layout (tape + heading down the left)
    When: the rendered tree is walked
    Then: the HEADING tile is inside `.live-heading-tile`, under `.live-heading`

    Placement, witnessed. The alternative -- grepping carousel.js for
    `appendTile(headBox, view.heading)` -- matches the source text whether or not
    the call ever runs.
    """
    tree = _run(_liveState(tmp_path))
    column = None
    for node in _walk(_homeCard(tree)):
        if "live-heading" in _classOf(node).split():
            column = node
            break
    assert column is not None, "the live heading column was never built"

    box = None
    for node in _walk(column):
        if "live-heading-tile" in _classOf(node).split():
            box = node
            break
    assert box is not None, "the heading tile box was never built"

    labels = [
        _childText(t, "tile-label") for t in _walk(box) if _classOf(t) == "tile"
    ]
    assert labels == ["HEADING"], labels


def test_compassTape_isDrawnAroundTheSameBearingTheTilePrints(tmp_path):
    """
    Given: a live bearing of 90 degrees and a 90-degree tape span
    When: the tape's rose labels are read off the panel
    Then: they bracket east -- {NE, E, SE} and nothing else

    The tape is the heading's SECOND surface and it is fed from the resolved
    `view.heading.deg`, not from a second derivation. Two heading instruments on
    one card that could disagree is the defect US-508 deliberately avoided; this
    is the assertion that they still cannot.
    """
    labels = _tapeLabels(_run(_liveState(tmp_path)))

    assert labels, "no rose label was drawn on the compass tape"
    assert set(labels) == {"NE", "E", "SE"}, sorted(set(labels))


# =============================================================================
# 2. THE FENCE -- an ABSENT bearing is still a typed absence with a reason.
# =============================================================================


def test_deadMagnetometer_producerWritesTypedNullWithItsReason(tmp_path):
    """
    Given: an accel burst with no magnetometer reading paired to it
    When: the state file is read back
    Then: `headingDeg` is JSON null and `reasons.headingDeg` is "no_mag_reading"

    The fence's producer end. Typed NULL, not an omitted key and not a sentinel:
    a missing field and a refused one are different facts, and only one of them
    can carry a reason.
    """
    state = _producedImuState(tmp_path, [_accel()])

    assert state["headingDeg"] is None
    assert "headingDeg" in state
    assert state["reasons"]["headingDeg"] == REASON_NO_MAG


def test_deadMagnetometer_headingTileReadsNaWithThatReason(tmp_path):
    """
    Given: that payload on the shipped panel
    When: the HEADING tile paints
    Then: it reads NA, its detail carries the reason, and it looks unavailable

    The story's negative case as the operator meets it. All three are asserted
    because any one alone can be right while the tile still reads as a settled
    value -- the word NA in the confident costume is punch-list 2.1's defect.
    """
    tile = _tile(_run(_producedImuState(tmp_path, [_accel()])), "HEADING")

    assert _value(tile) == "NA"
    assert _detail(tile) == "no compass reading"
    assert _level(tile) == "unavailable"


def test_absentHeading_carriesNoDigitAnywhereOnTheTile(tmp_path):
    """
    Given: the NA heading tile
    When: its value AND its detail are searched for a digit
    Then: there is none

    Necessary but NOT sufficient on this channel, which is why the next test
    exists: a heading of 0 is a real bearing, so banning the digit cannot by
    itself distinguish an absence from due north.
    """
    tile = _tile(_run(_producedImuState(tmp_path, [_accel()])), "HEADING")

    assert not re.search(r"\d", _value(tile)), _value(tile)
    assert not re.search(r"\d", _detail(tile)), _detail(tile)


def test_absenceAndDueNorth_areDifferentOnThePanel(tmp_path):
    """
    Given: a REAL north-pointing magnetometer, and separately a dead one
    When: both are painted
    Then: north reads "0° N" as a live neutral reading, absence reads NA as
          unavailable -- and the two agree on nothing

    THE STORY'S "NEVER 0 DEGREES", AND THE ONLY HONEST WAY TO CHECK IT. Altitude
    can ban the zero outright; a heading cannot, because 0 is due north and
    suppressing it would re-create the US-565 failure in reverse -- hiding a real
    measurement. So the claim is not "0 never appears", it is "0 means north and
    absence means absence, and the panel never lets one wear the other's face".
    """
    north = _tile(_run(_liveState(tmp_path, _MAG_NORTH)), "HEADING")
    absent = _tile(_run(_producedImuState(tmp_path, [_accel()])), "HEADING")

    assert _value(north) == f"{_NORTH_BEARING}° N"
    assert _level(north) == "neutral"

    assert _value(absent) == "NA"
    assert _level(absent) == "unavailable"
    assert _value(absent) != _value(north)
    assert _detail(absent) != _detail(north)


def test_absentHeading_drawsNoCompassTapeAtAll(tmp_path):
    """
    Given: a dead magnetometer
    When: the live face paints
    Then: not one rose label is drawn on the tape

    The heading's second surface must go absent WITH it. A tape left under the
    caret reads as a confident bearing in exactly the way the frozen needle did
    -- the same fabrication in different geometry (US-497's rule, US-508's
    instrument). Asserted as "no tick was EVER drawn" rather than "the tape
    cleared", per the harness limit in the header.
    """
    assert _tapeLabels(_run(_producedImuState(tmp_path, [_accel()]))) == []


def test_deadMagnetometer_doesNotRecruitTheRestOfTheCard(tmp_path):
    """
    Given: the same dead magnetometer
    When: the neighbouring tiles are read
    Then: GRADE and G-FORCE are still live readings

    Failures are independent. A card where one absent field took the others with
    it would turn a dead compass into a dead instrument -- and would also make
    every absence assertion above vacuous.
    """
    tiles = _tiles(_run(_producedImuState(tmp_path, [_accel()])))

    assert _value(tiles["HEADING"]) == "NA"
    assert re.search(r"\d", _value(tiles["GRADE"])), _value(tiles["GRADE"])
    assert re.search(r"\d", _value(tiles["G-FORCE"])), _value(tiles["G-FORCE"])


# =============================================================================
# 3. NEVER A HELD BEARING -- reached from a REAL 90 degrees, three ways.
#
# THE FINDING, recorded not fixed (I-us656): the gate's own refusal vocabulary
# -- `sensor_stale` / `sensor_mute` from plausibility_gate.py -- has NO entry in
# carousel.js's IMU_REASON_TEXT, so the tile paints the raw snake_case code at
# the operator. The pass-through is deliberate for reasons the card has not been
# taught, but these two are KNOWN producer words, not future unknowns. It
# UNDER-informs rather than claiming anything false, so it does not breach this
# story's end state, and the story forbids fixing it here. Characterised below.
# =============================================================================


def test_gateRefusal_dropsTheHeldBearingAndCarriesTheGatesOwnReason(tmp_path):
    """
    Given: a REAL 90 degree bearing published, then the magnetometer gate
           refusing the channel as `sensor_stale`
    When: the next accel frame writes and the panel paints
    Then: the heading is null with the GATE's reason, and no digit of 90 is
          anywhere on the card

    THE FABRICATED COMPASS, PREVENTED, on the exact failure this channel had: a
    chip answering with a vector it has not measured since boot. The bearing
    genuinely existed one frame earlier, so a bridge that kept the pairing window
    open across the refusal would have had a real 90 to print -- and it prints
    nothing instead.
    """
    state = _afterALiveBearing(
        tmp_path, _magGate(REASON_SENSOR_STALE), _accel(seq=3, capture=0.2)
    )

    assert state["headingDeg"] is None
    assert state["reasons"]["headingDeg"] == REASON_SENSOR_STALE

    tree = _run(state)
    assert _value(_tile(tree, "HEADING")) == "NA"
    assert "90" not in _text(_homeCard(tree))
    assert _tapeLabels(tree) == []


def test_gateRefusal_paintsTheRawCodeBecauseTheCardCannotSpellIt(tmp_path):
    """
    Given: the gate's `sensor_stale` refusal on the heading
    When: the tile's detail is read
    Then: it is the raw code, NOT operator-facing words

    CHARACTERISATION OF THE FINDING ABOVE, not an endorsement. Pinned so that
    whoever teaches IMU_REASON_TEXT the gate vocabulary fails this test ON
    PURPOSE and re-records it against the new wording, rather than the finding
    quietly evaporating. The value half is asserted alongside because THAT half
    must not change: an unspellable reason still renders a typed absence.
    """
    state = _afterALiveBearing(
        tmp_path, _magGate(REASON_SENSOR_STALE), _accel(seq=3, capture=0.2)
    )
    tile = _tile(_run(state), "HEADING")

    assert _value(tile) == "NA"
    assert _detail(tile) == REASON_SENSOR_STALE
    assert _detail(tile) == "sensor_stale"


def test_aRefusedCompass_doesNotBlankTheWholeInstrument(tmp_path):
    """
    Given: a live payload on disk, then the magnetometer gate refusing
    When: the state file is read RIGHT THEN, before the next accel frame
    Then: the instrument is still `available` -- the refusal wrote no
          blanket-unavailable payload

    THE ASYMMETRY IN `_CHANNEL_DERIVED_FIELDS`, PINNED FROM THE OTHER SIDE. Accel
    is deliberately absent from that map because it is not the input to SOME
    fields, it is the gravity reference under ALL of them, so its refusal blanks
    the instrument. The converse is the rule this asserts: a mag refusal must
    take the heading and NOTHING ELSE. A gate handler that fell through to the
    accel path would kill the g-meter over a dead compass.

    Stated because this test reads a transient and the transient is the point:
    the heading on disk here is still the LAST LIVE ONE. The mag branch does not
    write; the correction lands on the next accel frame, which is <=100 ms away
    at the 10 Hz display cadence and therefore well inside carousel.js's 2 s
    freshness window. That bounded lag is why this test asserts `available`
    rather than the heading -- and the two tests either side of it are what
    prove the correction actually arrives.
    """
    state = _afterALiveBearing(tmp_path, _magGate(REASON_SENSOR_STALE))

    assert state["available"] is True
    assert state["gMag"] is not None
    assert state["gradePct"] is not None


def test_aRefusedAccelerometer_doesBlankTheWholeInstrument(tmp_path):
    """
    Given: the same live payload, then the ACCELEROMETER gate refusing
    When: the state file is read
    Then: the instrument reports unavailable immediately, heading included

    The other half of the asymmetry, and the control that stops the test above
    from passing on a bridge that simply ignores gate refusals. This write
    bypasses the display cadence for the same reason an unplug does: the
    alternative is the last live reading sitting on the card looking current
    while nothing behind it is reading.
    """
    state = _afterALiveBearing(tmp_path, _accelGate(REASON_SENSOR_STALE))

    assert state["available"] is False
    assert state["headingDeg"] is None
    assert state["gMag"] is None
    assert state["reasons"]["headingDeg"] == REASON_SENSOR_STALE


def test_pairingWindowLapse_dropsTheHeldBearingRatherThanReusingIt(tmp_path):
    """
    Given: a REAL 90 degree bearing, then an accel frame far outside the
           magnetometer pairing window with no fresh mag beside it
    When: the state file is written
    Then: the heading is null with "no_mag_reading" and 90 reaches no pixel

    The quieter of the two stale paths, and the one with no gate to announce it:
    the compass simply stopped answering. `MAG_MAX_AGE_POLLS` is what decides
    this, and the failure it prevents is a bearing that stays on the card looking
    current while nothing behind it is reading.
    """
    state = _afterALiveBearing(tmp_path, _accel(seq=9, capture=0.2))

    assert state["headingDeg"] is None
    assert state["reasons"]["headingDeg"] == REASON_NO_MAG

    tree = _run(state)
    assert _value(_tile(tree, "HEADING")) == "NA"
    assert "90" not in _text(_homeCard(tree))


def test_unplug_takesTheBearingWithTheWholeInstrument(tmp_path):
    """
    Given: a REAL 90 degree bearing, then the reader reporting the IMU absent
    When: the bridge writes the unavailable payload and the panel paints
    Then: the heading is null with `sensor_absent`, the card leaves the live
          face, and 90 is nowhere on it

    The third path, and the one that removes the tile rather than emptying it.
    That is honest -- the tile is gone with the face it lived on. What must not
    happen, and does not, is a fallback face that fills the gap with the last
    bearing anyone saw.
    """
    state = _afterALiveBearing(tmp_path, _presence(False))

    assert state["available"] is False
    assert state["headingDeg"] is None
    assert state["reasons"]["headingDeg"] == REASON_SENSOR_ABSENT

    tree = _run(state)
    assert _homeCard(tree).get("attrs", {}).get("data-face") != "live"
    assert "HEADING" not in _tiles(tree)
    assert "90" not in _text(_homeCard(tree))


def test_absentStateFile_paintsNoBearingEither(tmp_path):
    """
    Given: no states/imu file at all -- the shipped Pi today, where
           pi.sensors.imu.enabled defaults false
    When: the Home card paints
    Then: it falls off the live face and no heading tile exists

    The absence case at the OTHER end of the chain, where there is no producer at
    all to have a reason. The shell owns this message, so one place decides
    absence rather than each tile inventing its own.
    """
    tree = _run(None)

    assert _homeCard(tree).get("attrs", {}).get("data-face") != "live"
    assert "HEADING" not in _tiles(tree)
    assert _tapeLabels(tree) == []


# =============================================================================
# 4. THE REASON IS CARRIED ACROSS THE SEAM -- NA alone is a shrug.
# =============================================================================


def test_producersReasonWord_isOneTheShippedRendererCanActuallySpell(tmp_path):
    """
    Given: the reason word the REAL producer wrote for a dead magnetometer
    When: it is looked up in the vocabulary read OUT OF the shipped carousel.js
    Then: it is present, and its rendered text is what the panel painted

    THE JOIN, stated as a join. Both sides can be internally consistent and still
    disagree: rename the producer's constant and the tile silently starts
    printing the raw code. The vocabulary is PARSED from the shipped file rather
    than hardcoded here, so this cannot pass by remembering what the map said.
    """
    js = Path(_CAROUSEL_JS).read_text(encoding="utf-8")
    block = re.search(r"var IMU_REASON_TEXT = \{(.*?)\};", js, re.S)
    assert block, "IMU_REASON_TEXT is no longer declared in carousel.js"
    vocabulary = dict(re.findall(r"(\w+):\s*\"([^\"]*)\"", block.group(1)))

    state = _producedImuState(tmp_path, [_accel()])
    code = state["reasons"]["headingDeg"]
    assert code in vocabulary, (
        f"the producer writes {code!r}, which carousel.js cannot spell: "
        f"{sorted(vocabulary)}"
    )

    assert _detail(_tile(_run(state), "HEADING")) == vocabulary[code]


def test_missingReasonsMap_stillReadsNaWithTheGenericUnavailable(tmp_path):
    """
    Given: a payload whose `reasons` map has been lost entirely
    When: the HEADING tile paints
    Then: it reads NA with the generic "unavailable" -- and still no number

    The degradation is toward LESS information, never toward a fabricated one. A
    renderer that fell back to a value instead of a word would be the exact
    failure the typed null exists to prevent.
    """
    state = _producedImuState(tmp_path, [_accel()])
    state.pop("reasons")

    tile = _tile(_run(state), "HEADING")

    assert _value(tile) == "NA"
    assert _detail(tile) == "unavailable"
    assert not re.search(r"\d", _detail(tile))


def test_aCalibrationReasonWouldPassThroughRatherThanBeSwallowed(tmp_path):
    """
    Given: a reason word the panel has not been taught -- the shape TD-087's own
           fix would arrive in, once a calibration routine can say "not yet"
    When: the tile paints
    Then: the raw code reaches the operator instead of a generic word

    TD-087 stays OPEN and this story does not close it. This is the seam that
    fix will land on: the day the bearing can be REFUSED for being uncalibrated
    (as opposed to shown plainly, which is today's ruling), the reason travels on
    this path. Pinned because the tempting tidy-up -- mapping anything unknown to
    "unavailable" -- would delete the only clue on the panel.
    """
    state = _producedImuState(tmp_path, [_accel()])
    state["reasons"]["headingDeg"] = "mag_calibrating"

    tile = _tile(_run(state), "HEADING")

    assert _value(tile) == "NA"
    assert _detail(tile) == "mag_calibrating"


def test_aBearingBesideItsOwnReason_stillReadsAsAnAbsence(tmp_path):
    """
    Given: a payload carrying a REAL bearing AND an absence reason for it -- what
           a producer that forgot to blank the field on refusal would write
    When: the tile paints
    Then: it reads the bearing, and the stray reason changes nothing

    CHARACTERISATION of the renderer's precedence, not a wish: `imuHeadingTile`
    branches on the VALUE and consults the reason only when there is no number.
    Recorded because it names where the trust boundary is -- the producer is the
    only thing that can refuse a heading, so a producer that publishes a number
    it has just disowned is a PRODUCER defect and will not be caught downstream.
    """
    state = _liveState(tmp_path)
    state["reasons"]["headingDeg"] = REASON_SENSOR_STALE

    tile = _tile(_run(state), "HEADING")

    assert _value(tile) == f"{_EAST_BEARING}° E"
    assert _level(tile) == "neutral"


# =============================================================================
# 5. ONE ACQUISITION PATH (ssot-design-pattern rule B).
# =============================================================================


def test_thePanelAcquiresTheHeadingExactlyOnce(tmp_path):
    """
    Given: the shipped carousel.js
    When: it is searched for heading acquisitions
    Then: `data.headingDeg` is read once, its reason is looked up once, and both
          consumers -- the tile and the tape -- read the RESOLVED `view.heading`

    Two acquisitions is how this project got a latched magnetometer. The
    asymmetry is the contract: ONE resolution, MANY consumers. The counts are
    deliberately split -- the ACQUISITIONS are pinned at exactly one each, while
    the consumers are named rather than counted, because a third consumer of the
    resolved value is fine and a second reader of `data.headingDeg` is not.
    """
    js = Path(_CAROUSEL_JS).read_text(encoding="utf-8")

    assert len(re.findall(r"\bdata\.headingDeg\b", js)) == 1
    assert len(re.findall(r'imuReason\(\s*\w+\s*,\s*"headingDeg"\s*\)', js)) == 1

    # The tape derives its geometry from the tile's OWN resolved bearing, which
    # is what makes it impossible for the two surfaces to disagree.
    assert re.search(
        r"compassTape\(\s*view\.heading\.available \? view\.heading\.deg : null", js
    ), "the compass tape no longer reads the resolved heading"
    assert re.search(r"appendTile\(\s*headBox,\s*view\.heading\s*\)", js), (
        "the heading tile is no longer appended from the resolved view"
    )


def test_theOnlyStatesImuWriterIsTheBridge():
    """
    Given: the whole src/ tree, swept
    When: the set of states/imu writers is named
    Then: it is exactly the IMU state bridge

    The story's SSOT clause. Naming the file rather than counting it means a
    second producer appearing under a different name cannot pass by keeping the
    count the same.
    """
    writers = _srcFilesContaining("buildImuState(")

    assert writers == {"src/pi/sensors/imu_state_bridge.py"}, sorted(writers)


def test_theBearingIsDerivedInExactlyOnePlace():
    """
    Given: the src/ sweep
    When: the modules computing a magnetic bearing are named
    Then: only the bridge does it, and only it publishes the result

    `computeHeadingDeg` is the single derivation. A second one -- a "quick"
    atan2 next to a consumer that already had the vectors -- is the same class of
    defect as a second acquisition, and it would be invisible until the two
    disagreed on a drive nobody was watching.
    """
    derivers = _srcFilesContaining("computeHeadingDeg(")

    assert derivers == {"src/pi/sensors/imu_state_bridge.py"}, sorted(derivers)
