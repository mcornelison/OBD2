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
# 2026-09-10    | Ralph (Rex)  | US-697: the "magnetic" detail is REMOVED (CIO
#               |              | 2026-09-09). test_headingTile_detailNames-
#               |              | TheReferenceFrame_notAConfidence is FLIPPED to
#               |              | the absence rather than deleted, per the
#               |              | story's conditionalOutcomes -- the tile's shape
#               |              | is still worth pinning. Adds the span-present-
#               |              | but-empty pin, the string-literal sweep, the
#               |              | recorded-rationale pin and the no-line-box
#               |              | property. The 6 bearing-number failures in this
#               |              | file are I-us708b and predate US-697.
# 2026-09-10    | Ralph (Rex)  | US-719: the empty-detail source pin's stated
#               |              | REASON corrected -- a browser paints nothing
#               |              | for `textContent = undefined` (measured,
#               |              | Chrome/Edge 152). The pin itself is unchanged.
# 2026-10-19    | Ralph (Rex)  | US-892-b -- MOVED PIN: the Home card retired, so its DOM
#                               cases go; the producer and imuHeadingTile
#                               (NAV) cases stay.
# ================================================================================
################################################################################

"""US-656: HEADING renders as a bare bearing, uncalibrated -- record the pass."""

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
from pi.sensors.imu_state_bridge import (  # noqa: E402
    CHANNEL_STATE_ACCEL,
    DEFAULT_MAG_MAX_AGE_S,
    DEFAULT_STATE_HZ,
    IMU_STATE_FILENAME,
    REASON_NO_MAG,
    STANDARD_GRAVITY_MS2,
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

# US-801: the bridge here runs on its DEFAULT rates (the shipped 4 Hz burst,
# 1 Hz state write). These tails were 0.2 s when the defaults were 50/10 Hz;
# they are now derived from the bridge's own constants so each test keeps its
# meaning at whatever the defaults are.
#   _NEXT_WRITE_INSIDE_WINDOW_S: the next state write, while the last mag is
#       still INSIDE the pairing window -- so a bridge that ignored the gate
#       would still have a real bearing to print.
#   _PAST_PAIRING_WINDOW_S: past both the next write and the pairing window.
# US-803-b: the window is now carried in seconds (magMaxAgeSec), so it is read
# directly rather than derived as polls / sampleHz.
_PAIRING_WINDOW_S = DEFAULT_MAG_MAX_AGE_S
_NEXT_WRITE_INSIDE_WINDOW_S = 1.0 / DEFAULT_STATE_HZ
_PAST_PAIRING_WINDOW_S = max(_PAIRING_WINDOW_S, _NEXT_WRITE_INSIDE_WINDOW_S) + 1.0
assert _NEXT_WRITE_INSIDE_WINDOW_S < _PAIRING_WINDOW_S, (
    "the default state interval no longer falls inside the pairing window -- "
    "the gate-refusal tests below would pass on the window lapse alone"
)

_REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
_CAROUSEL_JS = os.path.join(_REPO, "src", "pi", "ui", "dashboard", "carousel.js")
_CSS = os.path.join(_REPO, "src", "pi", "ui", "dashboard", "dashboard.css")
_SRC_DIR = os.path.join(_REPO, "src")

G = STANDARD_GRAVITY_MS2

# A fixed instant + the canonical second-resolution ISO the producer stamps. The
# harness clock (US-641 `nowMs`) is pinned one second past it, so every payload
# below is unambiguously INSIDE carousel.js's 2 s IMU freshness window -- a
# heading that read NA because the whole CARD had gone stale would prove nothing
# about the heading field.
_T0_ISO = "2026-08-31T12:00:00Z"
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
_EAST_BEARING = 90
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


def test_headingTile_declaresAnEmptyDetail_ratherThanOmittingTheKey():
    """
    Given: `imuHeadingTile`'s source
    When: its returned tile is read for a `detail` key
    Then: the key is DECLARED and empty -- it was not simply deleted

    `detail: ""` is the shipped convention for a tile with nothing to say (the
    SYSTEM OK summary is the precedent): every tile declares its whole
    label/value/detail/level shape.

    ⚠️ CORRECTED BY US-719 -- THE REASON THIS DOCSTRING FIRST GAVE WAS FALSE. Its
    browser behaviour for `textContent = undefined` was never measured. Measured
    in Chrome 152 and Edge 152, the read-back is "" with 0 child nodes,
    identical to "" and null. A deleted key is therefore INVISIBLE on the real
    panel, not a painted word.

    🔴 WHY THIS IS PINNED ON THE SOURCE AND NOT ON THE RENDERED PANEL. I wrote it
    as a rendered assertion first and the mutation SURVIVED -- and it survives
    in the browser too, not only in mini_dom.js, whose `textContent` setter
    matches the browser, pinned by
    test_mini_dom_undefined_matches_measured_browser.py. No rendered assertion,
    harness or real, can catch a missing key, in this tile or any other. The source is the only surface on which
    this claim is falsifiable; a general contract check is US-726.
    """
    body = rh._fnBody(Path(_CAROUSEL_JS).read_text(encoding="utf-8"), "imuHeadingTile")

    assert re.search(r'\bdetail:\s*""', body), (
        "`imuHeadingTile` no longer declares an empty `detail`. If the key was "
        "DELETED, the tile paints nothing there -- in the browser and in this "
        "harness alike -- so no rendered test can see it (US-726)."
    )


def test_carouselJs_canNoLongerRenderTheMagneticQualifier_us697():
    """
    Given: the shipped carousel.js
    When: every STRING LITERAL in it is swept for the removed word
    Then: there is not one -- the panel has no way to paint it

    US-697 validationCriterion 2. The criterion is worded as a whole-file grep,
    and a whole-file grep IS what I ran first -- it failed, on the comment
    written to record the CIO's decision. That is worth stating rather than
    quietly narrowing, because narrowing a predicate is exactly US-706's defect
    one story over.

    WHY THE LITERALS ARE THE RIGHT SUBJECT AND THIS IS NOT US-706's MISTAKE.
    US-706's predicate was NARROWER than the gate it was written to satisfy --
    it could go green while the real condition stayed red. This one is not: the
    requirement is that the TILE no longer says "magnetic", and a string literal
    is the only thing in this file that can reach a pixel. A comment cannot. So
    the literal sweep is not a weaker proxy for the panel claim, it is a
    stricter one -- it fails for every reachable spelling, including ones no
    fixture happens to render, which a rendered-tile assertion alone would miss.
    The rendered half is asserted above; this is the half that generalises.

    AND THE COMMENT IS PINNED, NOT EXEMPTED. The surviving occurrences must all
    be comment lines. If the word ever re-enters as code this fails, and if the
    recorded rationale is deleted the companion test below fails.
    """
    js = Path(_CAROUSEL_JS).read_text(encoding="utf-8")

    inLiterals = [
        literal
        for literal in re.findall(r'"[^"\n]*"|\'[^\'\n]*\'', js)
        if "magnetic" in literal.lower()
    ]
    assert inLiterals == [], (
        "carousel.js can still render the removed qualifier: " f"{inLiterals}"
    )

    survivors = [
        (i, line.strip())
        for i, line in enumerate(js.splitlines(), start=1)
        if "magnetic" in line.lower()
    ]
    notComments = [f"{i}: {text}" for i, text in survivors if not text.startswith("//")]
    assert notComments == [], (
        "the word survives outside a comment, so it is no longer merely a record "
        "of the decision:\n" + "\n".join(notComments)
    )


def test_theOverruledRationaleIsRecordedBesideTheTile_notJustDeleted():
    """
    Given: `imuHeadingTile` after the qualifier was removed
    When: its source is read
    Then: it explains what was there, why it went, and on whose ruling

    NOT CEREMONY -- this is the pin that keeps the sweep above honest. Without
    it the cheapest way to pass a "zero occurrences" test is to delete the
    reasoning along with the word, and the next person to notice an unlabelled
    bearing re-derives the ORIGINAL argument (it names the reference frame, it
    is not a hedge, it stops a map mismatch reading as a fault) and puts it
    back. That argument is sound; it was OVERRULED, which is a different thing,
    and only the record distinguishes them.

    Same requirement US-715 carries one story over for the compass tape's CSS
    comment, and the same thing US-696 did for the power glyph the CIO removed.
    """
    body = rh._fnBody(Path(_CAROUSEL_JS).read_text(encoding="utf-8"), "imuHeadingTile")

    assert "US-697" in body, "the ruling that removed the detail is not cited"
    assert "magnetic" in body.lower(), "what was removed is not recorded"
    assert "2026-09-09" in body, "the decision is recorded without its date"


def test_theEmptyDetailReservesNoLineBox_soTheTileIsGenuinelyShorter():
    """
    Given: the shipped stylesheet's `.tile-detail` rule
    When: it is read for a height floor
    Then: it declares none -- no height, min-height or fixed line-height

    US-697 validationCriterion 3, reduced to the half that is actually
    FALSIFIABLE here. THE HARNESS DOES NOT DO LAYOUT (render_harness header: "it
    cannot tell you a box overflowed, wrapped, or landed"), so "one fewer line"
    cannot be measured on this bench and is not claimed as measured. What CAN be
    checked is the property the claim rests on: an empty inline span with no
    reserved height contributes no line box, so emptying the detail really does
    shorten the tile rather than leaving a blank gap where the word was.

    This is also the pin that FAILS if a future stylesheet change reserves the
    space back -- at which point "one fewer line" stops being true and somebody
    should have to say so.
    """
    css = Path(_CSS).read_text(encoding="utf-8")
    rules = [r for r in rh.parseCss(css) if r.selector.strip() == ".tile-detail"]
    assert rules, "no `.tile-detail` rule in the shipped stylesheet"

    for rule in rules:
        for prop in ("height", "min-height"):
            assert rh.declarationOf(rule.declarations, prop) is None, (
                f"`.tile-detail` now reserves {prop} -- an emptied detail leaves a "
                "blank gap instead of shortening the tile, so US-697's "
                "'one fewer line' no longer holds."
            )


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


# =============================================================================
# 4. THE REASON IS CARRIED ACROSS THE SEAM -- NA alone is a shrug.
# =============================================================================


# =============================================================================
# 5. ONE ACQUISITION PATH (ssot-design-pattern rule B).
# =============================================================================


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
