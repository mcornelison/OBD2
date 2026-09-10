################################################################################
# File Name: test_carousel_battery_soc_headline.py
# Purpose/Description: US-699 tests for the startup card's BATTERY tile
#   (`idleBatteryFact` in src/pi/ui/dashboard/carousel.js). The CIO was shown the
#   full menu of available values on 2026-09-09 and chose the UPS state-of-charge
#   PERCENT as the headline -- not the car battery, not vcell, not the health
#   verdict. These tests pin that choice AND the three guards it must not run
#   over:
#     * F-8   the percent renders only from the MAX17048 SoC REGISTER; a null
#             register falls back to volts, never a voltage painted as a percent;
#     * US-429 an unavailable UPS source is a typed NA with its reason -- never a
#             blank, never a stale last-good percent;
#     * F-9   the one line allowed green at idle keeps its health-check age. The
#             volts ride BESIDE that age, never in place of it.
#   The vcell detail line is the US-685 MITIGATION: `battery_health_log` row 38
#   recorded 3.63 V at soc 100% while row 37 recorded a HIGHER 3.985 V at 95%, so
#   this gauge is known to contradict itself. Rendering both registers puts a
#   contradicting pair ON the card where it can be diagnosed instead of behind
#   the percent where it gets argued about.
#   Driven through the node subprocess probe (carousel_probe.js); skipped when
#   node is not on PATH. The staleness cases are fed by the REAL verdict producer
#   (pi.power.battery_health_verdict) rather than a hand-written `health` string,
#   so VC4 measures the shipped 90-day rule instead of restating it.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-10    | Ralph (Rex)  | Initial -- US-699 SOC headline + vcell detail.
# ================================================================================
################################################################################

"""US-699: the startup-card BATTERY tile reads the UPS charge percent."""

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from pi.power.battery_health_verdict import (
    STALE_HEALTH_CHECK_DAYS,
    VERDICT_GOOD,
    VERDICT_UNKNOWN,
    computeBatteryHealthVerdict,
)

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)

# The fixed clock every fixture below is dated against. A literal `now` in the
# STATE FILE (not the browser clock) is what makes the rendered age
# deterministic -- the same property F-9 was built on.
_NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)
_NOW_ISO = "2026-09-10T12:00:00Z"

# US-685's two logged rows, verbatim. Row 38 reports a LOWER voltage at a HIGHER
# charge than row 37 -- impossible for a voltage-based fuel gauge, measured
# anyway, and the reason this tile carries both registers.
_US685_ROW_38 = {"vcellV": 3.63, "soc": 100}
_US685_ROW_37 = {"vcellV": 3.985, "soc": 95}


def _view(fn: str, *args: object) -> dict | None:
    """Evaluate one carousel.js export against N fixtures via the node probe."""
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _iso(daysAgo: float) -> str:
    """Canonical ISO-8601 UTC instant `daysAgo` days before the fixed now."""
    return (_NOW - timedelta(days=daysAgo)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _healthRow(*, daysAgo: float) -> dict:
    """A QUALIFYING battery_health_log row (production load, run to depth).

    Values chosen to clear the shipped gate (`end_vcell_v <= 3.50`, runtime
    >= 60 s) and to land the median above the GOOD band, so the verdict this
    row set produces is a real `good` rather than an asserted one.
    """
    return {
        "start_timestamp": _iso(daysAgo),
        "end_timestamp": _iso(daysAgo - 0.01),
        "runtime_seconds": 700,
        "load_class": "production",
        "end_vcell_v": 3.45,
    }


def _battery(
    *,
    soc: int | None = 76,
    vcellV: float | None = 4.02,
    socCalibrated: bool = True,
    upsAvailable: bool = True,
    upsReason: str | None = None,
    health: str = "good",
    lastHealthCheckTs: str | None = None,
) -> dict:
    """A battery-health state payload shaped as the emitter writes it."""
    source = (
        {"ups": {"available": True, "reason": None}}
        if upsAvailable
        else {"ups": {"available": False, "reason": upsReason or "gauge unreadable"}}
    )
    return {
        "vcellV": vcellV,
        "soc": soc,
        "socCalibrated": socCalibrated,
        "health": health,
        "draining": False,
        "lastHealthCheckTs": _iso(2) if lastHealthCheckTs is None else lastHealthCheckTs,
        "source": source,
        "ts": _NOW_ISO,
    }


# ---------------------------------------------------------------------------
# VC1 -- the headline IS the charge percent (CIO decision 2026-09-09).
# ---------------------------------------------------------------------------


def test_idleBatteryFact_socReadable_headlineIsTheChargePercent():
    """A readable SoC register -> the tile's VALUE slot is the percent.

    The value slot is the one readable at arm's length, which is the whole
    basis of the CIO's legibility ruling; a percent in the detail line would
    satisfy the letter of the story and none of its point."""
    fact = _view("idleBatteryFact", _battery(soc=76, vcellV=4.02))
    assert fact["value"] == "76%"


def test_idleBatteryFact_headlineIsTheRegisterNotTheVolts():
    """F-8 survives the promotion: the percent comes from `soc`, never `vcellV`.

    Pinned with two numbers that could not be confused for one another -- a
    tile deriving a percent from volts would show something near 4.02, and a
    tile printing volts in the headline would show "4.02 V"."""
    fact = _view("idleBatteryFact", _battery(soc=42, vcellV=4.02))
    assert fact["value"] == "42%"
    assert "V" not in fact["value"]


def test_idleBatteryFact_headlineMatchesTheSocTileSsot():
    """The headline is `socTile`'s value verbatim -- one formatter, not two.

    Asserting the RELATIONSHIP rather than the literal is what stops the idle
    tile and the battery-health card drifting into two renderings of one
    register (the cross-module drift this codebase keeps paying for)."""
    data = _battery(soc=88, vcellV=3.90)
    assert _view("idleBatteryFact", data)["value"] == _view("socTile", data)["value"]


def test_idleBatteryFact_socRegisterUnreadable_showsVoltsNeverAPercent():
    """`soc: null` with the UPS still readable -> volts in the headline.

    The register is the ONLY source of a percent (F-8). An unread register
    must cost the operator the percent, not buy them a fabricated one."""
    fact = _view("idleBatteryFact", _battery(soc=None, vcellV=3.78))
    assert fact["value"] == "3.78 V"
    assert "%" not in fact["value"]


# ---------------------------------------------------------------------------
# VC1 (second half) + the US-685 mitigation -- vcell AND an age beneath it.
# ---------------------------------------------------------------------------


def test_idleBatteryFact_detailCarriesTheVoltsBeneathThePercent():
    """The mitigation: the volts render on the tile's DETAIL line.

    Compared against `vcellTile` rather than a literal so the two surfaces
    cannot drift apart on rounding."""
    data = _battery(soc=76, vcellV=4.02)
    volts = _view("vcellTile", data)["value"]
    assert volts in _view("idleBatteryFact", data)["detail"]


def test_idleBatteryFact_detailStillCarriesTheHealthCheckAge():
    """F-9 PRESERVED: the volts are added to the detail, not swapped in for it.

    A GOOD verdict without its health-check date is the exact stale-green this
    card exists to refuse, and 'we needed the room for the volts' is how that
    guard would plausibly be lost."""
    data = _battery(soc=76, vcellV=4.02, lastHealthCheckTs=_iso(2))
    fact = _view("idleBatteryFact", data)
    assert _view("healthCheckLine", data)["label"] in fact["detail"]
    assert "last health check" in fact["detail"]


def test_idleBatteryFact_detailCarriesBothVoltsAndAgeTogether():
    """Both halves of VC1 on ONE render.

    The two assertions above can each pass against a build that renders only
    the other half on the state the other test happens to use; this one has
    nowhere to hide."""
    data = _battery(soc=76, vcellV=4.02)
    fact = _view("idleBatteryFact", data)
    assert _view("vcellTile", data)["value"] in fact["detail"]
    assert _view("healthCheckLine", data)["label"] in fact["detail"]


def test_idleBatteryFact_voltsUnreadable_detailNamesTheAbsence():
    """A percent with NO volts beside it must say so.

    Silently dropping the volts leaves a tile that looks exactly like a
    working pair, which would hide the US-685 contradiction the detail line
    was added to expose."""
    fact = _view("idleBatteryFact", _battery(soc=88, vcellV=None))
    assert fact["value"] == "88%"
    assert "volts unavailable" in fact["detail"]
    assert "last health check" in fact["detail"]


def test_idleBatteryFact_voltsHeadline_doesNotRestateItselfInTheDetail():
    """When the volts ARE the headline they do not also fill the detail.

    One register printed twice on a two-line tile is a line of screen the
    operator reads and learns nothing from."""
    data = _battery(soc=None, vcellV=3.78)
    fact = _view("idleBatteryFact", data)
    assert fact["value"] == "3.78 V"
    assert fact["detail"] == _view("healthCheckLine", data)["label"]


# ---------------------------------------------------------------------------
# VC2 -- US-429 PRESERVED: an unreadable UPS is a typed NA, never a percent.
# ---------------------------------------------------------------------------


def test_idleBatteryFact_upsUnavailable_typedNaWithItsReason():
    """The whole tile is NA + the reason -- not a blank, not a stale percent."""
    fact = _view(
        "idleBatteryFact",
        _battery(soc=None, vcellV=None, upsAvailable=False, upsReason="gauge unreadable"),
    )
    assert fact["value"] == "NA"
    assert fact["detail"] == "gauge unreadable"
    assert fact["level"] == "unavailable"


def test_idleBatteryFact_upsUnavailable_neverRendersALastGoodPercent():
    """A payload that still CARRIES numbers beside `available:false` renders none.

    This is the defect the story names outright: a fabricated 100% on a dead
    sensor. The emitter nulls these fields itself (US-429), so a payload like
    this one means the producer regressed -- and the display must not be the
    thing that makes that regression invisible."""
    fact = _view(
        "idleBatteryFact",
        _battery(soc=100, vcellV=4.20, upsAvailable=False, upsReason="i2c read failed"),
    )
    assert fact["value"] == "NA"
    assert "%" not in fact["value"]
    assert "100" not in fact["detail"]
    assert fact["detail"] == "i2c read failed"


# ---------------------------------------------------------------------------
# VC3 -- the US-685 contradicting pair renders VERBATIM. No smoothing.
# ---------------------------------------------------------------------------


def test_idleBatteryFact_us685ContradictingPair_bothRegistersRenderVerbatim():
    """3.63 V @ 100% and 3.985 V @ 95% each render both of their own numbers.

    Row 38 is the impossible one -- a LOWER cell voltage reporting a HIGHER
    charge than row 37. The tile's job is to show it, not to fix it."""
    for row in (_US685_ROW_38, _US685_ROW_37):
        data = _battery(soc=row["soc"], vcellV=row["vcellV"])
        fact = _view("idleBatteryFact", data)
        assert fact["value"] == str(row["soc"]) + "%"
        assert _view("vcellTile", data)["value"] in fact["detail"]


def test_idleBatteryFact_us685Pair_isNotSmoothedAveragedOrSuppressed():
    """The two renders DISAGREE, and the card lets them.

    A tile that reconciled the pair would have to move one of these numbers;
    asserting the disagreement survives is the only way to catch a 'helpful'
    clamp added later by someone who read row 38 as a bug in the display."""
    low = _view("idleBatteryFact", _battery(**_US685_ROW_38))
    high = _view("idleBatteryFact", _battery(**_US685_ROW_37))
    # The LOWER voltage keeps the HIGHER percent -- the contradiction itself.
    assert low["value"] == "100%"
    assert high["value"] == "95%"
    assert low["value"] != high["value"]
    assert low["detail"] != high["detail"]
    # No midpoint anywhere: an averaging build would print ~97 or ~3.8 V.
    assert "97" not in low["value"] + high["value"]


# ---------------------------------------------------------------------------
# VC4 -- staleness. Fed by the REAL verdict producer so the 90-day rule is
# MEASURED here, not restated. A hand-written `health: "unknown"` would make
# this test pass against a producer that had stopped applying the rule at all.
# ---------------------------------------------------------------------------


def _producedBattery(*, checkDaysAgo: float, soc: int = 76, vcellV: float = 4.02) -> tuple:
    """Run the shipped verdict producer, then build the payload it produced.

    Returns ``(verdict, statePayload)`` -- the verdict is returned so each test
    can assert WHAT the producer said before asserting how it renders."""
    verdict = computeBatteryHealthVerdict(
        rows=[_healthRow(daysAgo=checkDaysAgo + n) for n in (0, 1, 2)],
        nowIso=_NOW_ISO,
    )
    return verdict, _battery(
        soc=soc,
        vcellV=vcellV,
        health=verdict.verdict,
        lastHealthCheckTs=verdict.lastHealthCheckTs,
    )


def test_idleBatteryFact_freshQualifyingDrains_isGreenAndCarriesItsAge():
    """The one line allowed green at idle -- with its date attached.

    The green half and the age half are asserted together because F-9 is not
    'show an age' and not 'be green', it is the CONJUNCTION."""
    verdict, data = _producedBattery(checkDaysAgo=2)
    assert verdict.verdict == VERDICT_GOOD
    fact = _view("idleBatteryFact", data)
    assert fact["level"] == "ok"
    assert "last health check" in fact["detail"]
    assert verdict.lastHealthCheckTs[:10] in fact["detail"]


def test_idleBatteryFact_healthDataPastTheStalenessThreshold_isNotGreen():
    """A check older than STALE_HEALTH_CHECK_DAYS -> the tile is not green.

    The producer forces `unknown` past the threshold and the display refuses
    `ok` for it; the story's requirement is that the SOC headline does not buy
    the tile a confidence its verdict no longer supports."""
    verdict, data = _producedBattery(checkDaysAgo=STALE_HEALTH_CHECK_DAYS + 1)
    assert verdict.verdict == VERDICT_UNKNOWN
    fact = _view("idleBatteryFact", data)
    assert fact["level"] != "ok"


def test_idleBatteryFact_staleVerdict_stillNamesTheCheckDate():
    """Stale does not mean silent: the aged date is itself the signal.

    The producer keeps `lastHealthCheckTs` through every unknown branch on
    purpose, and the tile is where that decision either pays off or is wasted."""
    verdict, data = _producedBattery(checkDaysAgo=STALE_HEALTH_CHECK_DAYS + 1)
    fact = _view("idleBatteryFact", data)
    assert verdict.lastHealthCheckTs[:10] in fact["detail"]
    assert "days ago" in fact["detail"]


def test_idleBatteryFact_staleVerdict_stillShowsTheLiveRegisters():
    """An aged VERDICT does not age the live SoC/vcell reads.

    Two different facts: the health check is a drain test from months ago, the
    percent is this second's register. Suppressing the percent because the
    verdict went stale would lose a real reading to protect a cosmetic one."""
    _, data = _producedBattery(checkDaysAgo=STALE_HEALTH_CHECK_DAYS + 1, soc=64, vcellV=3.88)
    fact = _view("idleBatteryFact", data)
    assert fact["value"] == "64%"
    assert "3.88 V" in fact["detail"]


# ---------------------------------------------------------------------------
# US-700 PRESERVED -- the pre-fetch window still outranks the percent.
# ---------------------------------------------------------------------------


def test_idleBatteryFact_prefetch_stillReadsAsLoadingNotAPercent():
    """No payload yet, inside the grace window -> LOADING, never "0%".

    US-700 landed one commit before this story; wiring a headline is exactly
    the kind of change that reaches for a numeric default and quietly undoes
    it."""
    fact = _view("idleBatteryFact", None, 0)
    assert fact["value"] == "LOADING"
    assert "%" not in fact["value"]
