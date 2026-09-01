################################################################################
# File Name: test_battery_health_emitter.py
# Purpose/Description: Tests for the F-097 battery-health emitter (US-401). The
#   battery-health schema builder is pure (Atlas A-3 shape); the emit factory is
#   best-effort (write failures logged, never raised -- same contract as the
#   F-103 + US-400 emitters). Covers: the A-3 schema shape, the two render-
#   breaking traps locked at the data contract (F-8 SoC is NEVER derived from
#   voltage -- a null soc passes through verbatim; F-9/F-10/F-11 are render-side),
#   the A-6 no-false-failsafe invariant (the ladder is forced null whenever
#   draining is false, even if a caller supplies one), atomic write + states-dir
#   provisioning, and the never-raise guarantee.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial implementation (US-401 battery-health card)
# ================================================================================
################################################################################

"""Tests for ``pi.splash.battery_health_emitter``."""

import json
import os

from pi.splash.battery_health_emitter import (
    BATTERY_HEALTH_FILENAME,
    VERDICT_DEGRADED,
    VERDICT_GOOD,
    buildBatteryHealthState,
    makeBatteryHealthEmitter,
)

_NOW = "2026-06-30T19:42:00Z"
_LAST_CHECK = "2026-05-16T00:00:00Z"

# A representative healthy-on-external-power reading (A-3 schema, all fields).
_HEALTHY_KW = dict(
    vcellV=4.02,
    soc=76,
    socCalibrated=False,
    crate=1.8,
    charging=True,
    draining=False,
    restedVcellV=4.05,
    weakEvents30d=0,
    restedHistory=[4.05, 4.04, 4.06],
    health=VERDICT_GOOD,
    fullChargeReached=True,
    runtimeToCutoffS=714,
    ambientTempC=None,
    lastHealthCheckTs=_LAST_CHECK,
    ladder=None,
)


# ---------------------------------------------------------------------------
# buildBatteryHealthState -- the pure A-3 schema builder.
# ---------------------------------------------------------------------------


def test_buildBatteryHealthState_a3Schema_hasExactShape():
    """Given the Atlas A-3 fields,
    When buildBatteryHealthState assembles the payload,
    Then it emits exactly the A-3 shape (spec §7) with the supplied values.

    US-632 added the ``reasons`` map (why an unresolved field is unresolved).
    This fixture carries a RESOLVED `good` verdict, so the map is pinned EMPTY
    here -- which makes this test strictly stronger than before: a builder that
    attached a reason beside a real verdict now fails at the schema gate, not
    only in the US-632 file."""
    state = buildBatteryHealthState(nowIso=_NOW, **_HEALTHY_KW)
    assert state == {
        "vcellV": 4.02,
        "soc": 76,
        "socCalibrated": False,
        "crate": 1.8,
        "charging": True,
        "draining": False,
        "restedVcellV": 4.05,
        "weakEvents30d": 0,
        "restedHistory": [4.05, 4.04, 4.06],
        "health": "good",
        "fullChargeReached": True,
        "runtimeToCutoffS": 714,
        "ambientTempC": None,
        "lastHealthCheckTs": _LAST_CHECK,
        "ladder": None,
        "reasons": {},
        "source": {"ups": {"available": True, "reason": None}},
        "ts": _NOW,
    }


def test_buildBatteryHealthState_socNull_passesThroughVerbatim_neverDerived():
    """F-8 (voltage-is-not-percent): a null SoC (register unavailable) is
    serialized as null -- the emitter NEVER lerps a percent from vcellV. The
    near-empty voltage (3.44 V) must not leak out as a percent."""
    kw = dict(_HEALTHY_KW)
    kw["vcellV"] = 3.44
    kw["soc"] = None
    state = buildBatteryHealthState(nowIso=_NOW, **kw)
    assert state["soc"] is None
    assert state["vcellV"] == 3.44


def test_buildBatteryHealthState_drainingFalse_forcesLadderNull_a6():
    """A-6 no-false-failsafe: when draining is false the ladder is forced null
    even if a caller mistakenly supplies one -- the failsafe never renders when
    the pack is not actually draining (the D-2 dishonest-instrument trap)."""
    kw = dict(_HEALTHY_KW)
    kw["draining"] = False
    kw["ladder"] = {"stage": "WARNING", "thresholds": {}, "runtimeRemainingS": 360}
    state = buildBatteryHealthState(nowIso=_NOW, **kw)
    assert state["ladder"] is None


def test_buildBatteryHealthState_drainingTrue_preservesLadder():
    """When actually draining, a supplied ladder (Spool S-2 / thresholds) is
    preserved verbatim so the failsafe can render stage + runtime."""
    kw = dict(_HEALTHY_KW)
    kw["draining"] = True
    ladder = {
        "stage": "WARNING",
        "thresholds": {"warn": 3.70, "alert": 3.55, "trigger": 3.45},
        "runtimeRemainingS": 360,
    }
    kw["ladder"] = ladder
    state = buildBatteryHealthState(nowIso=_NOW, **kw)
    assert state["draining"] is True
    assert state["ladder"] == ladder


def test_buildBatteryHealthState_drainingTrue_noSpoolData_ladderStaysNull():
    """Conditional: if Spool's S-2 / thresholds are not yet delivered the caller
    passes ladder=None -- the builder keeps it null (no fabricated minutes); the
    render shows VCELL + DRAINING only."""
    kw = dict(_HEALTHY_KW)
    kw["draining"] = True
    kw["ladder"] = None
    state = buildBatteryHealthState(nowIso=_NOW, **kw)
    assert state["draining"] is True
    assert state["ladder"] is None


# ---------------------------------------------------------------------------
# US-429 honest-availability -- the UPS/MAX17048 source (whole card).
# ---------------------------------------------------------------------------


def test_buildBatteryHealthState_upsAvailable_carriesAvailableSource():
    """US-429: a normal reading carries source.ups available with a null reason
    (a live source has no NA reason)."""
    state = buildBatteryHealthState(nowIso=_NOW, **_HEALTHY_KW)
    assert state["source"] == {"ups": {"available": True, "reason": None}}


def test_buildBatteryHealthState_upsUnavailable_forcesFreshNullNeverStale():
    """US-429: an unreadable gauge -> every ups-owned numeric is a FRESH typed
    NULL (never a stale last-real cell reading, never a fabricated one) and the
    typed reason travels in source.ups. NA is NULL+reason, never a number."""
    kw = dict(_HEALTHY_KW)  # a full real reading the caller may still pass
    state = buildBatteryHealthState(
        nowIso=_NOW,
        upsAvailable=False,
        upsUnavailableReason="gauge unreadable",
        **kw,
    )
    assert state["vcellV"] is None
    assert state["soc"] is None
    assert state["crate"] is None
    assert state["restedVcellV"] is None
    assert state["runtimeToCutoffS"] is None
    assert state["draining"] is False
    assert state["ladder"] is None
    assert state["source"] == {"ups": {"available": False, "reason": "gauge unreadable"}}


# ---------------------------------------------------------------------------
# makeBatteryHealthEmitter -- best-effort atomic writer (A-3 ownership).
# ---------------------------------------------------------------------------


def test_emitter_writesBatteryHealthFile_andEnforcesLadderInvariant(tmp_path):
    """Given a states dir,
    When the emit callable fires with draining=False but a stray ladder,
    Then it writes states/battery-health with the A-3 payload and the A-6
    invariant zeroes the ladder (provisioning the dir if absent -- C-5)."""
    statesDir = str(tmp_path / "states")  # does NOT exist yet
    emit = makeBatteryHealthEmitter(statesDir, nowIsoFn=lambda: _NOW)

    kw = dict(_HEALTHY_KW)
    kw["ladder"] = {"stage": "WARNING"}  # stray ladder, draining False
    emit(**kw)

    written = json.loads(
        (tmp_path / "states" / BATTERY_HEALTH_FILENAME).read_text(encoding="utf-8")
    )
    assert written["vcellV"] == 4.02
    assert written["soc"] == 76
    assert written["ladder"] is None  # A-6: not draining -> no failsafe
    assert written["lastHealthCheckTs"] == _LAST_CHECK
    assert written["ts"] == _NOW


def test_emitter_drainingTrue_writesLadder(tmp_path):
    """A real drain writes the supplied ladder so the failsafe sub-state renders."""
    statesDir = str(tmp_path / "states")
    emit = makeBatteryHealthEmitter(statesDir, nowIsoFn=lambda: _NOW)

    kw = dict(_HEALTHY_KW)
    kw["draining"] = True
    kw["charging"] = False
    kw["ladder"] = {"stage": "ALERT", "thresholds": {}, "runtimeRemainingS": 180}
    emit(**kw)

    written = json.loads(
        (tmp_path / "states" / BATTERY_HEALTH_FILENAME).read_text(encoding="utf-8")
    )
    assert written["draining"] is True
    assert written["ladder"]["stage"] == "ALERT"
    assert written["ladder"]["runtimeRemainingS"] == 180


def test_emitter_neverRaises_onWriteFailure(tmp_path):
    """Best-effort: a write failure is logged but NEVER raised -- the emit hook
    must never block the orchestrator. Point it at an un-creatable path."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    statesDir = str(blocker / "states")  # parent is a file -> mkdir fails
    emit = makeBatteryHealthEmitter(statesDir, nowIsoFn=lambda: _NOW)

    kw = dict(_HEALTHY_KW)
    kw["health"] = VERDICT_DEGRADED
    emit(**kw)  # must not raise

    assert not os.path.exists(statesDir)
