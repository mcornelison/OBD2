################################################################################
# File Name: test_system_status_prior_shutdown.py
# Purpose/Description: US-728 -- the system-status payload carries the
#   `priorShutdown` block (the startup_log verdict rendered by
#   pi.diagnostics.prior_shutdown_summary). Always present as a key, null when
#   not read, transported verbatim through the emit JSON round trip.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-13    | Ralph (Rex)  | Initial -- US-728 priorShutdown block.
# ================================================================================
################################################################################
"""US-728: system-status carries the prior-shutdown verdict block."""

import json
import os

from pi.splash.system_status_emitter import (
    SYSTEM_STATUS_FILENAME,
    buildSystemStatusState,
    makeSystemStatusEmitter,
)

_TS = "2026-09-13T12:00:00Z"
_BLOCK = {
    "verdict": "ungraceful",
    "reason": "crashed_during_operation",
    "lastStage": "RUNNING",
    "label": "UNGRACEFUL: ended without a recorded shutdown",
    "endedAtTs": None,
    "endedAtAbsence": "end time not recorded",
    "notAfterTs": "2026-09-11T22:11:25Z",
    "notAfterLabel": "next boot recorded (upper bound)",
    "caveat": "x",
    "dataQuality": "full",
}
_BASE: dict = {
    "obdLinkState": "down",
    "obdRetries": 0,
    "obdLastSeenS": None,
    "syncLastOkTs": None,
    "syncRows": 0,
    "syncPending": 0,
    "syncStale": False,
    "powerSource": "external",
    "driveState": "idle",
    "driveId": None,
    "nowIso": _TS,
}


def test_buildSystemStatusState_noPriorShutdown_carriesNullKey():
    """
    Given: no prior-shutdown summary supplied
    When: the state is built
    Then: priorShutdown is present and null -- one branch for the display
    """
    state = buildSystemStatusState(**_BASE)

    assert "priorShutdown" in state
    assert state["priorShutdown"] is None


def test_buildSystemStatusState_withPriorShutdown_carriesItVerbatim():
    """
    Given: a rendered prior-shutdown block
    When: the state is built
    Then: it is carried unchanged -- the emitter does not re-derive the verdict
    """
    state = buildSystemStatusState(**_BASE, priorShutdown=dict(_BLOCK))

    assert state["priorShutdown"] == _BLOCK


def test_emitter_forwardsPriorShutdown_throughJsonRoundTrip(tmp_path):
    """
    Given: a caller supplying the block
    When: the emit callable fires
    Then: the written file carries it verbatim
    """
    emit = makeSystemStatusEmitter(
        str(tmp_path), syncStaleThresholdS=60.0, nowIsoFn=lambda: _TS
    )
    kwargs = {k: v for k, v in _BASE.items() if k not in ("syncStale", "nowIso")}

    emit(**kwargs, priorShutdown=dict(_BLOCK))

    with open(os.path.join(str(tmp_path), SYSTEM_STATUS_FILENAME), encoding="utf-8") as fh:
        written = json.load(fh)
    assert written["priorShutdown"] == _BLOCK
