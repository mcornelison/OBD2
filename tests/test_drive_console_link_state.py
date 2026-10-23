################################################################################
# File Name: test_drive_console_link_state.py
# Purpose/Description: US-894-b (Atlas A2/P6) -- obdLink is retired from
#   system-status, and tools/imu/drive_console.py was its one non-UI reader. A
#   silent reader of a removed key reads None forever and "fails open", so the
#   console's `obd` is pinned to the field that replaced it: link.ecu.state.
#   (tools/imu/drive_test_ui.html prints s.obd verbatim, so its word changes
#   `linked` -> `up` -- harmless, noted in the story.)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-23    | Ralph (Rex)  | Initial -- US-894-b drive console reads link.ecu.
# ================================================================================
################################################################################

"""US-894-b: the drive console's `obd` reads system-status link.ecu.state."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pi.splash.system_status_emitter import (  # noqa: E402
    LINK_CONNECTING,
    LINK_UP,
    buildSystemStatusState,
)
from tools.imu.drive_console import ecuLinkState  # noqa: E402


def _status(ecu: str | None) -> dict:
    return buildSystemStatusState(
        # MOVED PIN (US-894-c): syncRows / syncPending dropped -- sync.rows / sync.pending retired (Atlas P7).
        syncLastOkTs=None, syncStale=False,
        powerSource="external", driveState="idle", driveId=None,
        nowIso="2026-10-23T07:30:00Z",
        link={"ecu": {"state": ecu, "ts": "2026-10-23T07:29:00Z" if ecu else None,
                      "lastOkTs": None}},
    )


@pytest.mark.parametrize("state", [LINK_UP, LINK_CONNECTING])
def test_theConsoleReadsTheEcuLayer_fromTheRealPayload(state: str):
    payload = _status(state)
    assert "obdLink" not in payload
    assert ecuLinkState(payload) == state


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"link": None}, {"link": "x"}, {"link": {"ecu": None}},
     {"link": {"ecu": {"state": 3}}}, {"obdLink": {"state": "linked"}}],
)
def test_anUnreadablePayload_isNotRead_neverAStaleObdLinkWord(payload):
    assert ecuLinkState(payload) is None


def test_aNullEcuLayer_isNotRead():
    assert ecuLinkState(_status(None)) is None
