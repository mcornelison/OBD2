################################################################################
# File Name: splash_done.py
# Purpose/Description: US-870-d -- the two facts the shutdown sequencer's
#                      splash-done wait reads: is the grace splash running, and
#                      has the shutdown page recorded 'splash done' for THIS
#                      boot. Kept out of controller.py, which never names a
#                      splash unit (F-103; tests/pi/power/power_watch/
#                      test_load_shed_splash.py). The record's filename lives
#                      here and states_http_server (its writer) imports it.
# Author: Rex (Ralph)
# Creation Date: 2026-10-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-27    | Rex (US-870-d) | Initial.
# ================================================================================
################################################################################

"""Splash-done record + grace-splash check for the shutdown sequencer (US-870-d)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable

from src.pi.diagnostics.boot_reason import readCurrentBootId
from src.pi.power.power_watch.load_shed import systemctlRunner

__all__ = [
    "SHUTDOWN_SPLASH_DONE_FILENAME",
    "SPLASH_GRACE_UNIT",
    "makeSplashDoneReader",
    "splashGraceActive",
]

#: states/<this>: {bootId, ts}, written by POST /shutdown-splash-done when the
#: shutdown page has played its ending. bootId is stamped by the server.
SHUTDOWN_SPLASH_DONE_FILENAME = "shutdown-splash-done"

#: The grace splash unit (src/pi/ops/unit_manifest.py; pinned there by the test).
SPLASH_GRACE_UNIT = "splash-grace.service"


def splashGraceActive(runner: Callable[[str, str], None] = systemctlRunner) -> bool:
    """True only when systemd reports the grace splash active.

    ``systemctl is-active`` exits non-zero for anything but active, which the
    runner raises on; that, a missing systemctl or a timeout all read False --
    no page is playing, so there is nothing to wait for.

    Args:
        runner: ``runner(action, unit)``; raises unless the command succeeded.

    Returns:
        Whether the grace splash is active.
    """
    try:
        runner("is-active", SPLASH_GRACE_UNIT)
    except Exception:  # noqa: BLE001 -- anything but a clean 'active' is inactive
        return False
    return True


def makeSplashDoneReader(
    statesDir: str | None = None,
    currentBootIdFn: Callable[[], str | None] = readCurrentBootId,
) -> Callable[[], str | None]:
    """Build the zero-arg reader of this boot's splash-done record.

    Args:
        statesDir: The tmpfs states directory; None is the production one.
        currentBootIdFn: This boot's id (None when unreadable).

    Returns:
        A reader returning the record's ``ts`` when the file names THIS boot,
        else None (no file, unreadable, malformed, another boot's record, or a
        boot id that cannot be read -- an unknown boot never matches).
    """
    if statesDir is None:
        # Imported here: the production default is only needed on the Pi path,
        # and push_lock is that constant's home.
        from src.pi.sync.push_lock import DEFAULT_STATES_DIR

        statesDir = DEFAULT_STATES_DIR
    path = os.path.join(statesDir, SHUTDOWN_SPLASH_DONE_FILENAME)

    def _read() -> str | None:
        try:
            with open(path, encoding="utf-8") as fh:
                record = json.load(fh)
        except (OSError, ValueError):
            return None
        if not isinstance(record, dict):
            return None
        bootId = record.get("bootId")
        if not bootId or bootId != currentBootIdFn():
            return None
        ts = record.get("ts")
        return ts if isinstance(ts, str) and ts else None

    return _read
