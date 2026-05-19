################################################################################
# File Name: test_lifecycle_power_source_ssot.py
# Purpose/Description: SS-T4 SSOT-enforcement tests. (1) Ruling-D behavioural
#                      proof: the UI/power_log path is fed by the
#                      PowerSourceProvider transition adapter, NOT by
#                      UpsMonitor.getPowerSource. (2) Static SSOT guard: the
#                      lifecycle subscription no longer references
#                      getPowerSource and consumes the provider.
# Author: (shutdown-sequencer plan 2026-05-18, SS-T4 / Atlas ruling 2026-05-19)
# Creation Date: 2026-05-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-19    | Plan (SS-T4) | Initial -- B1 bridge transition behaviour
#                                (Ruling D) + getPowerSource SSOT static guard.
# ================================================================================
################################################################################
"""SS-T4: UI power-source flows from PowerSourceProvider (SSOT), not UpsMonitor."""

from src.pi.obdii.orchestrator.lifecycle import _PowerSourceUiBridge


def test_powerSourceUiBridge_feedsCheckPowerStatusFromProviderOnTransitions():
    """Ruling D: inject a fake PowerSourceProvider, drive present->lost->present;
    the sink (PowerMonitor.checkPowerStatus) receives ONLY the transitions and
    the value originates from the provider. First read always fires (None->X);
    a repeated identical reading is suppressed (no spurious power_log churn)."""
    seq = iter([True, True, False, False, True])

    class _FakeProvider:
        def isExternalPowerPresent(self) -> bool:
            return next(seq)

    calls: list[bool] = []
    bridge = _PowerSourceUiBridge(
        provider=_FakeProvider(),
        sink=lambda onAcPower: calls.append(onAcPower),
        pollSec=0.0,
    )

    fired = [bridge.pollOnce() for _ in range(5)]

    # external power present == on AC; lost == on battery.
    assert calls == [True, False, True]
    assert fired == [True, False, True, False, True]


def test_lifecycle_subscribeMethod_doesNotReferenceGetPowerSource():
    """Static SSOT guard (plan Task 4 Step 1). The lifecycle subscription
    method must NOT reference the retired UpsMonitor.getPowerSource heuristic
    and MUST consume PowerSourceProvider. Catches accidental reintroduction
    of the heuristic source path in this method."""
    import inspect

    from src.pi.obdii.orchestrator import lifecycle

    method = lifecycle.LifecycleMixin._subscribePowerMonitorToPowerSourceProvider
    src = inspect.getsource(method)
    # Strip the docstring before checking -- a docstring may legitimately
    # mention the retired ``getPowerSource`` name as historical context;
    # what we forbid is an actual call site in this method.
    codeOnly = src.split('"""', 2)[-1] if '"""' in src else src
    assert ".getPowerSource(" not in codeOnly, (
        "lifecycle subscription still CALLS UpsMonitor.getPowerSource "
        "(SSOT violation -- retired heuristic source path must not return)"
    )
    assert "PowerSourceProvider" in src, (
        "lifecycle subscription does not consume PowerSourceProvider (SSOT)"
    )


def test_powerSourceUiBridge_neverRaisesOutOnProviderOrSinkError():
    """The bridge thread must survive a provider/sink fault (a status surface
    must not be able to take anything down). A faulting read is swallowed and
    state is left so a later good read still transitions."""

    class _BoomProvider:
        def isExternalPowerPresent(self) -> bool:
            raise RuntimeError("gpio read blew up")

    bridge = _PowerSourceUiBridge(
        provider=_BoomProvider(),
        sink=lambda onAcPower: (_ for _ in ()).throw(AssertionError("must not fire")),
        pollSec=0.0,
    )
    assert bridge.pollOnce() is False  # swallowed, no raise, sink not called
