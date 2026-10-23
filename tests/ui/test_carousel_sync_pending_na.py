################################################################################
# File Name: test_carousel_sync_pending_na.py
# Purpose/Description: US-564 instance A, DISPLAY half. `syncTile` independently
#   re-defaulted a null pending count to 0 (`s.pending == null ? 0 : s.pending`),
#   so fixing only the emitter would have shipped green while the panel still
#   read "0 pending". This file pinned the render; the emitter half is pinned in
#   tests/pi/splash/test_sync_pending_unmeasured.py.
#
#   MOVED PIN (US-894-c, Atlas P7, spec s4.3): `sync.pending` / `sync.rows` and
#   the SYNC tile are retired. The rule US-564 established is UNCHANGED and now
#   guards the count that replaced them -- the DATA row's `sync.rowsWaiting`:
#   a null count reads `rows not read`, NEVER `0 rows waiting`, and a measured
#   count (zero included) still reads as its number. Both directions stay
#   pinned: a row that said `rows not read` unconditionally would satisfy the
#   first and be as useless as the one it replaced.
# Author: Rex (US-564)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-564) | Initial -- null -> NA, measured counts unchanged.
# 2026-08-21    | Rex (US-559) | Re-point detail -> counts; the counts moved to
#               |              | the drill-down. Same rule, new field.
# 2026-10-23    | Rex (US-894-c)| MOVED PIN: the tile and sync.pending are
#               |              | retired; the same rule on the DATA row's
#               |              | rowsWaiting (row + detail).
# ================================================================================
################################################################################

"""US-564 null-honesty, now on the DATA row's rowsWaiting (via node)."""

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


def _call(fn: str, *args):
    """Evaluate one carousel.js export via the node probe, decoded as UTF-8
    explicitly (TD-084: `text=True` decodes with the ANSI code page)."""
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *(json.dumps(a) for a in args)],
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    return json.loads(proc.stdout.decode("utf-8"))


def _status(**sync):
    block = {
        "lastOkTs": "2026-08-21T11:00:00Z", "stale": False,
        "rowsWaiting": None, "edrRowsWaiting": None, "notCounted": None,
    }
    block.update(sync)
    return {"sync": block, "verdict": {"issueCount": 0, "members": []},
            "ts": "2026-08-21T12:00:00Z"}


def _sentence(payload) -> str:
    return _call("dataRowView", payload, None)["sentence"]


class TestNullRowsWaitingNeverRendersAsZero:
    def test_nullRowsWaiting_readsRowsNotRead_neverZero(self):
        sentence = _sentence(_status(rowsWaiting=None))
        assert "rows not read" in sentence
        assert "0 rows waiting" not in sentence

    def test_missingRowsWaitingKey_alsoReadsRowsNotRead(self):
        payload = _status()
        del payload["sync"]["rowsWaiting"]
        assert "rows not read" in _sentence(payload)

    @pytest.mark.parametrize("junk", ["12", True, -3])
    def test_aNonCount_readsRowsNotRead(self, junk):
        assert "rows not read" in _sentence(_status(rowsWaiting=junk))

    def test_measuredCount_stillRendersTheNumber(self):
        assert "4,820 rows waiting" in _sentence(_status(rowsWaiting=4820))

    def test_measuredZero_stillRendersZero(self):
        """A measured zero is real news and must stay sayable."""
        sentence = _sentence(_status(rowsWaiting=0))
        assert "0 rows waiting" in sentence
        assert "rows not read" not in sentence

    def test_nullEventRows_printsNothing_neverZero(self):
        sentence = _sentence(_status(rowsWaiting=5, edrRowsWaiting=None))
        assert "event row" not in sentence


class TestTheDetailCarriesTheSameRule:
    def test_detail_nullCounts_readUnread_neverZero(self):
        detail = _call("dataDetailView", _status(), None)
        assert detail["rowsWaiting"] == "rows not read"
        assert detail["eventRows"] == "--"

    def test_detail_measuredZeros_readZero(self):
        detail = _call("dataDetailView", _status(rowsWaiting=0, edrRowsWaiting=0), None)
        assert detail["rowsWaiting"] == "0"
        assert detail["eventRows"] == "0"
