################################################################################
# File Name: test_unit_manifest.py
# Purpose/Description: US-492 [F-122] tests for the OBD unit manifest -- the
#   SINGLE source of truth for which systemd units this project installs on the
#   Pi, what they are called, what order they may be brought up/down in, and
#   which of them the (unprivileged) kiosk is allowed to touch.
#
#   The manifest exists because US-492 would otherwise have created a SECOND
#   unit list beside the US-403 SERVICE_ALLOWLIST, and two lists drift. These
#   tests pin the three properties that make it a real SSOT:
#     1. the canonical list is exactly the 8 deploy-installed units,
#     2. the US-403 kiosk allow-list is DERIVED from it and is byte-identical to
#        what it was before (deriving must never WIDEN the kiosk's reach -- the
#        D-7 powerwatch restart-only rule and the 51- polkit mirror depend on
#        that list staying narrow),
#     3. start order respects the units' own `After=`/`Wants=` declarations and
#        stop order is its exact reverse.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-27    | Ralph (Rex)  | Initial implementation (US-492 obdctl SSOT).
# ================================================================================
################################################################################

"""Tests for the US-492 unit manifest (SSOT for the Pi's OBD systemd units)."""

from __future__ import annotations

import pytest

from pi.ops import unit_manifest as manifest

# The 10 deploy-installed units. The first 8 were verified on the Pi 2026-07-27
# (US-492 AC-2 grounding); eclipse-rfkill-unblock joined 2026-07-31 with the
# BL-025 P0 hotfix (verified live on the Pi by Atlas, then made repo-managed);
# eclipse-bond-selfheal joined 2026-08-10 with US-545 (A-18) -- its Pi-side
# verification is still owed, and it is listed here because deploy-pi.sh
# installs it, which is what CANONICAL_UNITS means.
# This literal is the ONE place the expectation is restated -- it is the fixture
# the SSOT is measured against, not a second production list.
EXPECTED_CANONICAL = {
    "eclipse-rfkill-unblock.service",
    "eclipse-bond-selfheal.service",
    "eclipse-obd.service",
    "eclipse-powerwatch.service",
    "eclipse-states-http.service",
    "eclipse-boot-state.service",
    "eclipse-dashboard.service",
    "rfcomm-bind.service",
    "splash-boot.service",
    "splash-grace.service",
}


# ---------------------------------------------------------------------------
# The canonical list (AC-2).
# ---------------------------------------------------------------------------


def test_canonicalUnits_matchesTheDeployInstalledUnits():
    """
    Given: the manifest is the SSOT for deploy-installed OBD units
    When: the canonical list is read
    Then: it is exactly the units verified installed on the Pi (8 from
        2026-07-27 + eclipse-rfkill-unblock from the 2026-07-31 BL-025 hotfix)
    """
    assert set(manifest.CANONICAL_UNITS) == EXPECTED_CANONICAL
    assert len(manifest.CANONICAL_UNITS) == len(EXPECTED_CANONICAL)


def test_canonicalUnits_excludesEclipseSyncWhichIsNotInstalled():
    """
    Given: eclipse-sync.service is on the US-403 allow-list but was NOT among the
        Pi's installed units (US-492 conditionalOutcome 2)
    When: the canonical list is read
    Then: eclipse-sync is known to the manifest but flagged not-installed, so
        `all` never targets it -- listed-but-absent is recorded, not silently
        dropped and not silently acted on
    """
    sync = manifest.lookup("eclipse-sync.service")

    assert sync is not None, "eclipse-sync must stay KNOWN so it can be reported honestly"
    assert sync.installedByDeploy is False
    assert "eclipse-sync.service" not in manifest.CANONICAL_UNITS


def test_everyCanonicalUnit_isMarkedInstalledByDeploy():
    """
    Given: the canonical list is derived, never hand-maintained
    When: each canonical entry is inspected
    Then: it is a manifest unit flagged installedByDeploy
    """
    for unit in manifest.CANONICAL_UNITS:
        spec = manifest.lookup(unit)
        assert spec is not None
        assert spec.installedByDeploy is True


# ---------------------------------------------------------------------------
# Ordering (AC-6) -- grounded in the units' own After= / Wants= declarations.
# ---------------------------------------------------------------------------


def test_stopOrder_isTheExactReverseOfStartOrder():
    """
    Given: `all` must bring units up in dependency order and down in reverse
    When: both orders are read
    Then: STOP_ORDER is START_ORDER reversed -- one list, no second ordering to
        drift out of sync
    """
    assert list(manifest.STOP_ORDER) == list(reversed(manifest.START_ORDER))


def test_startOrder_bringsStatesHttpUpBeforeItsConsumers():
    """
    Given: splash-boot/splash-grace/eclipse-dashboard all declare
        `After=eclipse-states-http.service`, and eclipse-boot-state declares
        `Wants=eclipse-states-http.service`
    When: the start order is read
    Then: states-http precedes every one of those consumers
    """
    order = list(manifest.START_ORDER)
    httpIndex = order.index("eclipse-states-http.service")

    for consumer in (
        "eclipse-boot-state.service",
        "splash-boot.service",
        "splash-grace.service",
        "eclipse-dashboard.service",
    ):
        assert httpIndex < order.index(consumer), f"{consumer} must start after states-http"


def test_stopOrder_takesTheKioskAndSplashDownFirstAndTheCoreLast():
    """
    Given: AC-6 -- stop kiosk/emitters/splash first, then states-http, then the
        core eclipse-obd/powerwatch last (avoids races + orphaned kiosks)
    When: the stop order is read
    Then: the kiosk leads, states-http follows the surfaces it feeds, and the
        core capture/guard pair is in the tail
    """
    order = list(manifest.STOP_ORDER)

    assert order[0] == "eclipse-dashboard.service"
    for surface in ("splash-boot.service", "splash-grace.service", "eclipse-dashboard.service"):
        assert order.index(surface) < order.index("eclipse-states-http.service")
    for core in ("eclipse-obd.service", "eclipse-powerwatch.service"):
        assert order.index(core) > order.index("eclipse-states-http.service")


def test_orders_containEveryCanonicalUnitAndNothingElse():
    """
    Given: `all` acts on the canonical list
    When: the start order is read
    Then: it covers every canonical unit exactly once, and no uninstalled unit
    """
    assert sorted(manifest.START_ORDER) == sorted(manifest.CANONICAL_UNITS)


# ---------------------------------------------------------------------------
# Alias resolution (AC-3).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token,expected",
    [
        ("obd", "eclipse-obd.service"),
        ("powerwatch", "eclipse-powerwatch.service"),
        ("dashboard", "eclipse-dashboard.service"),
        ("states", "eclipse-states-http.service"),
        ("splash", "splash-boot.service"),
        ("grace", "splash-grace.service"),
        ("boot-state", "eclipse-boot-state.service"),
        ("rfcomm", "rfcomm-bind.service"),
        ("eclipse-obd.service", "eclipse-obd.service"),
        ("eclipse-obd", "eclipse-obd.service"),
        ("ECLIPSE-OBD", "eclipse-obd.service"),
    ],
)
def test_resolveTarget_acceptsShortAliasesAndFullUnitNames(token, expected):
    """
    Given: AC-3 -- short aliases AND the full unit name are both accepted
    When: a token is resolved
    Then: it maps to the one canonical unit name
    """
    assert manifest.resolveTarget(token) == (expected,)


def test_resolveTarget_all_returnsEveryCanonicalUnitInStartOrder():
    """
    Given: AC-3 -- `all` targets every unit in the canonical list
    When: "all" is resolved
    Then: the full canonical list comes back in start order
    """
    assert manifest.resolveTarget("all") == tuple(manifest.START_ORDER)


def test_resolveTarget_unknownToken_raisesWithTheAcceptedTokens():
    """
    Given: a typo'd target
    When: it is resolved
    Then: an UnknownTargetError names the offending token -- the CLI can print
        the accepted tokens rather than guessing at what was meant
    """
    with pytest.raises(manifest.UnknownTargetError) as exc:
        manifest.resolveTarget("dashbaord")

    assert "dashbaord" in str(exc.value)


def test_acceptedTokens_includesAllAndEveryAlias():
    """
    Given: --help lists what may be typed
    When: the accepted-token list is read
    Then: it contains `all` plus every alias and unit name the resolver accepts
    """
    tokens = manifest.acceptedTokens()

    assert "all" in tokens
    for token in ("obd", "powerwatch", "dashboard", "eclipse-obd.service"):
        assert token in tokens


# ---------------------------------------------------------------------------
# Safety metadata (AC-4) + the derived US-403 kiosk allow-list.
# ---------------------------------------------------------------------------


def test_powerwatch_isFlaggedAsTheSafeShutdownGuard():
    """
    Given: D-7 / F-7 -- eclipse-powerwatch is the safe-shutdown guard
    When: the manifest is inspected
    Then: exactly one unit carries the guard flag, and it is powerwatch
    """
    guards = [u.unit for u in manifest.UNIT_MANIFEST if u.isSafeShutdownGuard]

    assert guards == ["eclipse-powerwatch.service"]
    assert manifest.SAFE_SHUTDOWN_GUARD == "eclipse-powerwatch.service"


def test_kioskAllowlist_derivedFromManifest_isUnchangedFromUS403():
    """
    Given: the US-403 kiosk allow-list is now DERIVED from the manifest
    When: it is rebuilt
    Then: it is byte-identical to the install-fixed list US-403 shipped. A
        derivation that WIDENS the kiosk's reach (e.g. to all 8 units) would
        hand an unprivileged, network-facing surface control of the splash and
        state server, and would silently diverge from the 51- polkit rule that
        mirrors this list. Narrowness is the safety property, so it is pinned.
    """
    assert manifest.kioskAllowlist() == {
        "eclipse-obd.service": frozenset({"start", "stop", "restart"}),
        "eclipse-sync.service": frozenset({"start", "stop", "restart"}),
        "eclipse-powerwatch.service": frozenset({"restart"}),
        "eclipse-dashboard.service": frozenset({"stop", "restart"}),
    }


def test_kioskAllowlist_neverGrantsStopOrKillOnTheSafeShutdownGuard():
    """
    Given: D-7 / F-7 cardinal rule (the polkit rule denies it too)
    When: the derived kiosk allow-list is read
    Then: powerwatch is restart-only
    """
    assert manifest.kioskAllowlist()[manifest.SAFE_SHUTDOWN_GUARD] == frozenset({"restart"})


def test_serviceControlModule_followsTheManifestRatherThanItsOwnList():
    """
    Given: AC-2 -- do NOT maintain a second divergent list
    When: the manifest gains a unit with kiosk verbs and service_control is
        re-imported
    Then: the US-403 allow-list FOLLOWS. Asserting only that the two lists are
        equal today would pass just as happily against a hardcoded copy -- the
        thing that must be proven is the WIRING, so the manifest is perturbed
        and the allow-list has to move with it.
    """
    import importlib

    from pi.splash import service_control

    probe = manifest.UnitSpec(
        unit="manifest-probe.service",
        aliases=(),
        description="derivation probe",
        kioskVerbs=frozenset({"restart"}),
    )
    original = manifest.UNIT_MANIFEST
    try:
        manifest.UNIT_MANIFEST = original + (probe,)
        reloaded = importlib.reload(service_control)
        assert reloaded.SERVICE_ALLOWLIST["manifest-probe.service"] == frozenset({"restart"})
    finally:
        manifest.UNIT_MANIFEST = original
        importlib.reload(service_control)

    assert dict(service_control.SERVICE_ALLOWLIST) == manifest.kioskAllowlist()


# ---------------------------------------------------------------------------
# Honest-state metadata (AC-7).
# ---------------------------------------------------------------------------


def test_oneshotAndPathTriggeredUnits_areFlaggedSoInactiveIsNotReadAsBroken():
    """
    Given: rfcomm-bind is Type=oneshot and splash-boot/splash-grace are
        boot/path-triggered -- `inactive` is their NORMAL resting state
    When: the manifest is inspected
    Then: they are flagged so a status table can say so instead of showing them
        red beside a genuinely-down daemon (F-1 honest instrument)
    """
    assert manifest.lookup("rfcomm-bind.service").inactiveIsNormal is True
    assert manifest.lookup("splash-grace.service").inactiveIsNormal is True
    assert manifest.lookup("eclipse-obd.service").inactiveIsNormal is False
    assert manifest.lookup("eclipse-powerwatch.service").inactiveIsNormal is False
