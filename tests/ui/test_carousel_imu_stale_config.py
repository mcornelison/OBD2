################################################################################
# File Name: test_carousel_imu_stale_config.py
# Purpose/Description: US-882-c (F-159, Atlas gap 6) -- the IMU card's stale
#   window is window.DISPLAY_STALE.imuSec (pi.display.stale.imuSec, injected per
#   request), not a carousel.js literal. When the injection is absent or not a
#   finite positive number the card uses a mirrored default, and this file pins
#   that mirror to the validator DEFAULTS value so drift fails a test.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Ralph (Rex)  | Initial -- US-882-c DISPLAY_STALE.imuSec.
# ================================================================================
################################################################################
"""US-882-c tests: the IMU stale window comes from window.DISPLAY_STALE."""

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime

import pytest

from common.config.validator import DEFAULTS

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_JS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard", "carousel.js")
)

_TS = "2026-10-14T12:00:00+00:00"
_TS_MS = int(datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC).timestamp() * 1000)

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic tests need node",
)

# Loads carousel.js with window.DISPLAY_STALE set (or left absent), then
# evaluates imuView -- the global is read at CALL time, exactly as in the kiosk.
_WITH_GLOBAL = """
const args = JSON.parse(process.argv[1]);
if (args.stale !== undefined) globalThis.DISPLAY_STALE = args.stale;
const carousel = require(args.js);
process.stdout.write(JSON.stringify(carousel.imuView(args.data, args.nowMs)));
"""


def _imu() -> dict:
    return {
        "available": True,
        "ts": _TS,
        "headingDeg": 247.0,
        "gradePct": 3.0,
        "gLat": 0.30,
        "gLon": 0.12,
        "gMag": 0.323,
        "altitude": None,
        "reasons": {"altitude": "no_source"},
    }


def _imuViewWith(ageSec: float, **stale: object) -> dict:
    """imuView for a reading ``ageSec`` old, with DISPLAY_STALE set if given."""
    args = {"js": _JS, "data": _imu(), "nowMs": _TS_MS + int(ageSec * 1000)}
    if "value" in stale:
        args["stale"] = stale["value"]
    proc = subprocess.run(
        [_NODE, "-e", _WITH_GLOBAL, json.dumps(args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _probe(fn: str, *args: object) -> object:
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_mirroredDefault_equalsTheValidatorDefault():
    """
    Given: no usable injection
    When: the card resolves its stale window
    Then: it is the validator DEFAULTS value -- the mirror cannot drift
    """
    assert _probe("resolveImuStaleSec", None) == DEFAULTS["pi.display.stale.imuSec"]


def test_injectedImuSec_isUsed():
    assert _probe("resolveImuStaleSec", {"imuSec": 3.5}) == 3.5


@pytest.mark.parametrize(
    "bad", ["__DISPLAY_STALE__", {}, {"imuSec": 0}, {"imuSec": -1}, {"imuSec": "3.5"}, {"imuSec": None}, [3.5]]
)
def test_unusableInjection_fallsBackToTheMirroredDefault(bad):
    assert _probe("resolveImuStaleSec", bad) == DEFAULTS["pi.display.stale.imuSec"]


def test_readingTwoAndAHalfSecondsOld_injected3point5_isNotStale():
    """Validation: a 2.5 s old reading with DISPLAY_STALE.imuSec 3.5 is live."""
    view = _imuViewWith(2.5, value={"imuSec": 3.5})
    assert view["idle"] is False


def test_readingTwoAndAHalfSecondsOld_noInjection_isStale_exactlyAsToday():
    """Validation: the same reading with no DISPLAY_STALE is stale (2.0 s)."""
    view = _imuViewWith(2.5)
    assert view["idle"] is True
    assert view["reason"].startswith("stale")


def test_unsubstitutedPlaceholder_behavesAsToday():
    """A file:// preview leaves the quoted placeholder string in place."""
    view = _imuViewWith(2.5, value="__DISPLAY_STALE__")
    assert view["idle"] is True
    assert _imuViewWith(1.5, value="__DISPLAY_STALE__")["idle"] is False


def test_literalIsGoneFromTheStaleTest():
    """The stale comparison reads the resolver, not a bare constant."""
    with open(_JS, encoding="utf-8") as fh:
        src = fh.read()
    assert "IMU_STALE_SEC)" not in src.replace("DEFAULT_IMU_STALE_SEC", "")
    assert "age > resolveImuStaleSec(" in src
