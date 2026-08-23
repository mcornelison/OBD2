################################################################################
# File Name: test_sync_pending_unmeasured.py
# Purpose/Description: US-564 instance A -- `syncPending` was a count nobody
#   measured, hard-coded to 0 at card_state_emitter.py:307 and then independently
#   re-defaulted to 0 by carousel.js::syncTile. This file pins the EMITTER half.
#   The DISPLAY half is pinned in tests/ui/test_carousel_sync_pending_na.py, and
#   the two are inseparable by design: either coercion alone ships green and the
#   panel still reads "0 pending".
#
#   Why this one mattered more than its size suggests: of every value this field
#   can take, 0 is the single most reassuring -- "every captured row is on the
#   server". It was a confident all-clear on data safety that no code had checked.
# Author: Rex (US-564)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-564) | Initial -- emitter emits None, carries through.
# ================================================================================
################################################################################

"""Tests for the US-564 syncPending emitter half (unmeasured -> None, not 0)."""

from __future__ import annotations

import inspect

from pi.splash.system_status_emitter import buildSystemStatusState


def _state(**overrides):
    """Build a system-status payload with the boring fields filled in."""
    kwargs = {
        "obdLinkState": "linked",
        "obdRetries": 0,
        "obdLastSeenS": 1,
        "syncLastOkTs": "2026-08-21T11:00:00Z",
        "syncRows": 120,
        "syncPending": None,
        "syncStale": False,
        "powerMode": "car",
        "powerSource": "external",
        "driveState": "idle",
        "driveId": None,
        "nowIso": "2026-08-21T12:00:00Z",
    }
    kwargs.update(overrides)
    return buildSystemStatusState(**kwargs)


class TestEmitterCarriesNullThrough:
    """A null must survive the payload build -- not be helpfully filled in."""

    def test_buildSystemStatusState_nonePending_staysNull(self):
        """
        Given: no caller measures a pending-row count
        When: the payload is built with syncPending=None
        Then: `sync.pending` is null in the emitted state. A helpful `or 0`
              anywhere on this path recreates the whole defect one layer down.
        """
        assert _state(syncPending=None)["sync"]["pending"] is None

    def test_buildSystemStatusState_realCountIsStillCarried(self):
        """
        Given: a caller that DOES measure a pending count
        When: the payload is built
        Then: the number lands unchanged -- the fix must not make the field
              permanently unreportable, only honestly-absent when unmeasured
        """
        assert _state(syncPending=7)["sync"]["pending"] == 7

    def test_buildSystemStatusState_measuredZeroIsStillZero(self):
        """
        Given: a caller that measured the count and it genuinely IS zero
        When: the payload is built
        Then: 0 is published. This is the whole point of the distinction: a
              measured zero is real news, and it must remain sayable now that
              an unmeasured one has stopped being said.
        """
        assert _state(syncPending=0)["sync"]["pending"] == 0

    def test_buildSystemStatusState_pendingKeyIsAlwaysPresent(self):
        """
        Given: an unmeasured count
        When: the payload is built
        Then: the KEY still exists carrying null -- an intermittently-absent key
              is the shape that lets a renderer fall through to a wrong branch,
              which is the sibling defect of coercing the value
        """
        assert "pending" in _state(syncPending=None)["sync"]


class TestTheEmitterNoLongerInventsACount:
    """The producer half of the two-layer fix, pinned at its source."""

    def test_cardStateEmitter_doesNotPassAHardCodedZero(self):
        """
        Given: the orchestrator call site that fills the system-status payload
        When: its source is read
        Then: it passes syncPending=None. Pinned STRUCTURALLY because no
              behavioural test of the emitter can see this: the call site is
              what chose the value, and a behavioural test would just observe
              whatever it chose.
        """
        from pi.obdii.orchestrator import card_state_emitter

        source = inspect.getsource(card_state_emitter)

        assert "syncPending=None" in source
        assert "syncPending=0" not in source

    def test_systemStatusEmitter_signaturesAcceptNone(self):
        """
        Given: the emitter's public entry point
        When: its annotation is read
        Then: the parameter is optional. A test that only passes None at runtime
              would pass against an `int` annotation too -- the contract has to
              SAY the field can be unmeasured, or the next caller re-adds a 0
              to satisfy the type.
        """
        annotation = inspect.signature(buildSystemStatusState).parameters["syncPending"].annotation

        assert "None" in str(annotation)
