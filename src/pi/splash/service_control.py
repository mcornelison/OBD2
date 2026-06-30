################################################################################
# File Name: service_control.py
# Purpose/Description: US-403 [Atlas A-7] System Setup menu service-control SSOT.
#   The chromium kiosk runs UNPRIVILEGED; the System Setup menu lets the operator
#   restart/stop a FIXED set of eclipse-* units. The privilege to call
#   `systemctl <verb> <unit>` comes from the net-new 51-eclipse-service-control
#   polkit rule (granted to User=mcornelison, scoped to specific units+verbs) --
#   NOT a root helper, NOT sudo (I-036 polkit precedent; kiosk never root).
#
#   This module owns the INSTALL-FIXED allow-list (SERVICE_ALLOWLIST) and the
#   action-path re-check: every action is validated against the allow-list HERE,
#   at execution time, so a tampered or bypassed UI can never drive an off-list
#   action (the F-092 analog of US-407's S-10 clear-gate re-check). The allow-list
#   is a code-fixed constant -- NOT config -- because "install-fixed" is a safety
#   property: a runtime-editable list would let a kiosk compromise widen its own
#   reach.
#
#   D-7 / F-7 cardinal rule: `eclipse-powerwatch` (the safe-shutdown guard) is
#   RESTART-ONLY. A stop/kill is refused here AND denied by the polkit rule
#   itself -- layered defense, never just a disabled UI button.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial implementation (US-403 service control).
# ================================================================================
################################################################################

"""Install-fixed service-control allow-list + action-path re-check (US-403)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass

# Seconds before a `systemctl` action is abandoned. A hung systemctl must not
# wedge the state-server request thread; on timeout the action reports an honest
# failure (never a fabricated success).
SYSTEMCTL_TIMEOUT_S = 15

# ---------------------------------------------------------------------------
# The install-fixed allow-list (Atlas A-7; design spec sec 4.6; deploy units).
#   eclipse-obd.service        -> start/stop/restart  (data capture)
#   eclipse-sync.service       -> start/stop/restart  (server upload)
#   eclipse-powerwatch.service -> restart ONLY        (D-7 safe-shutdown guard)
#   eclipse-dashboard.service  -> stop/restart        (A-8 Exit = stop the kiosk)
# Any other unit, or a verb outside a unit's set, is denied. Mirrored by the
# 51-eclipse-service-control polkit rule (deploy/polkit-rules/) which is the
# ultimate authorization backstop.
# ---------------------------------------------------------------------------
SERVICE_ALLOWLIST: Mapping[str, frozenset[str]] = {
    "eclipse-obd.service": frozenset({"start", "stop", "restart"}),
    "eclipse-sync.service": frozenset({"start", "stop", "restart"}),
    "eclipse-powerwatch.service": frozenset({"restart"}),
    "eclipse-dashboard.service": frozenset({"stop", "restart"}),
}


@dataclass(frozen=True)
class ServiceControlResult:
    """Outcome of a service-control request.

    Attributes:
        ok: True only when an allow-listed action ran and ``systemctl`` exited 0.
        unit: The requested unit (echoed back for the caller/log).
        verb: The requested verb.
        returnCode: The ``systemctl`` exit code, or ``None`` when the action was
            rejected before execution (off-list) or the call errored/timed out.
        reason: Empty on success; otherwise an honest, human-readable cause.
    """

    ok: bool
    unit: str
    verb: str
    returnCode: int | None
    reason: str


def isAllowed(unit: str, verb: str) -> bool:
    """Return True iff ``verb`` is permitted on ``unit`` by the fixed allow-list.

    Args:
        unit: A systemd unit name (e.g. ``eclipse-obd.service``).
        verb: A systemctl verb (e.g. ``restart``).

    Returns:
        True only for an exact (unit, verb) pair on ``SERVICE_ALLOWLIST``.
    """
    return verb in SERVICE_ALLOWLIST.get(unit, frozenset())


def runServiceAction(
    unit: str,
    verb: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    timeoutS: float = SYSTEMCTL_TIMEOUT_S,
) -> ServiceControlResult:
    """Validate against the allow-list, then run ``systemctl <verb> <unit>``.

    The allow-list is re-checked HERE (defense-in-depth): an off-list action is
    rejected and ``systemctl`` is never invoked, regardless of what the UI sent.
    A non-zero exit or a runner error yields an honest failure -- never a faked
    success -- and never propagates (the state-server thread must not crash).

    Args:
        unit: The systemd unit to act on.
        verb: The systemctl verb.
        runner: Injectable process runner (``subprocess.run``-compatible); tests
            substitute a fake so no real ``systemctl`` is invoked.
        timeoutS: Seconds before the systemctl call is abandoned.

    Returns:
        A ``ServiceControlResult`` describing the outcome.
    """
    if not isAllowed(unit, verb):
        return ServiceControlResult(
            ok=False,
            unit=unit,
            verb=verb,
            returnCode=None,
            reason="action not on the install-fixed allow-list",
        )

    try:
        proc = runner(
            ["systemctl", verb, unit],
            capture_output=True,
            text=True,
            timeout=timeoutS,
        )
    except Exception as exc:  # subprocess timeout / OSError -> honest failure
        return ServiceControlResult(
            ok=False,
            unit=unit,
            verb=verb,
            returnCode=None,
            reason=f"systemctl {verb} failed: {exc}",
        )

    ok = proc.returncode == 0
    reason = ""
    if not ok:
        reason = (proc.stderr or "").strip() or f"systemctl {verb} exited {proc.returncode}"
    return ServiceControlResult(
        ok=ok, unit=unit, verb=verb, returnCode=proc.returncode, reason=reason
    )
