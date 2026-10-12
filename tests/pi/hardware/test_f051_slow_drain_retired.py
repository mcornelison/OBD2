################################################################################
# File Name: test_f051_slow_drain_retired.py
# Purpose/Description: US-444 -- F-051 (UPS slow-drain detection) is RETIRED
#   (CIO 2026-10-08), superseded by ARCH-065's monthly battery test.
#
#   Why it went, measured: on the charger the X1209's sawtooth produced false
#   "slow drain" episodes of up to 1,580 s -- longer than the Pi lives on
#   battery -- so no threshold or dwell could work (Spool 2026-09-21). The
#   ratified state gate would have made the verdict UNKNOWN almost always (a
#   key-off lives ~10-15 s against a ~270 s window). Nothing read the verdict,
#   and two processes each ran a copy, each polling the MAX17048.
#
#   These tests keep it gone: a revived detector re-opens all of the above.
# Author: Atlas (Architect)
# Creation Date: 2026-10-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-10    | Atlas (US-444)| Initial.
# ================================================================================
################################################################################

"""US-444: F-051's slow-drain detector is retired and stays retired."""

from __future__ import annotations

import importlib.util
import inspect

from pi.hardware.ups_monitor import UpsMonitor


def test_theDetectorModuleIsGone() -> None:
    assert importlib.util.find_spec("pi.hardware.slow_drain_detector") is None


def test_upsMonitorNoLongerExposesAVerdict() -> None:
    assert not hasattr(UpsMonitor, "getSlowDrainState")


def test_upsMonitorTakesNoSlowDrainParameters() -> None:
    params = inspect.signature(UpsMonitor.__init__).parameters
    assert not [p for p in params if p.lower().startswith("slowdrain")]
