################################################################################
# File Name: test_carousel_ambient_temp_absent_recorded_pass.py
# Purpose/Description: US-640 (F-138, punch-list 4.4) -- RECORD THE PASS on
#   `ambientTempC` reading ABSENT rather than zero, through the REAL producer and
#   ON THE RENDERED PANEL.
#
#   THE VERIFY HELD, AND THE STORY'S PREMISE NEEDS ONE CORRECTION. Atlas's
#   punch-list 4.4 observation -- `ambientTempC` is null and that is CORRECT,
#   because the MAX17048 has no temperature register -- is TRUE. But the story is
#   titled "The Battery card SHOWS ambient temperature as ABSENT", and the card
#   does not show it at all: US-504 removed the TEMP tile outright, so there is no
#   surface on which a null could be painted as anything. The absence is
#   STRUCTURAL, not a null-check, and this file records that distinction rather
#   than letting a vacuous pass stand in for it. Atlas read the STATE FILE; the
#   state file is where the claim lives.
#
#   WHY THIS FILE EXISTS WHEN "THE TEMP TILE IS GONE" IS ALREADY TESTED. Five
#   assertions cover it today -- test_carousel_battery_health_verdict.py:109/115/
#   122 and tests/deploy/test_dashboard_kit.py:511/514 -- and EVERY ONE of them is
#   made on the pure view object (`view.temp === undefined`, `"temp" not in view`)
#   or on a STRING GREP of the renderer's function body. Not one renders a pixel,
#   and not one contains an orchestrator or a state file. So two halves are each
#   independently green and NOTHING tests the join:
#
#     (a) the PRODUCER hardcodes `ambientTempC: None` -- card_state_emitter.py:653
#         -- and the only test that touches the field hands the builder a None of
#         its own (tests/pi/splash/test_battery_health_emitter.py:54) and asserts
#         a None comes back. That is a passthrough test on a hand-supplied value:
#         it cannot witness the orchestrator's default changing. The US-634
#         lesson, third sprint running -- WHEN A DEFAULT IS LOAD-BEARING, TEST THE
#         DEFAULT, NOT A HAND-SUPPLIED VALUE.
#     (b) the VIEW drops the key. A view without a `temp` key says nothing about
#         what the DOM renderer paints; `_fnBody` grepping for "view.temp" does
#         not see a renderer that reached for `d.ambientTempC` directly. That is
#         the US-494/495/498 two-correct-halves shape this sprint keeps finding.
#
#   WHAT IS PINNED HERE. The REAL orchestrator emit tick -> the REAL battery-health
#   emitter -> a real state file on disk -> the SHIPPED carousel.js -> the SHIPPED
#   markup and stylesheet at 480x320. The field is JSON `null` in the file (not 0,
#   not "unknown", not a MISSING KEY -- an absent key is `undefined` in JS and
#   `undefined || 0` is 0 just as surely as `null || 0` is), the answer does not
#   move when the gauge dies, and no temperature of any kind reaches the card.
#
#   THE ANTI-VACUITY SECTION IS THE LOAD-BEARING ONE. "null renders as absence" is
#   satisfied by a panel with no temperature code in it at all, which is exactly
#   the panel we have -- so on its own it is an assertion that can be satisfied one
#   way only (the US-635 lesson). It is made real here by feeding a REAL 21.5 C
#   through the real emitter and measuring that the card STILL paints nothing.
#   That is the difference between "renders absence for null" and "has no surface",
#   and only the second is true.
#
#   THE INVERSE DEFECT, pinned because the field outlives the tile. The column and
#   the payload key survive "for a future BMP390" by the explicit design note in
#   three separate files. For that sensor 0 C is a REAL Chicago reading, and 0.0 is
#   falsy in Python: an `ambientTempC or None` tidy-up would erase a freezing
#   measurement into a typed absence -- the story's own negative case running
#   backwards. Pinned in both directions so the field is safe to fill.
#
#   TRIPWIRE, and it is deliberate: the renderer's silence is held by a
#   characterisation test. Whoever brings the TEMP tile back with the BMP390 WILL
#   fail it, on purpose, and lands in this header -- which is the only place the
#   "never 0 for a null" requirement can be waiting for them, since a panel with no
#   temperature code cannot carry a guard about how it formats one. RE-RECORD IT,
#   DO NOT RELAX IT.
#
#   TWO NOTES FOR THAT PERSON, both found by mutating this file rather than by
#   reading the code, and neither obvious from the source:
#
#     1. `appendTile` (carousel.js:3295) has NO null guard -- it dereferences
#        `tile.level` on its first line. A `temp: null` handed to it throws, and
#        because the tiles are appended in sequence the CHARGE tile below it
#        SILENTLY DISAPPEARS while the card still looks plausible. Guard at the
#        CALL SITE, the way `view.soc.shown` and `view.ladder` already do. A
#        version of this mutation that got it wrong is what turned the negative
#        controls in this file red, which is exactly what those controls are for.
#     2. A correct, null-respecting tile fails ONLY the two characterisation tests
#        and the three structural ones below -- it does NOT fail the negative-case
#        tests, because with a null payload it correctly paints nothing. That
#        asymmetry is measured, not assumed, and it is the point: this file
#        forbids FABRICATION, not a temperature surface. If your change turns the
#        `PaintsNoDegreeSymbol` / `PaintsNoZeroDegrees` tests red, you are
#        rendering something for a null, and that is the defect the story names.
#
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-640 punch-list 4.4 recorded pass,
#               |              | the structural-absence correction + the BMP390
#               |              | inverse-defect and renderer tripwires.
# ================================================================================
################################################################################

"""US-640 tests: ambient temperature is absent, never zero -- and never painted."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "src"))
sys.path.insert(0, _REPO)

import render_harness as rh  # noqa: E402

from pi.hardware.ups_monitor import (  # noqa: E402
    REGISTER_CRATE,
    REGISTER_SOC,
    REGISTER_VCELL,
    UpsMonitor,
)
from pi.obdii.orchestrator.card_state_emitter import (  # noqa: E402
    CardStateEmitterMixin,
)
from pi.splash.battery_health_emitter import (  # noqa: E402
    BATTERY_HEALTH_FILENAME,
    buildBatteryHealthState,
    makeBatteryHealthEmitter,
)

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The shipped panel, not the harness default. Measuring the 3.5in kit at
# 1920x1080 resolves media queries the operator never sees.
PANEL = (480, 320)

# Spelled as named constants, never inline -- this file is written and re-read on
# a Windows SMB share where raw non-ASCII copy has been mangled before (the same
# precaution US-633's, US-638's and US-639's files all take).
DEGREE = "°"
EM_DASH = "—"

# A live gauge, so every absence claim below is made on a card that demonstrably
# PAINTED. An absence test whose subject failed to render is not a measurement --
# a harness that throws is indistinguishable from a panel that omits (US-638).
LIVE_VCELL_RAW = 53299          # 0xD033 -> 4.163984375 V -> "4.16 V"
LIVE_SOC_RAW = 0x6040           # 96.25 % -> "96%"
CRATE_DISABLED_ON_THIS_CHIP = 0xFFFF  # US-235: this variant never populates CRATE
LIVE_VCELL_PRINTED = "4.16 V"
LIVE_SOC_PRINTED = "96%"

CELL = "CELL"
CHARGE = "CHARGE"
HEALTH = "HEALTH"

# The temperatures this file feeds through the producer. Each is chosen for a
# reason and none is decorative:
#   ROOM      an ordinary reading -- the one a working BMP390 would publish.
#   FREEZING  0.0, the story's forbidden output arriving as a REAL measurement.
#             This is the value that makes "no 0 on the card" and "0 survives to
#             the state file" different requirements rather than one.
#   CHICAGO   below zero, because a clamp or an abs() is a plausible tidy-up.
ROOM_C = 21.5
FREEZING_C = 0.0
CHICAGO_C = -12.0


# ---------------------------------------------------------------------------
# The REAL acquisition path, taken from tests/ui/test_carousel_vcell_soc_
# recorded_pass.py (US-639) so both files measure the same chain. The readings
# are taken in the orchestrator's `_emitBatteryHealthState`, which is where
# `ambientTempC` acquires its value -- a test that starts at the builder cannot
# see the orchestrator's default at all, which is precisely the gap (a) above.
# ---------------------------------------------------------------------------


class _FakeI2c:
    """A MAX17048 on a fake I2C bus. An absent register raises, as a dead chip does."""

    def __init__(self, registers: dict[int, int]) -> None:
        self._registers = registers

    def readWord(self, address: int, register: int) -> int:
        if register not in self._registers:
            raise OSError(f"no response from 0x{address:02x} register 0x{register:02x}")
        word = self._registers[register]
        return ((word & 0xFF) << 8) | ((word >> 8) & 0xFF)

    def close(self) -> None:
        return None


def _liveGauge() -> UpsMonitor:
    """A REAL UpsMonitor over a fake bus, holding a healthy pack's registers."""
    return UpsMonitor(
        i2cClient=_FakeI2c(
            {
                REGISTER_VCELL: LIVE_VCELL_RAW,
                REGISTER_SOC: LIVE_SOC_RAW,
                REGISTER_CRATE: CRATE_DISABLED_ON_THIS_CHIP,
            }
        )
    )


def _deadGauge() -> UpsMonitor:
    """A gauge whose every register read fails -- the chip absent or unpowered."""
    return UpsMonitor(i2cClient=_FakeI2c({}))


class _Orch(CardStateEmitterMixin):
    """The minimal composing object the mixin reads, as the orchestrator does.

    Mirrors tests/pi/orchestrator/test_card_state_emitters.py::_FakeOrch and the
    US-639 file's `_Orch`, so a change to the mixin's expectations breaks both
    together rather than leaving one file quietly measuring a shape that no
    longer exists.
    """

    def __init__(self, statesDir: str, *, upsMonitor: Any = None) -> None:
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
            }
        }
        self._configPath = None
        self._connection = None
        self._driveDetector = None
        self._powerSourceProvider = SimpleNamespace(
            isAvailable=True, isExternalPowerPresent=lambda: True
        )
        self._hardwareManager = SimpleNamespace(upsMonitor=upsMonitor)
        self._database = None
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardPowerModeProvider = SimpleNamespace(getPowerMode=lambda: "wall")
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0


def _emitRaw(tmp_path, upsMonitor: Any) -> str:
    """Run the REAL orchestrator emit tick; return the file's RAW TEXT.

    Raw text, not the parsed dict, because the distinction this story turns on --
    `null` versus `0` versus a missing key -- is a fact about what was WRITTEN.
    `json.loads` maps null to None and 0 to 0, but a reader that wants to know
    whether the producer fabricated a zero should look at the bytes it produced.
    """
    statesDir = tmp_path / "states"
    orch = _Orch(str(statesDir), upsMonitor=upsMonitor)
    orch._initializeCardStateEmitters()
    assert orch._maybeEmitCardStates() is True, "the emitter wrote nothing"
    return (statesDir / BATTERY_HEALTH_FILENAME).read_text(encoding="utf-8")


def _emit(tmp_path, upsMonitor: Any) -> dict:
    return json.loads(_emitRaw(tmp_path, upsMonitor))


def _emitWithAmbient(tmp_path, ambientTempC: float | None) -> dict:
    """Write the state file through the REAL emitter with a chosen ambient value.

    The orchestrator cannot be asked for a non-null ambient -- it hardcodes None
    because no sensor exists -- so a populated reading can only enter at the
    builder, which is EXACTLY the seam a BMP390 would attach to. Stated here
    rather than left implicit: this is the US-639 M13 lesson, that a fixture
    which hands a producer nothing to work with cannot witness the producer
    working. The rest of the payload is a healthy pack so the card renders.
    """
    statesDir = tmp_path / "states"
    statesDir.mkdir(parents=True, exist_ok=True)
    emit = makeBatteryHealthEmitter(str(statesDir))
    emit(
        vcellV=4.16,
        soc=96,
        socCalibrated=True,
        crate=None,
        charging=False,
        draining=False,
        restedVcellV=None,
        weakEvents30d=0,
        restedHistory=[],
        health="good",
        fullChargeReached=False,
        runtimeToCutoffS=None,
        ambientTempC=ambientTempC,
        lastHealthCheckTs="2026-08-30T12:00:00Z",
        ladder=None,
    )
    return json.loads(
        (statesDir / BATTERY_HEALTH_FILENAME).read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# Reading the rendered panel.
# ---------------------------------------------------------------------------


def _surface(routes: dict[str, Any]):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet."""
    tree = rh.runDashboard(routes=routes, viewport=PANEL)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _textOf(node: dict) -> list[str]:
    out: list[str] = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


def _cardPath(surface, stateKey: str):
    for path in surface.paths():
        if path[-1].get("attrs", {}).get("data-state") == stateKey:
            return path
    return None


def _cardText(payload: Any, stateKey: str = "battery-health") -> list[str]:
    """Every word a card paints, in reading order.

    Read from the card DOWN rather than tile by tile, because the absence
    assertions here ("no temperature anywhere on this card") are claims about the
    WHOLE card -- a degree symbol that landed in the title, the health detail line
    or a stray tile would slip straight past a per-tile lookup.
    """
    routes: dict[str, Any] = {"/battery-health": payload, "/light": _LIGHT_PAYLOAD}
    surface = _surface(routes)
    path = _cardPath(surface, stateKey)
    if path is None or not surface.rendered(path):
        return []
    return _textOf(path[-1])


# The pure-view probe, as tests/ui/test_carousel_battery_health_verdict.py uses
# it. Kept alongside the rendered-panel reader rather than instead of it: the
# rendered surface is the story's claim, and the view is where the existing (and
# insufficient) coverage lives, so the tripwire below has to speak both.
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")


def _view(fn: str, *args: object) -> Any:
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    # encoding pinned: the card's copy carries "·" and "—", which mojibake through
    # the Windows locale codec and turn a real assertion into noise.
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _labelsOn(payload: Any) -> list[str]:
    """The printed LABEL of every rendered `.tile` on the Battery card.

    A tile's label is its first text node. Collected separately from the card's
    full text because "no tile is called TEMP" and "no degree symbol is painted"
    are different guarantees -- a resurrected tile could carry either without the
    other, and a single assertion covering both would not say which broke.
    """
    surface = _surface({"/battery-health": payload})
    card = _cardPath(surface, "battery-health")
    if card is None:
        return []
    labels: list[str] = []
    for path in surface.pathsByClass("tile"):
        if not any(node is card[-1] for node in path):
            continue
        if not surface.rendered(path):
            continue
        printed = _textOf(path[-1])
        if printed:
            labels.append(printed[0])
    return labels


# A minimal Light-card payload. Present for exactly one test: the panel DOES
# paint the word AMBIENT, on a different card, about a different quantity.
_LIGHT_PAYLOAD = {
    "lux": 120.0,
    "band": "day",
    "ts": "2026-08-31T14:00:00Z",
    "source": {"light": {"available": True, "reason": None}},
}


def _joined(texts: list[str]) -> str:
    return " ".join(texts)


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS FIRST. Most of this file asserts that something is NOT on the
# card, and every one of those assertions is worthless if the card did not render
# or if the reader cannot see the thing it claims is missing.
# ---------------------------------------------------------------------------


def test_theBatteryCardActuallyRenders_negativeControl(tmp_path):
    """The card paints its real tiles in the same payload the absences are read
    from -- so "no temperature here" is a measurement, not a blank card."""
    text = _cardText(_emit(tmp_path, _liveGauge()))
    assert text, "the Battery card rendered nothing at all"
    assert LIVE_VCELL_PRINTED in _joined(text), _joined(text)
    assert LIVE_SOC_PRINTED in _joined(text), _joined(text)


def test_theReaderCanSeeAUnitSymbol_negativeControl(tmp_path):
    """A unit symbol on the card IS visible to `_cardText`.

    Without this, "no degree symbol on the card" could be true because the reader
    never sees units at all. The CELL tile's "V" proves symbols reach the text --
    an absence claim from a reader with a blind spot is not evidence.
    """
    text = _joined(_cardText(_emit(tmp_path, _liveGauge())))
    assert " V" in text, text


def test_thePanelDoesPaintTheWordAmbient_onADifferentCard(tmp_path):
    """AMBIENT on this panel is the LIGHT sensor, not a temperature.

    Recorded because it is the trap waiting for the next person to check this by
    grepping the panel for "AMBIENT": they will find it, on the Light card, about
    lux. Two different facts one word apart -- the same shape as US-635's
    `data-gated` versus `data-vehicle-gated`. Pinning it here means the Battery
    card's absence assertions below cannot be dismissed as a mis-grep.
    """
    lightText = _joined(_cardText(_emit(tmp_path, _liveGauge()), stateKey="light"))
    assert "AMBIENT" in lightText, lightText
    assert DEGREE not in lightText, "the Light card is about lux, not degrees"


# ---------------------------------------------------------------------------
# THE PASS, AT THE SSOT THE STORY NAMES: /run/eclipse-obd/states/battery-health
# -> ambientTempC. This is the field Atlas actually read.
# ---------------------------------------------------------------------------


def test_theRealEmitTickWritesAmbientTempAsNull(tmp_path):
    """Atlas's punch-list 4.4 reading, reproduced through the real producer."""
    payload = _emit(tmp_path, _liveGauge())
    assert payload["ambientTempC"] is None


def test_theFieldIsJsonNullInTheFile_notZeroAndNotAWord(tmp_path):
    """The bytes on disk say `null`.

    Asserted on the RAW TEXT, because this story is entirely about the difference
    between an absence and a plausible-looking value, and `json.loads` has already
    made that difference invisible by the time a dict is in hand. `0`, `0.0`,
    `"unknown"` and `"--"` are each a value a well-meaning producer might write;
    only `null` is the typed absence.
    """
    raw = _emitRaw(tmp_path, _liveGauge())
    assert '"ambientTempC": null' in raw, raw


def test_theKeyIsPresent_anAbsentKeyIsNotATypedAbsence(tmp_path):
    """A MISSING key is not the same honest answer as a null one.

    In the renderer a missing key reads `undefined`, and `undefined || 0` is 0
    exactly as surely as `null || 0` is -- so dropping the field would not make
    the panel safer, it would only move where the fabrication could happen. For a
    reader of the state file it is worse still: "this Pi has no temperature
    sensor" and "this Pi runs a build that predates the field" become
    indistinguishable.
    """
    assert "ambientTempC" in _emit(tmp_path, _liveGauge())


def test_theAnswerDoesNotMoveWhenTheGaugeDies(tmp_path):
    """A dead MAX17048 changes nothing about ambient temperature.

    The point is an INDEPENDENCE, not a repetition: the gauge is not the ambient
    source and never was, so an unreadable gauge must not turn the field into a
    different kind of nothing (a 0, a stale value, or a different absence). This
    is the assertion that would catch someone routing the field through the
    fuel-gauge read path on the way to wiring a real sensor.
    """
    live = _emit(tmp_path, _liveGauge())
    dead = _emit(tmp_path, _deadGauge())
    assert live["ambientTempC"] is None
    assert dead["ambientTempC"] is None
    # ...and the control: the gauge-owned readings DID change, so the fixture is
    # genuinely exercising two different gauges rather than one twice.
    assert live["vcellV"] is not None
    assert dead["vcellV"] is None


def test_ambientTempIsNotUpsOwned_soAnUnreadableGaugeDoesNotBlankIt():
    """US-429 one-truth-per-source: ambient is NOT the MAX17048's to lose.

    `buildBatteryHealthState` blanks every ups-owned numeric when the gauge is
    unavailable -- vcell, soc, crate, rested volts, runtime -- and deliberately
    does NOT blank ambient, because the future BMP390 is a separate instrument
    whose readings survive a dead fuel gauge. Today the field is always None so
    the distinction is invisible; pinned now, while it is cheap, because the
    obvious "tidy up the blanking list" change is wrong and would look right.
    """
    state = buildBatteryHealthState(
        vcellV=4.16,
        soc=96,
        socCalibrated=True,
        crate=-2.0,
        charging=False,
        draining=False,
        restedVcellV=4.10,
        weakEvents30d=0,
        restedHistory=[],
        health="good",
        fullChargeReached=False,
        runtimeToCutoffS=900,
        ambientTempC=ROOM_C,
        lastHealthCheckTs="2026-08-30T12:00:00Z",
        ladder=None,
        nowIso="2026-08-31T14:00:00Z",
        upsAvailable=False,
    )
    assert state["ambientTempC"] == ROOM_C
    # The control: the ups-owned readings WERE blanked in the same call, so this
    # is not passing because the blanking branch was never taken.
    assert state["vcellV"] is None
    assert state["soc"] is None
    assert state["crate"] is None


# ---------------------------------------------------------------------------
# THE NEGATIVE CASE THE STORY DEMANDS: null must never render as 0 degrees.
# ---------------------------------------------------------------------------


def test_theBatteryCardPaintsNoDegreeSymbol(tmp_path):
    """No temperature of any form reaches the rendered card."""
    text = _joined(_cardText(_emit(tmp_path, _liveGauge())))
    assert DEGREE not in text, text


def test_theBatteryCardPaintsNoZeroDegrees(tmp_path):
    """The specific forbidden output, spelled out in every form it could take.

    Named separately from the degree-symbol test above rather than folded into
    it, because "0 C" without the symbol is the same lie to the driver and would
    survive a guard written only against the glyph.
    """
    text = _joined(_cardText(_emit(tmp_path, _liveGauge())))
    for forbidden in ("0" + DEGREE, "0 " + DEGREE, "0C", "0 C", "0.0 C", DEGREE + "C"):
        assert forbidden not in text, f"{forbidden!r} painted on the card: {text}"


def test_noTileOnTheBatteryCardIsATemperature(tmp_path):
    """No tile is labelled TEMP, TEMPERATURE or AMBIENT.

    Asserted over the tile LABELS rather than the card text so the guard survives
    a tile that rendered its label and an em-dash and nothing else -- which is
    precisely the shape a resurrected-but-sourceless TEMP tile would have, and
    the shape US-504 removed.
    """
    labels = _labelsOn(_emit(tmp_path, _liveGauge()))
    assert labels, "no tiles rendered at all -- the absence claim is vacuous"
    assert HEALTH in labels and CELL in labels, labels
    for forbidden in ("TEMP", "TEMPERATURE", "AMBIENT"):
        assert forbidden not in labels, labels


# ---------------------------------------------------------------------------
# THE ABSENCE IS STRUCTURAL, NOT A NULL-CHECK.
#
# This is the section that stops the rest of the file passing for the wrong
# reason. Every assertion above is also satisfied by a panel with no temperature
# code in it whatsoever -- which is the panel we have. An assertion that can only
# be satisfied one way is not evidence (US-635). These three feed the producer a
# REAL reading and measure that the card still paints nothing.
# ---------------------------------------------------------------------------


def test_aRealAmbientReadingIsAlsoNotPainted(tmp_path):
    """21.5 C through the real emitter still reaches no pixel.

    THE CORRECTION TO THE STORY'S PREMISE, measured rather than argued: the card
    does not render a null as an absence, it has no temperature surface at all.
    That is the honest reading of punch-list 4.4 and the reason the pass is
    recorded at the state file rather than on the panel.
    """
    payload = _emitWithAmbient(tmp_path, ROOM_C)
    assert payload["ambientTempC"] == ROOM_C, "the fixture never reached the file"
    text = _joined(_cardText(payload))
    assert text, "the card rendered nothing -- the absence claim would be vacuous"
    assert DEGREE not in text, text
    assert "21.5" not in text, text


def test_aRealZeroReadingIsAlsoNotPainted(tmp_path):
    """0.0 C through the real emitter reaches no pixel either.

    The case that makes "no 0 on the card" and "0 survives to the state file" two
    different requirements instead of one. If a TEMP tile ever returns, a REAL
    freezing measurement and a fabricated null-as-zero would be the same six
    characters on a 3.5in panel -- so the guard has to be that neither is painted
    today, and that whoever paints one has to decide how to tell them apart.
    """
    payload = _emitWithAmbient(tmp_path, FREEZING_C)
    assert payload["ambientTempC"] == FREEZING_C
    text = _joined(_cardText(payload))
    assert text, "the card rendered nothing -- the absence claim would be vacuous"
    assert DEGREE not in text, text


def test_theCardIsUnchangedByTheAmbientField(tmp_path):
    """Byte-for-byte the same card with a reading and without one.

    The strongest form of "there is no surface": not merely that a temperature is
    missing, but that the field cannot influence the card at all. A renderer that
    consumed `ambientTempC` for anything -- a colour, a detail line, an ordering
    -- would fail here even if it never printed a number.
    """
    without = _cardText(_emitWithAmbient(tmp_path / "a", None))
    withReading = _cardText(_emitWithAmbient(tmp_path / "b", ROOM_C))
    assert without, "the control card rendered nothing"
    assert without == withReading


# ---------------------------------------------------------------------------
# THE INVERSE DEFECT. The field outlives the tile by explicit design note in
# card_state_emitter.py, battery_health_emitter.py and carousel.js: it is kept
# "for a future BMP390". For that sensor 0 C is a real reading and -12 C is a
# real Chicago January, and 0.0 is falsy in Python.
# ---------------------------------------------------------------------------


def test_aRealZeroSurvivesToTheStateFileAsZero(tmp_path):
    """0.0 C must NOT be erased into a typed absence.

    This is the story's negative case running backwards, and it is the one that
    will actually bite: `ambientTempC or None` reads like defensive tidying and
    would silently convert the coldest real measurement the sensor can take into
    "we never measured". A driver looking at a blank tile on a freezing morning
    cannot tell that from a dead sensor.
    """
    payload = _emitWithAmbient(tmp_path, FREEZING_C)
    assert payload["ambientTempC"] == 0.0
    assert payload["ambientTempC"] is not None


def test_aBelowZeroReadingSurvivesUnclamped(tmp_path):
    """-12.0 C survives with its sign.

    A clamp to zero or an abs() is a plausible "sanitising" change, and either
    would turn a Chicago January into a fabrication that reads perfectly
    plausibly. The vehicle lives outdoors in Illinois; below-zero IS the normal
    case for four months of the year.
    """
    payload = _emitWithAmbient(tmp_path, CHICAGO_C)
    assert payload["ambientTempC"] == CHICAGO_C


def test_theEmitterPassesTheReadingThroughUnrounded(tmp_path):
    """The producer does not round, bucket or unit-convert on the way out.

    The SSOT publishes the measurement; presentation is the card's job. Pinned so
    a future "tidy to one decimal for the tile" lands in the RENDERER, where it
    belongs, instead of destroying precision for every other consumer of the
    state file -- the same producer/consumer split ARCH-011 settled for the
    g-force values.
    """
    payload = _emitWithAmbient(tmp_path, 21.4567)
    assert payload["ambientTempC"] == 21.4567


# ---------------------------------------------------------------------------
# TRIPWIRE FOR THE BMP390.
#
# CHARACTERISATION TESTS -- they record what is true TODAY so that changing it is
# a deliberate act. Whoever wires the real sensor WILL fail these, on purpose.
# RE-RECORD THEM, DO NOT RELAX THEM: the requirement they carry forward is the
# story's negative case, and a panel with no temperature code in it has nowhere
# else to keep that requirement.
# ---------------------------------------------------------------------------


def test_characterisation_theRendererHasNoTemperaturePath():
    """carousel.js reads `ambientTempC` nowhere -- it only mentions it in prose.

    A source-level guard, and deliberately so: there is no rendered behaviour to
    assert against, so this is the only place that can notice the tile coming
    back. When it does, read this file's header before choosing a format.
    """
    js = os.path.join(_REPO, "src", "pi", "ui", "dashboard", "carousel.js")
    with open(js, encoding="utf-8") as handle:
        lines = handle.readlines()
    reads = [
        (n, line.rstrip())
        for n, line in enumerate(lines, 1)
        if "ambientTempC" in line and not line.lstrip().startswith("//")
    ]
    assert reads == [], (
        "carousel.js now consumes ambientTempC -- US-640's negative case applies: "
        "a null must render as a typed absence and NEVER as 0 degrees, and a real "
        f"0.0 C must stay distinguishable from it. Occurrences: {reads}"
    )


def test_characterisation_theViewBuildsNoTempTile(tmp_path):
    """The structured view carries no `temp` key, measured on a REAL payload.

    The existing coverage of this fact (test_carousel_battery_health_verdict.py,
    tests/deploy/test_dashboard_kit.py) hands the view a hand-written dict. Re-run
    here on a payload the shipped producer actually wrote, so a producer that
    started publishing a differently-shaped ambient block is seen by this file
    rather than only by a fixture nobody updated.
    """
    payload = _emitWithAmbient(tmp_path, ROOM_C)
    view = _view("batteryHealthView", payload)
    assert isinstance(view, dict), view
    assert "temp" not in view, view
    # The control: the view is the real, fully-built one, not an error object.
    assert view.get("vcell") is not None and view.get("health") is not None
