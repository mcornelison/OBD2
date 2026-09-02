################################################################################
# File Name: test_gforce_label_deadband.py
# Purpose/Description: US-645 (F-138) -- the G-FORCE direction labels must stop
#   flickering at rest. A bare sign test has no neutral, so at idle the label
#   reports the sign of the NOISE: Atlas measured ELEVEN longitudinal sign flips
#   in 17 seconds on +/-0.015 g straddling zero, and the lateral label has the
#   identical defect. Both axes get a deadband DERIVED from the display's own
#   rounding threshold, so the word goes neutral exactly when the number reads
#   0.0.
#
#   FIVE things are pinned here, and they fail for five different reasons:
#     1. THE CALIBRATION -- the recorded sequence REPRODUCES the observed defect
#        under the OLD rule. A quiet suite over a sequence that never flipped in
#        the first place would prove nothing at all.
#     2. THE FIX -- zero label changes across the whole 17 s, on both axes.
#     3. THE COUPLING -- neutral IFF the printed number is `0.0`, swept at 0.001
#        across the whole band boundary. This is the deadband-equals-rounding
#        claim measured as a behaviour, not read off the source.
#     4. THE OBD CLAIM -- `still` is upgraded ONLY on a truly-zero vehicle speed.
#        gLon is ~0 at a 65 mph cruise too, so an IMU-only "stopped" is a lie at
#        speed. No producer publishes speed to this dashboard today (I-us645),
#        so the shipped panel degrades to `coast` -- pinned as the CURRENT
#        rendered truth, and it goes red when a producer lands.
#     5. THE WIDTH -- every value a term can take is the width of its siblings
#        (lateral 1 char, longitudinal 5), so US-645 cannot re-open the bounce
#        US-631 (A) just closed. That constraint is why the neutral is `-` and
#        not `steady`, and `still` and not `stopped`.
#
#   WHAT IS NOT PINNED HERE, stated rather than implied: `still` is UNREACHABLE
#   on the shipped panel, because nothing publishes a vehicle speed to the
#   dashboard. Its branch is exercised through the shipped `liveCardView` with a
#   speed supplied, which is the level US-645's own validationCriteria are
#   written at ("feed ... through the label logic") -- but the wiring is owed and
#   is filed as I-us645, not quietly assumed.
#
#   The render harness resolves the CASCADE but NOT LAYOUT (render_harness.py
#   fidelity limit 1), so no claim here is "no wrap ON THE GLASS". The width
#   claims are LENGTH claims, joined to the calibrated wrap model US-631 built.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-01    | Ralph (Rex)  | Initial -- US-645 label deadband + speed gate.
# ================================================================================
################################################################################

"""US-645: the direction labels hold still when the car is not accelerating."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import shutil
import subprocess
from typing import Any

import pytest

from tests.ui import render_harness as rh
from tests.ui.css_type_scale import DASHBOARD_CSS, readCss

# The width model and the measured vocabulary are IMPORTED, never re-derived --
# the same coupling US-631's two files already keep with each other. A private
# second copy is how two files come to disagree about the same column.
from tests.ui.test_gforce_tile_width_budget import (
    ADVANCE_OBSERVED,
    CAROUSEL_JS,
    LONGITUDINAL_LABELS,
    _GColumn,
    _shippedAxisLabels,
    _wrapLines,
)

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")

# The shipped panel. Every rendered claim here is about THIS viewport.
PANEL = (480, 320)

# Atlas's observation, live at idle 2026-08-30, and the two numbers that make
# this file a measurement rather than a description.
OBSERVED_NOISE_G = 0.015
OBSERVED_FLIPS = 11
OBSERVED_WINDOW_S = 17

# The live poll cadence the panel actually runs at (the ~10 Hz motion loop), so
# a 17-second window is 170 samples rather than an arbitrary count.
SAMPLE_HZ = 10

# The deadband the shipped code DERIVES from _G_DECIMALS. Written out here as
# the expected ANSWER, never imported -- a test that computed it the same way
# the source does would agree with a wrong source.
EXPECTED_DEADBAND_G = 0.05

# THE VIRTUAL WALL CLOCK. Every payload in this file is stamped at this instant
# and every reader is told the time is this instant, so a reading is fresh by
# CONSTRUCTION rather than by luck.
#
# This is not tidiness -- it is I-us663b, filed against the neighbouring US-631
# file, which stamps from the real clock and does not pin the page's. `imuView`
# drops to the idle face past IMU_STALE_SEC = 2.0 s, and `%S` truncation spends
# up to 999 ms of that budget before node has even started, so under suite load
# the whole live face vanishes and every assertion about the tile passes or
# fails on process scheduling. That file is US-631's and is left alone; this one
# uses the `nowMs` seam US-641 added to the harness for exactly this reason.
FIXED_INSTANT = dt.datetime(2026, 9, 1, 14, 30, 0, tzinfo=dt.UTC)

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the shipped carousel.js needs node to render",
)


# ---------------------------------------------------------------------------
# Fixtures: the recorded sequence, and the shipped functions that consume it
# ---------------------------------------------------------------------------


def idleNoiseSequence(samples: int = OBSERVED_WINDOW_S * SAMPLE_HZ) -> list[float]:
    """A deterministic idle-noise sequence at Atlas's measured amplitude.

    STATED HONESTLY, because it is the one input this file cannot read back out
    of anything: Atlas's raw capture is not on this bench. What is recorded in
    US-645 is the AMPLITUDE (+/-0.015 g, straddling zero) and the CONSEQUENCE
    (eleven sign flips in seventeen seconds), so the sequence is synthesised to
    the amplitude and then CALIBRATED against the consequence -- see
    ``test_theRecordedSequenceReproducesTheObservedFlipCount``. A sequence that
    could not reproduce the flip count would be arithmetic, not a reproduction,
    and nothing else in this file could be trusted.

    Shape: a slow wander (a real accelerometer at rest drifts with temperature
    and chassis settle, it does not resample white noise at 10 Hz) plus a small
    deterministic jitter. Per-sample white noise would cross zero far more often
    than Atlas counted and would make the fix look easier than it is.

    Args:
        samples: how many 10 Hz samples to generate.

    Returns:
        Signed g values, every one inside the deadband.
    """
    out: list[float] = []
    seed = 20260830  # the date of the observation -- a stated seed, not a lucky one
    for i in range(samples):
        seed = (seed * 1103515245 + 12345) % 2147483648
        jitter = ((seed / 2147483648) - 0.5) * 2 * 0.004
        wander = 0.011 * math.sin(2 * math.pi * i / 30.0)
        out.append(round(wander + jitter, 6))
    return out


def _imuPayload(gLat: float, gLon: float, ts: dt.datetime) -> dict[str, Any]:
    """A states/imu payload the shipped ``imuView`` accepts as LIVE."""
    return {
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "available": True,
        "gLat": gLat,
        "gLon": gLon,
        "gMag": round((gLat**2 + gLon**2) ** 0.5, 3),
        "headingDeg": 180.0,
        "gradePct": 1.0,
    }


def _liveImu(gLat: float, gLon: float) -> dict[str, Any]:
    """The same payload, stamped at this file's ONE fixed instant."""
    return _imuPayload(gLat, gLon, FIXED_INSTANT)


def _nowMs() -> int:
    """The virtual wall clock, equal to the stamp every payload here carries."""
    return int(FIXED_INSTANT.timestamp() * 1000)


def _view(fn: str, *args: object) -> Any:
    """Evaluate one carousel.js export against fixtures via the node probe."""
    proc = subprocess.run(
        [_NODE, _PROBE, fn] + [json.dumps(a) for a in args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _viewMap(fn: str, argLists: list[list[object]]) -> list[Any]:
    """Evaluate one carousel.js export over MANY argument lists in one node run.

    170 samples is 170 node startups the naive way, which is a minute of process
    churn for a second of arithmetic. The batch mode keeps the sweep honest --
    it is still the SHIPPED function, loaded from the shipped file, once per
    sample -- while making it cheap enough to run densely.
    """
    proc = subprocess.run(
        [_NODE, _PROBE, "--map", fn],
        input=json.dumps(argLists),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _detailsForSequence(
    lat: list[float], lon: list[float], speedKph: object = None
) -> list[str]:
    """The detail string the SHIPPED liveCardView produces for each sample.

    The payload's stamp and the clock advance TOGETHER at the sample rate, so
    the feed stays live for the whole window: a sequence that quietly went stale
    half way through would render the idle face and report "no flips" for the
    most dishonest possible reason.
    """
    base = FIXED_INSTANT
    baseMs = _nowMs()
    argLists: list[list[object]] = []
    for i, (a, b) in enumerate(zip(lat, lon, strict=True)):
        stamp = base + dt.timedelta(milliseconds=i * (1000 // SAMPLE_HZ))
        argLists.append(
            [
                _imuPayload(a, b, stamp),
                None,
                baseMs + i * (1000 // SAMPLE_HZ),
                speedKph,
            ]
        )
    views = _viewMap("liveCardView", argLists)
    out: list[str] = []
    for i, view in enumerate(views):
        assert view and not view.get("idle"), (
            f"sample {i} did not render the LIVE face ({view!r}) -- the feed "
            f"went stale or unavailable mid-sequence, so every claim about the "
            f"labels below would be vacuous"
        )
        out.append(view["g"]["detail"])
    return out


def _lateralOf(detail: str) -> str:
    return detail.split()[1]


def _longitudinalOf(detail: str) -> str:
    return detail.split()[-1]


def _surface(gLat: float, gLon: float):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet.

    The page clock is PINNED to the payload's own stamp (US-641's ``nowMs``
    seam), so the reading is zero seconds old however long node takes to boot.
    See FIXED_INSTANT / I-us663b for why that is load-bearing rather than tidy.
    """
    tree = rh.runDashboard(
        routes={"/imu": _liveImu(gLat, gLon)}, viewport=PANEL, nowMs=_nowMs()
    )["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _textOf(node: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return out


def _paintedInGColumn(surface, className: str) -> str | None:
    """The printed text of the first PAINTED `className` inside `.live-g`."""
    for path in surface.pathsByClass(className):
        if not surface.rendered(path):
            continue
        if not any("live-g" in (n.get("attrs", {}).get("class") or "").split() for n in path):
            continue
        return " ".join(_textOf(path[-1])).strip()
    return None


def _paintedDetail(gLat: float, gLon: float) -> str:
    detail = _paintedInGColumn(_surface(gLat, gLon), "tile-detail")
    assert detail, "the G-FORCE tile painted no detail line"
    return detail


@pytest.fixture(scope="module")
def column() -> _GColumn:
    return _GColumn(readCss(DASHBOARD_CSS))


@pytest.fixture(scope="module")
def carouselSource() -> str:
    with open(CAROUSEL_JS, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 1. THE CALIBRATION -- the sequence reproduces the defect that was observed.
# ---------------------------------------------------------------------------


def test_theRecordedSequenceReproducesTheObservedFlipCount():
    """
    Given: Atlas measured eleven sign flips in seventeen seconds at idle
    When:  the OLD rule -- a bare sign test -- is run over this file's sequence
    Then:  it flips at least as often, within the measured amplitude

    THE TEST THAT LICENSES EVERY OTHER ONE. "No flips after the fix" is also
    what a sequence that never flipped before the fix would report, and that is
    the most likely way this file could be quietly worthless. The old rule is
    written out here rather than imported, because it no longer exists in the
    source -- this is the historical behaviour being reproduced, not the shipped
    one being asserted.
    """
    seq = idleNoiseSequence()
    assert len(seq) == OBSERVED_WINDOW_S * SAMPLE_HZ

    amplitude = max(abs(v) for v in seq)
    assert amplitude <= OBSERVED_NOISE_G, (
        f"the sequence reaches {amplitude:.4f} g, outside the +/-"
        f"{OBSERVED_NOISE_G} g Atlas measured -- a louder signal would make the "
        f"deadband look better than it is"
    )
    assert all(abs(v) < EXPECTED_DEADBAND_G for v in seq), (
        "the sequence leaves the deadband, so a quiet label would be evidence "
        "about the fix only for the samples that happened to stay inside it"
    )

    bareSign = ["accel" if v >= 0 else "brake" for v in seq]
    flips = sum(1 for a, b in zip(bareSign, bareSign[1:]) if a != b)
    assert flips >= OBSERVED_FLIPS, (
        f"the OLD rule flips only {flips} times over this sequence, fewer than "
        f"the {OBSERVED_FLIPS} Atlas counted in {OBSERVED_WINDOW_S} s. The "
        f"sequence does not reproduce the defect, so 'zero flips after the fix' "
        f"below would be a fact about the fixture, not about the fix."
    )


# ---------------------------------------------------------------------------
# 2. THE FIX -- validationCriteria #1, on both axes.
# ---------------------------------------------------------------------------


def test_seventeenSecondsOfIdleNoiseProducesNoLongitudinalFlip():
    """
    Given: 17 s of recorded idle noise on gLon, straddling zero
    When:  every sample is fed through the SHIPPED liveCardView
    Then:  the longitudinal label never changes -- one word for the whole window

    validationCriteria #1. Asserted as "the whole rendered line is identical",
    not merely "the word is stable": a stable word beside a number that flickers
    between `0.0` and `-0.0` would still move the tile, and the number is part
    of the same string.
    """
    seq = idleNoiseSequence()
    details = _detailsForSequence([0.0] * len(seq), seq)

    words = {_longitudinalOf(d) for d in details}
    assert words == {"coast"}, (
        f"the longitudinal label took {len(words)} distinct values over "
        f"{OBSERVED_WINDOW_S} s of idle noise ({sorted(words)}) -- the flicker "
        f"the CIO watched is still there"
    )
    assert len(set(details)) == 1, (
        "the detail line still changes at idle: "
        + "; ".join(sorted(set(details)))
        + " -- something other than the direction word is moving"
    )


def test_seventeenSecondsOfIdleNoiseProducesNoLateralFlip():
    """
    Given: the SAME sequence on gLat instead
    When:  every sample is fed through the SHIPPED liveCardView
    Then:  the lateral label never changes either

    US-645's acceptance is explicit that the lateral label "has the IDENTICAL
    defect and had never been noticed". One mechanical pattern applied twice --
    so it is measured twice, from the same recording, rather than assumed to
    follow.
    """
    seq = idleNoiseSequence()
    details = _detailsForSequence(seq, [0.0] * len(seq))

    words = {_lateralOf(d) for d in details}
    assert words == {"-"}, (
        f"the lateral label took {len(words)} distinct values over "
        f"{OBSERVED_WINDOW_S} s of idle noise ({sorted(words)})"
    )
    assert len(set(details)) == 1, (
        "the detail line still changes at idle: " + "; ".join(sorted(set(details)))
    )


def test_aRealAccelerationIsReportedPromptly():
    """
    Given: the car actually accelerates, then brakes, out of an idle window
    When:  the samples cross the deadband
    Then:  the label reports it on the VERY FIRST sample outside the band

    validationCriteria #2, and the negative half of the deadband: a fix that
    quietened the label by damping or debouncing it would satisfy the flicker
    tests above and make the instrument late. The deadband is a THRESHOLD, not a
    filter -- there is no state carried between samples, and this is what says
    so.
    """
    idle = idleNoiseSequence(20)
    seq = idle + [0.30] * 3 + [0.0] * 3 + [-0.30] * 3
    details = _detailsForSequence([0.0] * len(seq), seq)

    assert _longitudinalOf(details[len(idle)]) == "accel", (
        f"the first sample above the deadband painted "
        f"{details[len(idle)]!r} -- the label lags the car"
    )
    assert _longitudinalOf(details[len(idle) + 3]) == "coast"
    assert _longitudinalOf(details[len(idle) + 6]) == "brake", (
        f"the first braking sample painted {details[len(idle) + 6]!r}"
    )


# ---------------------------------------------------------------------------
# 3. THE COUPLING -- the deadband IS the displayed rounding threshold.
# ---------------------------------------------------------------------------


def test_theWordGoesNeutralExactlyWhenTheNumberReadsZero():
    """
    Given: US-645 requires the band to be DERIVED from the decimals constant,
        "so the word goes neutral exactly when the number reads 0.0"
    When:  the whole boundary region is swept at 0.001 g on both axes
    Then:  the label is neutral IF AND ONLY IF the printed magnitude is `0.0`

    THE LOAD-BEARING PIN OF THE COUPLING, and it is deliberately a BEHAVIOURAL
    claim rather than a reading of the source. A hardcoded 0.05 satisfies a
    source-level check and this one too -- today. What this measures is the
    invariant that survives a change to the decimals constant: the card can
    never show a direction beside a zero, and can never show a neutral beside a
    number. `conditionalOutcomes` asks for exactly that coupling; the source pin
    below records HOW it is expressed.
    """
    values = [round(n / 1000, 3) for n in range(0, 200)]
    # Both signs, because the band is a MAGNITUDE and a one-sided sweep would
    # leave a fix that only guarded the positive half looking correct.
    signed = values + [-v for v in values]
    argLists = [[v, v, None] for v in signed]
    details = _viewMap("gAxisDetail", argLists)

    for value, detail in zip(signed, details, strict=True):
        latNumber, latWord, _, lonNumber, lonWord = detail.split()
        assert (latWord == "-") == (latNumber == "0.0"), (
            f"at {value} g lateral the tile painted {detail!r}: the word and "
            f"the number disagree about whether this reading is zero"
        )
        assert (lonWord in ("coast", "still")) == (lonNumber == "0.0"), (
            f"at {value} g longitudinal the tile painted {detail!r}: the word "
            f"and the number disagree about whether this reading is zero"
        )


def test_theBandBoundaryIsHalfOfTheLastPrintedPlace():
    """
    Given: one decimal place is displayed
    When:  the two readings either side of half of the last place are rendered
    Then:  0.049 g is neutral and 0.050 g carries a direction

    Records the boundary as a NUMBER, so the derivation is not merely internally
    consistent but lands where US-645 says it should ("deadband at 0.05 g"). The
    inclusive side is the DIRECTION: at exactly 0.05 the number rounds up to
    `0.1`, so a neutral there would be the forbidden pairing in reverse -- a
    neutral word beside a non-zero reading.
    """
    below = _view("gAxisDetail", 0.0, EXPECTED_DEADBAND_G - 0.001, None)
    at = _view("gAxisDetail", 0.0, EXPECTED_DEADBAND_G, None)

    assert _longitudinalOf(below) == "coast", f"0.049 g painted {below!r}"
    assert _longitudinalOf(at) == "accel", f"0.050 g painted {at!r}"
    assert at.split()[3] == "0.1", (
        f"0.050 g printed {at.split()[3]!r}, so the boundary is no longer the "
        f"rounding threshold and the recorded 0.05 needs re-deriving"
    )


def test_theDeadbandIsDerivedFromTheDecimalsConstantInSource(carouselSource):
    """
    Given: `conditionalOutcomes` -- "if the decimals constant later changes the
        deadband must follow automatically"
    When:  the shipped source is read
    Then:  the band is an EXPRESSION over _G_DECIMALS, not a literal 0.05

    The behavioural sweep above cannot tell a derivation from a coincidence at
    today's value of the constant, so the coupling is ALSO pinned where it is
    expressed. Two weak checks on the same claim from opposite sides, because
    neither is sufficient alone.
    """
    match = re.search(r"var G_LABEL_DEADBAND_G = ([^;]+);", carouselSource)
    assert match is not None, "G_LABEL_DEADBAND_G is not declared in carousel.js"
    expression = match.group(1)
    assert "_G_DECIMALS" in expression, (
        f"the deadband is declared as {expression!r}, which does not read the "
        f"decimals constant. A literal here silently diverges from the "
        f"displayed rounding the day ARCH-011's decision changes -- which is "
        f"this defect again, one layer up."
    )
    assert "0.05" not in expression, (
        f"the deadband expression {expression!r} still carries the literal the "
        f"story asked to be derived away"
    )


# ---------------------------------------------------------------------------
# 4. THE OBD CLAIM -- `still` is a speed fact, not a motion fact.
# ---------------------------------------------------------------------------


def test_aZeroGReadingAtCruiseIsNeverReportedAsStopped():
    """
    Given: gLon is ~0 at a steady 65 mph cruise, exactly as it is when parked
    When:  the label logic is fed an in-band reading WITH a cruising speed
    Then:  it reads `coast`, never `still`

    validationCriteria #3, and the reason the upgrade needs a second instrument
    at all. This is the assertion that stops a quiet tile becoming a false one.
    """
    for speed in (105, 65, 1, 0.4):
        detail = _view("gAxisDetail", 0.0, 0.01, speed)
        assert _longitudinalOf(detail) == "coast", (
            f"at {speed} the panel painted {detail!r} -- the tile is calling a "
            f"moving car stopped on the strength of a flat accelerometer"
        )


def test_aTrulyZeroSpeedUpgradesTheNeutralToStill():
    """
    Given: the vehicle speed is truly zero and the accelerometer is quiet
    When:  the label logic is fed both facts
    Then:  it reads `still`

    validationCriteria #4. The upgrade is the ONLY thing on this tile that
    consumes a non-IMU fact, which is why it is a parameter rather than a field
    read off the states/imu payload -- a function that cannot see the OBD feed
    cannot quietly start inferring one.
    """
    detail = _view("gAxisDetail", 0.0, 0.01, 0)
    assert _longitudinalOf(detail) == "still", f"a stopped car painted {detail!r}"


def test_anUnknownSpeedNeverClaimsStill():
    """
    Given: no producer publishes a vehicle speed to this dashboard (I-us645)
    When:  the label logic is fed every shape an absent speed can arrive as
    Then:  it degrades to `coast`, which is true at any speed including zero

    HONEST DEGRADATION, and the pin that matters most today because null is what
    the shipped panel actually passes. The three JavaScript `==` traps are in the
    list deliberately -- `"0" == 0`, `"" == 0` and `false == 0` are ALL true, and
    every one of them is a shape a future producer could forward out of a JSON
    payload without coercing it. The comparison is strict, so each is refused
    rather than believed.

    NaN is deliberately absent: the transport is a JSON state file and JSON has
    no NaN, so it cannot arrive that way. Stating the gap rather than faking it
    with a string that merely spells the word.
    """
    for speed in (None, "0", "", False, "stopped", -1):
        detail = _view("gAxisDetail", 0.0, 0.01, speed)
        assert _longitudinalOf(detail) == "coast", (
            f"speed={speed!r} painted {detail!r} -- an unknown speed is being "
            f"read as a stopped car"
        )


def test_aRealReadingOutranksAStoppedSpeed():
    """
    Given: a speed of zero and a longitudinal reading well outside the deadband
    When:  both are fed to the label logic
    Then:  the MEASUREMENT wins -- `brake`, never `still`

    A stopped car with 0.3 g on the fore/aft axis is an impact, a tow or a
    mounting fault, and `still` there would be the display overruling the
    instrument. The speed only ever upgrades a neutral; it can never create one.
    """
    detail = _view("gAxisDetail", 0.0, -0.30, 0)
    assert _longitudinalOf(detail) == "brake", f"painted {detail!r}"


def test_theLateralAxisHasNoStoppedState():
    """
    Given: the lateral neutral must be ONE character (US-645's width constraint)
    When:  an in-band lateral reading is rendered with a truly-zero speed
    Then:  it is still the dash -- the speed upgrade is longitudinal only

    Recorded so the asymmetry reads as a decision rather than an omission: there
    is no one-character spelling of `still`, and inventing a second lateral
    neutral would put a variable-width term back on the axis US-631 (A)
    abbreviated to fix exactly that.
    """
    detail = _view("gAxisDetail", 0.01, 0.01, 0)
    assert _lateralOf(detail) == "-", f"painted {detail!r}"
    assert _longitudinalOf(detail) == "still", (
        f"painted {detail!r} -- the longitudinal upgrade should still apply"
    )


def test_theShippedPanelRendersCoastBecauseNoProducerPublishesSpeed():
    """
    Given: the browser call site passes null for the vehicle speed (I-us645)
    When:  a genuinely at-rest reading is rendered on the SHIPPED panel
    Then:  the driver sees `coast`, and `still` appears nowhere

    THE CURRENT RENDERED TRUTH, recorded rather than narrated. `still` is
    unreachable on the panel today; that is the honest consequence of having no
    speed producer, and it is pinned here so it cannot change silently. WHOEVER
    WIRES THE PRODUCER FAILS HERE ON PURPOSE and re-records this as `still` --
    which is the point: the wiring becomes a visible act instead of a tile that
    quietly starts making a new claim.
    """
    painted = _paintedDetail(0.01, -0.02)
    assert _longitudinalOf(painted) == "coast", f"the panel painted {painted!r}"
    assert "still" not in painted, (
        f"the panel painted {painted!r} -- something is supplying a vehicle "
        f"speed to the tile. If a producer has landed, re-record this test."
    )
    assert painted == "0.0 - · 0.0 coast", (
        f"the at-rest tile now reads {painted!r}; the recorded rest state is "
        f"'0.0 - · 0.0 coast'"
    )


# ---------------------------------------------------------------------------
# 5. THE WIDTH -- US-645 must not re-open the bounce US-631 (A) closed.
# ---------------------------------------------------------------------------


def test_everyLabelStateRendersTheSameLengthOnThePanel():
    """
    Given: US-631 (A) bought a constant tile height by making every direction
        word the width of its siblings
    When:  the panel is rendered at rest, cornering, accelerating and braking
    Then:  every painted detail line is the SAME length

    THE US-631 INTERACTION, measured on the panel rather than trusted. US-645's
    acceptance warns in as many words that a six-character `steady` "would
    REINTRODUCE A WORSE BOUNCE THAN THE ONE US-631 JUST REMOVED". The neutral
    states are the new terms, so they are the ones swept here.
    """
    reference = _paintedDetail(0.30, 0.12)
    for gLat, gLon in ((0.01, 0.01), (0.30, 0.01), (0.01, 0.12), (0.01, -0.12),
                       (-0.30, -0.12)):
        painted = _paintedDetail(gLat, gLon)
        assert len(painted) == len(reference), (
            f"{painted!r} is {len(painted)} chars and the cornering reference "
            f"{reference!r} is {len(reference)}. The tile can reflow between "
            f"those two states, which is the bounce US-631 was raised for -- "
            f"now on the neutral transition instead of the left/right one."
        )


def test_theNeutralStatesWrapToTheSameLineCountAsTheLiveOnes(column):
    """
    Given: `.tile-detail` sets no `white-space` and no `min-height`, so in a
        fixed column the line count is a pure function of length
    When:  the rest state and the cornering state are wrapped by the model
        US-631 calibrated against the observed bounce
    Then:  they occupy the same number of line boxes

    Length equality is the invariant; this is the consequence that the CIO can
    actually see, expressed through the one model in this repo that has been
    shown to reproduce a bounce a human watched.
    """
    rest = _paintedDetail(0.01, 0.01)
    live = _paintedDetail(0.30, 0.12)
    restLines = _wrapLines(rest, column.width, column.detailPx, ADVANCE_OBSERVED)
    liveLines = _wrapLines(live, column.width, column.detailPx, ADVANCE_OBSERVED)
    assert restLines == liveLines, (
        f"{rest!r} wraps to {restLines} lines and {live!r} to {liveLines} in the "
        f"shipped {column.width}px column -- the tile grows when the car stops"
    )


def test_theShippedVocabularyIsWidthMatchedPerAxis():
    """
    Given: US-645's hard constraint -- "EVERY VALUE A TERM CAN TAKE MUST BE THE
        SAME WIDTH AS ITS SIBLINGS"
    When:  the words gAxisDetail actually ships are read out of the source
    Then:  the lateral set is all one character and the longitudinal set all five

    Read from the SHIPPED source, not written out here: a check against this
    file's memory of the vocabulary would stay green over a renderer that had
    gone back to variable-width words. This is the guard that makes the
    constraint survive whoever touches this tile third.
    """
    shipped = _shippedAxisLabels()
    longitudinal = shipped & LONGITUDINAL_LABELS
    lateral = shipped - LONGITUDINAL_LABELS

    assert longitudinal == {"accel", "brake", "coast", "still"}, (
        f"the shipped longitudinal vocabulary is {sorted(longitudinal)}"
    )
    assert lateral == {"L", "R", "-"}, (
        f"the shipped lateral vocabulary is {sorted(lateral)}"
    )
    assert {len(w) for w in longitudinal} == {5}, (
        f"the shipped longitudinal labels {sorted(longitudinal)} are not all 5 "
        f"characters -- US-645's own acceptance requires it, because `accel` "
        f"and `brake` are 5 and a third state of any other width starts that "
        f"axis bouncing where it never did before"
    )
    assert {len(w) for w in lateral} == {1}, (
        f"the shipped lateral labels {sorted(lateral)} are not all 1 character"
    )


def test_theStorysOwnSpellingsAreAbsentAndWhyIsRecorded():
    """
    Given: US-645's prose names `steady` and `stopped`
    When:  the shipped vocabulary is inspected
    Then:  neither word is on the tile

    RECORDED AS A DELIBERATE DEPARTURE, not an accident. The same story carries a
    HARD CONSTRAINT added later -- one character laterally, five longitudinally
    -- and `steady` (6) and `stopped` (7) violate it. `coast` and `still` carry
    the same two meanings at the required widths. This test exists so a reader
    comparing the story text to the panel finds the reason here rather than
    filing a defect.
    """
    shipped = _shippedAxisLabels()
    assert "steady" not in shipped and "stopped" not in shipped, (
        f"the tile ships {sorted(shipped)}. `steady` is 6 characters and "
        f"`stopped` is 7, against 5-character siblings -- landing either "
        f"re-opens the bounce US-631 (A) closed."
    )


# ---------------------------------------------------------------------------
# 6. HONESTY -- what the deadband must NOT do.
# ---------------------------------------------------------------------------


def test_theDeadbandNeverTouchesTheNumberOrTheDot():
    """
    Given: the deadband quiets the WORD
    When:  an in-band reading is put through the shipped view
    Then:  the magnitude and the meter dot still carry the real reading

    THE OVER-REACH THIS TEST EXISTS TO CATCH. Snapping the reading to zero
    inside the band would make every flicker test above pass perfectly and would
    fabricate a stillness the accelerometer never measured -- the zeroed
    instrument this card has refused since US-497. The word is a rounding of the
    DESCRIPTION; the number and the dot are the measurement.
    """
    view = _view("liveCardView", _liveImu(0.03, -0.04), None, _nowMs())
    g = view["g"]

    assert g["dot"] is not None, "an in-band reading painted no dot at all"
    assert g["dot"]["x"] != 0 or g["dot"]["y"] != 0, (
        f"the meter dot sits at the origin for a real 0.03/-0.04 g reading "
        f"({g['dot']!r}) -- the deadband has reached the instrument"
    )
    assert g["value"] == "0.1 g", (
        f"the magnitude painted {g['value']!r}; 0.03/-0.04 g is 0.05 g of true "
        f"magnitude and rounds to 0.1, so a 0.0 here means the reading was "
        f"suppressed rather than described"
    )


def test_aNeutralLabelIsNotAnAbsence():
    """
    Given: a quiet tile and an ABSENT tile are different facts
    When:  an unavailable motion feed is rendered
    Then:  it does NOT paint the neutral pair -- it degrades to the idle face

    The neutral words describe a real, successful measurement of very little.
    The day they become indistinguishable from a dead sensor is the day the
    deadband has re-created the defect US-497 removed, one word over.
    """
    dead = dict(_liveImu(0.0, 0.0))
    dead["available"] = False
    dead["reason"] = "imu unwired"

    view = _view("liveCardView", dead, None, _nowMs())
    assert view["idle"] is True, (
        f"an unavailable feed rendered the LIVE face ({view!r}) -- a dead "
        f"sensor is about to be painted as a car sitting still"
    )
