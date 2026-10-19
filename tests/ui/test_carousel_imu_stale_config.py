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
# 2026-10-18    | Ralph (Rex)  | US-896-a -- the mirror pin moves 2.0 -> 3.0 s.
# 2026-10-19    | Ralph (Rex)  | US-892-b -- MOVED PIN: imuView retired with the
#                               Home card; the validation rows re-point at
#                               resolveImuStaleSec, as its consumers call it.
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

# Loads carousel.js with window.DISPLAY_STALE set (or left absent), resolves
# the window exactly as the kiosk's consumers do -- resolveImuStaleSec of the
# global, read at CALL time -- and judges the reading through the Motion view.
# MOVED PIN (US-892-b): this evaluated imuView, which retired with the Home card.
_WITH_GLOBAL = """
const args = JSON.parse(process.argv[1]);
if (args.stale !== undefined) globalThis.DISPLAY_STALE = args.stale;
const carousel = require(args.js);
const staleSec = carousel.resolveImuStaleSec(globalThis.DISPLAY_STALE);
const view = carousel.motionView(args.data, args.nowMs, staleSec, null);
process.stdout.write(JSON.stringify({staleSec: staleSec, stale: view.stale}));
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
    """The resolved window + verdict for a reading ``ageSec`` old, with
    DISPLAY_STALE set if given."""
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
    assert view == {"staleSec": 3.5, "stale": False}


def test_noInjection_usesTheThreeSecondMirror_strictGreaterThan():
    """Validation: with no DISPLAY_STALE the mirrored default applies.
    MOVED PIN (US-896-a, Atlas S105 Q3/G1): the mirror is 3.0 s, not 2.0 -- a
    2.5 s old reading is now live, and 3.5 s is stale."""
    assert _imuViewWith(2.5) == {"staleSec": 3.0, "stale": False}
    assert _imuViewWith(3.0)["stale"] is False
    assert _imuViewWith(3.5) == {"staleSec": 3.0, "stale": True}


def test_unsubstitutedPlaceholder_behavesAsToday():
    """A file:// preview leaves the quoted placeholder string in place.
    MOVED PIN (US-896-a): the mirror it falls back to is 3.0 s (was 2.0)."""
    view = _imuViewWith(3.5, value="__DISPLAY_STALE__")
    assert view["stale"] is True
    assert _imuViewWith(2.5, value="__DISPLAY_STALE__")["stale"] is False


def test_literalIsGoneFromTheStaleTest():
    """The stale comparison reads the resolver, not a bare constant.
    MOVED PIN (US-892-b): the comparison takes the window as an argument
    (`age > staleSec`), and both IMU pages pass it the resolver's value."""
    with open(_JS, encoding="utf-8") as fh:
        src = fh.read()
    assert "IMU_STALE_SEC)" not in src.replace("DEFAULT_IMU_STALE_SEC", "")
    assert "age > staleSec" in src
    assert src.count("resolveImuStaleSec(global && global.DISPLAY_STALE)") == 2
