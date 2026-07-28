################################################################################
# File Name: unit_manifest.py
# Purpose/Description: US-492 [F-122] THE single source of truth for the systemd
#   units this project installs on the Pi -- their names, short aliases,
#   bring-up order, and per-consumer policy.
#
#   Why this module exists: before US-492 the unit list lived in
#   src/pi/splash/service_control.py (the US-403 kiosk allow-list) and, in
#   fragments, across deploy-pi.sh and the two UI kit installers. Adding the
#   obdctl operator CLI would have created a SECOND list, and two lists drift
#   (US-492 AC-2 forbids it). So the names live HERE once and both consumers
#   derive from them:
#
#     * obdctl (pi/ops/obdctl.py)  -- the OPERATOR path. Runs as a human with
#       sudo. May act on every installed unit; the safety rails are a confirm
#       prompt + honest reporting, not a short list.
#     * service_control.py         -- the KIOSK path. Runs unprivileged behind
#       the 51-eclipse-service-control polkit rule. Sees a deliberately NARROW
#       subset (`kioskVerbs`), because a compromised kiosk must not be able to
#       reach the splash, the state server or the safe-shutdown guard.
#
#   Sharing the NAMES while keeping the POLICIES separate is the point: one
#   spelling of "eclipse-powerwatch.service", two different sets of rights.
#
#   D-7 / F-7 cardinal rule: eclipse-powerwatch is the safe-shutdown guard.
#   `isSafeShutdownGuard` is the flag every consumer keys its protection off.
#
# GROUNDING (US-492 AC-2): the 8 canonical units were verified installed on the
#   Pi 2026-07-27 (PM/CIO, recorded in the story). Ordering is grounded in the
#   units' own declarations, NOT invented:
#     rfcomm-bind.service        Requires/After=bluetooth.service (Type=oneshot)
#     eclipse-obd.service        After=network.target bluetooth.target
#     eclipse-powerwatch.service After=local-fs.target
#     eclipse-states-http.service After=local-fs.target
#     eclipse-boot-state.service Wants=eclipse-states-http.service
#     splash-boot.service        After=... eclipse-states-http eclipse-boot-state
#     splash-grace.service       After=eclipse-states-http.service
#     eclipse-dashboard.service  After=graphical.target eclipse-states-http
#
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

"""SSOT for the Pi's OBD systemd units: names, aliases, order, per-consumer policy."""

from __future__ import annotations

from dataclasses import dataclass, field

# The safe-shutdown guard (D-7 / F-7). Named here so no consumer has to spell it.
SAFE_SHUTDOWN_GUARD = "eclipse-powerwatch.service"

# Suffix every unit in this project carries. Accepted-but-optional when typing.
UNIT_SUFFIX = ".service"


class UnknownTargetError(ValueError):
    """Raised when a typed target matches no unit, alias or ``all``."""


@dataclass(frozen=True)
class UnitSpec:
    """One systemd unit this project owns.

    Attributes:
        unit: Full unit name (e.g. ``eclipse-obd.service``).
        aliases: Short tokens an operator may type instead of ``unit``.
        description: One line for the ``--help`` / status table.
        installedByDeploy: True when a deploy actually installs this unit on the
            Pi. A False entry stays KNOWN (so it can be reported honestly) but is
            never targeted by ``all``.
        inactiveIsNormal: True for oneshot / boot- / path-triggered units whose
            resting state is ``inactive``. Consumers annotate rather than
            implying a unit is broken (F-1 honest instrument).
        kioskVerbs: Verbs the UNPRIVILEGED kiosk may drive via US-403. Empty
            means the kiosk has no reach at all -- the default, deliberately.
        isSafeShutdownGuard: True only for the D-7 safe-shutdown guard.
    """

    unit: str
    aliases: tuple[str, ...]
    description: str
    installedByDeploy: bool = True
    inactiveIsNormal: bool = False
    kioskVerbs: frozenset[str] = field(default_factory=frozenset)
    isSafeShutdownGuard: bool = False


# ---------------------------------------------------------------------------
# THE manifest. Declared in START order (dependency order); stop order is this
# list reversed, so there is exactly one ordering to keep correct.
# ---------------------------------------------------------------------------
UNIT_MANIFEST: tuple[UnitSpec, ...] = (
    UnitSpec(
        unit="rfcomm-bind.service",
        aliases=("rfcomm", "bt"),
        description="Binds /dev/rfcomm0 to the OBDLink LX (oneshot, RemainAfterExit)",
        inactiveIsNormal=True,
    ),
    UnitSpec(
        unit=SAFE_SHUTDOWN_GUARD,
        aliases=("powerwatch", "pw"),
        description="Safe-shutdown guard: pre-shutdown pipeline + graceful poweroff",
        kioskVerbs=frozenset({"restart"}),
        isSafeShutdownGuard=True,
    ),
    UnitSpec(
        unit="eclipse-obd.service",
        aliases=("obd", "orchestrator"),
        description="Core OBD-II capture orchestrator",
        kioskVerbs=frozenset({"start", "stop", "restart"}),
    ),
    UnitSpec(
        unit="eclipse-states-http.service",
        aliases=("states", "states-http", "http"),
        description="Localhost token-gated state server (127.0.0.1:9899)",
    ),
    UnitSpec(
        unit="eclipse-boot-state.service",
        aliases=("boot-state", "bootstate"),
        description="Boot-state emitter (Wants=states-http)",
    ),
    UnitSpec(
        unit="splash-boot.service",
        aliases=("splash", "splash-boot"),
        description="Animated boot splash (renders at boot; WantedBy=graphical.target)",
        inactiveIsNormal=True,
    ),
    UnitSpec(
        unit="splash-grace.service",
        aliases=("grace", "splash-grace"),
        description="Grace-period shutdown splash (triggered by splash-grace.path)",
        inactiveIsNormal=True,
    ),
    UnitSpec(
        unit="eclipse-dashboard.service",
        aliases=("dashboard", "dash", "kiosk"),
        description="Chromium carousel dashboard kiosk",
        kioskVerbs=frozenset({"stop", "restart"}),
    ),
    # KNOWN-BUT-NOT-INSTALLED. eclipse-sync is on the US-403 allow-list + the 51-
    # polkit rule but was NOT among the Pi's installed units on 2026-07-27
    # (US-492 conditionalOutcome 2). Keeping the row -- rather than deleting it --
    # preserves the kiosk allow-list exactly as US-403/polkit shipped it while
    # keeping the unit out of `all`, and lets obdctl report it honestly as
    # not-installed if someone targets it by name.
    UnitSpec(
        unit="eclipse-sync.service",
        aliases=("sync",),
        description="Server upload (listed by US-403/polkit; not installed by deploy)",
        installedByDeploy=False,
        kioskVerbs=frozenset({"start", "stop", "restart"}),
    ),
)

# Derived views. Nothing below is hand-maintained.
START_ORDER: tuple[str, ...] = tuple(u.unit for u in UNIT_MANIFEST if u.installedByDeploy)
STOP_ORDER: tuple[str, ...] = tuple(reversed(START_ORDER))
CANONICAL_UNITS: tuple[str, ...] = START_ORDER

_BY_NAME: dict[str, UnitSpec] = {u.unit: u for u in UNIT_MANIFEST}


def lookup(unit: str) -> UnitSpec | None:
    """Return the spec for a full unit name, or None when unknown.

    Args:
        unit: Full unit name (e.g. ``eclipse-obd.service``).

    Returns:
        The ``UnitSpec``, or ``None`` if this project does not own that unit.
    """
    return _BY_NAME.get(unit)


def _normalize(token: str) -> str:
    """Lower-case a typed token and strip a redundant ``.service`` suffix."""
    token = token.strip().lower()
    if token.endswith(UNIT_SUFFIX):
        token = token[: -len(UNIT_SUFFIX)]
    return token


_BY_TOKEN: dict[str, str] = {}
for _spec in UNIT_MANIFEST:
    _BY_TOKEN[_normalize(_spec.unit)] = _spec.unit
    for _alias in _spec.aliases:
        _BY_TOKEN[_normalize(_alias)] = _spec.unit


def resolveTarget(token: str) -> tuple[str, ...]:
    """Resolve a typed target to one or more full unit names.

    ``all`` expands to every deploy-installed unit in START order; the caller
    reverses it for stop/kill. An alias, a bare unit name and a fully-suffixed
    unit name are all accepted, case-insensitively.

    Args:
        token: What the operator typed (``all``, an alias, or a unit name).

    Returns:
        A tuple of full unit names.

    Raises:
        UnknownTargetError: The token matches nothing. The message carries the
            offending token so the CLI can print it back verbatim rather than
            guessing at intent.
    """
    normalized = _normalize(token)
    if normalized == "all":
        return START_ORDER

    unit = _BY_TOKEN.get(normalized)
    if unit is None:
        raise UnknownTargetError(f"unknown target {token!r}")
    return (unit,)


def acceptedTokens() -> tuple[str, ...]:
    """Return every token ``resolveTarget`` accepts, for ``--help`` and errors."""
    tokens = {"all"}
    for spec in UNIT_MANIFEST:
        tokens.add(spec.unit)
        tokens.update(spec.aliases)
    return tuple(sorted(tokens))


def kioskAllowlist() -> dict[str, frozenset[str]]:
    """Build the US-403 kiosk (unit -> permitted verbs) allow-list.

    Only units that declare ``kioskVerbs`` appear: an empty set means the
    unprivileged kiosk has NO reach, which is the default for everything the
    System Setup menu was never designed to touch. This mirrors
    ``deploy/polkit-rules/51-eclipse-service-control.rules``; widening it here
    without widening the polkit rule would produce a UI that offers an action
    PolicyKit then denies.

    Returns:
        Mapping of unit name to the frozenset of verbs the kiosk may drive.
    """
    return {u.unit: u.kioskVerbs for u in UNIT_MANIFEST if u.kioskVerbs}
