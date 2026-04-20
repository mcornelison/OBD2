#!/usr/bin/env python3
################################################################################
# File Name: render_primary_screen_live.py
# Purpose/Description: Live full-screen pygame render of the basic-tier primary
#                      screen on the Pi's OSOYOO 3.5" HDMI display.  Used by
#                      scripts/validate_hdmi_display.sh for US-183 CIO
#                      validation.  Drives primary_renderer for N seconds with
#                      a scripted RPM sweep + live clock so the CIO can
#                      eyeball that the render loop is not stalled.  Exits
#                      cleanly on SIGTERM, SIGINT, or after --duration.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-183 (Sprint 12)
# 2026-04-19    | Rex          | US-192: --from-db flag for live SQLite polling
# ================================================================================
################################################################################
"""
Render the basic-tier primary screen live on the Pi's HDMI display.

This is the CIO's eyeball harness for US-183 Sprint 12 validation. Unlike
``scripts/render_advanced_tier_sample.py`` (which uses the SDL dummy driver
to generate offline PNGs), this script opens the REAL Pi framebuffer via
``pygame.display.set_mode((480, 320))`` and refreshes the screen in a tight
loop for ``--duration`` seconds.

Heartbeat (so the CIO can tell the render loop is alive):
  * RPM sweeps 800 -> 6500 -> 800 over a ~4 second cycle.
  * Other gauges hold steady so the sweep is the obvious animation.
  * The timestamp embedded in log output advances on every frame.

Exit behaviour:
  * SIGTERM / SIGINT / Ctrl+C -> flag the loop, blank the display, quit.
  * --duration seconds elapsed -> blank the display, quit.
  * Any uncaught exception -> best-effort pygame.quit(), re-raise.

Usage (on the Pi)::

    # 30 second render (default)
    ~/obd2-venv/bin/python scripts/render_primary_screen_live.py

    # Custom duration
    ~/obd2-venv/bin/python scripts/render_primary_screen_live.py --duration 60

    # Windowed (non-kiosk) for desktop debugging
    ~/obd2-venv/bin/python scripts/render_primary_screen_live.py --windowed

    # Optional: save the final frame as a PNG snapshot
    ~/obd2-venv/bin/python scripts/render_primary_screen_live.py \\
        --duration 30 --snapshot /tmp/hdmi_render.png
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from types import FrameType

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pygame  # noqa: E402

from pi.display.live_readings import buildReadingsFromDb  # noqa: E402
from pi.display.screens.primary_renderer import (  # noqa: E402
    DEFAULT_BACKGROUND,
    PYGAME_AVAILABLE,
    renderPrimaryScreen,
)
from pi.display.screens.primary_screen import (  # noqa: E402
    BASIC_TIER_DISPLAY_ORDER,
    buildBasicTierScreenState,
)

SCREEN_WIDTH = 480
SCREEN_HEIGHT = 320
DEFAULT_DURATION_SECONDS = 30
TARGET_FPS = 10

_RPM_SWEEP_MIN = 800.0
_RPM_SWEEP_MAX = 6500.0
_RPM_SWEEP_PERIOD_SECONDS = 4.0

_STATIC_READINGS: dict[str, float] = {
    "COOLANT_TEMP": 195.0,
    "BOOST": 8.5,
    "AFR": 14.2,
    "SPEED": 35.0,
    "BATTERY_VOLTAGE": 14.1,
}

_THRESHOLDS: dict[str, dict[str, float]] = {
    "coolantTemp": {
        "normalMin": 180.0,
        "cautionMin": 210.0,
        "dangerMin": 220.0,
    },
    "rpm": {
        "normalMin": 600.0,
        "cautionMin": 6500.0,
        "dangerMin": 7000.0,
    },
}

logger = logging.getLogger(__name__)


class _ExitRequested(Exception):
    """Raised internally when SIGTERM/SIGINT is received."""


def _installSignalHandlers() -> dict[str, bool]:
    """Install SIGTERM + SIGINT handlers that flip a shared exit flag.

    Returns a dict the render loop polls each frame to decide whether to
    exit. Using a dict rather than a free variable keeps this testable and
    avoids ``nonlocal`` plumbing.
    """
    state = {"exitRequested": False}

    def _handler(signum: int, _frame: FrameType | None) -> None:
        state["exitRequested"] = True
        logger.info("Signal %d received; requesting clean exit", signum)

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)
    return state


def _currentRpm(elapsedSeconds: float) -> float:
    """Triangle-wave RPM sweep between _RPM_SWEEP_MIN and _RPM_SWEEP_MAX.

    Period is ``_RPM_SWEEP_PERIOD_SECONDS``. Linear ramp so the gauge
    movement is unambiguous at a glance — exactly the heartbeat signal
    the CIO needs to confirm the render loop is not stalled.
    """
    span = _RPM_SWEEP_MAX - _RPM_SWEEP_MIN
    cycle = (elapsedSeconds % _RPM_SWEEP_PERIOD_SECONDS) / _RPM_SWEEP_PERIOD_SECONDS
    # Triangle: 0->1 on first half, 1->0 on second half.
    position = cycle * 2.0 if cycle < 0.5 else (1.0 - cycle) * 2.0
    return _RPM_SWEEP_MIN + span * position


def _buildReadings(elapsedSeconds: float) -> dict[str, float]:
    readings = dict(_STATIC_READINGS)
    readings["RPM"] = _currentRpm(elapsedSeconds)
    return readings


def _buildReadingsFromLiveDb(dbPath: Path) -> dict[str, float]:
    """Return live gauge readings from the Pi's realtime_data table.

    Empty dict if the db is missing / empty / has no real rows yet; the
    renderer shows ``---`` placeholders for absent gauges, so the display
    still refreshes cleanly (heartbeat proof) while waiting for OBD rows.
    """
    return buildReadingsFromDb(dbPath, BASIC_TIER_DISPLAY_ORDER)


def _renderOneFrame(
    surface: pygame.Surface,
    elapsedSeconds: float,
    liveDbPath: Path | None = None,
) -> None:
    if liveDbPath is not None:
        readings = _buildReadingsFromLiveDb(liveDbPath)
    else:
        readings = _buildReadings(elapsedSeconds)
    state = buildBasicTierScreenState(
        readings=readings,
        thresholdConfigs=_THRESHOLDS,
    )
    renderPrimaryScreen(state, surface)


def _blankDisplay(surface: pygame.Surface) -> None:
    """Clear to black and flip so the display doesn't freeze on the last frame."""
    surface.fill(DEFAULT_BACKGROUND)
    pygame.display.flip()


def runRenderLoop(
    durationSeconds: float,
    *,
    windowed: bool = False,
    snapshotPath: Path | None = None,
    liveDbPath: Path | None = None,
) -> int:
    """Run the live render loop for ``durationSeconds``.

    When ``liveDbPath`` is set, each frame polls the Pi's ``data/obd.db``
    realtime_data table for the latest value per gauge (US-192 live-path).
    Otherwise, falls back to the hardcoded ``_STATIC_READINGS`` + RPM sweep
    heartbeat (US-183 kiosk demo mode).

    Returns an integer exit code: 0 for normal completion / signal exit,
    1 for an unexpected failure.
    """
    if not PYGAME_AVAILABLE:
        logger.error("pygame is not available; cannot render on HDMI")
        return 1

    exitFlag = _installSignalHandlers()

    pygame.init()
    pygame.font.init()
    flags = 0 if windowed else pygame.NOFRAME
    try:
        screen = pygame.display.set_mode(
            (SCREEN_WIDTH, SCREEN_HEIGHT), flags
        )
        pygame.mouse.set_visible(False)
        pygame.display.set_caption("Eclipse OBD-II Primary Screen (US-183)")

        startTime = time.monotonic()
        frameInterval = 1.0 / TARGET_FPS
        lastSnapshotSurface: pygame.Surface | None = None

        while True:
            elapsed = time.monotonic() - startTime
            if elapsed >= durationSeconds:
                logger.info(
                    "Duration %.1fs elapsed; exiting cleanly", durationSeconds
                )
                break
            if exitFlag["exitRequested"]:
                logger.info("Exit flag set; leaving render loop")
                break

            # Drain pygame event queue so the window stays responsive and
            # we can catch a QUIT event (window close on a windowed run).
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    exitFlag["exitRequested"] = True

            _renderOneFrame(screen, elapsed, liveDbPath=liveDbPath)
            pygame.display.flip()
            lastSnapshotSurface = screen

            # Frame pacing: sleep the remainder of the target interval.
            frameTime = time.monotonic() - startTime - elapsed
            sleepFor = frameInterval - frameTime
            if sleepFor > 0:
                time.sleep(sleepFor)

        if snapshotPath is not None and lastSnapshotSurface is not None:
            snapshotPath.parent.mkdir(parents=True, exist_ok=True)
            pygame.image.save(lastSnapshotSurface, str(snapshotPath))
            logger.info("Saved final-frame snapshot to %s", snapshotPath)

        _blankDisplay(screen)
    finally:
        pygame.display.quit()
        pygame.quit()

    return 0


def parseArguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_DURATION_SECONDS,
        help=f"Seconds to keep rendering (default: {DEFAULT_DURATION_SECONDS})",
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Open in a normal window instead of borderless kiosk mode",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=None,
        help="Optional: path to save the final frame as PNG before exit",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging to stderr",
    )
    parser.add_argument(
        "--from-db",
        type=Path,
        default=None,
        dest="fromDb",
        help=(
            "Poll live realtime_data values from this SQLite path each frame "
            "(US-192 live-path mode).  Example: --from-db ~/Projects/"
            "Eclipse-01/data/obd.db.  Missing keys render as '---'."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parseArguments(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.duration <= 0:
        logger.error("--duration must be positive (got %.2f)", args.duration)
        return 2
    try:
        return runRenderLoop(
            durationSeconds=args.duration,
            windowed=args.windowed,
            snapshotPath=args.snapshot,
            liveDbPath=args.fromDb,
        )
    except _ExitRequested:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
