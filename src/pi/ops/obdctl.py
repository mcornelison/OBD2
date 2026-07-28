#!/usr/bin/env python3
################################################################################
# File Name: obdctl.py
# Purpose/Description: US-492 [F-122] `obdctl` -- the on-Pi operator CLI for the
#   OBD services. ONE command to status/start/stop/restart/kill any single unit
#   or ALL of them, so maintenance does not mean hand-typing systemctl eight
#   times and remembering the unit list.
#
#   Unit names, aliases and ordering come from pi.ops.unit_manifest (the SSOT) --
#   this module contributes POLICY only, and its policy is the operator's, not
#   the kiosk's (see unit_manifest for why those are deliberately different).
#
#   Design posture, in priority order:
#     1. SAFE BY DEFAULT. A bare invocation is `status all`. Nothing destructive
#        ever happens without an action word, and the two genuinely dangerous
#        moves -- stopping the safe-shutdown guard (D-7 / F-7) and SIGKILL --
#        need an explicit yes. Confirmation is collected BEFORE the first unit
#        is touched, so declining never leaves a half-torn-down stack.
#     2. HONEST (F-1). Every after-state is READ BACK from systemctl, never
#        assumed from a zero exit code; a unit this Pi does not have reads
#        `not-installed`, not an error; an unreadable state reads `unknown`,
#        never a confident guess.
#     3. WORKS WHEN THINGS ARE BROKEN. Stdlib only, no app imports, no config,
#        no venv -- the operator reaches for this tool precisely when those are
#        the things that are wrong.
#
#   `kill` is never an automatic escalation from a failed `stop`: silently
#   SIGKILLing a unit the operator was trying to shut down cleanly would destroy
#   the state they were trying to preserve.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-27    | Ralph (Rex)  | Initial implementation (US-492 obdctl).
# ================================================================================
################################################################################

"""obdctl: on-Pi service-control CLI for the Eclipse OBD units (US-492)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

# Allow `python3 /path/to/src/pi/ops/obdctl.py` with no PYTHONPATH set -- the
# deploy wrapper invokes this file by path, and a maintenance tool must not
# depend on the environment being right.
if __package__ in (None, ""):  # pragma: no cover - only on direct execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pi.ops import unit_manifest  # noqa: E402  (must follow the path bootstrap)

# Exit codes follow the project convention: 0 success / 1 config / 2 runtime.
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_ACTION_FAILED = 2

ACTIONS = ("status", "start", "stop", "restart", "kill")
DEFAULT_ACTION = "status"
DEFAULT_TARGET = "all"

# Seconds before a systemctl call is abandoned. A stuck unit must not wedge the
# operator's terminal; on timeout the unit reports an honest FAIL.
SYSTEMCTL_TIMEOUT_S = 15

STATE_NOT_INSTALLED = "not-installed"
STATE_UNKNOWN = "unknown"

# Post-action states that mean the action actually took. A `kill` commonly ends
# in `failed` (systemd records the signal), which is a successful kill.
_EXPECTED_AFTER = {
    "start": {"active", "activating", "reloading"},
    "restart": {"active", "activating", "reloading"},
    "stop": {"inactive", "deactivating", "failed"},
    "kill": {"inactive", "deactivating", "failed"},
}

# systemctl's own words for "you are not allowed to do that".
_PRIVILEGE_MARKERS = (
    "access denied",
    "authentication is required",
    "interactive authentication required",
    "permission denied",
    "not authorized",
)

USAGE = """\
obdctl -- control the Eclipse OBD services on the Pi

  usage: obdctl [status|start|stop|restart|kill] [<service>|all] [flags]

  Bare `obdctl` = `obdctl status all` (never a destructive default).

  actions:
    status    read each unit's state (no privilege needed, changes nothing)
    start     bring units up   -- `all` starts in dependency order
    stop      bring units down -- `all` stops in reverse-dependency order
    restart   stop+start
    kill      SIGKILL a STUCK unit. Forceful: resources may be left uncleaned.
              Use `stop` first; kill is never an automatic fallback for it.

  flags:
    -y, --yes, --force   skip the confirm prompts (scripted use)
    -n, --dry-run        print what would run; execute nothing
    -h, --help           this text

  SAFETY: {guard} is the safe-shutdown guard. With it
  stopped the Pi has NO graceful shutdown on power loss, so stop/kill of it
  (directly or via `all`) asks first. `restart` and `status` are unrestricted.

  exit: 0 all good | 1 usage error | 2 an action failed, was declined, or a
  named unit is not installed.

  targets: {targets}
"""


@dataclass
class UnitOutcome:
    """One unit's row in the report."""

    unit: str
    before: str
    action: str
    after: str
    result: str
    reason: str = ""


@dataclass
class _Options:
    """Parsed command line."""

    action: str = DEFAULT_ACTION
    target: str = DEFAULT_TARGET
    force: bool = False
    dryRun: bool = False
    help: bool = False
    error: str = ""


def parseArgs(argv: list[str]) -> _Options:
    """Parse obdctl's argument list.

    Flags may appear anywhere. Two positionals at most: action then target.

    Args:
        argv: Arguments WITHOUT the program name.

    Returns:
        An ``_Options``; ``error`` is non-empty when the line is unusable.
    """
    opts = _Options()
    positionals: list[str] = []

    for arg in argv:
        if arg in ("-h", "--help"):
            opts.help = True
        elif arg in ("-n", "--dry-run"):
            opts.dryRun = True
        elif arg in ("-y", "--yes", "--force"):
            opts.force = True
        elif arg.startswith("-"):
            opts.error = f"unknown flag {arg!r}"
            return opts
        else:
            positionals.append(arg)

    if len(positionals) > 2:
        opts.error = f"expected at most 2 arguments, got {len(positionals)}: {positionals}"
        return opts

    if positionals:
        opts.action = positionals[0].lower()
    if len(positionals) > 1:
        opts.target = positionals[1]

    if opts.action not in ACTIONS:
        opts.error = f"unknown action {opts.action!r} (expected one of: {', '.join(ACTIONS)})"
    return opts


def queryState(
    unit: str,
    runner: Callable[..., subprocess.CompletedProcess],
    timeoutS: float = SYSTEMCTL_TIMEOUT_S,
) -> str:
    """Read a unit's state, honestly.

    One `systemctl show` yields both LoadState and ActiveState, so
    not-installed and inactive can be told apart in a single call. Reading is
    unprivileged -- this never elevates.

    Args:
        unit: Full unit name.
        runner: ``subprocess.run``-compatible callable.
        timeoutS: Seconds before the read is abandoned.

    Returns:
        ``not-installed``, ``unknown``, or systemd's ActiveState string.
    """
    try:
        proc = runner(
            ["systemctl", "show", "-p", "LoadState", "-p", "ActiveState", "--value", unit],
            capture_output=True,
            text=True,
            timeout=timeoutS,
        )
    except Exception:
        return STATE_UNKNOWN

    fields = (proc.stdout or "").split()
    if proc.returncode != 0 or len(fields) < 2:
        return STATE_UNKNOWN
    loadState, activeState = fields[0], fields[1]
    if loadState == "not-found":
        return STATE_NOT_INSTALLED
    return activeState


def buildCommand(action: str, unit: str, isRoot: bool, sudoPath: str | None) -> list[str] | None:
    """Build the elevated systemctl argv for a mutating action.

    Args:
        action: One of start/stop/restart/kill.
        unit: Full unit name.
        isRoot: Whether this process is already root.
        sudoPath: Path to sudo, or None when unavailable.

    Returns:
        The argv, or None when there is no privilege path at all (the caller
        reports that rather than letting systemctl fail cryptically).
    """
    if action == "kill":
        base = ["systemctl", "kill", "-s", "SIGKILL", unit]
    else:
        base = ["systemctl", action, unit]

    if isRoot:
        return base
    if sudoPath:
        return ["sudo", *base]
    return None


def needsConfirmation(action: str, unit: str) -> bool:
    """Return True when this (action, unit) must be explicitly confirmed.

    Two cases, both from the story's safety criteria: stopping the D-7
    safe-shutdown guard (AC-4), and any SIGKILL (AC-5).
    """
    if action == "kill":
        return True
    return action == "stop" and unit == unit_manifest.SAFE_SHUTDOWN_GUARD


def _warningFor(action: str, unit: str) -> str:
    """The loud pre-action warning text for a protected action."""
    if unit == unit_manifest.SAFE_SHUTDOWN_GUARD and action in ("stop", "kill"):
        return (
            f"\n!! SAFETY: {unit} is the SAFE-SHUTDOWN GUARD.\n"
            "!! With it stopped the Pi has NO graceful shutdown on power loss --\n"
            "!! a key-off or a UPS drain can then corrupt the capture database.\n"
            "!! Bring it back with:  obdctl start powerwatch\n"
        )
    return (
        f"\n!! {action.upper()} sends SIGKILL to {unit}.\n"
        "!! The unit gets NO chance to clean up (sockets, /run files, DB handles).\n"
        "!! Prefer `obdctl stop` first; kill only when a unit is genuinely stuck.\n"
    )


def _resultFor(action: str, returnCode: int | None, after: str) -> bool:
    """Decide OK/FAIL from BOTH the exit code and the state read back."""
    if returnCode != 0:
        return False
    return after in _EXPECTED_AFTER[action]


def _translateReason(stderr: str, returnCode: int | None) -> str:
    """Turn systemctl's stderr into something an operator can act on."""
    text = (stderr or "").strip()
    if any(marker in text.lower() for marker in _PRIVILEGE_MARKERS):
        return (
            "insufficient privilege -- re-run with sudo "
            "(or check the 51-eclipse-service-control polkit rule)"
        )
    return text or f"systemctl exited {returnCode}"


def _promptConfirm(prompt: str) -> bool:  # pragma: no cover - interactive path
    """Ask on the terminal. A non-interactive stdin answers NO, never yes."""
    if not sys.stdin.isatty():
        print("(no terminal to confirm on -- refusing; pass --yes to proceed)")
        return False
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def _renderStatusRow(unit: str, state: str) -> str:
    """One status line, annotated when `inactive` is this unit's normal rest."""
    spec = unit_manifest.lookup(unit)
    note = ""
    if state == "inactive" and spec is not None and spec.inactiveIsNormal:
        note = "  (inactive is normal for this oneshot/triggered unit)"
    elif state == STATE_NOT_INSTALLED:
        note = "  (not installed on this Pi)"
    return f"  {unit:<28} {state:<14}{note}".rstrip()


def _renderActionRow(outcome: UnitOutcome) -> str:
    """One before -> action -> after line."""
    line = (
        f"  {outcome.unit:<28} {outcome.before:<13} -> {outcome.action:<8} -> "
        f"{outcome.after:<13} {outcome.result}"
    )
    if outcome.reason:
        line += f"\n      {outcome.reason}"
    return line


def main(
    argv: list[str] | None = None,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    confirmer: Callable[[str], bool] = _promptConfirm,
    stream: TextIO | None = None,
    isRoot: bool | None = None,
    sudoPath: str | None = None,
) -> int:
    """Run obdctl.

    Every side-effecting dependency is injected so the safety behaviour can be
    tested without a systemd on the other end.

    Args:
        argv: Arguments without the program name (defaults to sys.argv[1:]).
        runner: ``subprocess.run``-compatible callable.
        confirmer: Prompt callback; returns True to proceed.
        stream: Where to write the report (defaults to stdout).
        isRoot: Override the root check (defaults to a real euid check).
        sudoPath: Override sudo discovery (defaults to shutil.which).

    Returns:
        0 all good, 1 usage error, 2 an action failed / was declined / a named
        unit is not installed.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    stream = stream if stream is not None else sys.stdout
    if isRoot is None:
        isRoot = getattr(os, "geteuid", lambda: 1)() == 0
    if sudoPath is None:
        sudoPath = shutil.which("sudo")

    def emit(text: str = "") -> None:
        print(text, file=stream)

    opts = parseArgs(argv)

    if opts.help:
        emit(
            USAGE.format(
                guard=unit_manifest.SAFE_SHUTDOWN_GUARD,
                targets=", ".join(unit_manifest.acceptedTokens()),
            )
        )
        return EXIT_OK

    if opts.error:
        emit(f"obdctl: {opts.error}")
        emit(f"  accepted targets: {', '.join(unit_manifest.acceptedTokens())}")
        emit("  try: obdctl --help")
        return EXIT_USAGE

    try:
        units = unit_manifest.resolveTarget(opts.target)
    except unit_manifest.UnknownTargetError as exc:
        emit(f"obdctl: {exc}")
        emit(f"  accepted targets: {', '.join(unit_manifest.acceptedTokens())}")
        emit("  try: obdctl --help")
        return EXIT_USAGE

    isBatch = len(units) > 1
    if opts.action in ("stop", "kill"):
        units = tuple(reversed(units))

    # ---- read-only path -----------------------------------------------------
    if opts.action == "status":
        emit(f"obdctl status -- {len(units)} unit(s)")
        states = {unit: queryState(unit, runner) for unit in units}
        for unit in units:
            emit(_renderStatusRow(unit, states[unit]))
        emit(_statusSummary(states))
        _emitGuardBanner(emit, states)
        return EXIT_OK

    # ---- plan ---------------------------------------------------------------
    installed = {unit: queryState(unit, runner) != STATE_NOT_INSTALLED for unit in units}

    declined: set[str] = set()
    for unit in units:
        if not installed[unit] or not needsConfirmation(opts.action, unit):
            continue
        emit(_warningFor(opts.action, unit))
        if opts.force:
            emit(f"   --force given: proceeding with {opts.action} {unit}")
            continue
        if not confirmer(f"{opts.action} {unit}?"):
            declined.add(unit)

    # ---- act ----------------------------------------------------------------
    mode = "DRY-RUN " if opts.dryRun else ""
    emit(f"\nobdctl {mode}{opts.action} -- {len(units)} unit(s)")

    outcomes: list[UnitOutcome] = []
    for unit in units:
        outcomes.append(
            _actOnUnit(
                unit=unit,
                action=opts.action,
                declined=unit in declined,
                isBatch=isBatch,
                dryRun=opts.dryRun,
                runner=runner,
                isRoot=isRoot,
                sudoPath=sudoPath,
            )
        )
        emit(_renderActionRow(outcomes[-1]))

    emit(_actionSummary(outcomes))
    _emitGuardBanner(emit, {o.unit: o.after for o in outcomes})

    # A DECLINED action is non-zero too. The operator refusing is not a bug, but
    # the run did NOT do what the command line asked for, and a script (or a
    # half-read terminal) must not mistake a partial teardown for a complete
    # one. `SKIP` -- a unit this Pi never had -- is different: nothing was
    # requested of a unit that does not exist, so `all` still exits 0.
    incomplete = {"FAIL", "SKIPPED"}
    return EXIT_ACTION_FAILED if any(o.result in incomplete for o in outcomes) else EXIT_OK


def _actOnUnit(
    *,
    unit: str,
    action: str,
    declined: bool,
    isBatch: bool,
    dryRun: bool,
    runner: Callable[..., subprocess.CompletedProcess],
    isRoot: bool,
    sudoPath: str | None,
) -> UnitOutcome:
    """Run one unit's action and report what actually happened to it."""
    before = queryState(unit, runner)

    if before == STATE_NOT_INSTALLED:
        # Honest, not a crash. Inside `all` this is information; asked for by
        # name it is a failure, because the action the operator requested did
        # not happen.
        return UnitOutcome(
            unit=unit,
            before=before,
            action=action,
            after=before,
            result="SKIP" if isBatch else "FAIL",
            reason="not installed on this Pi",
        )

    if declined:
        return UnitOutcome(
            unit=unit,
            before=before,
            action=action,
            after=before,
            result="SKIPPED",
            reason="declined at the confirm prompt -- nothing was done to this unit",
        )

    command = buildCommand(action, unit, isRoot, sudoPath)
    if command is None:
        return UnitOutcome(
            unit=unit,
            before=before,
            action=action,
            after=before,
            result="FAIL",
            reason="needs root privilege and sudo is unavailable -- re-run as root",
        )

    if dryRun:
        return UnitOutcome(
            unit=unit,
            before=before,
            action=action,
            after=before,
            result="DRY-RUN",
            reason=f"would run: {' '.join(command)}",
        )

    try:
        proc = runner(command, capture_output=True, text=True, timeout=SYSTEMCTL_TIMEOUT_S)
        returnCode: int | None = proc.returncode
        stderr = proc.stderr or ""
    except Exception as exc:
        returnCode, stderr = None, f"{type(exc).__name__}: {exc}"

    after = queryState(unit, runner)
    ok = _resultFor(action, returnCode, after)
    return UnitOutcome(
        unit=unit,
        before=before,
        action=action,
        after=after,
        result="OK" if ok else "FAIL",
        reason="" if ok else _translateReason(stderr, returnCode),
    )


def _statusSummary(states: dict[str, str]) -> str:
    """Count line for a status run."""
    counts: dict[str, int] = {}
    for state in states.values():
        counts[state] = counts.get(state, 0) + 1
    breakdown = ", ".join(f"{n} {state}" for state, n in sorted(counts.items()))
    return f"\n  {len(states)} unit(s): {breakdown}"


def _actionSummary(outcomes: list[UnitOutcome]) -> str:
    """Count line for an action run."""
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.result] = counts.get(outcome.result, 0) + 1
    breakdown = ", ".join(f"{n} {result}" for result, n in sorted(counts.items()))
    return f"\n  {len(outcomes)} unit(s): {breakdown}"


def _emitGuardBanner(emit: Callable[[str], None], states: dict[str, str]) -> None:
    """Shout if the safe-shutdown guard is not running, and say how to fix it.

    Only fires when the guard was actually looked at, and only when it is down:
    an alarm that is always on is noise, and noise is how a real one gets
    ignored.
    """
    guard = unit_manifest.SAFE_SHUTDOWN_GUARD
    state = states.get(guard)
    if state is None or state == "active":
        return

    if state == STATE_UNKNOWN:
        # `unknown` means the read FAILED, not that the guard is down. Claiming
        # DOWN here would be a confident wrong answer about the one unit whose
        # status matters most -- and an operator who chases a phantom outage
        # once stops believing the banner the time it is real.
        emit("")
        emit(f"?? Could not read the state of {guard} (the safe-shutdown guard).")
        emit("?? Its status is UNKNOWN -- not confirmed down, not confirmed up.")
        emit("?? Check by hand:  systemctl status eclipse-powerwatch")
        return

    emit("")
    emit(f"!! SAFE-SHUTDOWN GUARD IS DOWN -- {guard} is {state}.")
    emit("!! The Pi has NO graceful shutdown on power loss while it is down.")
    emit("!! Bring it back with:  obdctl start powerwatch")


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
