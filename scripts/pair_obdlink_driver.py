#!/usr/bin/env python3
################################################################################
# File Name: pair_obdlink_driver.py
# Purpose/Description: bluetoothctl pairing driver for the OBDLink LX -- lifted
#                      out of the scripts/pair_obdlink.sh heredoc so it can be
#                      unit-tested.  Drives an SSP passkey-confirm pair, trusts
#                      the device, then RE-READS `info` and refuses to claim
#                      success unless Paired/Bonded/Trusted are all yes (the
#                      deliverable is a bond that survives a reboot, not a
#                      transient link).
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-31    | Rex (hotfix) | Initial -- Atlas CIO-directed P0 (BL-025 half 2,
#               |              | supersedes shelved US-475).  Fixes the prompt
#               |              | regex (bluez 5.82 prints `>`, not `#`, wrapped
#               |              | in ANSI) and swaps NoInputNoOutput ->
#               |              | DisplayYesNo so the confirm branch can fire.
# ================================================================================
################################################################################

"""Non-interactive OBDLink LX pairing over ``bluetoothctl``.

WHY A MODULE AND NOT A HEREDOC
------------------------------
This logic used to be a ``python3 - <<'PYEOF'`` block inside
``pair_obdlink.sh``.  Heredoc code cannot be imported, so it could not be
tested, and two defects shipped undetected until Atlas ran the script live on
the Pi (2026-07-31):

1. **Prompt regex.**  It waited for ``\\[.+\\]#``.  The Pi's bluez 5.82 prompts
   ``[bluetoothctl]>`` -- a ``>``, not a ``#`` -- so the very first
   ``expect()`` timed out before a single command was sent.  Worse, bluez
   wraps the prompt in ANSI (``\\x1b[0;94m[bluetoothctl]> \\x1b[0m``) and that
   escape sequence *contains a ``[``*, so the greedy ``.+`` would have spanned
   from the escape into the prompt even on a ``#``-terminated box.
   :data:`PROMPT_PATTERN` fixes both: the bracket body excludes ``[``/``]``, so
   a match can never start inside an escape, and either terminator is accepted
   (older bluez boxes keep working).

2. **Agent vs confirm branch.**  It registered ``agent NoInputNoOutput`` --
   "just works" pairing -- while the code below waited for
   ``Confirm passkey NNNNNN (yes/no):``, which only a display-capable agent
   ever produces.  The confirm branch was dead code and the LX's SSP could
   fail with ``org.bluez.Error.AuthenticationFailed``.  :data:`DEFAULT_AGENT`
   is now ``DisplayYesNo`` (the mode the CIO's phone pairs with).

TRANSPORT SEAM
--------------
:func:`runPairSession` never imports ``pexpect``.  It talks to a *child*
object with ``sendline`` / ``expect`` / ``before`` / ``close``, and translates
transport failures into :class:`PairTimeout` / :class:`PairEof`.
:class:`PexpectChild` is the production adapter and the only pexpect-aware
code here -- which matters because ``pexpect`` is a Pi-only requirement
(``requirements-pi.txt``) and is not installed on the Windows dev box.

Usage (normally invoked by ``scripts/pair_obdlink.sh``)::

    MAC=AA:BB:CC:DD:EE:FF python3 scripts/pair_obdlink_driver.py
    MAC=AA:BB:CC:DD:EE:FF python3 scripts/pair_obdlink_driver.py --force
"""

from __future__ import annotations

import os
import re
import sys
import time
from collections.abc import Callable
from typing import Any

# ==============================================================================
# Protocol constants
# ==============================================================================

#: Matches a bluetoothctl prompt in the RAW (still ANSI-coloured) stream.
#:
#: The bracket body forbids ``[``/``]``/newlines, which is what stops a match
#: starting inside an ANSI escape such as ``\x1b[0;94m``.  Both terminators are
#: accepted: ``>`` for bluez >= ~5.7x (``[bluetoothctl]>``) and ``#`` for the
#: legacy prompt (``[bluetooth]#``).  The body also matches the device alias
#: bluetoothctl switches to mid-pair (``[OBDLink LX]>``).
PROMPT_PATTERN = r"\[[^\[\]\r\n]{1,64}\]\s*[#>]"

#: bluez words the SSP confirmation several ways depending on agent + device
#: (``Confirm passkey N (yes/no):``, ``Accept pairing (yes/no):``,
#: ``Authorize service ... (yes/no):``).  ``(yes/no)`` is the invariant, so it
#: is listed as a fallback AFTER the specific passkey form.
CONFIRM_PASSKEY_PATTERN = r"Confirm passkey \d+ \(yes/no\)"
CONFIRM_GENERIC_PATTERN = r"\(yes/no\)"

PAIRING_SUCCESS_PATTERN = r"Pairing successful"
PAIRING_FAILURE_PATTERN = r"(?:Failed to pair[^\r\n]*|org\.bluez\.Error\.\w+)"
DEVICE_UNAVAILABLE_PATTERN = r"not available"

#: Display-capable agent -- REQUIRED for the passkey-confirm dance to fire at
#: all.  ``NoInputNoOutput`` (the previous value) silently skips it.
DEFAULT_AGENT = "DisplayYesNo"

DEFAULT_SCAN_SECONDS = 7
DEFAULT_PROMPT_TIMEOUT = 10
DEFAULT_PAIR_TIMEOUT = 60

#: How many confirm prompts to answer before giving up.  bluez can ask twice
#: (pairing confirm + service authorization); an unbounded loop against a
#: chatty stack would spin forever.
MAX_CONFIRM_ROUNDS = 8

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

_INFO_FLAG_RE = {
    "paired": re.compile(r"^\s*Paired:\s*(yes|no)\s*$", re.MULTILINE),
    "bonded": re.compile(r"^\s*Bonded:\s*(yes|no)\s*$", re.MULTILINE),
    "trusted": re.compile(r"^\s*Trusted:\s*(yes|no)\s*$", re.MULTILINE),
}


# ==============================================================================
# Errors
# ==============================================================================


class PairError(Exception):
    """The pairing attempt failed for a reason bluez reported."""


class PairTimeout(PairError):
    """The child produced nothing matching within the timeout."""


class PairEof(PairError):
    """bluetoothctl exited before the session finished."""


# ==============================================================================
# Pure helpers
# ==============================================================================


def stripAnsi(text: str) -> str:
    """Remove ANSI CSI escape sequences from ``text``.

    Args:
        text: Raw terminal output, possibly colour-wrapped.

    Returns:
        The same text with escape sequences removed.
    """
    return _ANSI_RE.sub("", text)


def parseBondState(infoOutput: str) -> dict[str, bool]:
    """Parse ``bluetoothctl info <MAC>`` output into bond flags.

    A device bluez has never seen prints ``Device <MAC> not available`` and no
    flags at all.  That is reported as ``known=False`` with every flag False --
    an unread flag is never rendered as a positive (honest-instrument; see
    specs/ssot-design-pattern.md).

    Args:
        infoOutput: Raw (possibly ANSI-coloured) output of ``info <MAC>``.

    Returns:
        ``{'known', 'paired', 'bonded', 'trusted'}`` -> bool.
    """
    plain = stripAnsi(infoOutput)
    state: dict[str, bool] = {"known": False, "paired": False, "bonded": False,
                              "trusted": False}
    for flag, pattern in _INFO_FLAG_RE.items():
        match = pattern.search(plain)
        if match is not None:
            state["known"] = True
            state[flag] = match.group(1) == "yes"
    return state


def isDurableBond(state: dict[str, bool]) -> bool:
    """True only when the bond survives a reboot AND auto-reconnects.

    ``Paired`` alone is not enough: without ``Bonded`` the link keys are not
    persisted, and without ``Trusted`` bluez will not let the device reconnect
    unattended -- which is exactly the in-car case (BL-025).
    """
    return bool(state.get("paired") and state.get("bonded") and state.get("trusted"))


def describeBondState(state: dict[str, bool]) -> str:
    """Human-readable one-liner for a bond state (used in error messages)."""
    if not state.get("known"):
        return "no bond on record (bluez does not know this device)"
    return (
        f"Paired: {'yes' if state['paired'] else 'no'}, "
        f"Bonded: {'yes' if state['bonded'] else 'no'}, "
        f"Trusted: {'yes' if state['trusted'] else 'no'}"
    )


# ==============================================================================
# Transport adapter (the only pexpect-aware code)
# ==============================================================================


class PexpectChild:
    """Adapts ``pexpect.spawn`` to the driver's transport surface.

    Translates ``pexpect.TIMEOUT`` / ``pexpect.EOF`` into :class:`PairTimeout`
    / :class:`PairEof` so :func:`runPairSession` stays pexpect-free (and
    therefore importable on a box without pexpect installed).
    """

    def __init__(self, command: str = "bluetoothctl", *, timeout: int = DEFAULT_PAIR_TIMEOUT,
                 logStream: Any | None = None) -> None:
        import pexpect  # local import: Pi-only dependency

        self._pexpect = pexpect
        self._child = pexpect.spawn(command, encoding="utf-8", timeout=timeout)
        if logStream is not None:
            self._child.logfile_read = logStream
        self.before = ""
        self.after = ""

    def sendline(self, line: str) -> None:
        self._child.sendline(line)

    def expect(self, patterns: list[str], timeout: float | None = None) -> int:
        try:
            index = self._child.expect(patterns, timeout=timeout)
        except self._pexpect.TIMEOUT as exc:
            raise PairTimeout(str(exc)) from exc
        except self._pexpect.EOF as exc:
            raise PairEof(str(exc)) from exc
        self.before = self._child.before or ""
        self.after = self._child.after or ""
        return index

    def close(self, force: bool = False) -> None:
        self._child.close(force=force)


# ==============================================================================
# The session
# ==============================================================================


def runPairSession(
    child: Any,
    mac: str,
    *,
    agentName: str = DEFAULT_AGENT,
    scanSeconds: int = DEFAULT_SCAN_SECONDS,
    promptTimeout: int = DEFAULT_PROMPT_TIMEOUT,
    pairTimeout: int = DEFAULT_PAIR_TIMEOUT,
    force: bool = False,
    sleepFn: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Drive a full pair + trust + verify against a bluetoothctl child.

    Args:
        child: Transport with ``sendline``/``expect``/``before``/``close``.
        mac: Bluetooth MAC of the dongle (validated by the shell wrapper).
        agentName: bluez agent capability; must be display-capable.
        scanSeconds: How long to leave discovery running before pairing.
        promptTimeout: Seconds to wait for a prompt to return.
        pairTimeout: Seconds to wait for the pair handshake to resolve.
        force: Re-pair even when a durable bond already exists.
        sleepFn: Injected sleep (tests pass a no-op).
        log: Injected line logger.

    Returns:
        ``{'action': 'paired'|'already-bonded', 'state': <bond state>}``.

    Raises:
        PairError: bluez reported a failure, or the resulting bond is not
            durable (Paired+Bonded+Trusted).
        PairTimeout: The dongle never answered -- usually not in pair mode.
        PairEof: bluetoothctl exited mid-session.
    """
    _awaitPrompt(child, promptTimeout)

    existing = _readBondState(child, mac, promptTimeout)
    if isDurableBond(existing) and not force:
        log(f"--- {mac} already has a durable bond ({describeBondState(existing)}) ---")
        log("--- nothing to do; pass --force to re-pair anyway ---")
        _send(child, "quit", promptTimeout, expectPrompt=False)
        return {"action": "already-bonded", "state": existing}

    # A half-bond (paired but not bonded/trusted, or a stale key after a dongle
    # factory reset) is precisely what makes `pair` fail with AlreadyExists or
    # AuthenticationFailed.  Clear it first.  Tolerated if bluez has no record.
    if existing["known"]:
        log(f"--- clearing existing bond record for {mac} ---")
        _send(child, f"remove {mac}", promptTimeout)

    _send(child, "power on", promptTimeout)
    _send(child, f"agent {agentName}", promptTimeout)
    _send(child, "default-agent", promptTimeout)

    # Discovery must have SEEN the device for `pair` to resolve it, but an
    # active scan competes with the pairing handshake on the same radio -- so
    # scan, then stop, then pair (Atlas's live-proven ordering, 2026-07-31).
    log(f"--- scanning {scanSeconds}s for {mac} (LX must show a solid blue LED) ---")
    _send(child, "scan on", promptTimeout)
    sleepFn(scanSeconds)
    _send(child, "scan off", promptTimeout)

    _runPairHandshake(child, mac, pairTimeout, log)

    _awaitPrompt(child, promptTimeout)
    _send(child, f"trust {mac}", promptTimeout)

    finalState = _readBondState(child, mac, promptTimeout)
    _send(child, "quit", promptTimeout, expectPrompt=False)

    if not isDurableBond(finalState):
        raise PairError(
            "pair reported success but the bond is NOT durable "
            f"({describeBondState(finalState)}) -- it will not survive a reboot"
        )

    return {"action": "paired", "state": finalState}


def _runPairHandshake(
    child: Any, mac: str, pairTimeout: int, log: Callable[[str], None]
) -> None:
    """Send ``pair`` and answer whatever confirmation bluez asks for."""
    child.sendline(f"pair {mac}")
    # Same echo anchor as _send: without it a stale prompt/`info` remnant could
    # satisfy one of the content patterns below before `pair` has said anything.
    _expectEcho(child, f"pair {mac}", pairTimeout)
    patterns = [
        CONFIRM_PASSKEY_PATTERN,
        CONFIRM_GENERIC_PATTERN,
        PAIRING_SUCCESS_PATTERN,
        PAIRING_FAILURE_PATTERN,
        DEVICE_UNAVAILABLE_PATTERN,
    ]
    for _round in range(MAX_CONFIRM_ROUNDS):
        try:
            index = child.expect(patterns, timeout=pairTimeout)
        except PairTimeout as exc:
            raise PairTimeout(
                "pair timed out -- is the LX powered (engine on) and in pair "
                f"mode (solid blue LED)? ({exc})"
            ) from exc
        if index in (0, 1):
            log("--- answering SSP confirmation: yes ---")
            child.sendline("yes")
            continue
        if index == 2:
            return
        if index == 3:
            raise PairError(f"pair failed: {stripAnsi(child.after).strip()}")
        raise PairError(
            f"{mac} was not found by discovery -- check the MAC and that the "
            "dongle is powered + in pair mode"
        )
    raise PairError(
        f"pair did not resolve after {MAX_CONFIRM_ROUNDS} confirmation prompts"
    )


def _readBondState(child: Any, mac: str, promptTimeout: int) -> dict[str, bool]:
    """Run ``info <MAC>`` and parse the reply."""
    return parseBondState(_send(child, f"info {mac}", promptTimeout))


def _send(child: Any, line: str, promptTimeout: int, *, expectPrompt: bool = True) -> str:
    """Send a command and return everything bluetoothctl printed in reply.

    ECHO ANCHORING -- load-bearing, not defensive.  bluetoothctl redraws its
    prompt several times during startup (verified in the captured transcript:
    a prompt, then padding + backspaces, then ``Agent registered``, then the
    prompt again).  A naive ``sendline(cmd); expect(PROMPT)`` therefore matches
    a STALE prompt that was already in the buffer, and ``before`` comes back
    holding terminal padding instead of the command's output -- a silent wrong
    answer rather than a hang, which is the worse failure of the two.  Waiting
    for the pty's echo of ``line`` first re-synchronises the stream, so the
    following prompt match is guaranteed to be the one this command caused.

    Fidelity limit: this assumes the echo arrives on one line.  A command long
    enough to wrap at the terminal width would break the anchor; every command
    this driver sends is well under 80 columns.
    """
    child.sendline(line)
    if not expectPrompt:
        return ""
    _expectEcho(child, line, promptTimeout)
    _awaitPrompt(child, promptTimeout)
    return child.before


def _expectEcho(child: Any, line: str, promptTimeout: int) -> None:
    """Consume the pty echo of ``line`` so the next prompt match is this one's."""
    child.expect([re.escape(line)], timeout=promptTimeout)


def _awaitPrompt(child: Any, promptTimeout: int) -> None:
    """Block until the bluetoothctl prompt comes back."""
    child.expect([PROMPT_PATTERN], timeout=promptTimeout)


# ==============================================================================
# CLI entry point (invoked by scripts/pair_obdlink.sh)
# ==============================================================================


def main(argv: list[str] | None = None) -> int:
    """Entry point.  MAC comes from ``$MAC`` (the shell wrapper validates it)."""
    args = list(sys.argv[1:] if argv is None else argv)
    force = "--force" in args

    mac = os.environ.get("MAC", "").strip()
    if not mac:
        sys.stderr.write("pair_obdlink_driver: $MAC is not set\n")
        return 2

    timeoutSeconds = int(os.environ.get("PAIR_TIMEOUT_S", str(DEFAULT_PAIR_TIMEOUT)))
    scanSeconds = int(os.environ.get("PAIR_SCAN_S", str(DEFAULT_SCAN_SECONDS)))

    try:
        child = PexpectChild(timeout=timeoutSeconds, logStream=sys.stdout)
    except ImportError:
        sys.stderr.write("pexpect missing -- see pair_obdlink.sh pre-flight message\n")
        return 1

    try:
        result = runPairSession(
            child,
            mac,
            scanSeconds=scanSeconds,
            pairTimeout=timeoutSeconds,
            force=force,
        )
    except PairError as exc:
        sys.stderr.write(f"\n{exc}\n")
        child.close(force=True)
        return 1

    if result["action"] == "already-bonded":
        sys.stdout.write(f"\n--- {mac} already bonded; no change made ---\n")
    else:
        sys.stdout.write(
            f"\n--- pair + trust successful for {mac} "
            f"({describeBondState(result['state'])}) ---\n"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
