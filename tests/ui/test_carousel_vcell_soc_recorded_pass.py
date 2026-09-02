################################################################################
# File Name: test_carousel_vcell_soc_recorded_pass.py
# Purpose/Description: US-639 (F-138, punch-list 4.1) -- RECORD THE PASS on VCELL
#   and SOC rendering live from the MAX17048, ON THE RENDERED PANEL and through
#   the REAL acquisition path, starting at the fuel gauge's own registers.
#
#   WHY THIS FILE EXISTS WHEN THE TILES ARE "ALREADY TESTED". Every assertion on
#   the CELL and CHARGE tiles in this repository today is made on a HAND-WRITTEN
#   dict passed straight to the pure view through carousel_probe.js --
#   test_carousel_battery_health_verdict.py:75, test_carousel_source_cards.py:166,
#   test_carousel_honest_availability.py:132, test_carousel_idle_home.py:155,
#   test_carousel_card_set.py:152. Not one of them renders a pixel, and not one of
#   them contains a fuel gauge, an orchestrator or a state file. Two of the
#   fixtures that DO reach the render harness spell the key `vcell`
#   (test_render_regression.py:110, test_dashboard_animation_gating.py:97) -- the
#   emitter's key is `vcellV`, so those payloads carry no cell voltage at all and
#   would render identically with the tile deleted.
#
#   So the chain this story names -- "live from the MAX17048" -- had never been
#   composed anywhere. This file composes it: MAX17048 register words on a fake
#   I2C wire -> the REAL UpsMonitor (byte-swap + 78.125 uV/LSB scale + SOC high
#   byte) -> the REAL orchestrator emit tick -> the REAL battery-health emitter ->
#   a real state file on disk -> the SHIPPED carousel.js -> the SHIPPED markup and
#   stylesheet at 480x320.
#
#   THE PASS IS REAL AND IS RECORDED BELOW. Atlas's punch-list 4.1 observation
#   (4.164 V / 96 %, "real and live") is CORRECT, and correct all the way to the
#   panel: the CELL tile paints "4.16 V" and the CHARGE tile paints "96%", both
#   at the `neutral` level, from register words a real chip would put on the bus.
#   An unreadable gauge paints the whole card as a typed NA carrying the reason,
#   and it does so ON A PANEL THAT WAS ALREADY SHOWING 4.16 V -- the reading does
#   not survive the instrument that produced it.
#
#   THE LOAD-BEARING PIN IS F-8, VOLTAGE-IS-NOT-PERCENT, MEASURED AS AN
#   INDEPENDENCE. A percent silently lerped from cell voltage looks right in every
#   healthy payload -- a 4.16 V LiPo really is around 96 % -- so no single-payload
#   assertion can tell a register read from a formula. It is pinned here by moving
#   ONE register at a time: the SOC register alone moves the percent with the
#   voltage held still, and the VCELL register alone moves the volts with the
#   percent held still. Both directions, because a derivation could run either way.
#
#   MEASURED AND RECORDED, NOT FILED AS A DEFECT (see the foot of this file): the
#   F-8 volts-only fallback -- `socTile(shown:false)`, the branch that omits the
#   percent and leaves the voltage standing -- CANNOT BE PRODUCED by the shipped
#   producer. There is exactly one writer of this state file, and it reads VCELL
#   and SOC inside one `try`, so a SOC register failure takes the whole card to NA
#   and a readable voltage with it. The branch is honest defense-in-depth against a
#   future second producer, and the existing test of it
#   (test_carousel_source_cards.py:327) can only ever be satisfied by a
#   hand-written payload. Characterised here so the fact is recorded rather than
#   remembered; filed as offices/pm/tech_debt/TD-us639-the-f8-volts-only-fallback-
#   has-no-producer.md.
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
# 2026-08-31    | Ralph (Rex)  | Initial -- US-639 punch-list 4.1 recorded pass +
#               |              | the unreachable-F-8-fallback characterisation.
# ================================================================================
################################################################################

"""US-639 tests: VCELL and SOC, from the fuel gauge's registers to the panel."""

from __future__ import annotations

import json
import os
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
    MAX17048_VCELL_LSB_V,
    REGISTER_CRATE,
    REGISTER_SOC,
    REGISTER_VCELL,
    UpsMonitor,
)
from pi.obdii.orchestrator.card_state_emitter import (  # noqa: E402
    CardStateEmitterMixin,
)
from pi.splash.source_availability import REASON_UPS_UNREADABLE  # noqa: E402

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
# precaution US-633's and US-638's files both take).
EM_DASH = "—"
MIDDOT = "·"

# ---------------------------------------------------------------------------
# Atlas's punch-list 4.1 reading, expressed as the REGISTER WORDS a MAX17048
# would have to hold to produce it -- which is the only honest way to state the
# fixture for a story whose claim is "live from the MAX17048".
#
#   VCELL: 4.164 V / 78.125 uV per LSB = 53299.2 -> 53299 (0xD033), which the
#          chip's own scale turns back into 4.163984375 V.
#   SOC:   the HIGH byte is the integer percent, the low byte is 1/256 % and is
#          dropped -- 0x6040 is 96.25 %, published as 96.
#   CRATE: 0xFFFF. Not an invention: US-235 recorded this variant returning the
#          disabled sentinel across all four April 2026 drain tests, so this is
#          what the CIO's actual chip puts on the bus.
# ---------------------------------------------------------------------------
ATLAS_VCELL_RAW = 53299
ATLAS_VCELL_VOLTS = ATLAS_VCELL_RAW * MAX17048_VCELL_LSB_V  # 4.163984375
ATLAS_VCELL_PRINTED = "4.16 V"
ATLAS_SOC_RAW = 0x6040
ATLAS_SOC_PERCENT = 96
ATLAS_SOC_PRINTED = "96%"
CRATE_DISABLED_ON_THIS_CHIP = 0xFFFF

# What the SAME wire bytes would print if the big-endian/little-endian swap were
# ever dropped. The module's own docstring records this as a shipped defect
# class; naming the wrong answer is what makes the swap load-bearing here rather
# than incidentally exercised.
UNSWAPPED_VOLTS = (((ATLAS_VCELL_RAW & 0xFF) << 8) | (ATLAS_VCELL_RAW >> 8)) * (
    MAX17048_VCELL_LSB_V
)
UNSWAPPED_PRINTED = f"{UNSWAPPED_VOLTS:.2f} V"

# Tile labels, as the operator reads them.
CELL = "CELL"
CHARGE = "CHARGE"
HEALTH = "HEALTH"
BATTERY_LABEL = "Pi UPS battery"


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
        self.reads: list[tuple[int, int]] = []

    def readWord(self, address: int, register: int) -> int:
        self.reads.append((address, register))
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
# `_emitBatteryHealthState`, which is where the gauge is consulted and where the
# unreadable-gauge decision is actually made. A test that starts at the builder
# cannot see either.
# ---------------------------------------------------------------------------


class _Orch(CardStateEmitterMixin):
    """The minimal composing object the mixin reads, as the orchestrator does.

    Mirrors tests/pi/orchestrator/test_card_state_emitters.py::_FakeOrch. The
    UPS is reached through `self._hardwareManager.upsMonitor` at emit time, which
    is the seam the story's negative case turns on.
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
        # `upsMonitor=None` is the bench/hardware-disabled Pi: a HardwareManager
        # exists, but it never built a gauge. Materially different from a gauge
        # that exists and cannot be read, and both are covered below.
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
# ---------------------------------------------------------------------------


def _surface(payload: Any, steps: list[dict[str, Any]] | None = None):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet."""
    routes: dict[str, Any] = {} if payload is None else {"/battery-health": payload}
    tree = rh.runDashboard(routes=routes, steps=steps, viewport=PANEL)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _textOf(node: dict) -> list[str]:
    out: list[str] = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


def _cardPath(surface):
    for path in surface.paths():
        if path[-1].get("attrs", {}).get("data-state") == "battery-health":
            return path
    return None


def _cardText(payload: Any, steps: list[dict[str, Any]] | None = None) -> list[str]:
    """Every word the Battery card paints, in reading order.

    Read from the card down rather than tile by tile, because the absence
    assertions below ("no voltage anywhere on this card") are claims about the
    WHOLE card -- a stale reading that migrated into the title or a stray tile
    would slip past a per-tile lookup.
    """
    surface = _surface(payload, steps)
    path = _cardPath(surface)
    if path is None or not surface.rendered(path):
        return []
    return _textOf(path[-1])


def _tile(payload: Any, label: str, steps: list[dict[str, Any]] | None = None):
    """The rendered `.tile` on the Battery card whose printed label is `label`.

    Found by its PRINTED LABEL rather than by grid position, so a tile that moved
    in the layout still resolves and a tile that VANISHED returns None instead of
    silently matching its neighbour. Carries the level the stylesheet is keyed on
    AND the colour that level actually resolves to, because "visually distinct"
    is a claim about the panel and a level token only means it while the sheet
    agrees.
    """
    surface = _surface(payload, steps)
    card = _cardPath(surface)
    if card is None:
        return None
    for path in surface.pathsByClass("tile"):
        if not any(node is card[-1] for node in path):
            continue
        printed = _textOf(path[-1])
        if not printed or printed[0] != label:
            continue
        if not surface.rendered(path):
            continue
        value = ""
        detail = ""
        valuePath = None
        for child in path[-1].get("children", []):
            classes = (child.get("attrs", {}).get("class") or "").split()
            if "tile-value" in classes:
                value = " ".join(_textOf(child))
                valuePath = path + [child]
            elif "tile-detail" in classes:
                detail = " ".join(_textOf(child))
        declaration = (
            surface.winningDeclaration(valuePath, "color") if valuePath else None
        )
        return {
            "value": value,
            "detail": detail,
            "level": path[-1].get("attrs", {}).get("data-level"),
            "colour": declaration[0] if declaration else "",
        }
    return None


# A panel that reads a good gauge, then reads a state file the producer has
# rewritten because the gauge died under it. This is what the story's negative
# case means to the driver: not "an NA payload renders NA" -- which is trivially
# true of a fresh boot -- but "the number that was on the screen a second ago is
# gone".
def _thenReplacedWith(payload: Any) -> list[dict[str, Any]]:
    return [{"flush": 4}, {"setRoutes": {"/battery-health": payload}}, {"flush": 4}]


# The control for the above: the same two-step render with the file left alone,
# so a harness whose second step reset everything unconditionally cannot pass the
# replacement tests while proving nothing.
_THEN_KEPT = [{"flush": 4}, {"flush": 4}]


def _digitsOf(texts: list[str]) -> str:
    return "".join(ch for ch in " ".join(texts) if ch.isdigit())


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS FIRST. A large share of the assertions in this file are
# absence-shaped ("no voltage on the card", "the percent did not move"), and
# every one of them passes vacuously if the harness reads nothing at all. A
# renamed class or a probe crash would turn the whole file green while pinning
# nothing.
# ---------------------------------------------------------------------------


def test_theHarnessActuallyReadsBothTiles_negativeControl(tmp_path):
    """
    Given: every "must not" assertion below fails open if a tile is unreadable
    When: Atlas's gauge is rendered on the shipped panel
    Then: the harness reads a real value, level and colour on BOTH tiles.
    """
    payload = _emit(tmp_path, _atlasGauge())

    cell = _tile(payload, CELL)
    assert cell is not None, "no CELL tile in the rendered DOM"
    assert cell["value"] != "", f"harness read no CELL value: {cell!r}"
    assert cell["level"] == "neutral", f"harness read no CELL level: {cell!r}"
    assert cell["colour"] != "", f"harness resolved no CELL colour: {cell!r}"

    charge = _tile(payload, CHARGE)
    assert charge is not None, "no CHARGE tile in the rendered DOM"
    assert charge["value"] != "", f"harness read no CHARGE value: {charge!r}"
    assert charge["level"] == "neutral", f"harness read no CHARGE level: {charge!r}"


def test_theFakeBusIsActuallyRead_negativeControl(tmp_path):
    """
    Given: a fixture that never got consulted would let every value below come
           from a default somewhere downstream instead of from the gauge
    When: one emit tick runs
    Then: the VCELL and SOC registers were both read off the wire, at the
          MAX17048's own I2C address.
    """
    client = _FakeI2c(
        {
            REGISTER_VCELL: ATLAS_VCELL_RAW,
            REGISTER_SOC: ATLAS_SOC_RAW,
            REGISTER_CRATE: CRATE_DISABLED_ON_THIS_CHIP,
        }
    )
    monitor = UpsMonitor(i2cClient=client)
    _emit(tmp_path, monitor)

    registers = [register for _address, register in client.reads]
    assert REGISTER_VCELL in registers, client.reads
    assert REGISTER_SOC in registers, client.reads
    assert {address for address, _r in client.reads} == {0x36}, client.reads


def test_theStylesheetSeparatesALiveReadingFromATypedAbsence(tmp_path):
    """
    Given: this file claims a dead gauge is "visually distinct" from a live one
    When: the shipped stylesheet is resolved for the two levels in question
    Then: `neutral` and `unavailable` do NOT resolve to the same colour.

          Without this, "the level changed" is a claim about a data attribute
          and not about anything the driver can see -- a sheet that painted both
          levels identically would leave this file green while a dead gauge and
          a live one looked the same on the panel.
    """
    surface = _surface(_emit(tmp_path, _atlasGauge()))
    card = _cardPath(surface)
    valuePath = None
    tilePath = None
    for path in surface.pathsByClass("tile"):
        if not any(node is card[-1] for node in path):
            continue
        printed = _textOf(path[-1])
        if printed and printed[0] == CELL:
            tilePath = path
    assert tilePath is not None
    for child in tilePath[-1].get("children", []):
        if "tile-value" in (child.get("attrs", {}).get("class") or "").split():
            valuePath = tilePath + [child]
    assert valuePath is not None

    resolved = {}
    for level in ("neutral", "unavailable"):
        tilePath[-1]["attrs"]["data-level"] = level
        declaration = surface.winningDeclaration(valuePath, "color")
        resolved[level] = declaration[0] if declaration else ""

    assert resolved["neutral"] != resolved["unavailable"], resolved


# ---------------------------------------------------------------------------
# SURFACE A -- VCELL. Atlas's punch-list 4.1 voltage, from the register to the
# panel.
# ---------------------------------------------------------------------------


def test_atlasVcellObservation_reachesThePanelInVolts(tmp_path):
    """
    Given: Atlas's punch-list 4.1 reading -- 4.164 V on a live MAX17048
    When: the shipped panel renders what the shipped producer wrote
    Then: the CELL tile paints "4.16 V", labelled as the Pi's own UPS cell, at
          the `neutral` level.

          THE RECORDED PASS for the voltage half. `neutral` and not `ok`: a cell
          voltage is a reading, not a verdict -- the verdict is the HEALTH tile's
          job and it is deliberately unknown on this Pi.
    """
    tile = _tile(_emit(tmp_path, _atlasGauge()), CELL)

    assert tile is not None
    assert tile["value"] == ATLAS_VCELL_PRINTED, tile
    assert tile["detail"] == BATTERY_LABEL, tile
    assert tile["level"] == "neutral", tile


def test_theVoltageOnThePanelTracksTheRegister_itIsNotAConstant(tmp_path):
    """
    Given: a single-payload assertion cannot tell a live reading from a literal
    When: the VCELL register is moved across the LiPo's real working range
    Then: the printed volts move with it, at the datasheet's 78.125 uV/LSB.

          53760 -> 4.20 V is the top of a healthy charge, 44800 -> 3.50 V is
          well down the discharge curve; a card that printed either of those
          when the chip held the other would be lying about a shutdown margin.
    """
    for raw in (44800, 47000, 53760):
        expected = f"{raw * MAX17048_VCELL_LSB_V:.2f} V"
        tile = _tile(_emit(tmp_path, _atlasGauge(vcell=raw)), CELL)
        assert tile is not None, raw
        assert tile["value"] == expected, (raw, tile)


def test_theBigEndianSwapIsInsideTheRenderedChain(tmp_path):
    """
    Given: MAX17048 registers are big-endian on the wire and SMBus hands them
           back little-endian, and the module's own header records that a
           missing swap once made a full cell read as a wildly wrong voltage
    When: the bytes a real chip would put on the bus are rendered end to end
    Then: the panel prints the SWAPPED reading and never the unswapped one.

          Stated as the wrong answer by name rather than as "a plausible
          voltage": 1.04 V is inside the range a float check would accept and is
          exactly what the panel would print if the swap were dropped.
    """
    texts = _cardText(_emit(tmp_path, _atlasGauge()))

    assert ATLAS_VCELL_PRINTED in texts, texts
    assert UNSWAPPED_PRINTED not in texts, (UNSWAPPED_PRINTED, texts)


def test_theVoltageIsRoundedForThePanel_notPrintedRaw(tmp_path):
    """
    Given: the chip's scale yields 4.163984375 V for Atlas's register word
    When: the tile paints it on a 3.5in panel
    Then: two decimals reach the driver, and the raw float does not.

          Not cosmetic: the tile column is sized for a fixed width, and a
          nine-digit value is the shape that overflows it (the defect US-631
          measured on the neighbouring g-force column).
    """
    tile = _tile(_emit(tmp_path, _atlasGauge()), CELL)

    assert tile is not None
    assert tile["value"] == ATLAS_VCELL_PRINTED, tile
    assert str(ATLAS_VCELL_VOLTS) not in tile["value"], tile


def test_theCellTileSpeaksVoltsAndNeverPercent(tmp_path):
    """
    Given: F-8 forbids the two units being confused in either direction
    When: a gauge reporting 4.16 V at 96 % is rendered
    Then: the CELL tile carries a volts unit and no percent sign, and its value
          is not the SoC number wearing a different unit.
    """
    tile = _tile(_emit(tmp_path, _atlasGauge()), CELL)

    assert tile is not None
    assert tile["value"].endswith(" V"), tile
    assert "%" not in tile["value"], tile
    assert str(ATLAS_SOC_PERCENT) not in tile["value"], tile


# ---------------------------------------------------------------------------
# SURFACE B -- SOC. Atlas's punch-list 4.1 percent, from the register to the
# panel, and proven independent of the voltage.
# ---------------------------------------------------------------------------


def test_atlasSocObservation_reachesThePanelAsPercent(tmp_path):
    """
    Given: Atlas's punch-list 4.1 reading -- 96 % on a live MAX17048
    When: the shipped panel renders what the shipped producer wrote
    Then: the CHARGE tile paints "96%" at the `neutral` level.

          THE RECORDED PASS for the charge half.
    """
    tile = _tile(_emit(tmp_path, _atlasGauge()), CHARGE)

    assert tile is not None
    assert tile["value"] == ATLAS_SOC_PRINTED, tile
    assert tile["level"] == "neutral", tile


def test_thePercentMovesWithTheSocRegisterAlone(tmp_path):
    """
    Given: F-8 -- the percent must come from the SoC register and nowhere else
    When: the SOC register is moved while VCELL is held at Atlas's exact word
    Then: the printed percent follows the register, and the printed volts do not
          move at all.

          Half one of the independence pin. A percent lerped from voltage would
          be FROZEN here while the register swung from 10 % to 100 %.
    """
    for raw, expected in ((0x0A00, "10%"), (0x4000, "64%"), (0xFF00, "100%")):
        payload = _emit(tmp_path, _atlasGauge(soc=raw))
        charge = _tile(payload, CHARGE)
        cell = _tile(payload, CELL)
        assert charge is not None and cell is not None, raw
        assert charge["value"] == expected, (hex(raw), charge)
        assert cell["value"] == ATLAS_VCELL_PRINTED, (hex(raw), cell)


def test_thePercentDoesNotMoveWithTheVcellRegister(tmp_path):
    """
    Given: a derivation could run the other way -- volts inferred INTO a percent
    When: VCELL is swung the full width of the cell's range while the SOC
          register is held at Atlas's exact word
    Then: the printed percent does not move, while the printed volts do.

          Half two, and the one that matters on a draining pack: at 3.50 V a
          voltage-derived percent would read somewhere near empty, and the panel
          would be inventing a shutdown warning the gauge never issued.
    """
    printedVolts = set()
    for raw in (44800, 47000, 53760):
        payload = _emit(tmp_path, _atlasGauge(vcell=raw))
        charge = _tile(payload, CHARGE)
        cell = _tile(payload, CELL)
        assert charge is not None and cell is not None, raw
        assert charge["value"] == ATLAS_SOC_PRINTED, (raw, charge)
        printedVolts.add(cell["value"])

    assert len(printedVolts) == 3, printedVolts


def test_theFractionalLowByteIsDropped_notRoundedUp(tmp_path):
    """
    Given: the SOC register's low byte is 1/256 % and the contract drops it
    When: two words that share a high byte but differ in the low one are read
    Then: both publish the same integer percent -- 96, not 97.

          0x60F0 is 96.94 %, which rounds to 97. Pinning truncation here means
          the panel and the `battery_health_log` cannot disagree by a point over
          a rounding rule nobody wrote down twice.
    """
    for raw in (0x6040, 0x60F0):
        tile = _tile(_emit(tmp_path, _atlasGauge(soc=raw)), CHARGE)
        assert tile is not None, hex(raw)
        assert tile["value"] == ATLAS_SOC_PRINTED, (hex(raw), tile)


def test_theDisabledCrateRegisterDoesNotSuppressTheLiveReadings(tmp_path):
    """
    Given: this MAX17048 variant returns 0xFFFF on CRATE -- US-235 recorded it
           doing so across all four April 2026 drain tests, so it is what the
           CIO's chip actually does
    When: the card is rendered from a chip whose charge-rate register is dead
    Then: both live readings still paint, and no failsafe drain ladder appears.

          A reading must not be gated on a register its own chip does not
          populate; and A-6 forbids a drain ladder without a real drain, so an
          unreadable CRATE must resolve to "no ladder" rather than to a guess.
    """
    payload = _emit(tmp_path, _atlasGauge(crate=CRATE_DISABLED_ON_THIS_CHIP))

    assert payload["crate"] is None, payload
    assert payload["draining"] is False, payload
    assert payload["ladder"] is None, payload
    assert _tile(payload, CELL)["value"] == ATLAS_VCELL_PRINTED
    assert _tile(payload, CHARGE)["value"] == ATLAS_SOC_PRINTED


def test_aLiveGaugeDoesNotBuyAHealthVerdict(tmp_path):
    """
    Given: a perfect live gauge and no drain history to judge it by
    When: the card is rendered
    Then: real numbers and an HONEST unknown verdict stand side by side -- the
          HEALTH tile reads the em-dash at `unavailable` with "never" beside it,
          while CELL and CHARGE carry live values.

          The composition nothing had pinned. Two correct halves in one card is
          exactly where a "the gauge is fine, so the battery is fine" shortcut
          would land, and it would paint a green health claim off a reading that
          says nothing whatever about capacity.
    """
    payload = _emit(tmp_path, _atlasGauge())
    health = _tile(payload, HEALTH)

    assert health is not None
    assert health["value"] == EM_DASH, health
    assert health["level"] == "unavailable", health
    assert health["detail"] == "last health check " + MIDDOT + " never", health
    assert _tile(payload, CELL)["value"] == ATLAS_VCELL_PRINTED
    assert _tile(payload, CHARGE)["value"] == ATLAS_SOC_PRINTED


# ---------------------------------------------------------------------------
# SURFACE C -- THE NEGATIVE CASE, which the story's acceptance criteria make
# mandatory: "when the gauge is unreadable the card shows a typed absence, never
# a last-known value presented as current".
# ---------------------------------------------------------------------------


def test_anUnreadableGaugeRendersATypedAbsenceWithItsReason(tmp_path):
    """
    Given: the MAX17048 stops answering
    When: the card is rendered from what the producer wrote
    Then: the whole card is one NA tile carrying the reason, at the
          `unavailable` level -- not a blank card, and not a bare "unavailable"
          that leaves the driver guessing which instrument went quiet.
    """
    payload = _emit(tmp_path, _deadGauge())
    texts = _cardText(payload)

    assert "NA" in texts, texts
    assert REASON_UPS_UNREADABLE in texts, texts
    assert BATTERY_LABEL in texts, texts
    assert _tile(payload, CELL) is None, "a CELL tile survived a dead gauge"
    assert _tile(payload, CHARGE) is None, "a CHARGE tile survived a dead gauge"


def test_anAbsentGaugeIsAsHonestAsADeadOne(tmp_path):
    """
    Given: a bench Pi whose HardwareManager never built a UPS monitor at all
    When: the card is rendered
    Then: the same typed absence, with the same reason.

          A DIFFERENT code path from the test above -- `ups is None` returns
          before any register is touched -- reaching the same honest end state.
          Pinned separately because a fix to one branch cannot be assumed to
          reach the other.
    """
    texts = _cardText(_emit(tmp_path, None))

    assert "NA" in texts, texts
    assert REASON_UPS_UNREADABLE in texts, texts


def test_noReadingSurvivesTheGaugeThatProducedIt(tmp_path):
    """
    Given: a panel that has been showing 4.16 V / 96 % for several poll rounds
    When: the gauge dies under it and the producer rewrites the state file
    Then: the panel repaints to the typed absence, and NO DIGIT of the old
          reading is left anywhere on the card.

          THE LOAD-BEARING NEGATIVE TEST, and the one the acceptance criterion
          is actually about. "An NA payload renders NA" is true of a cold boot
          and proves nothing -- a card that never repainted would pass it. The
          claim that matters is that the number the driver was reading a second
          ago is GONE, and only a panel that held a real value first can make it.
    """
    live = _emit(tmp_path, _atlasGauge())
    dead = _emit(tmp_path, _deadGauge())

    texts = _cardText(live, steps=_thenReplacedWith(dead))

    assert "NA" in texts, texts
    assert REASON_UPS_UNREADABLE in texts, texts
    assert ATLAS_VCELL_PRINTED not in texts, texts
    assert ATLAS_SOC_PRINTED not in texts, texts
    assert _digitsOf(texts) == "", f"a digit of the dead reading survived: {texts!r}"


def test_theControlProvesTheSecondRoundIsNotAReset(tmp_path):
    """
    Given: the test above would also pass on a harness that blanked the card on
           its second round for any reason at all
    When: the identical two-round render runs with the state file LEFT ALONE
    Then: the live reading is still on the panel.

          Without this, "the value disappeared" is not evidence about the state
          file -- it is evidence about the harness.
    """
    texts = _cardText(_emit(tmp_path, _atlasGauge()), steps=_THEN_KEPT)

    assert ATLAS_VCELL_PRINTED in texts, texts
    assert ATLAS_SOC_PRINTED in texts, texts


def test_aVanishedStateFileTakesTheReadingWithIt(tmp_path):
    """
    Given: the emitter dying, or /run being cleared under a running kiosk
    When: the state file stops answering entirely after a good read
    Then: the card names the silent feed and keeps no digit of the old reading.

          A third distinct failure mode -- 404, not an NA payload -- and the one
          where nothing downstream is left to blank the numbers. It reaches a
          DIFFERENT reason from the two above ("no data", not "gauge
          unreadable"), which is the honest distinction: a file that is not
          there is not the same fact as a chip that will not answer.
    """
    texts = _cardText(_emit(tmp_path, _atlasGauge()), steps=_thenReplacedWith(None))

    assert "NA" in texts, texts
    assert "no data" in " ".join(texts), texts
    assert _digitsOf(texts) == "", f"a digit survived a vanished state file: {texts!r}"


def test_theStateFileCarriesNoReadingWhenTheGaugeIsUnreadable(tmp_path):
    """
    Given: the state file is read by more than the one renderer this file drives
    When: the gauge is unreadable
    Then: the readings are NULL ON DISK, not merely flagged unavailable beside a
          preserved last-real number.

          Pinned at the file and not only at the panel because a stale number
          sitting in the SSOT is a loaded gun for the next consumer: the card
          happens to override it today, and nothing forces the next reader to.

          What this does NOT witness is WHICH layer produced the nulls -- see
          the test below.
    """
    payload = _emit(tmp_path, _deadGauge())

    assert payload["vcellV"] is None, payload
    assert payload["soc"] is None, payload
    assert payload["crate"] is None, payload
    assert payload["source"]["ups"] == {
        "available": False,
        "reason": REASON_UPS_UNREADABLE,
    }, payload


def test_theEmitterDiscardsReadingsHandedToItWithAnUnavailableSource():
    """
    Given: TWO layers null the readings -- the orchestrator never gathers any on
           its unreadable branch, and the emitter throws away anything it is
           handed while `upsAvailable` is False
    When: the emitter is handed a full 4.16 V / 96 % reading AND told the source
          is unavailable
    Then: it discards them, and the reason travels in `source.ups`.

          THIS TEST EXISTS BECAUSE THE END-TO-END ONES CANNOT SEE IT, and that
          was MEASURED, not assumed: deleting the emitter's discard outright
          leaves every other test in this file GREEN. The orchestrator's
          unreadable path calls `_batteryHealthKwargs(upsAvailable=False)` with
          no readings at all, so the discard has nothing to bite on and the two
          layers' guarantees are indistinguishable through the chain. A fixture
          that hands a producer nothing to throw away cannot witness the
          throwing away -- so this one goes straight at the SSOT builder and
          hands it something real to destroy.
    """
    from pi.splash.battery_health_emitter import buildBatteryHealthState

    payload = buildBatteryHealthState(
        vcellV=ATLAS_VCELL_VOLTS,
        soc=ATLAS_SOC_PERCENT,
        socCalibrated=True,
        crate=-1.2,
        charging=False,
        draining=True,
        restedVcellV=4.1,
        weakEvents30d=0,
        restedHistory=[],
        health="good",
        fullChargeReached=True,
        runtimeToCutoffS=720,
        ambientTempC=None,
        lastHealthCheckTs=None,
        ladder={"stage": "DRAINING"},
        nowIso="2026-08-31T14:46:00Z",
        upsAvailable=False,
        upsUnavailableReason=REASON_UPS_UNREADABLE,
    )

    assert payload["vcellV"] is None, payload
    assert payload["soc"] is None, payload
    assert payload["crate"] is None, payload
    assert payload["source"]["ups"]["reason"] == REASON_UPS_UNREADABLE, payload


def test_anUnavailableSourceOverridesAReadingLeftBesideIt(tmp_path):
    """
    Given: the producer blanking and the renderer's source check are TWO
           independent guarantees that always agree on a real payload
    When: they are made to DISAGREE -- an unavailable `source.ups` beside a
          fully populated 4.16 V / 96 % reading, which is what a future producer
          that forgot to blank would write
    Then: the panel still renders the typed absence.

          Every payload the shipped producer can emit zeroes the readings and
          marks the source unavailable TOGETHER, so a renderer that simply
          printed whatever numbers it found would pass every other test in this
          file. Only a payload whose halves contradict each other can say which
          guarantee is holding -- and this one shows BOTH are.
    """
    live = _emit(tmp_path, _atlasGauge())
    forgotToBlank = dict(live)
    forgotToBlank["source"] = {
        "ups": {"available": False, "reason": REASON_UPS_UNREADABLE}
    }
    assert forgotToBlank["vcellV"] == ATLAS_VCELL_VOLTS, "fixture lost its stale value"
    assert forgotToBlank["soc"] == ATLAS_SOC_PERCENT, "fixture lost its stale value"

    texts = _cardText(forgotToBlank)

    assert "NA" in texts, texts
    assert ATLAS_VCELL_PRINTED not in texts, texts
    assert ATLAS_SOC_PRINTED not in texts, texts


def test_theTypedAbsenceIsVisuallyDistinctFromALiveReading(tmp_path):
    """
    Given: an absence that LOOKS like a reading is the dishonest-instrument trap
    When: a dead gauge and a live gauge are rendered in turn
    Then: the NA tile sits at `unavailable` and resolves to a different colour
          from the live tile's `neutral`.

          The level alone would be a claim about an attribute; the resolved
          colour is the claim about the panel.
    """
    liveTile = _tile(_emit(tmp_path, _atlasGauge()), CELL)
    deadTile = _tile(_emit(tmp_path, _deadGauge()), BATTERY_LABEL)

    assert liveTile is not None and deadTile is not None
    assert deadTile["value"] == "NA", deadTile
    assert deadTile["level"] == "unavailable", deadTile
    assert liveTile["level"] == "neutral", liveTile
    assert deadTile["colour"] != liveTile["colour"], (deadTile, liveTile)


# ---------------------------------------------------------------------------
# CHARACTERISATION -- recorded, NOT fixed. See TD-us639.
#
# These do not assert that the current behaviour is RIGHT. They pin what it IS,
# so the fact survives as evidence and so the day somebody fixes it, a test goes
# red and names the thing that changed.
# ---------------------------------------------------------------------------


def test_thereIsExactlyOneProducerOfTheBatteryHealthState():
    """
    Given: the test below claims a render branch is UNREACHABLE, and an
           unreachability claim is only as good as the search behind it
    When: src/ is swept for anything that builds the battery-health emitter
    Then: exactly one module does -- the orchestrator's card-state mixin.

          A second writer would invalidate the characterisation below outright,
          so the sweep is an assertion and not a comment.
    """
    srcDir = os.path.join(_REPO, "src")
    writers = set()
    for root, _dirs, files in os.walk(srcDir):
        for name in files:
            if not name.endswith(".py"):
                continue
            full = os.path.join(root, name)
            with open(full, encoding="utf-8") as fh:
                body = fh.read()
            if "makeBatteryHealthEmitter(" in body and "def makeBatteryHealthEmitter" \
                    not in body:
                writers.add(os.path.relpath(full, srcDir).replace("\\", "/"))

    assert writers == {"pi/obdii/orchestrator/card_state_emitter.py"}, writers


def test_aSocRegisterFailureBlanksTheVoltageToo_theF8FallbackHasNoProducer(tmp_path):
    """
    Given: F-8's volts-only fallback -- `socTile` omits the percent and leaves
           the voltage standing when `soc` is null -- and one producer
    When: the VCELL register answers and the SOC register does not
    Then: the card is a WHOLE-CARD typed absence. The readable voltage is
          discarded, `soc` never reaches the renderer as null-beside-a-number,
          and the fallback branch is therefore unreachable on the shipped path.

          MEASURED, NOT JUDGED. The end state is honest -- a card that says
          nothing beats a card that says half of something -- but the branch
          designed for exactly this case cannot be reached by the only thing
          that writes the file, and the existing test of it
          (test_carousel_source_cards.py:327) is satisfied only by a
          hand-written payload. That is the US-635 shape: an assertion that can
          be satisfied one way only is not evidence about the shipped path.
          Recorded in TD-us639; deliberately NOT fixed here, because a verify
          story that quietly becomes a fix story hides the defect rate.
    """
    partial = UpsMonitor(
        i2cClient=_FakeI2c(
            {
                REGISTER_VCELL: ATLAS_VCELL_RAW,
                REGISTER_CRATE: CRATE_DISABLED_ON_THIS_CHIP,
            }
        )
    )
    payload = _emit(tmp_path, partial)

    assert payload["soc"] is None, payload
    assert payload["vcellV"] is None, "the readable voltage reached the file"
    assert payload["source"]["ups"]["available"] is False, payload

    texts = _cardText(payload)
    assert "NA" in texts, texts
    assert ATLAS_VCELL_PRINTED not in texts, texts
