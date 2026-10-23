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
# 2026-10-20    | Ralph (Rex)  | MOVED PIN (US-898-b1): the alertsCardView cases
#               |              | re-pointed at warningsPageView (states/alerts).
# 2026-10-20    | Ralph (Rex)  | MOVED PIN (US-898-b2): not-read with nothing
#               |              | active is the NOT CHECKED header + empty state.
# 2026-10-20    | Ralph (Rex)  | MOVED PIN (US-899-a2): takeoverView/ribbonView
#               |              | cases retired with the deleted functions.
# 2026-10-23    | Ralph (Rex)  | MOVED PIN (US-894-a): glyphs.bt is the link
#               |              | chain {bt, adapter, ecu}.
# 2026-10-23    | Ralph (Rex)  | US-894-e -- MOVED PIN: the UPS source and the power
#               |              | witness read the UPS row.
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


def _view(fn: str, arg: dict | None, *more: object) -> dict | None:
    """Evaluate one carousel.js export against a fixture via the node probe
    (extra positional arguments are passed through, JSON-encoded)."""
    proc = subprocess.run(
        [_NODE, _PROBE, fn, json.dumps(arg), *(json.dumps(m) for m in more)],
        capture_output=True,
        text=True,
        encoding="utf-8",
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
    """OBD source unavailable -> nothing on the page claims a link: the OBD row
    reads its unread chain (dashed, not read yet), the chain glyph is hollow,
    and sync/power/drive stay honest independently.

    MOVED PIN (US-894-b): the OBD LINK tile's typed NA is retired with the tile;
    the OBD row reads `link` verbatim and ignores source.obd (spec s4.2)."""
    view = _view(
        "systemStatusView",
        {
            # MOVED PIN (US-876-a): obdLink.lastSeenS is gone from system-status.
            "obdLink": {"state": None, "retries": 0},
            "sync": {"lastOkTs": None, "rows": 3, "pending": 0, "stale": False},
            "power": {"mode": "wall", "source": "external"},
            "drive": {"state": "idle", "driveId": None},
            "source": _unavailable("obd", "OBD: off"),
            "ts": "2026-07-02T00:00:00Z",
        },
    )
    assert "obdLink" not in view["tiles"]
    assert view["rows"][0]["steps"] == ["dashed", "dashed", "dashed"]
    assert view["rows"][0]["sentence"] == "Bluetooth not read yet"
    # MOVED PIN (US-894-a): glyphs.bt is the link chain, read from `link` and
    # never forced by source.obd; no link published -> three hollow dots.
    assert view["glyphs"]["bt"] == {"bt": "hollow", "adapter": "hollow", "ecu": "hollow"}
    # US-668: the power tile renders the SENSED source now, not the removed
    # operator-declared mode. The point of the assertion is unchanged -- one
    # source going unavailable must not disturb another.
    # MOVED PIN (US-894-e): the POWER tile is retired; the sensed source is the
    # UPS row's sentence.
    assert view["rows"][3]["key"] == "ups"
    assert view["rows"][3]["sentence"] == "on external power"  # other sources unaffected


def test_systemStatusView_obdAvailable_rendersRealLink():
    """OBD source available -> the real link state renders (no NA).
    MOVED PIN (US-894-b): on the OBD row, from `link`."""
    view = _view(
        "systemStatusView",
        {
            "obdLink": {"state": "linked", "retries": 0},
            # MOVED PIN (US-894-a): the chain reads the layers, not obdLink.
            "link": {"bt": {"state": "up"}, "adapter": {"state": "up"}, "ecu": {"state": "up"}},
            "sync": {"lastOkTs": None, "rows": 0, "pending": 0, "stale": False},
            "power": {"mode": "car", "source": "external"},
            "drive": {"state": "idle", "driveId": None},
            "source": _available("obd"),
            "ts": "2026-07-02T00:00:00Z",
        },
    )
    assert view["rows"][0]["steps"] == ["ok", "ok", "ok"]
    assert view["rows"][0]["sentence"] == "ECU answering"
    assert view["glyphs"]["bt"] == {"bt": "ok", "adapter": "ok", "ecu": "ok"}


# ---------------------------------------------------------------------------
# Battery Health -- the UPS source (single source -> typed NA).
# MOVED PIN (US-894-e): the Battery card is retired; the UPS source now
# governs the System page's UPS row (upsRowView) and its UPS detail.
# ---------------------------------------------------------------------------

_SYS_EXTERNAL = {"power": {"source": "external", "reasons": {}}, "ts": "2026-07-02T00:00:00Z"}
_NOW_MS = 1782950400000  # 2026-07-02T00:00:00Z


def test_upsRow_upsUnavailable_isTheTypedNa():
    """UPS source unavailable -> the UPS row's cell is a typed NA with the
    reason; never a blank or a stale last-real cell reading."""
    row = _view(
        "upsRowView",
        _SYS_EXTERNAL,
        {
            "vcellV": None,
            "soc": None,
            "source": _unavailable("ups", "gauge unreadable"),
            "ts": "2026-07-02T00:00:00Z",
        },
        _NOW_MS,
    )
    assert row["word"] == "--"
    assert row["value"] == "-- · gauge unreadable"


def test_upsRow_upsAvailable_rendersTheCell():
    """UPS source available -> the real cell reading (not unavailable)."""
    row = _view(
        "upsRowView",
        _SYS_EXTERNAL,
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
        _NOW_MS,
    )
    assert row["value"] == "4.02 V"


# ---------------------------------------------------------------------------
# Alerts card -- Bug-3b: never mis-fire on absent/empty.
# ---------------------------------------------------------------------------


def test_alertsCardView_dtcUnavailable_typedNaNotAllClear():
    """Codes not read (no read happened) -> 'codes not read yet', NOT "No stored
    codes" (which would falsely imply a clean all-clear read).

    MOVED PIN (US-898-b1): the card reads states/alerts; "not read" is the
    provider's null sources.code.checkedAtTs.
    MOVED PIN (US-898-b2): with nothing active an unassessed read is the amber
    'NOT CHECKED' header (no meta) over '? NOT CHECKED YET'."""
    view = _view(
        "warningsPageView",
        {"sources": {"code": {"assessed": False, "checkedAtTs": None}}, "entries": []},
    )
    assert view["missing"] is False
    assert view["header"]["text"] == "NOT CHECKED"
    assert view["quiet"]["head"] == "NOT CHECKED YET"
    assert "no stored codes" not in json.dumps(view).lower()


def test_alertsCardView_dtcAvailableEmpty_honestAllClear():
    """Codes read with nothing active -> a read view (the read time, no rows),
    NOT missing and NOT 'not read'.

    MOVED PIN (US-898-b1): re-pointed at warningsPageView; the NONE / NO
    WARNINGS words for this state are US-898-b2's."""
    view = _view(
        "warningsPageView",
        {
            "sources": {"code": {"assessed": True, "checkedAtTs": "2026-07-02T12:00:00Z"}},
            "entries": [],
        },
    )
    assert view["missing"] is False
    assert view["header"]["meta"].startswith("codes read ")
    assert view["rows"] == []


# MOVED PIN (US-899-a2): the takeoverView / ribbonView cases are retired with
# the deleted functions. The takeover is takeoverAlertView over states/alerts
# (no payload or a null takeover -> none), pinned in test_warnings_takeover.py.
