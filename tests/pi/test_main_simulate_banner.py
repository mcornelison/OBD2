################################################################################
# File Name: test_main_simulate_banner.py
# Purpose/Description: US-210 banner-sentinel assertion for src/pi/main.py.
#                      When --simulate is passed on the CLI, the entry point
#                      MUST print the literal string
#                      'SIMULATE MODE -- NOT FOR PRODUCTION' to stdout before
#                      logging setup so operators cannot confuse sim output
#                      for real-OBD capture. Production eclipse-obd.service
#                      never passes --simulate (see
#                      tests/deploy/test_eclipse_obd_service.py).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex          | Initial implementation (Sprint 16 US-210)
# ================================================================================
################################################################################

"""US-210 banner-sentinel regression test.

The banner is the second layer of defence behind the systemd-unit assertion
that --simulate is not in ExecStart. If someone does start main.py with
--simulate locally (legitimate developer path), the banner prints a
human-readable warning so they can't mistake the sim output for real
capture. The test locks the exact sentinel string used by the docs
(docs/testing.md Developer Simulate Mode section) and by future log-scrapers.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src is importable the same way other tests/pi/ tests do.
SRC = Path(__file__).resolve().parent.parent.parent / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pi.main import SIMULATE_BANNER_SENTINEL, _printSimulateBanner


def test_simulateBanner_sentinelConstantIsStable():
    """The exact sentinel string is a public contract for log-scrapers + docs.

    If you need to change it, update docs/testing.md Developer Simulate Mode
    section at the same commit so they don't drift.
    """
    assert SIMULATE_BANNER_SENTINEL == 'SIMULATE MODE -- NOT FOR PRODUCTION'


def test_printSimulateBanner_writesSentinelToStdout(capsys):
    """Banner text must contain the sentinel and land on stdout (not stderr)."""
    _printSimulateBanner()
    captured = capsys.readouterr()
    assert SIMULATE_BANNER_SENTINEL in captured.out, (
        f"Sentinel missing from stdout; got:\n{captured.out!r}"
    )
    # Banner goes to stdout, not stderr -- journalctl and tee -a both
    # pick it up cleanly alongside the logger's own banner.
    assert SIMULATE_BANNER_SENTINEL not in captured.err


def test_printSimulateBanner_isHighVisibility(capsys):
    """Banner is framed by '!' rules so it can't be missed in a log tail.

    The exact rule length isn't contractual; only that the banner
    surrounds the sentinel with visual framing. Guards against a future
    refactor turning the banner into a single low-visibility line.
    """
    _printSimulateBanner()
    captured = capsys.readouterr()
    # At least one line of '!' framing above AND below the sentinel.
    lines = captured.out.splitlines()
    sentinelIdx = next(
        (i for i, ln in enumerate(lines) if SIMULATE_BANNER_SENTINEL in ln),
        -1,
    )
    assert sentinelIdx > 0, f"Sentinel should not be the first line; got:\n{captured.out}"
    assert sentinelIdx < len(lines) - 1, (
        f"Sentinel should not be the last line; got:\n{captured.out}"
    )
    above = lines[sentinelIdx - 1]
    below = lines[-1]
    assert set(above) == {'!'}, f"Expected '!' rule above sentinel; got {above!r}"
    assert set(below) == {'!'}, f"Expected '!' rule below sentinel; got {below!r}"
