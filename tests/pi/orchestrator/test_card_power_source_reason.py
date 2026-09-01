################################################################################
# File Name: test_card_power_source_reason.py
# Purpose/Description: US-628 validationCriteria 3 -- the TYPED REASON that
#   travels beside an unresolved `power.source`, pinned from the acquisition
#   branch that produces it all the way onto the state file the dashboard and
#   the punch list both read.
#
#   WHY THIS FILE EXISTS. `_gatherPowerSource` has always distinguished three
#   genuinely different operational facts -- no acquisition path was ever built,
#   the line exists but cannot be read, the read itself raised -- and published
#   ONE word for all three. The live Pi sits on the middle branch (two services
#   both claim BCM GPIO6; the loser's PldSensor gets EBUSY and `isAvailable` is
#   False forever -- I-us628), and a reader of the state file could not tell
#   that from a bench Pi with no provider wired at all. Those have different
#   fixes, and one word for three causes is the defect this sprint keeps finding.
#
#   NOT A NODE TEST, deliberately. Its sibling
#   tests/ui/test_carousel_power_mode_both_branches.py drives the same chain
#   through carousel.js and is skipped wherever node is absent. The claim HERE
#   is about the state file's contents, which is exactly the artefact Atlas read
#   to write punch list H3/3.3 -- so it must run on every box, including the
#   ones that cannot render.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-01    | Ralph (Rex)  | Initial -- US-628 typed power-source reason.
# ================================================================================
################################################################################

"""US-628: a typed reason travels with an unresolved power.source."""

import json
import re

import pytest

from pi.obdii.orchestrator.card_state_emitter import (
    POWER_SOURCE_UNKNOWN_REASONS,
    REASON_POWER_SOURCE_PROVIDER_ABSENT,
    REASON_POWER_SOURCE_READ_FAILED,
    REASON_POWER_SOURCE_UNREADABLE,
    CardStateEmitterMixin,
)

# The three words `source` may take. A reason is a claim about an ABSENCE, so it
# must never collide with one of these -- a consumer switching on `source` has
# to keep working unchanged.
_SOURCE_VALUES = frozenset({"external", "battery", "unknown"})


class _FakePld:
    """Models the REAL PldSensor contract (src/pi/hardware/pld_sensor.py:96-121).

    Load-bearing: an unreadable line answers ``isExternalPowerPresent() ==
    True`` -- the shutdown path's non-bricking safe direction -- NOT the stored
    value. A fake that returned ``_present`` when unavailable would let a test
    pass while the tile painted a confident `external` off a dead GPIO.
    """

    def __init__(self, present: bool, available: bool = True) -> None:
        self._present, self.isAvailable = present, available

    def isExternalPowerPresent(self) -> bool:
        return True if not self.isAvailable else self._present

    def isPowerLost(self) -> bool:
        return self.isAvailable and not self._present

    def startupPolarityOk(self) -> bool:
        return self.isAvailable and self._present


class _RaisingPld:
    """A line whose read blows up rather than answering -- the third cause."""

    isAvailable = True

    def isExternalPowerPresent(self) -> bool:
        raise OSError("I2C/GPIO read exploded")


def _provider(pld):
    from pi.power.power_source_provider import PowerSourceProvider

    return PowerSourceProvider(pld=pld)


class _Orch(CardStateEmitterMixin):
    """The real mixin with only the power facts attached.

    ``_powerSourceProvider`` is set ONLY when one is supplied, because the
    provider-absent branch is reached through ``getattr(self, ..., None)`` --
    assigning None here would test a different line of code than production
    executes on a Pi whose hardware manager has not started yet.
    """

    def __init__(self, statesDir, *, provider=None, mode=None):
        power = {} if mode is None else {"mode": mode}
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "power": power,
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
            }
        }
        self._connection = None
        self._driveDetector = None
        self._hardwareManager = None
        if provider is not None:
            self._powerSourceProvider = provider
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardPowerModeProvider = None
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0


def _emitPowerBlock(tmp_path, *, provider=None, mode=None) -> dict:
    """Run the REAL emit tick; return the `power` object written to disk.

    Everything between the PLD fake and the parsed JSON is production code:
    PowerSourceProvider -> _gatherPowerSource -> _gatherPowerState ->
    _emitSystemStatusState -> makeSystemStatusEmitter -> buildSystemStatusState
    -> writeStateAtomic. A pin taken anywhere short of the file would not have
    caught the missing passthrough this story spent an iteration blocked on.
    """
    orch = _Orch(str(tmp_path / "states"), provider=provider, mode=mode)
    orch._initializeCardStateEmitters()
    assert orch._maybeEmitCardStates() is True
    state = json.loads(
        (tmp_path / "states" / "system-status").read_text(encoding="utf-8")
    )
    return state["power"]


# ---------------------------------------------------------------------------
# The acquisition: one cause, one word.
# ---------------------------------------------------------------------------


def test_gatherPowerSource_externalPower_resolvesWithNoReason(tmp_path):
    """A REAL reading carries no reason. The reason field explains an absence
    and has no business standing beside a measurement -- the same contract
    US-632 pinned for the battery-health verdict."""
    orch = _Orch(str(tmp_path), provider=_provider(_FakePld(present=True)))
    assert orch._gatherPowerSource() == ("external", None)


def test_gatherPowerSource_battery_resolvesWithNoReason(tmp_path):
    """The other resolved branch. Both are pinned because one passing case is
    not evidence -- that is the mistake that produced this story's 2026-08-30
    correction."""
    orch = _Orch(str(tmp_path), provider=_provider(_FakePld(present=False)))
    assert orch._gatherPowerSource() == ("battery", None)


def test_gatherPowerSource_unreadableLine_saysSoByName(tmp_path):
    """THE LIVE PI'S STATE, and the reason this story exists.

    eclipse-powerwatch and eclipse-obd both construct PldSensor on BCM GPIO6;
    the loser gets EBUSY, `_dev` is None and `isAvailable` is False for the life
    of the process. Before this, that published the bare string `unknown` --
    indistinguishable from a bench Pi that was never wired at all.
    """
    orch = _Orch(
        str(tmp_path), provider=_provider(_FakePld(present=False, available=False))
    )
    assert orch._gatherPowerSource() == ("unknown", REASON_POWER_SOURCE_UNREADABLE)


def test_gatherPowerSource_noProviderAtAll_saysSoByName(tmp_path):
    """A DIFFERENT fact from the one above, and it has a different fix: there is
    no acquisition path here to be blocked. Reached through the production
    `getattr` miss, not through an injected None."""
    orch = _Orch(str(tmp_path))
    assert orch._gatherPowerSource() == (
        "unknown",
        REASON_POWER_SOURCE_PROVIDER_ABSENT,
    )


def test_gatherPowerSource_readRaises_saysSoByName(tmp_path):
    """The third cause: we had a line, we asked, and the ask threw. An
    instrument fault, not an absent instrument."""
    orch = _Orch(str(tmp_path), provider=_provider(_RaisingPld()))
    assert orch._gatherPowerSource() == ("unknown", REASON_POWER_SOURCE_READ_FAILED)


def test_theThreeCausesAreThreeDifferentWords(tmp_path):
    """The whole point, stated as one assertion.

    Collapsing any two of these back into a shared word passes every test
    above that names its own constant -- so the DISTINCTNESS is pinned
    separately, and by construction rather than by listing today's values.
    """
    reasons = [
        _Orch(str(tmp_path))._gatherPowerSource()[1],
        _Orch(
            str(tmp_path), provider=_provider(_FakePld(present=False, available=False))
        )._gatherPowerSource()[1],
        _Orch(str(tmp_path), provider=_provider(_RaisingPld()))._gatherPowerSource()[1],
    ]
    assert len(set(reasons)) == 3, f"three causes must not share a word: {reasons}"
    assert None not in reasons


def test_everyPublishedReasonIsInTheDeclaredVocabulary():
    """Closure guard: a new unresolved branch must register its word here, or
    a consumer that maps reasons to display text silently paints raw
    snake_case at the driver (the I-us656 shape)."""
    assert set(POWER_SOURCE_UNKNOWN_REASONS) == {
        REASON_POWER_SOURCE_PROVIDER_ABSENT,
        REASON_POWER_SOURCE_UNREADABLE,
        REASON_POWER_SOURCE_READ_FAILED,
    }


def test_theReasonsFollowTheSnakeCaseMachineIdiom():
    """`reasons.altitude: no_source` is the idiom the story names, and
    `gear_derivation` + `battery_health_verdict` already follow it. These are
    MACHINE words a renderer maps, which is why they are not the spaced human
    text used by the `source.*` block (`"not read yet"`) -- that one is rendered
    verbatim. Two shapes, two jobs; this pin keeps them from drifting together.
    """
    for reason in POWER_SOURCE_UNKNOWN_REASONS:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", reason), reason


def test_aReasonIsNeverAlsoALegalSourceValue():
    """`unknown` stays the VALUE; the reason explains it. If a reason could be
    mistaken for a source, a consumer reading the wrong key would still look
    right -- which is precisely how this field went unnoticed."""
    assert not (set(POWER_SOURCE_UNKNOWN_REASONS) & _SOURCE_VALUES)


# ---------------------------------------------------------------------------
# The transport: the reason reaches the FILE. This is the half that was fenced
# off last iteration -- the producer already knew the answer and had no way to
# say it.
# ---------------------------------------------------------------------------


def test_stateFile_unreadableLine_carriesTheTypedReason(tmp_path):
    """validationCriteria 3, end to end, on the live Pi's exact state:
    mode KNOWN (`wall`), source undeterminable. The file carries a typed reason
    -- not a bare `unknown`, not silence, and not a fabricated resolved value.
    """
    power = _emitPowerBlock(
        tmp_path,
        provider=_provider(_FakePld(present=False, available=False)),
        mode="wall",
    )
    assert power["source"] == "unknown"
    assert power["reasons"]["source"] == REASON_POWER_SOURCE_UNREADABLE
    # NOT a fabricated resolved value: the story's "SCOPE IS BOTH FIELDS"
    # warning, still in force. Legibility must not become confidence.
    assert power["source"] not in ("external", "battery")
    # The mode is a separate SSOT and the reason must not disturb it.
    assert power["mode"] == "wall"


def test_stateFile_noProvider_carriesADifferentReasonThanAnUnreadableLine(tmp_path):
    """The distinction has to survive the transport, not just the function.
    A passthrough that hardcoded one word would pass every producer test above.
    """
    absent = _emitPowerBlock(tmp_path / "a")
    unreadable = _emitPowerBlock(
        tmp_path / "b", provider=_provider(_FakePld(present=False, available=False))
    )
    assert absent["reasons"]["source"] == REASON_POWER_SOURCE_PROVIDER_ABSENT
    assert unreadable["reasons"]["source"] == REASON_POWER_SOURCE_UNREADABLE
    assert absent["reasons"] != unreadable["reasons"]


def test_stateFile_readRaises_carriesItsOwnReason(tmp_path):
    """Third cause, through the file. The emit path also has to SURVIVE it --
    a raising provider must not take the whole system-status write down."""
    power = _emitPowerBlock(tmp_path, provider=_provider(_RaisingPld()))
    assert power["reasons"]["source"] == REASON_POWER_SOURCE_READ_FAILED


def test_stateFile_resolvedSource_carriesNoReason(tmp_path):
    """A reason beside a real reading would be a second, contradictory account
    of the same fact. Both resolved branches, because either could regress
    alone."""
    external = _emitPowerBlock(tmp_path / "a", provider=_provider(_FakePld(True)))
    battery = _emitPowerBlock(tmp_path / "b", provider=_provider(_FakePld(False)))
    assert external["source"] == "external"
    assert external["reasons"] == {}
    assert battery["source"] == "battery"
    assert battery["reasons"] == {}


def test_stateFile_theReasonsKeyIsAlwaysPresent(tmp_path):
    """Never an intermittently-missing key -- the shape that lets a renderer
    fall quietly through to the wrong branch. This emitter already states the
    rule for `lastDrive` (system_status_emitter.py:227) and the same rule
    applies here."""
    for power in (
        _emitPowerBlock(tmp_path / "a", provider=_provider(_FakePld(True))),
        _emitPowerBlock(tmp_path / "b", provider=_provider(_FakePld(False))),
        _emitPowerBlock(tmp_path / "c"),
    ):
        assert "reasons" in power
        assert isinstance(power["reasons"], dict)


def test_buildSystemStatusState_refusesAReasonBesideAResolvedSource():
    """The guard, taken straight at the builder because no orchestrator branch
    can currently produce this pairing -- which is exactly why it needs a test.
    A future caller that forgot to clear the reason on recovery would publish
    "running on external power, because the line is unreadable"."""
    from pi.splash.system_status_emitter import buildSystemStatusState

    state = buildSystemStatusState(
        obdLinkState="linked",
        obdRetries=0,
        obdLastSeenS=1,
        syncLastOkTs=None,
        syncRows=0,
        syncPending=None,
        syncStale=False,
        powerMode="car",
        powerSource="external",
        powerSourceReason=REASON_POWER_SOURCE_UNREADABLE,
        driveState="idle",
        driveId=None,
        nowIso="2026-09-01T00:00:00Z",
    )
    assert state["power"]["reasons"] == {}


def test_buildSystemStatusState_unknownWithNoReasonStaysSilentRatherThanGuessing():
    """A caller that has no reason to give must not have one invented for it.
    `unknown` with an empty reasons map is honest under-reporting; a
    default-filled reason would be a fabricated diagnosis -- the same defect
    class as the `wall` default this story was corrected for."""
    from pi.splash.system_status_emitter import buildSystemStatusState

    state = buildSystemStatusState(
        obdLinkState="linked",
        obdRetries=0,
        obdLastSeenS=1,
        syncLastOkTs=None,
        syncRows=0,
        syncPending=None,
        syncStale=False,
        powerMode="car",
        powerSource="unknown",
        driveState="idle",
        driveId=None,
        nowIso="2026-09-01T00:00:00Z",
    )
    assert state["power"] == {"mode": "car", "source": "unknown", "reasons": {}}


@pytest.mark.parametrize("mode", ["car", "wall"])
def test_stateFile_theReasonDoesNotDisturbEitherModeBranch(mode, tmp_path):
    """US-628's first validationCriterion stays closed. The two facts come from
    two SSOTs and adding a reason to one must not perturb the other -- pinned on
    BOTH modes, because pinning one is the error this story was corrected for.
    """
    power = _emitPowerBlock(
        tmp_path,
        provider=_provider(_FakePld(present=False, available=False)),
        mode=mode,
    )
    assert power["mode"] == mode
    assert power["reasons"]["source"] == REASON_POWER_SOURCE_UNREADABLE
