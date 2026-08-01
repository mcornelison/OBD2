################################################################################
# File Name: test_pair_obdlink_driver.py
# Purpose/Description: Unit tests for scripts/pair_obdlink_driver.py -- the
#                      bluetoothctl pairing driver lifted out of the
#                      pair_obdlink.sh heredoc so it can be tested at all.
#                      Drives the REAL driver state machine against a RECORDED
#                      bluetoothctl transcript captured live from the Pi
#                      (bluez 5.82, Trixie) on 2026-07-31, including the ANSI
#                      colour escapes bluetoothctl wraps its prompt in.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-31    | Rex (hotfix) | Initial -- Atlas CIO-directed P0 pair fix.
#               |              | Bugs pinned: (1) prompt regex expected the
#               |              | legacy `[bluetooth]#`, (2) NoInputNoOutput
#               |              | agent vs a Confirm-passkey branch.
# ================================================================================
################################################################################

"""Driver tests for the OBDLink LX pairing session.

WHY THIS SUITE EXISTS
---------------------
The pairing logic used to live in a ``python3 - <<'PYEOF'`` heredoc inside
``scripts/pair_obdlink.sh``.  Heredoc code cannot be imported, so it could not
be tested, and it shipped broken for months: it waited for a bluetoothctl
prompt ending in ``#`` while the Pi's bluez 5.82 prompts with ``>``.

FIDELITY -- what these tests really prove, and what they do not
--------------------------------------------------------------
The transcript below is **verbatim captured bytes** from the Pi
(``2026-07-31``, ``bluetoothctl 5.82``, controller ``88:A2:9E:84:46:1D``), so
the prompt/regex assertions are ground truth, not a guess at what bluez emits.

``_TranscriptChild`` is a miniature pexpect: it accumulates a byte stream and
resolves ``expect()`` by ``re.search`` for the EARLIEST match (ties broken by
pattern order), which is what ``pexpect.searcher_re`` does.  That is enough to
prove the pattern-vs-real-bytes question -- the question the shipped bug was
about.  It is NOT a pexpect substitute: pty behaviour, ``timeout`` wall-clock
and terminal echo are out of scope, and ``pexpect`` is not installed on the
Windows dev box (it is a Pi-only requirement), so the real ``PexpectChild``
adapter is exercised only on the Pi.

The one transcript fragment NOT captured live is the device-selected prompt
``[OBDLink LX]>`` -- there is no bond on the Pi to produce it.  It is Atlas's
reported observation (inbox 2026-07-31), and is marked as such below.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DRIVER_PATH = REPO_ROOT / "scripts" / "pair_obdlink_driver.py"


def _loadDriver():
    """Import the driver by path (scripts/ is not importable under pytest here)."""
    spec = importlib.util.spec_from_file_location("pair_obdlink_driver", DRIVER_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {DRIVER_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["pair_obdlink_driver"] = module
    spec.loader.exec_module(module)
    return module


driver = _loadDriver()


# ================================================================================
# Recorded transcript fragments -- VERBATIM bytes from the Pi, 2026-07-31
# ================================================================================

#: The prompt bluez 5.82 actually prints.  Note the ANSI wrapper CONTAINS a '['
#: -- that is why the old greedy ``\[.+\]#`` was wrong twice over.
REAL_PROMPT = "\x1b[0;94m[bluetoothctl]> \x1b[0m"

#: Verbatim opening of a real session (captured).  The old regex hung HERE, on
#: the very first expect(), before a single command was sent.
REAL_STARTUP = (
    "Waiting to connect to bluetoothd...\r"
    "\x1b[0;94m[bluetoothctl]> \x1b[0m        \x08\x08\x08\x08\x08\x08\x08\x08\r"
    "                                                                               \r"
    "Agent registered\r\n"
    "\x1b[0;94m[bluetoothctl]> \x1b[0m"
)

#: Device-selected prompt.  NOT captured live (no bond exists on the Pi to
#: produce it) -- reported by Atlas, inbox 2026-07-31.  Treated as a shape the
#: pattern must tolerate, not as measured ground truth.
REPORTED_DEVICE_PROMPT = "\x1b[0;94m[OBDLink LX]> \x1b[0m"

#: The legacy prompt from bluez <= 5.6x, which the shipped script assumed.
LEGACY_PROMPT = "[bluetooth]# "

TEST_MAC = "00:04:3E:85:0D:FB"

INFO_UNKNOWN = "Device 00:04:3E:85:0D:FB not available\r\n"

INFO_FULLY_BONDED = (
    "Device 00:04:3E:85:0D:FB (public)\r\n"
    "\tName: OBDLink LX\r\n"
    "\tAlias: OBDLink LX\r\n"
    "\tPaired: yes\r\n"
    "\tBonded: yes\r\n"
    "\tTrusted: yes\r\n"
    "\tBlocked: no\r\n"
    "\tConnected: no\r\n"
)

INFO_PAIRED_NOT_TRUSTED = (
    "Device 00:04:3E:85:0D:FB (public)\r\n"
    "\tPaired: yes\r\n"
    "\tBonded: no\r\n"
    "\tTrusted: no\r\n"
)

CONFIRM_PASSKEY = (
    "Request confirmation\r\n"
    "\x1b[0;93m[agent]\x1b[0m Confirm passkey 034567 (yes/no): "
)

PAIRING_SUCCESSFUL = "Pairing successful\r\n"

AUTH_FAILED = "Failed to pair: org.bluez.Error.AuthenticationFailed\r\n"


# ================================================================================
# _TranscriptChild -- a miniature pexpect over a scripted byte stream
# ================================================================================


class _TranscriptChild:
    """Replays recorded bluetoothctl bytes with pexpect's matching semantics.

    ``responses`` maps a command prefix to the bytes bluetoothctl emits for it.
    A value may be a list, in which case successive sends of that command get
    successive entries (the last one repeats) -- that is how a session that
    reads ``info`` before AND after pairing is modelled without giving the
    production driver a test-only parameter.

    An unmapped command simply returns to the prompt, which is what
    bluetoothctl does for a command with no output (verified in the capture:
    ``devices Paired`` with no bonds emitted nothing but the redrawn prompt).
    """

    def __init__(
        self,
        responses: dict[str, str | list[str]],
        *,
        startup: str = REAL_STARTUP,
        prompt: str = REAL_PROMPT,
    ) -> None:
        self._buffer = startup
        self._position = 0
        self._responses = responses
        self._callCounts: dict[str, int] = {}
        self._prompt = prompt
        self.sentLines: list[str] = []
        self.closed = False
        self.before = ""
        self.after = ""

    # -- driver-facing surface ------------------------------------------------

    def sendline(self, line: str) -> None:
        self.sentLines.append(line)
        self._buffer += f"{line}\r\n{self._responseFor(line)}{self._prompt}"

    def expect(self, patterns: list[str], timeout: float | None = None) -> int:
        """Earliest-match-wins over the unconsumed buffer (pexpect semantics)."""
        window = self._buffer[self._position:]
        best: tuple[int, int, re.Match[str]] | None = None
        for index, pattern in enumerate(patterns):
            found = re.search(pattern, window)
            if found is None:
                continue
            if best is None or (found.start(), index) < (best[0], best[1]):
                best = (found.start(), index, found)
        if best is None:
            raise driver.PairTimeout(f"no pattern matched; patterns={patterns!r}")
        _, matchedIndex, match = best
        self.before = window[: match.start()]
        self.after = match.group(0)
        self._position += match.end()
        return matchedIndex

    def close(self, force: bool = False) -> None:
        self.closed = True

    # -- internals ------------------------------------------------------------

    def _responseFor(self, line: str) -> str:
        for prefix, response in self._responses.items():
            if not line.startswith(prefix):
                continue
            if isinstance(response, str):
                return response
            seen = self._callCounts.get(prefix, 0)
            self._callCounts[prefix] = seen + 1
            return response[min(seen, len(response) - 1)]
        return ""

    # -- test-facing surface --------------------------------------------------

    @property
    def consumed(self) -> int:
        return self._position


def _pairingChild(
    *,
    info: str | list[str],
    pairOutcome: str = PAIRING_SUCCESSFUL,
    extra: dict[str, str | list[str]] | None = None,
) -> _TranscriptChild:
    responses: dict[str, str | list[str]] = {
        f"info {TEST_MAC}": info,
        f"pair {TEST_MAC}": pairOutcome,
    }
    if extra:
        responses.update(extra)
    return _TranscriptChild(responses)


def _run(child: _TranscriptChild, **kwargs) -> dict:
    return driver.runPairSession(
        child, TEST_MAC, sleepFn=_sleptNothing, log=lambda _m: None, **kwargs
    )


def _sleptNothing(_seconds: float) -> None:
    """Scan waits are wall-clock only -- never sleep in the suite."""


# ================================================================================
# The prompt contract -- the shipped defect, pinned against captured bytes
# ================================================================================


class TestPromptPattern:
    """Bug 1: the regex expected `#`; bluez 5.82 prints `>`."""

    def test_legacyPattern_cannotMatchTheRealPrompt_thisIsTheShippedBug(self) -> None:
        """The exact regex from the old heredoc, against the exact real bytes."""
        shippedPattern = r"\[.+\]#"
        assert re.search(shippedPattern, REAL_STARTUP) is None, (
            "if this ever matches, the transcript no longer reproduces the bug "
            "and the regression proof below is worthless"
        )

    def test_promptPattern_matchesTheRealCapturedPrompt(self) -> None:
        assert re.search(driver.PROMPT_PATTERN, REAL_PROMPT) is not None

    def test_promptPattern_matchesTheRealStartupBanner(self) -> None:
        """The first expect() is where the shipped script actually hung."""
        assert re.search(driver.PROMPT_PATTERN, REAL_STARTUP) is not None

    def test_promptPattern_stillMatchesTheLegacyHashPrompt(self) -> None:
        """Older bluez boxes must keep working (US-475 DoD: tolerate both)."""
        assert re.search(driver.PROMPT_PATTERN, LEGACY_PROMPT) is not None

    def test_promptPattern_matchesTheDeviceSelectedPrompt(self) -> None:
        """bluetoothctl swaps the prompt to the device alias mid-pair."""
        assert re.search(driver.PROMPT_PATTERN, REPORTED_DEVICE_PROMPT) is not None

    def test_promptPattern_doesNotSwallowTheAnsiEscape(self) -> None:
        """
        The ANSI wrapper contains a '[', so a greedy ``\\[.+\\]`` spans from the
        ESCAPE to the real bracket.  The match must begin at the real prompt.
        """
        match = re.search(driver.PROMPT_PATTERN, REAL_PROMPT)
        assert match is not None
        assert "\x1b" not in match.group(0), (
            f"prompt match captured an ANSI escape: {match.group(0)!r}"
        )
        assert match.group(0).startswith("[bluetoothctl]")

    def test_promptPattern_doesNotMatchABareAnsiColourCode(self) -> None:
        """An ANSI code alone must never be mistaken for a prompt."""
        assert re.search(driver.PROMPT_PATTERN, "\x1b[0;94m") is None


class TestStripAnsi:

    def test_stripAnsi_removesTheColourWrapperAroundTheRealPrompt(self) -> None:
        assert driver.stripAnsi(REAL_PROMPT) == "[bluetoothctl]> "

    def test_stripAnsi_leavesPlainTextUntouched(self) -> None:
        assert driver.stripAnsi("Pairing successful") == "Pairing successful"

    def test_stripAnsi_removesTheAgentTagColourInAConfirmPrompt(self) -> None:
        assert "\x1b" not in driver.stripAnsi(CONFIRM_PASSKEY)


# ================================================================================
# The agent contract -- Bug 2
# ================================================================================


class TestAgentSelection:
    """Bug 2: NoInputNoOutput never fires the Confirm-passkey prompt."""

    def test_defaultAgent_isDisplayCapable(self) -> None:
        assert driver.DEFAULT_AGENT in ("DisplayYesNo", "KeyboardDisplay"), (
            "the confirm branch only runs with a display-capable agent; "
            "NoInputNoOutput makes it dead code and SSP can auth-fail"
        )

    def test_session_registersTheDisplayCapableAgent(self) -> None:
        child = _pairingChild(info=[INFO_UNKNOWN, INFO_FULLY_BONDED])
        _run(child)
        assert f"agent {driver.DEFAULT_AGENT}" in child.sentLines
        assert "NoInputNoOutput" not in " ".join(child.sentLines)

    def test_session_makesTheAgentTheDefaultAgent(self) -> None:
        child = _pairingChild(info=[INFO_UNKNOWN, INFO_FULLY_BONDED])
        _run(child)
        agentIndex = child.sentLines.index(f"agent {driver.DEFAULT_AGENT}")
        assert "default-agent" in child.sentLines[agentIndex:], (
            "registering an agent without default-agent leaves bluez's own "
            "agent holding the callback"
        )


# ================================================================================
# Bond-state parsing -- the honest completion claim
# ================================================================================


class TestParseBondState:

    def test_parseBondState_readsAFullyBondedDevice(self) -> None:
        state = driver.parseBondState(INFO_FULLY_BONDED)
        assert state == {"known": True, "paired": True, "bonded": True, "trusted": True}

    def test_parseBondState_readsAPartialBond(self) -> None:
        state = driver.parseBondState(INFO_PAIRED_NOT_TRUSTED)
        assert state["paired"] is True
        assert state["bonded"] is False
        assert state["trusted"] is False

    def test_parseBondState_unknownDeviceIsNotSilentlyPaired(self) -> None:
        state = driver.parseBondState(INFO_UNKNOWN)
        assert state["known"] is False
        assert state["paired"] is False

    def test_parseBondState_toleratesTheAnsiWrappedOutput(self) -> None:
        noisy = REAL_PROMPT + INFO_FULLY_BONDED + REAL_PROMPT
        assert driver.parseBondState(noisy)["bonded"] is True

    def test_isDurableBond_requiresAllThreeFlags(self) -> None:
        assert driver.isDurableBond(driver.parseBondState(INFO_FULLY_BONDED)) is True
        assert driver.isDurableBond(driver.parseBondState(INFO_PAIRED_NOT_TRUSTED)) is False
        assert driver.isDurableBond(driver.parseBondState(INFO_UNKNOWN)) is False


# ================================================================================
# The pairing session
# ================================================================================


class TestRunPairSession:

    def test_session_pairsTrustsAndVerifies_onTheHappyPath(self) -> None:
        child = _pairingChild(info=[INFO_UNKNOWN, INFO_FULLY_BONDED])
        result = _run(child)
        assert result["action"] == "paired"
        assert result["state"]["bonded"] is True
        assert f"pair {TEST_MAC}" in child.sentLines
        assert f"trust {TEST_MAC}" in child.sentLines

    def test_session_answersTheConfirmPasskeyPrompt(self) -> None:
        child = _pairingChild(
            info=[INFO_UNKNOWN, INFO_FULLY_BONDED],
            pairOutcome=CONFIRM_PASSKEY,
            extra={"yes": PAIRING_SUCCESSFUL},
        )
        _run(child)
        assert "yes" in child.sentLines, (
            "the SSP passkey confirm is the whole reason this driver exists"
        )

    def test_session_answersABareYesNoPromptToo(self) -> None:
        """bluez words the confirm several ways; '(yes/no)' is the invariant."""
        child = _pairingChild(
            info=[INFO_UNKNOWN, INFO_FULLY_BONDED],
            pairOutcome="[agent] Accept pairing (yes/no): ",
            extra={"yes": PAIRING_SUCCESSFUL},
        )
        _run(child)
        assert "yes" in child.sentLines

    def test_session_raisesOnAuthenticationFailure(self) -> None:
        child = _pairingChild(info=INFO_UNKNOWN, pairOutcome=AUTH_FAILED)
        with pytest.raises(driver.PairError) as excinfo:
            _run(child)
        assert "AuthenticationFailed" in str(excinfo.value)

    def test_session_refusesToClaimSuccessWhenTheBondIsNotDurable(self) -> None:
        """
        'Pairing successful' is bluez's word for the LINK.  The deliverable is a
        bond that survives a reboot, so the driver re-reads ``info`` and refuses
        to print success on a paired-but-untrusted device.
        """
        child = _pairingChild(info=[INFO_UNKNOWN, INFO_PAIRED_NOT_TRUSTED])
        with pytest.raises(driver.PairError) as excinfo:
            _run(child)
        assert "trusted" in str(excinfo.value).lower()

    def test_session_isIdempotent_anExistingDurableBondIsNotDestroyed(self) -> None:
        """
        Re-running the script must NOT wipe a working bond -- re-pairing needs
        the dongle powered (engine on), so a needless ``remove`` can strand the
        car.  Verified by absence: no remove/pair is ever sent.
        """
        child = _pairingChild(info=INFO_FULLY_BONDED)
        result = _run(child)
        assert result["action"] == "already-bonded"
        assert not any(line.startswith("remove") for line in child.sentLines)
        assert not any(line.startswith("pair") for line in child.sentLines)

    def test_session_forceRepairsEvenWhenAlreadyBonded(self) -> None:
        child = _pairingChild(info=INFO_FULLY_BONDED)
        result = _run(child, force=True)
        assert result["action"] == "paired"
        assert f"remove {TEST_MAC}" in child.sentLines, (
            "a forced re-pair must clear the stale bond first, or bluez "
            "refuses with AlreadyExists"
        )

    def test_session_clearsAPartialBondBeforePairing(self) -> None:
        """A half-bond is what makes `pair` fail with AlreadyExists/AuthFailed."""
        child = _pairingChild(info=[INFO_PAIRED_NOT_TRUSTED, INFO_FULLY_BONDED])
        _run(child)
        removeIndex = child.sentLines.index(f"remove {TEST_MAC}")
        pairIndex = child.sentLines.index(f"pair {TEST_MAC}")
        assert removeIndex < pairIndex

    def test_session_scanIsOffBeforePairing(self) -> None:
        """
        Atlas's live-proven ordering: an active discovery session competes with
        the pairing handshake on the same radio.
        """
        child = _pairingChild(info=[INFO_UNKNOWN, INFO_FULLY_BONDED])
        _run(child)
        assert child.sentLines.index("scan on") < child.sentLines.index("scan off")
        assert child.sentLines.index("scan off") < child.sentLines.index(f"pair {TEST_MAC}")

    def test_session_waitsTheConfiguredScanWindow(self) -> None:
        slept: list[float] = []
        child = _pairingChild(info=[INFO_UNKNOWN, INFO_FULLY_BONDED])
        driver.runPairSession(
            child,
            TEST_MAC,
            scanSeconds=3,
            sleepFn=slept.append,
            log=lambda _m: None,
        )
        assert 3 in slept, "the scan window must be the injected value, not a literal"

    def test_session_neverSendsSudo(self) -> None:
        """Invariant from the script header: Python must not call sudo."""
        child = _pairingChild(info=[INFO_UNKNOWN, INFO_FULLY_BONDED])
        _run(child)
        assert not any("sudo" in line for line in child.sentLines)

    def test_session_quitsTheReplCleanly(self) -> None:
        child = _pairingChild(info=[INFO_UNKNOWN, INFO_FULLY_BONDED])
        _run(child)
        assert "quit" in child.sentLines


# ================================================================================
# Stale-prompt resynchronisation
# ================================================================================


class TestStalePromptResynchronisation:
    """
    bluetoothctl redraws its prompt during startup, so more than one prompt is
    sitting in the buffer before the first command is even sent.  A naive
    ``sendline(); expect(PROMPT)`` matches the STALE one and reads back terminal
    padding as if it were the command's reply -- a silent wrong answer, which is
    worse than the hang this hotfix set out to fix.
    """

    def test_capturedStartup_reallyDoesContainTwoPrompts(self) -> None:
        """Without this, the regression test below would be vacuous."""
        assert len(re.findall(driver.PROMPT_PATTERN, REAL_STARTUP)) >= 2

    def test_send_returnsTheCommandsOwnOutput_notTheStalePrompt(self) -> None:
        child = _TranscriptChild({f"info {TEST_MAC}": INFO_FULLY_BONDED})
        driver._awaitPrompt(child, 10)
        reply = driver.stripAnsi(driver._send(child, f"info {TEST_MAC}", 10))
        assert "Paired: yes" in reply, (
            "the reply is not this command's output -- the prompt match landed "
            "on a stale prompt left over from the startup banner"
        )
        assert "Agent registered" not in reply


# ================================================================================
# Harness self-check -- a silently no-op harness makes every test above green
# ================================================================================


class TestHarnessActuallyRan:

    def test_transcriptChild_actuallyConsumedTheRecordedBytes(self) -> None:
        child = _pairingChild(info=[INFO_UNKNOWN, INFO_FULLY_BONDED])
        _run(child)
        assert child.consumed > len(REAL_STARTUP), (
            "the driver never advanced past the startup banner -- the harness "
            "is not exercising the session"
        )
        assert len(child.sentLines) >= 8

    def test_transcriptChild_raisesPairTimeoutWhenNothingMatches(self) -> None:
        child = _TranscriptChild({}, startup="nothing resembling a prompt")
        with pytest.raises(driver.PairTimeout):
            child.expect([driver.PROMPT_PATTERN])


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
