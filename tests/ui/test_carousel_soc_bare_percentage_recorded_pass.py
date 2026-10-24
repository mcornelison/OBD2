################################################################################
# File Name: test_carousel_soc_bare_percentage_recorded_pass.py
# Purpose/Description: US-657 (F-138, punch-list 4.3) -- the CIO's 2026-08-31
#   ruling applied to the Battery card's CHARGE tile: a real-but-uncalibrated
#   reading is fit to display as a BARE NUMBER, no qualifier.
#
#   VERIFY OUTCOME: MIXED, and the split is the point of this file.
#
#     * THE VALUE PASSES. Atlas's punch-list 4.3 reading (soc 96 with
#       socCalibrated:false) paints "96%" -- a bare percentage, no hedge on the
#       value, at the `neutral` level. Recorded below.
#     * THE NEGATIVE CASE PASSES. An unreadable gauge takes the WHOLE card to a
#       typed NA carrying "gauge unreadable", with no percent left standing --
#       and it does so on a panel that was already showing 96%.
#     * THE TILE FAILS. Beside that bare value the tile paints a DETAIL line
#       reading "(uncalibrated)". MEASURED on the shipped panel, not inferred
#       from the source: the CHARGE tile renders
#           ['CHARGE', '96%', '(uncalibrated)']
#       "(uncalibrated)" is the first word in the hedge vocabulary US-656
#       established for this same ruling, so validationCriteria 1's "no
#       qualifier" is NOT met at the tile.
#
#   THE US-656 LINE THIS TURNS ON, restated because it is the whole judgement.
#   That story admitted the HEADING tile's detail "magnetic" as legitimate: it
#   names the reference frame, which is a fact about the QUANTITY, like a unit.
#   "(uncalibrated)" is a claim about how well the quantity was MEASURED, which
#   is exactly what the ruling removes. Same sprint, same ruling, opposite side
#   of the same line -- and US-656 already killed a mutation that relabelled its
#   detail "uncalibrated", so treating this one as a pass would contradict a
#   guard already standing in this suite.
#
#   ⚠️ THE EXAMPLE IS HISTORICAL AS OF US-697; THE DISTINCTION IS NOT. The CIO
#   removed "magnetic" from the HEADING tile on 2026-09-09 -- on CLUTTER grounds
#   (one less thing to read at arm's length), NOT because it was reclassified as
#   a hedge. So the frame-vs-confidence line above still decides this file's
#   finding, and the tile it was drawn on no longer carries the illustration.
#   Do not read the removal as US-656 having been overturned.
#
#   AND IT IS NOT EVEN CONDITIONAL. `socCalibrated` is HARDCODED False at the
#   single writer of this state file (card_state_emitter.py:763, whose own
#   docstring says "no claimed calibration"), so socTile's `"register"` branch is
#   unreachable in production. The tag is not a calibration report the driver can
#   act on -- it is a constant string appended to every SOC reading the shipped
#   producer can ever emit. Pinned below in both directions.
#
#   RECORDED, NOT FIXED, per the story's own instruction ("IF THE BEHAVIOUR IS
#   WRONG, record the finding and file a fix story") and because the fix reaches
#   specs/architecture.md:4375, which documents the tag and is READ-ONLY for
#   Ralph. Filed as offices/pm/issues/I-us657-the-charge-tile-hedges-a-reading-
#   the-ruling-says-to-show-plainly.md.
#
#   THE test_characterisation_* TESTS BELOW PIN BEHAVIOUR THAT IS WRONG. Whoever
#   applies the fix will fail them ON PURPOSE. RE-RECORD THEM, DO NOT RELAX THEM
#   -- a stale measurement sitting green in a suite is worse than none.
#
#   Everything here runs the REAL chain: MAX17048 register words on a fake I2C
#   wire -> the REAL UpsMonitor -> the REAL orchestrator emit tick -> the REAL
#   emitter -> a real state file on disk -> the SHIPPED carousel.js -> the
#   SHIPPED markup + stylesheet at 480x320. Not socTile() in isolation: the
#   US-494/495/498 defects were all two-correct-halves with no test on the join.
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
# 2026-08-31    | Ralph (Rex)  | Initial -- US-657 punch-list 4.3: the bare
#               |              | percentage recorded, the tile hedge characterised.
# 2026-10-23    | Ralph (Rex)  | MOVED PIN (US-894-e): the Battery card is retired.
#               |              | The SOC is the parked UPS detail's line
#               |              | `≈ 96 % (modelled[, uncalibrated])` (spec s4.6.1,
#               |              | Iris I6 -- the caveat survives by ruling), never
#               |              | on the UPS row. Characterisations re-recorded.
# ================================================================================
################################################################################

"""US-657 tests: the CHARGE tile's bare percentage, and the qualifier beside it."""

from __future__ import annotations

import json
import os
import re
import shutil
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
from pi.obdii.gear_derivation import GEAR_PARK, REASON_PARK, GearReading  # noqa: E402
from pi.obdii.gear_state_emitter import buildGearState  # noqa: E402
from pi.obdii.orchestrator.card_state_emitter import (  # noqa: E402
    CardStateEmitterMixin,
)
from pi.splash.system_status_emitter import buildSystemStatusState  # noqa: E402

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The shipped panel, not the harness default.
PANEL = (480, 320)

# Spelled as named constants, never inline -- this file is written and re-read on
# a Windows SMB share where raw non-ASCII copy has been mangled before.
EM_DASH = "—"
APPROX = "≈"
MIDDOT = "·"
# MOVED PIN (US-894-e): the page's one no-data mark (spec s4.4).
NO_DATA = "--"

CELL = "CELL"
CHARGE = "CHARGE"
BATTERY_LABEL = "Pi UPS battery"
REASON_GAUGE_UNREADABLE = "gauge unreadable"

# ---------------------------------------------------------------------------
# Atlas's punch-list 4.3 reading, expressed as the REGISTER WORDS a MAX17048
# would have to hold to produce it -- the only honest way to state the fixture
# for a story whose claim is that the value is "REAL and live from the MAX17048".
#   SOC: the HIGH byte is the integer percent, the low byte is 1/256 % and is
#        dropped -- 0x6040 is 96.25 %, published as 96.
# ---------------------------------------------------------------------------
ATLAS_VCELL_RAW = 53299
ATLAS_VCELL_PRINTED = "4.16 V"
ATLAS_SOC_RAW = 0x6040
ATLAS_SOC_PERCENT = 96
# MOVED PIN (US-894-e): the percent as the UPS detail's SOC line prints it.
ATLAS_SOC_PRINTED = "96 %"

# A DIFFERENT percent, reachable by moving the SOC register ALONE. Used to prove
# the printed percent tracks the register rather than the voltage.
OTHER_SOC_RAW = 0x2A00
OTHER_SOC_PERCENT = 42
OTHER_SOC_PRINTED = "42 %"

# A genuinely FLAT pack. 0 is a LEGAL reading from this register, not a sentinel,
# and the ruling's "never 0%" cannot be read as a ban on the digit -- see
# test_aRealZeroPercentIsRenderedAndAnUnreadableGaugeIsNot.
FLAT_VCELL_RAW = 44800
FLAT_SOC_RAW = 0x0000
FLAT_SOC_PRINTED = "0 %"

CRATE_DISABLED_ON_THIS_CHIP = 0xFFFF

# MOVED PIN (US-894-e): spec s4.6.1 (Iris I6) -- the SOC line's two forms.
SOC_UNCALIBRATED_TAIL = "(modelled, uncalibrated)"
SOC_CALIBRATED_TAIL = "(modelled)"

# The hedge vocabulary, carried over VERBATIM from US-656's file so this ruling is
# enforced by ONE vocabulary across the panel rather than two that can drift. The
# ruling is a rule about what must NOT be on the tile, so it is asserted as a
# vocabulary rather than an equality: an equality passes the day someone appends
# " (approx)" that nobody re-read the assertion for.
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


def _hedgesIn(text: str) -> list[str]:
    """Every hedge token present in `text`, case-insensitively."""
    low = text.lower()
    found = [w for w in _HEDGE_WORDS if w in low]
    found += [m for m in _HEDGE_MARKS if m in text]
    return found


# ---------------------------------------------------------------------------
# The wire. `readWord` is the SMBus contract: 16-bit registers arrive
# LITTLE-endian and UpsMonitor byte-swaps them back, so the fixture stores what
# the CHIP holds and hands the monitor the swapped form -- otherwise the test
# would supply the monitor's own answer and the swap would never be exercised.
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


def _gauge(**registers: int) -> UpsMonitor:
    """A REAL UpsMonitor over a fake bus, keyed by register NAME for readability."""
    byAddress = {
        REGISTER_VCELL: registers["vcell"],
        REGISTER_SOC: registers["soc"],
        REGISTER_CRATE: registers.get("crate", CRATE_DISABLED_ON_THIS_CHIP),
    }
    return UpsMonitor(i2cClient=_FakeI2c(byAddress))


def _atlasGauge(**overrides: int) -> UpsMonitor:
    args: dict[str, int] = {"vcell": ATLAS_VCELL_RAW, "soc": ATLAS_SOC_RAW}
    args.update(overrides)
    return _gauge(**args)


def _deadGauge() -> UpsMonitor:
    """A gauge whose every register read fails -- the chip absent or unpowered."""
    return UpsMonitor(i2cClient=_FakeI2c({}))


# ---------------------------------------------------------------------------
# The REAL acquisition path. `buildBatteryHealthState` is only the third link in
# the chain; the readings are taken one layer UP, in the orchestrator's
# `_emitBatteryHealthState`, which is where the gauge is consulted, where the
# unreadable-gauge decision is made, and where `socCalibrated` is pinned to
# False. A test that starts at the builder cannot see any of the three.
# ---------------------------------------------------------------------------


class _Orch(CardStateEmitterMixin):
    """The minimal composing object the mixin reads, as the orchestrator does."""

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


def _emit(tmp_path, upsMonitor: Any) -> dict:
    """Run the REAL orchestrator emit tick and return what it wrote to disk."""
    statesDir = tmp_path / "states"
    orch = _Orch(str(statesDir), upsMonitor=upsMonitor)
    orch._initializeCardStateEmitters()
    assert orch._maybeEmitCardStates() is True, "the emitter wrote nothing"
    return json.loads((statesDir / "battery-health").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Reading the rendered panel.
#
# MOVED PIN (US-894-e): the Battery card is RETIRED (spec s4.5 / s4.6.1). The
# cell voltage is the System page's UPS row value; the SOC is the parked UPS
# detail's line. The helpers render the System page with a parked gear, open
# the UPS detail, and read the row and the detail together.
# ---------------------------------------------------------------------------

# A fixed page clock, later than any stamp the real emitter writes, so the
# row's freshness age is deterministic whatever day this runs.
_NOW_ISO = "2030-01-01T00:00:00Z"
_NOW_MS = 1893456000000
_OPEN_UPS = [{"clickNth": {"selector": ".sys-row", "index": 3}}, {"flush": 1}]


def _surface(payload: Any, steps: list[dict[str, Any]] | None = None):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet, parked,
    with the UPS detail open; `steps` run after it opened."""
    routes: dict[str, Any] = {
        "/system-status": buildSystemStatusState(
            syncLastOkTs=_NOW_ISO, syncStale=False, powerSource="external",
            driveState="idle", driveId=None, nowIso=_NOW_ISO,
        ),
        "/gear": buildGearState(GearReading(True, GEAR_PARK, REASON_PARK), nowIso=_NOW_ISO),
    }
    if payload is not None:
        routes["/battery-health"] = payload
    allSteps = [{"flush": 4}, {"advanceMs": 9000, "flush": 4}] + _OPEN_UPS + (steps or [])
    tree = rh.runDashboard(routes=routes, steps=allSteps, viewport=PANEL, nowMs=_NOW_MS)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _textOf(node: dict) -> list[str]:
    out: list[str] = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


def _classes(path: list[dict]) -> set[str]:
    return set((path[-1].get("attrs", {}).get("class") or "").split())


def _child(path: list[dict], cls: str):
    """The first descendant path carrying `cls`, or None."""
    stack = [path]
    while stack:
        cur = stack.pop(0)
        if cur is not path and cls in _classes(cur):
            return cur
        for child in cur[-1].get("children", []):
            if "text" not in child:
                stack.append(cur + [child])
    return None


def _upsRow(surface):
    for path in surface.pathsByClass("sys-row"):
        if path[-1].get("attrs", {}).get("data-row") == "ups":
            return path
    return None


def _cardPath(surface):
    """The UPS row (the surface every reading here starts from)."""
    return _upsRow(surface)


def _cardText(payload: Any, steps: list[dict[str, Any]] | None = None) -> list[str]:
    """Every word the UPS row and the open UPS detail paint, in reading order.

    Read from the surface DOWN rather than line by line, because the absence
    assertions here ("no percent anywhere") are claims about the WHOLE surface
    -- a stale reading that migrated into a label or a stray line would slip
    past a per-line lookup.
    """
    surface = _surface(payload, steps)
    row = _upsRow(surface)
    body = surface.pathById("sys-detail-body")
    out = _textOf(row[-1]) if row is not None else []
    return out + (_textOf(body[-1]) if body is not None else [])


def _cellText(payload: Any, steps: list[dict[str, Any]] | None = None) -> list[str]:
    """The reading surfaces only: the row's value and the detail's CELL / SOC
    lines. The row's sentence carries the payload's AGE, a different fact, so a
    digit sweep over it would measure the clock, not the reading."""
    surface = _surface(payload, steps)
    out: list[str] = []
    row = _upsRow(surface)
    if row is not None:
        value = _child(row, "sys-row-value")
        if value is not None:
            out.extend(_textOf(value[-1]))
    for label in ("CELL", "SOC"):
        fact = _fact(surface, label)
        if fact is not None:
            out.append(fact["value"])
    return out


def _fact(surface, label: str):
    """The UPS detail fact line whose printed label is `label`, or None."""
    for path in surface.pathsByClass("data-fact-row"):
        head = _child(path, "sys-diag-label")
        if head is None or " ".join(_textOf(head[-1])) != label:
            continue
        if not surface.rendered(path):
            continue
        value = _child(path, "sys-diag-text")
        declaration = surface.winningDeclaration(value, "color") if value else None
        text = " ".join(_textOf(value[-1])) if value else ""
        return {
            "value": text,
            "text": [label, text],
            "allText": text,
            "colour": declaration[0] if declaration else "",
        }
    return None


def _tile(payload: Any, label: str, steps: list[dict[str, Any]] | None = None):
    """The reading the operator sees under `label`, or None.

    CELL is the UPS row's value (`detail` = the row's sentence); CHARGE is the
    UPS detail's SOC line; any other label is looked up among the detail's
    fact lines, so a nonsense label resolves to None rather than a neighbour.
    """
    surface = _surface(payload, steps)
    if label == CELL:
        row = _upsRow(surface)
        word = _child(row, "sys-row-word") if row is not None else None
        if word is None:
            return None
        sentence = _child(row, "sys-row-sentence")
        value = " ".join(_textOf(word[-1]))
        detail = " ".join(_textOf(sentence[-1])) if sentence else ""
        return {"value": value, "detail": detail, "allText": value + " " + detail}
    return _fact(surface, "SOC" if label == CHARGE else label)


def _socOf(value: str) -> int | None:
    """The integer percent of a SOC line `≈ 96 % (modelled...)`, else None."""
    m = re.match(r"^" + APPROX + r" (\d+) % \(modelled", value)
    return int(m.group(1)) if m else None


# A panel that reads a good gauge, then reads a state file the producer has
# rewritten because the gauge died under it. This is what "never a stale value
# shown as current" means to the driver: not "an NA payload renders NA" -- which
# is trivially true of a fresh boot -- but "the number that was on the screen a
# second ago is gone".
def _thenReplacedWith(payload: Any) -> list[dict[str, Any]]:
    return [{"flush": 4}, {"setRoutes": {"/battery-health": payload}}, {"flush": 4}]


# The control for the above: the same two-step render with the file left alone,
# so a harness whose second step reset everything unconditionally cannot pass the
# replacement tests while proving nothing.
_THEN_KEPT = [{"flush": 4}, {"flush": 4}]


def _digitsOf(texts: list[str]) -> str:
    return "".join(ch for ch in " ".join(texts) if ch.isdigit())


# ===========================================================================
# NEGATIVE CONTROLS FIRST. Several assertions below are absence-shaped ("no
# percent on the card", "the hedge is gone"), and every one of them passes
# vacuously if the harness reads nothing at all.
# ===========================================================================


def test_theBatteryCardActuallyRendersBeforeAnythingIsClaimedAboutIt(tmp_path):
    """
    Given: Atlas's live gauge reading
    When:  the shipped panel is booted at 480x320
    Then:  the UPS row is present AND painted, and the UPS detail opened

    Without this every absence assertion in the file is satisfied by a probe
    that found no surface at all. MOVED PIN (US-894-e): the Battery card is the
    UPS row + detail now.
    """
    payload = _emit(tmp_path, _atlasGauge())
    surface = _surface(payload)
    row = _cardPath(surface)

    assert row is not None, "no UPS row in the rendered tree"
    assert surface.rendered(row), "the UPS row is in the tree but not painted"
    assert _textOf(surface.pathById("sys-detail-head")[-1]) == ["UPS"]
    assert BATTERY_LABEL in _textOf(surface.pathById("sys-detail-body")[-1])


def test_theChargeTileIsFoundByItsPrintedLabel(tmp_path):
    """
    Given: Atlas's live gauge reading
    When:  the CHARGE tile is looked up by its printed label
    Then:  it resolves, and a nonsense label does not

    Proves the lookup helper discriminates -- otherwise a tile-shaped assertion
    could be reading its neighbour.
    """
    payload = _emit(tmp_path, _atlasGauge())

    assert _tile(payload, CHARGE) is not None
    assert _tile(payload, "NOT-A-TILE") is None


# ===========================================================================
# THE RECORDED PASS -- validationCriteria 1, the VALUE half.
# ===========================================================================


def test_atlasReadingPaintsTheBarePercentOnTheRenderedPanel(tmp_path):
    """
    Given: a MAX17048 holding Atlas's punch-list 4.3 SOC register word
    When:  the Battery card is rendered at 480x320
    Then:  the UPS detail's SOC line reads "≈ 96 % (modelled, uncalibrated)",
           and the UPS row carries no percent at all

    THE RECORDED PASS, re-stated by MOVED PIN (US-894-e): the number is the
    register's integer, the SOC lives ONLY in the detail (s4.5: never on the
    row), and it always carries its `(modelled` caveat (s4.6.1, Iris I6).
    """
    payload = _emit(tmp_path, _atlasGauge())

    assert payload["soc"] == ATLAS_SOC_PERCENT
    assert payload["socCalibrated"] is False, "Atlas's reading is the uncalibrated one"

    tile = _tile(payload, CHARGE)
    assert tile is not None
    assert tile["value"] == APPROX + " " + ATLAS_SOC_PRINTED + " " + SOC_UNCALIBRATED_TAIL
    cell = _tile(payload, CELL)
    assert "%" not in cell["allText"], cell


def test_theBarePercentValueCarriesNoHedgeOfAnyKind(tmp_path):
    """
    Given: the rendered CHARGE tile on Atlas's reading
    When:  its VALUE is swept for hedge vocabulary and hedge marks
    Then:  the NUMBER carries none -- the hedge lives only in the line's one
           ruled caveat, and the UPS row carries no hedge and no percent

    The ruling as a RULE, not an equality. MOVED PIN (US-894-e): the bare
    number is the `96 %` token; s4.6.1 rules the `≈` and `(modelled...)` caveat
    onto the line, so the sweep runs over the number and the row, never bare.
    """
    payload = _emit(tmp_path, _atlasGauge())
    tile = _tile(payload, CHARGE)

    assert tile is not None
    number = tile["value"][len(APPROX) + 1:].split(" (")[0]
    assert number == ATLAS_SOC_PRINTED, tile
    assert _hedgesIn(number) == [], f"the SOC number hedges: {number!r}"
    cell = _tile(payload, CELL)
    assert _hedgesIn(cell["allText"]) == [], cell
    assert "%" not in cell["allText"], cell


def test_theBarePercentIsShownAtTheNeutralLevelNotAWarningTier(tmp_path):
    """
    Given: a real but uncalibrated SOC reading
    When:  the CHARGE tile's level is read
    Then:  it is --text-secondary (s4.6.1) -- not an alarm tier. MOVED PIN
           (US-894-e): the detail line's resolved colour replaces the tile level.

    The ruling is that an uncalibrated reading is FIT TO DISPLAY. Painting it at
    a degraded level would hedge through the stylesheet what the text no longer
    hedges in words -- the same claim by another channel.
    """
    payload = _emit(tmp_path, _atlasGauge())
    tile = _tile(payload, CHARGE)

    assert tile is not None
    assert tile["colour"] == "var(--text-secondary)", tile


def test_thePrintedPercentTracksTheSocRegisterAndNotTheVoltage(tmp_path):
    """
    Given: two gauges differing ONLY in the SOC register, VCELL held identical
    When:  each is rendered
    Then:  the percent moves 96% -> 42% while the volts stay 4.16 V

    F-8 (voltage-is-not-percent) measured as an INDEPENDENCE. A percent silently
    lerped from cell voltage looks right in every healthy payload -- a 4.16 V
    LiPo really is about 96% -- so no single-payload assertion can tell a
    register read from a formula. This story's claim is that the value is REAL,
    and "real" means it came from the register it says it came from.
    """
    atlas = _emit(tmp_path / "a", _atlasGauge())
    other = _emit(tmp_path / "b", _atlasGauge(soc=OTHER_SOC_RAW))

    assert _socOf(_tile(atlas, CHARGE)["value"]) == ATLAS_SOC_PERCENT
    assert _socOf(_tile(other, CHARGE)["value"]) == OTHER_SOC_PERCENT
    # The voltage did NOT move: the two readings are independent.
    assert _tile(atlas, CELL)["value"] == ATLAS_VCELL_PRINTED
    assert _tile(other, CELL)["value"] == ATLAS_VCELL_PRINTED


def test_thePercentIsAnIntegerWithNoFabricatedPrecision(tmp_path):
    """
    Given: a SOC register word whose low byte carries a 0.25% fraction
    When:  the percent is rendered
    Then:  it reads "96%" -- no decimal point

    The MAX17048's low byte is 1/256%, well below what the gauge is accurate to.
    Printing "96.25%" would dress an uncalibrated reading in precision it has
    not got, which is the mirror image of the hedge this story is about: both
    misreport confidence, one downward and one upward.
    """
    payload = _emit(tmp_path, _atlasGauge())
    tile = _tile(payload, CHARGE)

    assert tile is not None
    assert "." not in tile["value"], f"fabricated precision: {tile['value']!r}"
    assert _socOf(tile["value"]) == ATLAS_SOC_PERCENT


# ===========================================================================
# THE RECORDED PASS -- validationCriteria 2, the NEGATIVE case.
# ===========================================================================


def test_anUnreadableGaugeRendersATypedAbsenceWithItsReason(tmp_path):
    """
    Given: a gauge present on the bus whose every register read fails
    When:  the Battery card is rendered
    Then:  the cell is the typed absence `--` carrying "gauge unreadable"

    US-429: the UPS/MAX17048 is a SINGLE source, so an unreadable gauge takes
    every cell line rather than leaving half-readings standing. MOVED PIN
    (US-894-e): the whole-card NA is the row's `--` + reason.
    """
    payload = _emit(tmp_path, _deadGauge())

    assert payload["soc"] is None
    assert payload["source"]["ups"]["available"] is False

    text = _cardText(payload)
    assert _tile(payload, CELL)["value"] == NO_DATA
    assert (NO_DATA + " " + MIDDOT + " " + REASON_GAUGE_UNREADABLE) in " ".join(text)
    assert BATTERY_LABEL in text


def test_anUnreadableGaugeLeavesNoPercentAnywhereOnTheCard(tmp_path):
    """
    Given: an unreadable gauge
    When:  every word the card paints is collected
    Then:  no percent sign appears anywhere on the row or the detail, and no
           digit on the reading surfaces

    Asserted on the WHOLE surface for the percent, at DIGIT level on the
    reading surfaces (MOVED PIN US-894-e: the row's sentence carries the
    payload's age, a different fact): a renderer that coerced a missing reading
    to "0 %" would be caught either way.
    """
    payload = _emit(tmp_path, _deadGauge())
    text = _cardText(payload)

    assert text, "control: the surface must have rendered for this absence to mean anything"
    assert "%" not in " ".join(text), f"a percent survived an unreadable gauge: {text}"
    cells = _cellText(payload)
    assert NO_DATA in cells, cells
    assert _digitsOf(cells) == "", f"a digit survived an unreadable gauge: {cells}"


def test_aRealZeroPercentIsRenderedAndAnUnreadableGaugeIsNot(tmp_path):
    """
    Given: a genuinely FLAT pack (SOC register reads 0) and, separately, a dead gauge
    When:  both are rendered
    Then:  the flat pack paints "≈ 0 % (modelled...)"; the dead gauge paints
           `--` and no SOC line at all -- the two are never confused (MOVED PIN
           US-894-e)

    THE STORY'S "NEVER 0%" RE-STATED AS THE CLAIM IT CAN ACTUALLY BE.

    0 is a LEGAL reading from this register, not a sentinel, so "never 0%" cannot
    be a ban on the digit -- suppressing a real zero would hide a true
    measurement, which is US-565 in reverse and would blank the tile at exactly
    the moment the pack is about to die. This is the same collision US-656 hit
    with a heading of 0 degrees (due north is a real bearing), and it resolves
    the same way: stop testing for the sentinel, and start testing that a real
    reading and an absence are TOLD APART.

    What "never 0%" must mean is therefore: a MISSING reading is never DRESSED as
    0%. Both halves are asserted here, together, because either alone is
    satisfiable the wrong way.
    """
    flat = _emit(tmp_path / "flat", _gauge(vcell=FLAT_VCELL_RAW, soc=FLAT_SOC_RAW))
    dead = _emit(tmp_path / "dead", _deadGauge())

    # A real zero is a reading, and it is SHOWN.
    assert flat["soc"] == 0
    flatTile = _tile(flat, CHARGE)
    assert flatTile is not None, "a flat pack must still have a SOC line"
    assert _socOf(flatTile["value"]) == 0, flatTile
    assert flatTile["colour"] == "var(--text-secondary)", flatTile

    # An absent reading is NOT dressed as that same zero.
    deadText = _cardText(dead)
    assert FLAT_SOC_PRINTED not in " ".join(deadText)
    assert _tile(dead, CHARGE) is None, "an unreadable gauge must have no SOC line"

    # And the two rendered cards are not the same card.
    assert _cardText(flat) != deadText


def test_theLiveReadingDoesNotSurviveTheGaugeThatProducedIt(tmp_path):
    """
    Given: a panel driven live at 96% for four poll rounds
    When:  the gauge dies under it and the producer rewrites the state file
    Then:  96 is gone, replaced by the typed absence `--` + reason (US-894-e)

    "Never a stale value shown as current", tested as a REPLACEMENT rather than
    as a cold boot. "An NA payload renders NA" is trivially true of a fresh boot
    and a card that never repainted would pass it; the claim the story actually
    makes is that the number the driver was reading a second ago is gone.
    """
    live = _emit(tmp_path / "live", _atlasGauge())
    dead = _emit(tmp_path / "dead", _deadGauge())

    after = _cardText(live, steps=_thenReplacedWith(dead))

    assert after, "the surface must still render after the replacement"
    assert ATLAS_SOC_PRINTED not in " ".join(after), f"stale percent held: {after}"
    cells = _cellText(live, steps=_thenReplacedWith(dead))
    assert str(ATLAS_SOC_PERCENT) not in _digitsOf(cells), f"stale digits held: {cells}"
    assert NO_DATA in cells, cells
    assert REASON_GAUGE_UNREADABLE in " ".join(after)


def test_theControlProvesTheSecondRenderIsNotABlanketReset(tmp_path):
    """
    Given: the same two-step render as above with the state file left ALONE
    When:  the card is read after the second flush
    Then:  96% is still there

    Without this control the replacement test above passes on a harness whose
    second step simply wipes the panel, proving nothing about staleness.
    """
    live = _emit(tmp_path, _atlasGauge())

    after = _cardText(live, steps=_THEN_KEPT)

    assert ATLAS_SOC_PRINTED in " ".join(after)


def test_aVanishedStateFileDoesNotLeaveThePercentStanding(tmp_path):
    """
    Given: a panel showing 96% whose state file then disappears entirely
    When:  the card is read
    Then:  no percent is left standing

    A different failure mode from a dead gauge -- the producer stopped rather
    than reported -- and it must not be the one shape where a stale reading
    lingers. A lingering percent is indistinguishable from a live one, so this
    failure is invisible on the panel by construction.
    """
    live = _emit(tmp_path, _atlasGauge())

    after = _cardText(live, steps=_thenReplacedWith(None))

    assert ATLAS_SOC_PRINTED not in " ".join(after), f"percent lingered: {after}"


# ===========================================================================
# THE FINDING -- characterisation. These pin behaviour that is WRONG under the
# CIO's ruling. Whoever fixes it FAILS THESE ON PURPOSE; re-record them, do not
# relax them. See offices/pm/issues/I-us657-*.md.
# ===========================================================================


def test_characterisation_theChargeTilePaintsAnUncalibratedQualifier(tmp_path):
    """
    Given: Atlas's live, real, uncalibrated SOC reading
    When:  the UPS detail's SOC line is read off the rendered panel
    Then:  it paints "(modelled, uncalibrated)" after the number

    RE-RECORDED, MOVED PIN (US-894-e): the CHARGE tile retired with the Battery
    card; spec s4.6.1 (Iris I6) keeps the shipped uncalibrated caveat on the UPS
    detail's SOC line, BY RULING. The finding below is history for the tile.

    THE FINDING, MEASURED. validationCriteria 1 asks for "a bare percentage, no
    qualifier". The VALUE is bare; the TILE is not. The driver reads
    "CHARGE / 96% / (uncalibrated)".

    WHY THIS IS A QUALIFIER AND "magnetic" (US-656) WAS NOT: "magnetic" named the
    reference frame, a fact about the QUANTITY, like a unit. "(uncalibrated)" is
    a claim about how well the quantity was MEASURED -- precisely what the CIO's
    ruling removes as clutter at 480x320. (US-697 has since taken "magnetic" off
    the HEADING tile on clutter grounds, which does not move the line: a frame
    label is still not a hedge, it just is not worth the pixels there.)

    FAIL THIS ON PURPOSE when the qualifier goes.
    """
    payload = _emit(tmp_path, _atlasGauge())
    tile = _tile(payload, CHARGE)

    assert tile is not None
    assert tile["value"].endswith(" " + SOC_UNCALIBRATED_TAIL), (
        "RE-RECORD THIS TEST -- the SOC line's caveat changed: "
        f"{tile['value']!r}"
    )


def test_characterisation_theChargeTileStillHedgesUnderTheSharedVocabulary(tmp_path):
    """
    Given: the whole rendered CHARGE tile on a live reading
    When:  it is swept with the SAME hedge vocabulary US-656 applied to HEADING
    Then:  a hedge IS found -- the s4.6.1 caveat (MOVED PIN US-894-e: the SOC
           line in the UPS detail)

    The vocabulary is shared with US-656 deliberately: one ruling, one
    vocabulary, so the two tiles cannot drift apart in what they consider a
    hedge. On HEADING this sweep passes clean; here it does not, and that
    difference IS the finding.

    FAIL THIS ON PURPOSE when the qualifier goes -- then this file's sweep should
    be flipped to the US-656 form (assert no hedges) rather than deleted.
    """
    payload = _emit(tmp_path, _atlasGauge())
    tile = _tile(payload, CHARGE)

    assert tile is not None
    assert _hedgesIn(tile["allText"]) == ["uncalibrated", "calibrat"], (
        "RE-RECORD THIS TEST -- the CHARGE tile's hedge vocabulary changed: "
        f"{tile['allText']!r}"
    )


def test_theHedgeSweepIsDiscriminatingAndNotABlanketDetailBan(tmp_path):
    """
    Given: the UPS row (value + sentence) and the detail's "Pi UPS battery"
           label line
    When:  the same hedge sweep is applied to them
    Then:  it finds nothing (MOVED PIN US-894-e: the CELL tile is the UPS row)

    NOT a characterisation -- a CONTROL, and a load-bearing one. Without it the
    sweep above could be flagging the mere PRESENCE of a detail line, which would
    make the finding an artefact of the test rather than a property of the tile.
    A detail that names the SOURCE of a quantity is legitimate -- which is what
    "Pi UPS battery" does here, and it is the live example now that US-697 has
    removed the HEADING tile's "magnetic".
    """
    payload = _emit(tmp_path, _atlasGauge())
    cell = _tile(payload, CELL)

    assert cell is not None
    assert cell["value"] == ATLAS_VCELL_PRINTED
    assert _hedgesIn(cell["allText"]) == [], cell
    assert BATTERY_LABEL in _cardText(payload)
    assert _hedgesIn(BATTERY_LABEL) == []


def test_characterisation_theQualifierIsUnconditionalBecauseNoProducerCalibrates(
    tmp_path,
):
    """
    Given: the SINGLE writer of states/battery-health, across three live readings
    When:  socCalibrated is read off each emitted payload
    Then:  it is False every time -- hardcoded, never measured

    THE FINDING'S SECOND HALF, and it is what makes the tag worse than a
    conditional label. `socCalibrated` is pinned to False at
    card_state_emitter.py:763 (its docstring: "no claimed calibration"), so the
    tag is not a calibration report the driver can act on -- it is a CONSTANT
    appended to every SOC reading the shipped producer can ever emit. There is no
    state of the vehicle, the pack or the gauge that removes it.

    FAIL THIS ON PURPOSE if a producer is ever wired to the real cold-start
    calibration window in src/pi/power/soc_calibration.py.
    """
    for name, gauge in (
        ("atlas", _atlasGauge()),
        ("other", _atlasGauge(soc=OTHER_SOC_RAW)),
        ("flat", _gauge(vcell=FLAT_VCELL_RAW, soc=FLAT_SOC_RAW)),
    ):
        payload = _emit(tmp_path / name, gauge)
        assert payload["socCalibrated"] is False, f"{name}: socCalibrated moved"
        assert _tile(payload, CHARGE)["value"].endswith(" " + SOC_UNCALIBRATED_TAIL), name


def test_characterisation_theCalibratedBranchIsUnreachableFromTheProducer(tmp_path):
    """
    Given: a payload HAND-FORCED to socCalibrated:true -- which no producer writes
    When:  it is rendered
    Then:  the SOC line paints "(modelled)" instead (MOVED PIN US-894-e: the
           retired tile's "register")

    Records that the branch EXISTS and what it would paint, so the finding above
    is a statement about the PRODUCER rather than about dead renderer code. Both
    halves matter to whoever sizes the fix: removing the qualifier means removing
    a two-way conditional whose true side has never once been taken in
    production.

    The hand-written payload is deliberate and is the ONLY one in this file --
    the state it describes is unreachable through the real chain, which is
    exactly the fact being recorded.
    """
    payload = _emit(tmp_path, _atlasGauge())
    assert payload["socCalibrated"] is False, "the producer's real answer"

    payload["socCalibrated"] = True
    tile = _tile(payload, CHARGE)

    assert tile is not None
    assert _socOf(tile["value"]) == ATLAS_SOC_PERCENT, "the value does not move with the tag"
    assert tile["value"] == APPROX + " " + ATLAS_SOC_PRINTED + " " + SOC_CALIBRATED_TAIL


def test_characterisation_theSuiteItselfPinsTheQualifierInTheDeployKit():
    """
    Given: tests/deploy/test_dashboard_kit.py
    When:  it is read
    Then:  it still asserts the "(uncalibrated)" tag is present

    NOT a defect in that file -- it correctly recorded the behaviour of its day.
    It is recorded HERE because it sizes the fix: removing the qualifier turns
    that assertion red, so a fix confined to carousel.js breaks the deploy-kit
    gate. Whoever takes the fix story needs both files and the architecture spec
    (specs/architecture.md, which documents the tag and is read-only for Ralph).

    FAIL THIS ON PURPOSE when that assertion is retired alongside the fix.
    """
    kit = os.path.join(_REPO, "tests", "deploy", "test_dashboard_kit.py")
    with open(kit, encoding="utf-8") as handle:
        source = handle.read()

    # MOVED PIN (US-894-e): re-recorded. The kit's US-401 script moved to the
    # UPS detail's SOC line and now asserts the spec s4.6.1 caveat verbatim.
    assert "(modelled, uncalibrated)" in source, (
        "RE-RECORD THIS TEST -- the deploy kit's uncalibrated assertion moved or "
        "was retired. If it was retired as part of the US-657 fix, that is correct."
    )
