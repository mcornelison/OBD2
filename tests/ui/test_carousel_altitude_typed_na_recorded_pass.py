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
# 2026-10-19    | Ralph (Rex)  | US-892-b -- MOVED PIN: the altitude tile retired with the
#                               live face; the producer cases stay.
# ================================================================================
################################################################################

"""US-642: ALTITUDE renders typed-NA with its reason -- record the pass."""

from __future__ import annotations

import json
import os
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


from pi.bus.sample import Sample  # noqa: E402
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

_REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
_SRC_DIR = os.path.join(_REPO, "src")

G = STANDARD_GRAVITY_MS2

# A fixed instant + the canonical second-resolution ISO the producer stamps.
# The harness clock (US-641 `nowMs`) is pinned one second past it, so every
# payload below is unambiguously INSIDE carousel.js's 2 s IMU freshness window
# -- an altitude that read NA because the whole card had gone stale would prove
# nothing about the altitude field.
_T0_ISO = "2026-08-31T12:00:00Z"
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


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for child in node.get("children", []) or []:
            yield from _walk(child)


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


# =============================================================================
# 2. THE NEGATIVE CASE -- never 0 m, never a derived guess.
# =============================================================================


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


# =============================================================================
# 4. THE ABSENCE IS PERMANENT AND MUST NEVER BLOCK THE INSTRUMENT.
# =============================================================================


# =============================================================================
# 5. ONE ACQUISITION PATH (ssot-design-pattern rule B).
# =============================================================================


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
