################################################################################
# File Name: test_carousel_sync_pending_na.py
# Purpose/Description: US-564 instance A, DISPLAY half. `syncTile` independently
#   re-defaulted a null pending count to 0 (`s.pending == null ? 0 : s.pending`),
#   so fixing only the emitter would have shipped green while the panel still
#   read "0 pending". This file pins the render; the emitter half is pinned in
#   tests/pi/splash/test_sync_pending_unmeasured.py.
#
#   Both directions are pinned: null renders as an em-dash AND a real count still
#   renders as a number. A tile that showed "—" unconditionally would satisfy the
#   first assertion and be just as useless as the one it replaced.
# Author: Rex (US-564)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-564) | Initial -- null -> NA, measured counts unchanged.
# ================================================================================
################################################################################

"""US-564 fixture tests for carousel.js syncTile null-honesty (via node)."""

import json
import os
import shutil
import subprocess

import pytest

# The tile renders U+2014 EM DASH. Spelled as an escape, never a literal:
# this file has to survive being written and re-read on a Windows SMB share
# where a raw em-dash has already been mangled once.
EM_DASH = "—"

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _view(fn: str, arg):
    """Evaluate one carousel.js export against a fixture via the node probe.

    Decodes the probe's stdout as UTF-8 EXPLICITLY. The shared helper in the
    sibling tests/ui files passes ``text=True``, which on Windows decodes with
    the ANSI code page -- so a rendered em-dash comes back as mojibake and an
    assertion on it fails while the printed message still LOOKS right. It has
    never bitten because no existing tests/ui assertion contains a non-ASCII
    glyph; this file's do. (TD-084.)
    """
    proc = subprocess.run(
        [_NODE, _PROBE, fn, json.dumps(arg)],
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    return json.loads(proc.stdout.decode("utf-8"))


def _sync(**overrides):
    payload = {"lastOkTs": "2026-08-21T11:00:00Z", "rows": 120, "pending": None, "stale": False}
    payload.update(overrides)
    return payload


class TestNullPendingNeverRendersAsZero:
    """The panel must not claim an all-clear on data safety it never measured."""

    def test_syncTile_nullPending_rendersAnEmDashNotZero(self):
        """
        Given: the emitter reporting no measured pending count
        When: the sync tile renders
        Then: the detail line says "— pending", never "0 pending"
        """
        tile = _view("syncTile", _sync(pending=None))

        assert EM_DASH + " pending" in tile["detail"]
        assert "0 pending" not in tile["detail"]

    def test_syncTile_missingPendingKey_alsoRendersAnEmDash(self):
        """
        Given: a payload from an OLDER Pi that omits the key entirely
        When: the tile renders
        Then: still an em-dash. `undefined == null` is true in JS, so the same
              branch covers it -- pinned because a deploy skew between Pi and
              dashboard assets is a real state this project has been in.
        """
        payload = _sync()
        payload.pop("pending")
        tile = _view("syncTile", payload)

        assert EM_DASH + " pending" in tile["detail"]

    def test_syncTile_measuredCount_stillRendersTheNumber(self):
        """
        Given: a real measured pending count
        When: the tile renders
        Then: the number appears. Without this, a tile hard-coded to "—" would
              pass every other assertion here.
        """
        tile = _view("syncTile", _sync(pending=7))

        assert "7 pending" in tile["detail"]

    def test_syncTile_measuredZero_stillRendersZero(self):
        """
        Given: a count that was measured and genuinely is zero
        When: the tile renders
        Then: "0 pending". The fix removes an UNMEASURED zero; a measured one is
              real news and must stay sayable.
        """
        tile = _view("syncTile", _sync(pending=0))

        assert "0 pending" in tile["detail"]

    def test_syncTile_nullRows_alsoRendersAnEmDash(self):
        """
        Given: a null row count (the same coercion, one expression away)
        When: the tile renders
        Then: an em-dash. Left as `? 0` it would be the identical defect sitting
              beside the one being fixed -- the sweep-the-consumer-copies rule.
        """
        tile = _view("syncTile", _sync(rows=None))

        assert EM_DASH + " rows" in tile["detail"]


class TestTileStructureIsUnchanged:
    """The null-honesty change must not alter the tile's level or shape."""

    def test_syncTile_nullPending_isStillAnOkTileWhenNotStale(self):
        """
        Given: a healthy, non-stale sync with an unmeasured pending count
        When: the tile renders
        Then: the level stays "ok". An unmeasured COUNT is not a sync FAULT --
              inflating it to amber would be the opposite lie, and would train
              the operator to ignore the amber that means something.
        """
        tile = _view("syncTile", _sync(pending=None, stale=False))

        assert tile["level"] == "ok"
        assert tile["value"] == "OK"

    def test_syncTile_staleStillWinsWithANullPending(self):
        """
        Given: a stale-while-driving sync and an unmeasured pending count
        When: the tile renders
        Then: STALE/amber, unchanged. The stale flag is the load-bearing
              un-backed-up-data signal and this story must not disturb it.
        """
        tile = _view("syncTile", _sync(pending=None, stale=True))

        assert tile["value"] == "STALE"
        assert tile["level"] == "amber"

    def test_syncTile_nonObject_isStillUnavailable(self):
        """
        Given: no sync payload at all
        When: the tile renders
        Then: the pre-existing unavailable tile, untouched
        """
        tile = _view("syncTile", None)

        assert tile["level"] == "unavailable"
