################################################################################
# File Name: test_carousel_idle_home.py
# Purpose/Description: US-481 fixture tests for the carousel's idle-state home
#   card (specs/UI/dist/dashboard-pi/carousel.js). The idle card is the calm,
#   honest PARKED view (engine off / OBD asleep). These tests drive the pure
#   view/logic exports through the tiny node subprocess (carousel_probe.js) and
#   assert the JSON result. Covers the load-bearing honest-instrument invariants
#   (Iris spec 1.3): idle is the emitter's SSOT boolean (never re-derived from
#   the drive-state string); the STANDBY hero is NEVER green; the faults line is
#   NEVER amber/red unless a REAL stored STOP/WATCH code exists; an absent DTC
#   read reads "DTC not read since key-off" (absence != clean, != fault); green
#   appears ONLY on the battery line and only carrying its data-age.
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
# idleFaultsFact -- honest faults line (Iris 1.3): never amber/red unless a REAL
# stored STOP/WATCH code; absent read = "DTC not read since key-off"; never green.
# ---------------------------------------------------------------------------


def test_idleFaultsFact_notRead_saysKeyOff():
    """DTC source unavailable (no key-on read) -> "DTC not read · since key-off"
    at a NEUTRAL level -- absence is neither a clean all-clear nor a fault."""
    fact = _view("idleFaultsFact", {"codes": [], "source": _unavailable("dtc", "not read yet")})
    assert fact["value"] == "DTC not read"
    assert fact["detail"] == "since key-off"
    assert fact["level"] == "neutral"


def test_idleFaultsFact_availableEmpty_neutralNotGreen():
    """A real empty read -> "No stored codes" but NEUTRAL, never green (honest-
    instrument 1.3: no green OK at idle except the battery line)."""
    fact = _view("idleFaultsFact", {"codes": [], "mil": False, "source": _available("dtc")})
    assert fact["value"] == "No stored codes"
    assert fact["level"] == "neutral"


def test_idleFaultsFact_storedStopCode_isDownRed():
    """A REAL stored STOP code -> the faults line goes red (down) -- idle never
    suppresses a genuine fault (AC-5)."""
    fact = _view(
        "idleFaultsFact",
        {
            "codes": [{"code": "P0301", "severity": "stop", "short": "Misfire"}],
            "source": _available("dtc"),
        },
    )
    assert fact["value"] == "P0301"
    assert fact["level"] == "down"


def test_idleFaultsFact_watchCode_isAmber():
    """A stored WATCH code -> amber (a real STOP/WATCH is the ONLY thing that
    tints the faults line at idle)."""
    fact = _view(
        "idleFaultsFact",
        {
            "codes": [{"code": "P0420", "severity": "watch", "short": "Cat efficiency"}],
            "source": _available("dtc"),
        },
    )
    assert fact["level"] == "amber"


def test_idleFaultsFact_minorCode_staysNeutral():
    """A MINOR code is real but NOT a STOP/WATCH -> stays neutral at idle (never
    amber/red for a minor, and never green)."""
    fact = _view(
        "idleFaultsFact",
        {
            "codes": [{"code": "P0455", "severity": "minor", "short": "EVAP leak"}],
            "source": _available("dtc"),
        },
    )
    assert fact["level"] == "neutral"


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
# idleCardView -- the assembled card. Hero is STANDBY and NEVER green.
# ---------------------------------------------------------------------------


def test_idleCardView_assemblesStandbyHeroAndThreeFacts():
    """The card = a STANDBY hero (neutral, never green) + the 3-fact strip."""
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
        {"codes": [], "source": _unavailable("dtc", "not read yet")},
    )
    assert view["hero"]["title"] == "STANDBY"
    assert view["hero"]["level"] == "neutral"
    assert view["hero"]["level"] != "ok"  # never green
    assert set(view["facts"].keys()) == {"lastDrive", "battery", "faults"}
    assert view["facts"]["faults"]["value"] == "DTC not read"
    assert view["facts"]["battery"]["level"] == "ok"  # the one allowed green


def test_idleCardView_heroNeverGreenEvenWhenAllHealthy():
    """Honest-instrument 1.3: even with a healthy battery + clean read, the
    STANDBY hero stays neutral -- the parked screen never paints a green "OK"."""
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
        {"codes": [], "mil": False, "source": _available("dtc")},
    )
    assert view["hero"]["level"] == "neutral"
    assert view["facts"]["faults"]["level"] == "neutral"  # clean read is NOT green
