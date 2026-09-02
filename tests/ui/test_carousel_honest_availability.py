################################################################################
# File Name: test_carousel_honest_availability.py
# Purpose/Description: US-429 fixture/DOM tests for the carousel display's honest-
#   availability logic (src/pi/ui/dashboard/carousel.js). carousel.js is a
#   browser module that also exports its pure view/logic functions for node unit
#   testing; there is no JS test framework in-repo, so these tests drive the pure
#   functions through a tiny node subprocess (carousel_probe.js) against fixtures
#   and assert the JSON result. Covers: per-source availability rendering (obd
#   tile NA, whole-card NA for ups/dtc), the typed reason travelling with the NA,
#   and the load-bearing Bug-3b guard -- the DTC takeover/ribbon fire ONLY on a
#   real new code and NEVER on an absent/unavailable/empty source. Skipped when
#   node is not on PATH (a node-less CI box); node is present on the dev machine.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-02    | Ralph (Rex)  | Initial -- US-429 carousel honest-availability.
# ================================================================================
################################################################################

"""US-429 fixture tests for carousel.js honest-availability (via node)."""

import json
import os
import shutil
import subprocess

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _view(fn: str, arg: dict | None) -> dict | None:
    """Evaluate one carousel.js export against a fixture via the node probe."""
    proc = subprocess.run(
        [_NODE, _PROBE, fn, json.dumps(arg)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _available(name: str) -> dict:
    return {name: {"available": True, "reason": None}}


def _unavailable(name: str, reason: str) -> dict:
    return {name: {"available": False, "reason": reason}}


# ---------------------------------------------------------------------------
# System Status -- the OBD source governs the obdLink tile (one truth / source).
# ---------------------------------------------------------------------------


def test_systemStatusView_obdUnavailable_obdTileIsTypedNa():
    """OBD source unavailable -> the obdLink tile renders NA (<reason>) at the
    `unavailable` level (never a fabricated/stale LINKED), the glyph goes neutral,
    and sync/power/drive stay honest independently."""
    view = _view(
        "systemStatusView",
        {
            "obdLink": {"state": None, "retries": 0, "lastSeenS": None},
            "sync": {"lastOkTs": None, "rows": 3, "pending": 0, "stale": False},
            "power": {"mode": "wall", "source": "external"},
            "drive": {"state": "idle", "driveId": None},
            "source": _unavailable("obd", "OBD: off"),
            "ts": "2026-07-02T00:00:00Z",
        },
    )
    assert view["tiles"]["obdLink"]["value"] == "NA"
    assert view["tiles"]["obdLink"]["detail"] == "OBD: off"
    assert view["tiles"]["obdLink"]["level"] == "unavailable"
    assert view["glyphs"]["bt"] == "neutral"
    # US-668: the power tile renders the SENSED source now, not the removed
    # operator-declared mode. The point of the assertion is unchanged -- one
    # source going unavailable must not disturb another.
    assert view["tiles"]["power"]["value"] == "EXTERNAL"  # other sources unaffected


def test_systemStatusView_obdAvailable_rendersRealLink():
    """OBD source available -> the real link state renders (no NA)."""
    view = _view(
        "systemStatusView",
        {
            "obdLink": {"state": "linked", "retries": 0, "lastSeenS": 1},
            "sync": {"lastOkTs": None, "rows": 0, "pending": 0, "stale": False},
            "power": {"mode": "car", "source": "external"},
            "drive": {"state": "idle", "driveId": None},
            "source": _available("obd"),
            "ts": "2026-07-02T00:00:00Z",
        },
    )
    assert view["tiles"]["obdLink"]["value"] == "LINKED"
    assert view["glyphs"]["bt"] == "ok"


# ---------------------------------------------------------------------------
# Battery Health -- the UPS source (single source -> whole-card NA).
# ---------------------------------------------------------------------------


def test_batteryHealthView_upsUnavailable_wholeCardTypedNa():
    """UPS source unavailable -> the whole card is a typed NA with the reason;
    never a blank or a stale last-real cell reading."""
    view = _view(
        "batteryHealthView",
        {
            "vcellV": None,
            "soc": None,
            "source": _unavailable("ups", "gauge unreadable"),
            "ts": "2026-07-02T00:00:00Z",
        },
    )
    assert view["unavailable"] is True
    assert view["reason"] == "gauge unreadable"


def test_batteryHealthView_upsAvailable_rendersTiles():
    """UPS source available -> the normal tiled view (not unavailable)."""
    view = _view(
        "batteryHealthView",
        {
            "vcellV": 4.02,
            "soc": 76,
            "socCalibrated": True,
            "health": "green",
            "draining": False,
            "ambientTempC": None,
            "lastHealthCheckTs": "2026-05-16T00:00:00Z",
            "source": _available("ups"),
            "ts": "2026-07-02T00:00:00Z",
        },
    )
    assert view["unavailable"] is False
    assert view["vcell"]["value"] == "4.02 V"


# ---------------------------------------------------------------------------
# Alerts card + takeover + ribbon -- Bug-3b: never mis-fire on absent/empty.
# ---------------------------------------------------------------------------


def test_alertsCardView_dtcUnavailable_typedNaNotAllClear():
    """DTC source unavailable (no read happened) -> a typed NA, NOT "No stored
    codes" (which would falsely imply a clean all-clear read)."""
    view = _view(
        "alertsCardView",
        {"codes": [], "source": _unavailable("dtc", "not read yet")},
    )
    assert view["unavailable"] is True
    assert view["reason"] == "not read yet"


def test_alertsCardView_dtcAvailableEmpty_honestAllClear():
    """DTC source available with an empty read -> an honest all-clear view (a
    real read found nothing), NOT unavailable and with no hero."""
    view = _view(
        "alertsCardView",
        {"codes": [], "mil": False, "source": _available("dtc")},
    )
    assert view.get("unavailable") in (False, None)
    assert view["hero"] is None
    assert view["rows"] == []


def test_takeoverView_dtcUnavailable_neverFires():
    """Bug-3b: an unavailable DTC source NEVER fires a takeover, even if a stale
    newSinceTs + code somehow rode along -- an absent source reads unavailable."""
    view = _view(
        "takeoverView",
        {
            "newSinceTs": "2026-07-02T00:00:00Z",
            "codes": [{"code": "P0301", "severity": "stop", "short": "Misfire"}],
            "source": _unavailable("dtc", "not read yet"),
        },
    )
    assert view is None


def test_takeoverView_emptyAvailable_neverFires():
    """An available but empty read (no new code) -> no takeover (honest quiet)."""
    view = _view(
        "takeoverView",
        {"newSinceTs": None, "codes": [], "source": _available("dtc")},
    )
    assert view is None


def test_takeoverView_realNewCode_fires():
    """A real new code on an available source DOES fire the takeover (the guard
    only suppresses absent/unavailable/empty, never a genuine fault)."""
    view = _view(
        "takeoverView",
        {
            "newSinceTs": "2026-07-02T00:00:00Z",
            "codes": [{"code": "P0301", "severity": "stop", "short": "Misfire"}],
            "source": _available("dtc"),
        },
    )
    assert view is not None
    assert view["code"] == "P0301"
    assert view["severity"] == "stop"


def test_ribbonView_dtcUnavailable_noRibbon():
    """An unavailable DTC source carries no active fault -> no ribbon."""
    view = _view(
        "ribbonView",
        {
            "codes": [{"code": "P0301", "severity": "stop", "short": "Misfire"}],
            "source": _unavailable("dtc", "not read yet"),
        },
    )
    assert view is None
