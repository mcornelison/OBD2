################################################################################
# File Name: test_sync_pending_unmeasured.py
# Purpose/Description: US-564 instance A -- `syncPending` was a count nobody
#   measured, hard-coded to 0 at card_state_emitter.py:307 and then independently
#   re-defaulted to 0 by carousel.js::syncTile. This file pinned the EMITTER half
#   (unmeasured -> None, never 0).
#
#   MOVED PIN (US-894-c, Atlas P7): `sync.pending` and `sync.rows` are RETIRED
#   with the SYNC tile. The honest end state of an unmeasured count is no key at
#   all -- the backlog is US-916's `rowsWaiting`, null when not read. What this
#   file now pins is that the retired count cannot come back by either door:
#   the payload, or a builder / emit / call-site parameter.
# Author: Rex (US-564)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-564) | Initial -- emitter emits None, carries through.
# 2026-10-23    | Rex (US-894-c)| MOVED PIN: sync.pending / sync.rows retired;
#               |              | pins their absence instead of their null.
# ================================================================================
################################################################################

"""Tests that the retired sync.pending / sync.rows count stays retired (US-894-c)."""

from __future__ import annotations

import inspect

import pytest

from pi.splash.system_status_emitter import (
    buildSystemStatusState,
    makeSystemStatusEmitter,
)


def _state(**overrides):
    """Build a system-status payload with the boring fields filled in."""
    kwargs = {
        "syncLastOkTs": "2026-08-21T11:00:00Z",
        "syncStale": False,
        "powerSource": "external",
        "driveState": "idle",
        "driveId": None,
        "nowIso": "2026-08-21T12:00:00Z",
    }
    kwargs.update(overrides)
    return buildSystemStatusState(**kwargs)


class TestTheRetiredCountIsNotPublished:
    """MOVED PIN (US-894-c): no `pending` / `rows` key -- not null, absent."""

    def test_buildSystemStatusState_publishesNoPendingAndNoRows(self):
        """
        Given: a payload built with every sync input the builder takes
        When: its sync block is read
        Then: neither `pending` nor `rows` is a key. The backlog travels as
              rowsWaiting, null when not read -- the unmeasured all-clear US-564
              fought has no field left to live in.
        """
        sync = _state()["sync"]

        assert "pending" not in sync
        assert "rows" not in sync
        assert sync["rowsWaiting"] is None

    @pytest.mark.parametrize("retired", ["syncPending", "syncRows"])
    def test_buildSystemStatusState_refusesTheRetiredInput(self, retired):
        """
        Given: a caller still passing a retired input
        When: the payload is built
        Then: it raises -- a stale caller fails loudly rather than having its
              count silently dropped or, worse, published again.
        """
        with pytest.raises(TypeError):
            _state(**{retired: 0})

    @pytest.mark.parametrize("retired", ["syncPending", "syncRows"])
    def test_emitSignature_hasNoRetiredParameter(self, retired, tmp_path):
        emit = makeSystemStatusEmitter(str(tmp_path), syncStaleThresholdS=60)

        assert retired not in inspect.signature(emit).parameters
        assert retired not in inspect.signature(buildSystemStatusState).parameters


class TestTheCallSiteNoLongerPassesACount:
    """The producer half, pinned at its source."""

    def test_cardStateEmitter_passesNeitherRetiredInput(self):
        """
        Given: the orchestrator call site that fills the system-status payload
        When: its source is read
        Then: it passes neither syncPending nor syncRows, and caches no
              _lastSyncRows. Structural because a behavioural test of the
              emitter only observes what the call site chose.
        """
        from pi.obdii.orchestrator import card_state_emitter, core

        source = inspect.getsource(card_state_emitter)

        assert "syncPending=" not in source
        assert "syncRows=" not in source
        assert "self._lastSyncRows" not in source
        assert "_lastSyncRows: int" not in source
        assert "_lastSyncRows" not in inspect.getsource(core)
