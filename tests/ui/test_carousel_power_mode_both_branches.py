################################################################################
# File Name: test_carousel_power_mode_both_branches.py
# Purpose/Description: US-628 END-TO-END pin for BOTH power-mode branches on the
#   SHIPPED rendered surface. The pre-existing US-502 chain test
#   (test_carousel_power_source_wiring.py) drives the emitter with
#   `pi.power.mode = "car"` and NOTHING ELSE -- so the wall branch of the power
#   tile has never been rendered by a test. That is the identical mistake the
#   story exists to correct: Atlas recorded power.mode as "wall and CORRECT"
#   from a desk where the Pi genuinely WAS on wall power, and a value that is
#   only right in the context it was checked in is not evidence.
#
#   These tests therefore pin car AND wall, and pin that the two do not
#   collapse into one another, through the REAL emitter into the REAL
#   carousel.js under node -- never on powerTile() alone. US-494/495/498 were
#   "two correct halves that did not agree" defects that every pure unit test
#   passed; only the emitter -> state file -> renderer chain catches those.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-628 car/wall both-branch pin.
# ================================================================================
################################################################################

"""US-628: both power-mode branches, pinned on the shipped rendered surface."""

import json
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _view(fn: str, arg):
    # encoding="utf-8" is load-bearing on Windows: `text=True` alone decodes
    # node's UTF-8 stdout with the locale codec (cp1252 here), which turns the
    # tile's `—` / `·` glyphs into U+FFFD and fails a correct assertion.
    proc = subprocess.run(
        [_NODE, _PROBE, fn, json.dumps(arg)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# The two non-ASCII glyphs the tile emits, named so this source file stays pure
# ASCII. A literal here would be re-encoded by whatever codec a given box reads
# the file with, which silently softens the pin instead of failing it.
_MIDDOT = chr(0x00B7)
_EMDASH = chr(0x2014)

# Sentinel: omit `pi.power.mode` entirely, rather than set it to anything.
# A distinct object (not None) because None is itself one of the invalid values
# this file pins, and the two cases must stay separable.
_ABSENT = object()


class _Orch(CardStateEmitterMixin):
    """The real mixin, driven with only the power facts attached.

    ``powerModeKey`` is written into the config the mixin actually reads, so the
    mode travels the production acquisition path (ConfigPowerModeSource ->
    PowerModeProvider -> emitter -> state file) rather than being injected at
    the renderer. A sentinel of ``_ABSENT`` omits the key entirely, which is how
    a Pi that was never told its deployment context really looks.
    """

    def __init__(self, statesDir, provider, powerModeKey):
        power: dict = {} if powerModeKey is _ABSENT else {"mode": powerModeKey}
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "power": power,
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
            }
        }
        self._connection = None
        self._driveDetector = None
        self._hardwareManager = None
        self._powerSourceProvider = provider
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardPowerModeProvider = None
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0


_ABSENT = object()


def _pld(present: bool, available: bool = True):
    from pi.power.power_source_provider import PowerSourceProvider

    return PowerSourceProvider(
        pld=SimpleNamespace(
            isAvailable=available,
            # Real PldSensor: unreadable line answers "present" (safe dir).
            isExternalPowerPresent=lambda: True if not available else present,
        )
    )


def _emitPower(tmp_path, *, mode, present=True, available=True) -> dict:
    """Run the real emitter, return the `power` object the carousel reads."""
    orch = _Orch(str(tmp_path / "states"), _pld(present, available), mode)
    orch._initializeCardStateEmitters()
    assert orch._maybeEmitCardStates() is True
    state = json.loads(
        (tmp_path / "states" / "system-status").read_text(encoding="utf-8")
    )
    return state["power"]


# ---------------------------------------------------------------------------
# THE TWO BRANCHES. One passing case is not evidence -- that is the mistake
# that produced this story's 2026-08-30 correction.
# ---------------------------------------------------------------------------


def test_wallPower_rendersWALL_theBranchThatWasNeverPinned(tmp_path):
    """The bench/desk deployment context, end to end.

    This is the branch the US-502 chain test never exercised. It is also the
    value the live Pi is stuck on, so a renderer that could not display it at
    all would have been invisible to the whole suite.
    """
    power = _emitPower(tmp_path, mode="wall")
    assert power["mode"] == "wall"

    tile = _view("powerTile", power)
    assert tile["value"] == "WALL"
    assert tile["detail"] == "external"
    assert tile["level"] == "ok"


def test_carPower_rendersCAR_theOtherBranch(tmp_path):
    """The in-car deployment context, end to end. Held alongside the wall case
    so a mutation that hardcodes EITHER badge is caught by the other test."""
    power = _emitPower(tmp_path, mode="car")
    assert power["mode"] == "car"

    tile = _view("powerTile", power)
    assert tile["value"] == "CAR"
    assert tile["detail"] == "external"
    assert tile["level"] == "ok"


def test_theTwoModesDoNotCollapseIntoOneAnother(tmp_path):
    """`neither defaults to the other` -- stated as a direct comparison.

    The two tests above could BOTH pass against a renderer that echoed an
    upper-cased raw string while the emitter silently dropped the fact. This
    asserts the surfaces actually differ, which is the property the story
    asks for and the one a shared default would break.
    """
    wall = _view("powerTile", _emitPower(tmp_path / "w", mode="wall"))
    car = _view("powerTile", _emitPower(tmp_path / "c", mode="car"))

    assert wall["value"] != car["value"]
    assert {wall["value"], car["value"]} == {"WALL", "CAR"}


def test_theModeSurvivesOntoTheBatteryBranchToo(tmp_path):
    """Mode and source are INDEPENDENT facts, so the mode must still be named
    when the source is battery -- not silently replaced by the car default.

    The battery branch renders the mode in `detail`, and it renders it from the
    same value: a wall-powered Pi running on the UPS pack says `wall`, not
    `car`. Pinned because this branch's only prior test hardcoded car.
    """
    power = _emitPower(tmp_path, mode="wall", present=False)
    assert power["mode"] == "wall"
    assert power["source"] == "battery"

    tile = _view("powerTile", power)
    assert tile["value"] == "BATTERY"
    # Escapes, not literals: this file stays pure ASCII so the pin cannot be
    # softened by whatever encoding a given box reads the source with.
    assert tile["detail"] == "wall " + _MIDDOT + " on UPS"
    assert tile["level"] == "amber"


# ---------------------------------------------------------------------------
# THE TYPED ABSENCE. "never a default that happens to be one of the legal
# values" -- an unset mode must not resolve to car or wall.
# ---------------------------------------------------------------------------


def test_absentMode_rendersLowercaseUnknown_neverAConfidentMode(tmp_path):
    """A Pi nobody has told its deployment context renders `unknown`.

    Lowercase is the load-bearing part: a real known mode is upper-case
    (CAR/WALL), so the confident values are visibly the confident ones and the
    honest one cannot be mistaken for a third location.
    """
    power = _emitPower(tmp_path, mode=_ABSENT)
    assert power["mode"] == "unknown"

    tile = _view("powerTile", power)
    assert tile["value"] == "unknown"
    assert tile["value"] not in ("CAR", "WALL")


@pytest.mark.parametrize("junk", ["garage", "WALL", "", "car ", 12, None, True])
def test_invalidMode_isCoercedByTheProducerBeforeItIsEverRendered(tmp_path, junk):
    """Anything outside the two legal modes leaves the PRODUCER as `unknown`.

    Includes `"WALL"` deliberately: a case-variant is exactly the near-miss a
    hand-edited overlay produces, and coercing it upward would invent a
    confident deployment context out of a value the SSOT rejected.

    Note what this does and does NOT pin. Because PowerModeProvider sanitises
    first, the renderer only ever SEES car/wall/unknown here -- so this is a
    pin on the producer, and the tile assertion below is a consequence of it,
    not an independent check of the renderer. The renderer's own guard is
    pinned separately in the test that follows; discovered by mutating
    carousel.js and finding this test could not tell the difference.
    """
    power = _emitPower(tmp_path, mode=junk)
    assert power["mode"] == "unknown"
    assert _view("powerTile", power)["value"] == "unknown"


@pytest.mark.parametrize("junk", ["garage", "WALL", "", "car ", 12, True, ["car"]])
def test_rendererRejectsAnIllegalModeEvenIfTheProducerNeverWould(junk):
    """DEFENCE IN DEPTH, pinned directly on carousel.js.

    Fed straight to powerTile, bypassing the emitter, because a state file is
    an on-disk artefact: it can be hand-edited, half-written, or produced by a
    future emitter that forgets to coerce. The renderer is the last thing
    standing between a corrupt `mode` and a driver reading a confident CAR on
    a bench. `unknown` is the only honest answer to a value we do not
    recognise -- never the raw string, upper-cased or otherwise.
    """
    tile = _view("powerTile", {"mode": junk, "source": "external"})
    assert tile["value"] == "unknown"


# ---------------------------------------------------------------------------
# SSOT rule B: ONE acquisition of the power fact, and the glyph is a consumer
# of it -- never a second reader that could disagree with the tile.
# ---------------------------------------------------------------------------


def test_theDashboardAcquiresPowerStateExactlyOnce():
    """`grep the dashboard for a second acquisition of power state`.

    Both surfaces the story names -- the header glyph AND the System Status
    tile -- must derive from the SAME `data.power` object read from the
    system-status state file. Two readers is how this project got a latched
    magnetometer, and here it would let the glyph and the tile disagree about
    the same instant.

    `pi.power.mode` also appears in the settings band, and that is deliberately
    NOT a violation: it is the operator's WRITE control for the config key, the
    opposite direction of travel. The assertion below is scoped to reads of the
    emitted state object so it cannot be satisfied by deleting that control.
    """
    js = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "src", "pi", "ui", "dashboard", "carousel.js",
    )
    with open(js, encoding="utf-8") as fh:
        source = fh.read()

    reads = [ln.strip() for ln in source.splitlines() if "data.power" in ln]
    assert reads == [
        "power: powerTile(data.power),",
        "power: powerGlyphState(data.power),",
    ], (
        "power state must be acquired from `data.power` exactly twice -- once "
        "for the tile, once for the glyph -- and from nowhere else. Got:\n"
        + "\n".join(reads)
    )


# ---------------------------------------------------------------------------
# CHARACTERISATION, not an endorsement -- see
# offices/pm/issues/I-us628-power-tile-drops-a-known-mode-when-source-is-unknown.md
# ---------------------------------------------------------------------------


def test_unknownSource_currentlyDropsTheKnownMode_characterisation(tmp_path):
    """RECORDED FINDING, deliberately not fixed here.

    This is the live Pi's exact state: the mode is KNOWN (wall) and the source
    is unreadable. The tile collapses to the same "unavailable" surface it
    shows when the whole power block is missing, discarding a fact it holds.
    Nothing here is dishonest -- it under-reports rather than over-reports --
    so it does not breach this story's END STATE, and the story says not to
    paper over the producer's defect in the renderer. Pinned so the behaviour
    is a decision on the record rather than an accident, and so whoever wires
    the mode into this branch fails this test ON PURPOSE.
    """
    power = _emitPower(tmp_path, mode="wall", present=False, available=False)
    assert power["mode"] == "wall"
    assert power["source"] == "unknown"

    tile = _view("powerTile", power)
    assert tile["value"] == _EMDASH
    assert tile["detail"] == "unavailable"
    assert "wall" not in tile["detail"]
    # The glyph IS honest and IS distinct from both real states -- the story's
    # END STATE for the header, met today.
    assert _view("powerGlyphState", power) == "neutral"
    assert _view("powerGlyphState", {"source": "external"}) == "ok"
    assert _view("powerGlyphState", {"source": "battery"}) == "amber"
