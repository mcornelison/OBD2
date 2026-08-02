################################################################################
# File Name: test_power_source_provider.py
# Purpose/Description: Unit tests for PowerSourceProvider -- the Single Source of
#                      Truth wrapper over the X1209 GPIO6 PLD line. Verifies it
#                      is a faithful thin policy-free wrapper: the safe-direction
#                      ("unavailable => power present, do NOT shut down") and the
#                      arm self-check both come from the sound PldSensor, not a
#                      second acquisition path.
# Author: (shutdown-sequencer plan 2026-05-18, SS-T3)
# Creation Date: 2026-05-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-19    | Plan (SS-T3) | Initial -- provider is the single source for the
#                                power-source fact; unavailable is the safe
#                                direction; arm-check refuses to arm when unsure.
# ================================================================================
################################################################################
"""Tests for src/pi/power/power_source_provider.py (Shutdown Sequencer SS-T3)."""

from src.pi.power.power_source_provider import PowerSourceProvider


class _FakePld:
    """Models the REAL PldSensor contract (src/pi/hardware/pld_sensor.py:96-121).

    Critical: ``isExternalPowerPresent()`` returns the SAFE direction (True)
    when the line is unavailable -- the real sensor does ``if self._dev is
    None: return True`` (a read failure must NEVER read as 'power lost'). A
    fake that returned ``self._present`` regardless of availability would be
    mock-theatre: it would not model the dependency it stands in for.
    ``isPowerLost``/``startupPolarityOk`` are False when unavailable.
    """

    def __init__(self, present: bool, available: bool = True) -> None:
        self._present, self.isAvailable = present, available

    def isExternalPowerPresent(self) -> bool:
        # Real PldSensor: device unreadable -> True (non-bricking safe dir).
        return True if not self.isAvailable else self._present

    def isPowerLost(self) -> bool:
        return self.isAvailable and not self._present

    def startupPolarityOk(self) -> bool:
        return self.isAvailable and self._present


def test_provider_isTheSingleSourceForPowerFact():
    p = PowerSourceProvider(pld=_FakePld(present=True))
    assert p.isExternalPowerPresent() is True
    assert p.startupArmCheck() is True
    lost = PowerSourceProvider(pld=_FakePld(present=False))
    assert lost.isExternalPowerPresent() is False
    assert lost.startupArmCheck() is False


def test_provider_unavailable_isSafeDirection():
    p = PowerSourceProvider(pld=_FakePld(present=False, available=False))
    assert p.isExternalPowerPresent() is True   # uncertain => do NOT shut down
    assert p.startupArmCheck() is False          # but refuse to arm


# ---------------------------------------------------------------------------
# US-502: line readability, so each consumer can apply its OWN uncertainty
# policy over the one fact (SSOT: one provider, two policies).
# ---------------------------------------------------------------------------


def test_provider_exposesLineReadability_forConsumerUncertaintyPolicy():
    """The sequencer's safe direction ("unreadable => power present, do NOT
    self-brick") is a LIE on a UI tile -- it would paint a confident
    "external" off a dead GPIO. The provider therefore surfaces whether the
    line is readable at all, so the UI can resolve uncertainty its own way
    (unknown) without ever acquiring the fact a second way."""
    assert PowerSourceProvider(pld=_FakePld(present=True)).isAvailable is True
    assert PowerSourceProvider(pld=_FakePld(present=False)).isAvailable is True
    unreadable = PowerSourceProvider(pld=_FakePld(present=False, available=False))
    assert unreadable.isAvailable is False
    # The safe direction is UNCHANGED -- this adds a fact, it does not
    # re-point the shutdown path at a new one.
    assert unreadable.isExternalPowerPresent() is True


def test_provider_pldNotReportingAvailability_readsUnreadable():
    """A duck-typed pld that does not report readability resolves to NOT
    readable -- the honest direction for a display consumer (unknown), never
    an assumed-good line."""

    class _SilentPld:
        def isExternalPowerPresent(self) -> bool:
            return True

    assert PowerSourceProvider(pld=_SilentPld()).isAvailable is False
