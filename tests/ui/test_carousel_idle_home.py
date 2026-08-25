################################################################################
# File Name: test_carousel_idle_home.py
# Purpose/Description: US-481 fixture tests for the carousel's idle-state home
#   card (src/pi/ui/dashboard/carousel.js). The idle card is the calm,
#   honest PARKED view (engine off / OBD asleep). These tests drive the pure
#   view/logic exports through the tiny node subprocess (carousel_probe.js) and
#   assert the JSON result. Covers the load-bearing honest-instrument invariants
#   (Iris spec 1.3): idle is the emitter's SSOT boolean (never re-derived from
#   the drive-state string); the hero is NEVER green; green appears ONLY on the
#   battery line and only carrying its data-age.
#   SUPERSEDED IN PART BY US-542 (F-127): the STANDBY hero and the faults line
#   are RETIRED -- the live IMU is the permanent home face, and "DTC not read
#   since key-off" is an Alerts fact now. `carouselIdle` is untouched by that
#   and is still the parked SSOT for the auto-rotate pause, which is exactly
#   the distinction tests/ui/test_carousel_idle_face_retirement.py pins.
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-22    | Ralph (Rex)  | Initial -- US-481 idle-state home card.
# ================================================================================
################################################################################

"""US-481 fixture tests for the carousel idle-state home card (via node)."""

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


def _view(fn: str, *args: object) -> dict | None:
    """Evaluate one carousel.js export against N fixtures via the node probe."""
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _available(name: str) -> dict:
    return {name: {"available": True, "reason": None}}


def _unavailable(name: str, reason: str) -> dict:
    return {name: {"available": False, "reason": reason}}


def _sys(idle: bool, *, drive_state: str = "idle", drive_id=None) -> dict:
    """A minimal system-status state with the US-480-a `idle` SSOT boolean."""
    return {
        "obdLink": {"state": None, "retries": 0, "lastSeenS": None},
        "sync": {"lastOkTs": None, "rows": 0, "pending": 0, "stale": False},
        "power": {"mode": "wall", "source": "external"},
        "drive": {"state": drive_state, "driveId": drive_id},
        "idle": idle,
        "source": _unavailable("obd", "OBD: off"),
        "ts": "2026-07-22T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# carouselIdle -- the emitter's `idle` boolean is the SSOT (Atlas idle-SSOT b).
# The display RENDERS the flag; it NEVER re-derives idle from the drive string.
# ---------------------------------------------------------------------------


def test_carouselIdle_flagTrue_isIdle():
    """The emitted `idle: true` -> the carousel is idle."""
    assert _view("carouselIdle", _sys(True)) is True


def test_carouselIdle_flagFalse_notIdle():
    """The emitted `idle: false` -> not idle (a drive is recording / OBD awake)."""
    assert _view("carouselIdle", _sys(False, drive_state="recording", drive_id=42)) is False


def test_carouselIdle_flagAbsent_notIdle():
    """No `idle` key (a pre-US-480-a state) -> honestly NOT idle (never guess)."""
    data = _sys(True)
    del data["idle"]
    assert _view("carouselIdle", data) is False


def test_carouselIdle_nonObject_notIdle():
    """A missing/malformed system-status file -> not idle (fail closed)."""
    assert _view("carouselIdle", None) is False


def test_carouselIdle_neverDerivesFromDriveState():
    """SSOT proof: `idle:false` while drive.state=="idle" -> NOT idle. The flag
    wins; the display does not re-derive idle from the drive-state string (the
    replaced carousel.js:170 display-derived pattern)."""
    assert _view("carouselIdle", _sys(False, drive_state="idle")) is False


# ---------------------------------------------------------------------------
# idleFaultsFact -- DELETED BY US-542, and the tests went with the code.
#
# The faults line was never an idle fact: "no read has happened" is a statement
# about the CODES, and it lived here only because this was the screen a parked
# operator was looking at. US-542 moves it to the Alerts card, so its one
# irreplaceable assertion -- absence reads "DTC not read · since key-off",
# neither a clean all-clear nor a fault -- is re-asserted THERE, in
# tests/ui/test_carousel_idle_face_retirement.py, against `alertsCardView`.
#
# The severity-tier assertions (stop -> down, watch -> amber, minor -> neutral)
# are NOT relocated, and that is not a coverage loss: they pinned this tile's
# private level vocabulary, and the tile is gone. The Alerts card has always
# carried its own tier mapping and its own tests (test_carousel_dtc_alerts.py).
# A test kept alive past the behaviour it described is worse than no test: it
# reads as coverage of a surface that no longer exists.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# idleBatteryFact -- the ONE line allowed green at idle, and only with its age.
# ---------------------------------------------------------------------------


def test_idleBatteryFact_upsUnavailable_typedNa():
    """UPS unavailable -> a typed NA with the reason, never a stale cell reading."""
    fact = _view(
        "idleBatteryFact",
        {"vcellV": None, "soc": None, "source": _unavailable("ups", "gauge unreadable")},
    )
    assert fact["value"] == "NA"
    assert fact["detail"] == "gauge unreadable"
    assert fact["level"] == "unavailable"


def test_idleBatteryFact_healthGreen_greenWithAge():
    """A GREEN Spool verdict -> level ok (green) AND the detail carries the data-
    age (F-9 stale-green guard: a month-old GOOD can never read as live)."""
    fact = _view(
        "idleBatteryFact",
        {
            "vcellV": 4.02,
            "soc": 76,
            "socCalibrated": True,
            "health": "good",
            "draining": False,
            "lastHealthCheckTs": "2026-07-20T00:00:00Z",
            "source": _available("ups"),
            "ts": "2026-07-22T00:00:00Z",
        },
    )
    assert fact["level"] == "ok"
    assert fact["value"] == "76%"
    assert "last health check" in fact["detail"]
    assert "2026-07-20" in fact["detail"]


def test_idleBatteryFact_healthDegraded_isNeutralNeverGreenNeverRed():
    """US-504: a DEGRADED verdict is informational -- it must not claim health
    (`ok`) and must not alarm (`down`) on the idle surface either."""
    fact = _view(
        "idleBatteryFact",
        {
            "vcellV": 3.6,
            "soc": 40,
            "health": "degraded",
            "lastHealthCheckTs": "2026-07-20T00:00:00Z",
            "source": _available("ups"),
            "ts": "2026-07-22T00:00:00Z",
        },
    )
    assert fact["level"] == "neutral"


# ---------------------------------------------------------------------------
# idleLastDriveFact -- honest degradation when no last-drive reference exists.
# ---------------------------------------------------------------------------


def test_idleLastDriveFact_noDrive_honestAbsent():
    """Parked with no drive reference (the emitter writes driveId:null when idle)
    -> "No recent drive", never a fabricated last trip."""
    fact = _view("idleLastDriveFact", _sys(True))
    assert fact["value"] == "No recent drive"
    assert fact["level"] == "neutral"


def test_idleLastDriveFact_absentBlock_unavailable():
    """A malformed system-status (no drive block) -> unavailable, not fabricated."""
    fact = _view("idleLastDriveFact", None)
    assert fact["level"] == "unavailable"


# ---------------------------------------------------------------------------
# idleCardView -- the assembled card. US-542 retired the STANDBY hero, so what
# is asserted here is what SURVIVED the retirement: the two facts a dead motion
# feed does not make unreadable, and the never-green rule over the hero that
# replaced it. The retirement itself is gated in
# tests/ui/test_carousel_idle_face_retirement.py.
# ---------------------------------------------------------------------------


def test_idleCardView_assemblesTheHeroAndTheTwoSurvivingFacts():
    """The card = a neutral (never green) hero + the last-drive/battery strip.

    The faults tile is deliberately absent: US-542 moved it to Alerts. Asserting
    the key SET rather than only the two members is what makes that a real pin --
    a membership check goes green on a view that quietly grew the tile back."""
    view = _view(
        "idleCardView",
        _sys(True),
        {
            "vcellV": 4.02,
            "soc": 76,
            "socCalibrated": True,
            "health": "good",
            "lastHealthCheckTs": "2026-07-20T00:00:00Z",
            "source": _available("ups"),
            "ts": "2026-07-22T00:00:00Z",
        },
        "no motion feed",
    )
    assert view["hero"]["level"] == "neutral"
    assert view["hero"]["level"] != "ok"  # never green
    assert set(view["facts"].keys()) == {"lastDrive", "battery"}
    assert view["facts"]["battery"]["level"] == "ok"  # the one allowed green


def test_idleCardView_heroNeverGreenEvenWhenAllHealthy():
    """Honest-instrument 1.3, carried across the retirement: even with a healthy
    battery, the hero stays neutral. It reports a DEAD INSTRUMENT -- a green
    backdrop over that is the one colour it must never take."""
    view = _view(
        "idleCardView",
        _sys(True),
        {
            "vcellV": 4.1,
            "soc": 90,
            "health": "good",
            "lastHealthCheckTs": "2026-07-22T00:00:00Z",
            "source": _available("ups"),
            "ts": "2026-07-22T00:00:00Z",
        },
        "compass reading absent",
    )
    assert view["hero"]["level"] == "neutral"
    assert view["facts"]["battery"]["level"] == "ok"
