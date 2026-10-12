################################################################################
# File Name: test_system_status_last_drive.py
# Purpose/Description: US-505 tests for the `drive.lastDrive` block the
#   system-status state file gained so the idle-home card can render a real last
#   drive instead of a permanent "No recent drive".
#
#   The block is ALWAYS present as a key (null when there is no known last
#   drive) rather than sometimes-absent: a stable schema is what the display can
#   be tested against, and an intermittently-missing key is the shape that lets
#   a renderer quietly fall through to the wrong branch.
#
#   The pre-existing `drive.state` / `drive.driveId` keys are unchanged --
#   `driveId` remains the ACTIVE drive (null at idle).  lastDrive is a second,
#   different fact: the most recent COMPLETED drive.  Collapsing the two would
#   make a parked Pi look like it were recording.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Ralph (Rex)  | Initial -- US-505 drive.lastDrive block.
# ================================================================================
################################################################################

"""US-505: system-status carries a real last-drive block."""

from pi.splash.system_status_emitter import buildSystemStatusState

_TS = "2026-08-02T12:00:00Z"

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
    "obdAvailable": False,
}


def _state(**extra: object) -> dict:
    kwargs = dict(_BASE)
    kwargs.update(extra)
    return buildSystemStatusState(**kwargs)  # type: ignore[arg-type]


def test_buildSystemStatusState_noLastDrive_carriesNullLastDriveKey():
    """
    Given: no last-drive summary is supplied (default)
    When: the system-status state is built
    Then: drive.lastDrive is present and null -- the key always exists so the
          display has one branch to test, never a missing-key fall-through
    """
    state = _state()

    assert "lastDrive" in state["drive"]
    assert state["drive"]["lastDrive"] is None


def test_buildSystemStatusState_withLastDrive_carriesItVerbatim():
    """
    Given: a real last-drive summary
    When: the system-status state is built
    Then: the block is carried through unchanged (the emitter transports the
          producer's fact; it does not reformat or re-derive it)
    """
    state = _state(
        lastDrive={"driveId": 35, "startedAtTs": "2026-08-02T09:15:00Z"}
    )

    assert state["drive"]["lastDrive"] == {
        "driveId": 35,
        "startedAtTs": "2026-08-02T09:15:00Z",
    }


def test_buildSystemStatusState_idleWithLastDrive_activeDriveIdStaysNull():
    """
    Given: the Pi is idle but a previous drive exists
    When: the system-status state is built
    Then: drive.driveId (the ACTIVE drive) stays null while lastDrive carries
          the completed one -- two different facts, never merged; a parked Pi
          must not read as recording
    """
    state = _state(
        driveState="idle",
        driveId=None,
        lastDrive={"driveId": 35, "startedAtTs": "2026-08-02T09:15:00Z"},
    )

    assert state["drive"]["state"] == "idle"
    assert state["drive"]["driveId"] is None
    assert state["drive"]["lastDrive"]["driveId"] == 35


def test_buildSystemStatusState_recordingWithLastDrive_bothPresent():
    """
    Given: a drive is actively recording and an earlier drive exists
    When: the system-status state is built
    Then: the active id and the previous drive coexist without overwriting
    """
    state = _state(
        driveState="recording",
        driveId=36,
        lastDrive={"driveId": 35, "startedAtTs": "2026-08-02T09:15:00Z"},
    )

    assert state["drive"]["driveId"] == 36
    assert state["drive"]["lastDrive"]["driveId"] == 35


def test_buildSystemStatusState_lastDrive_doesNotAffectIdleSsot():
    """
    Given: a last drive exists while the OBD source is absent and nothing records
    When: the system-status state is built
    Then: the idle SSOT flag is untouched -- a REMEMBERED drive is not an active
          one, so it must never flip the card off its idle disposition
    """
    state = _state(
        obdAvailable=False,
        driveState="idle",
        lastDrive={"driveId": 35, "startedAtTs": "2026-08-02T09:15:00Z"},
    )

    assert state["idle"] is True
