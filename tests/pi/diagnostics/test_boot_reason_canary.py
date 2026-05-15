################################################################################
# File Name: test_boot_reason_canary.py
# Purpose/Description: Regression test for I-037 (V0.27.11 US-342).  Drain 22
#                      forensic (2026-05-15): orchestrator INTENT marker
#                      "PowerDownOrchestrator: TRIGGER at 3.446V" was in the
#                      prior-boot journal but poweroff FAILED (I-036
#                      PolicyKit denial). The US-308 ladder probe matched
#                      the intent marker and promoted prior_boot_clean to
#                      True -- a lie. Fix: repoint LADDER_GRACEFUL_GREP_PATTERN
#                      at SHUTDOWN_SUCCESS_MARKER (the post-success marker
#                      emitted by shutdown_handler._executeShutdown ONLY on
#                      returncode==0). This file also pins the runtime
#                      contract: handler-emit MUST contain the probe pattern,
#                      so future drift breaks the test at PR time instead
#                      of at next drain.
# Author: Ralph
# Creation Date: 2026-05-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-15    | Ralph (US-342) | Initial -- V0.27.11 regression gate +
#                                  contract test for handler-emit / probe-
#                                  pattern coupling.
# ================================================================================
################################################################################

"""Regression + contract tests for V0.27.11 honest-canary."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.pi.diagnostics.boot_reason import (
    LADDER_GRACEFUL_GREP_PATTERN,
    detectBootReason,
)
from src.pi.hardware.shutdown_handler import (
    SHUTDOWN_SUCCESS_MARKER,
    ShutdownHandler,
)

# Drain 22 prior-boot journal lines (the smoking gun).  TRIGGER intent
# marker is present; success marker is NOT (poweroff failed PolicyKit).
DRAIN_22_PRIOR_BOOT_LINES = [
    "May 14 22:53:08 chi-eclipse-01 python3[1234]: PowerDownOrchestrator: TRIGGER at 3.446V -- initiating poweroff",
    "May 14 22:53:09 chi-eclipse-01 python3[1234]: Initiating system shutdown",
    "May 14 22:53:09 chi-eclipse-01 python3[1234]: Shutdown command returned non-zero: 1. stderr: Call to PowerOff failed: Interactive authentication required.",
    "May 14 22:54:00 chi-eclipse-01 python3[1234]: drain continues ...",
    "May 14 22:55:24 chi-eclipse-01 python3[1234]: tick ...",
    # Journal ends abruptly mid-tick (buck-dropout hard-crash at ~3.30V).
]

# Drain N+1 prior-boot journal lines (graceful shutdown after V0.27.11 fix).
DRAIN_GRACEFUL_PRIOR_BOOT_LINES = [
    "May 16 22:53:08 chi-eclipse-01 python3[1234]: PowerDownOrchestrator: TRIGGER at 3.446V -- initiating poweroff",
    "May 16 22:53:09 chi-eclipse-01 python3[1234]: Initiating system shutdown",
    "May 16 22:53:09 chi-eclipse-01 python3[1234]: " + SHUTDOWN_SUCCESS_MARKER,
    "May 16 22:53:09 chi-eclipse-01 systemd[1]: Reached target Shutdown.",
    "May 16 22:53:10 chi-eclipse-01 systemd-shutdown[1]: Powering off.",
]


def _makeJournalctlRunner(priorBootLines: list[str]):
    """Build a journalctlRunner that mimics journalctl behavior over a fixed
    journal -- supports --list-boots, -b/-n/--reverse tail, and -b/-g/-n grep.
    """
    listBootsOutput = (
        "IDX BOOT ID                          FIRST ENTRY                LAST ENTRY                CONTAINER\n"
        "  0 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa Mon 2026-05-16 06:00:00 UTC Mon 2026-05-16 06:00:30 UTC -\n"
        " -1 bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb Thu 2026-05-14 21:00:00 UTC Thu 2026-05-14 22:55:24 UTC -\n"
    )

    def runner(args: list[str]) -> str | None:
        if args == ['--list-boots']:
            return listBootsOutput
        if '-g' in args:
            patternIdx = args.index('-g') + 1
            pattern = args[patternIdx]
            matches = [line for line in priorBootLines if pattern in line]
            return "\n".join(matches[-5:]) if matches else ""
        if '-n' in args and '--reverse' in args:
            # Tail of prior boot journal.
            return "\n".join(reversed(priorBootLines[-100:]))
        return ""

    return runner


class TestProbeLadderGracefulHonesty:
    """Drain-22-style journal -> priorClean MUST be False post-fix."""

    def test_intentMarkerOnly_priorBootCleanIsFalse(self) -> None:
        runner = _makeJournalctlRunner(DRAIN_22_PRIOR_BOOT_LINES)
        report = detectBootReason(
            bootIdReader=lambda: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            journalctlRunner=runner,
            sleeper=lambda _s: None,
        )
        assert report is not None
        assert report.priorBootClean is False, (
            "Drain 22 prior boot contains the TRIGGER intent marker but "
            "NO success marker (PolicyKit denied poweroff) -- the canary "
            "must NOT promote this to clean. Pre-fix it did (I-037)."
        )

    def test_successMarkerPresent_priorBootCleanIsTrue(self) -> None:
        runner = _makeJournalctlRunner(DRAIN_GRACEFUL_PRIOR_BOOT_LINES)
        report = detectBootReason(
            bootIdReader=lambda: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            journalctlRunner=runner,
            sleeper=lambda _s: None,
        )
        assert report is not None
        assert report.priorBootClean is True, (
            "Graceful prior boot contains SHUTDOWN_SUCCESS_MARKER -- the "
            "canary MUST recognize this as clean."
        )


class TestCanaryProbeContractWithHandler:
    """Runtime drift gate: handler-emit MUST contain the probe pattern."""

    def test_handlerSuccessEmit_containsProbePatternVerbatim(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The pattern boot_reason.py greps for MUST appear in the literal
        log line shutdown_handler emits on success.  If a future refactor
        renames either side without the other, this test breaks at PR
        time -- not at next drain.
        """
        handler = ShutdownHandler(shutdownDelay=30, lowBatteryThreshold=10)
        mockResult = MagicMock(returncode=0, stderr="", stdout="")
        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run",
            return_value=mockResult,
        ):
            with caplog.at_level(logging.WARNING):
                handler._executeShutdown()
        emitted = "\n".join(r.getMessage() for r in caplog.records)
        assert LADDER_GRACEFUL_GREP_PATTERN in emitted, (
            f"DRIFT: boot_reason.LADDER_GRACEFUL_GREP_PATTERN "
            f"({LADDER_GRACEFUL_GREP_PATTERN!r}) is not a substring of any "
            f"log line emitted by shutdown_handler._executeShutdown on "
            f"success. The canary contract is broken -- the next drain's "
            f"prior_boot_clean canary will lie 'hard-crash' on a graceful "
            f"shutdown. Either re-point LADDER_GRACEFUL_GREP_PATTERN at the "
            f"new handler emit, or restore the verbatim string."
        )
        handler.close()

    def test_probePatternIsSubstringOfSuccessMarkerConstant(self) -> None:
        """Static pin: pattern <= marker. Catches drift even without
        runtime invocation (e.g. when the handler module is refactored
        such that subprocess.run is mocked indirectly)."""
        assert LADDER_GRACEFUL_GREP_PATTERN in SHUTDOWN_SUCCESS_MARKER, (
            f"LADDER_GRACEFUL_GREP_PATTERN ({LADDER_GRACEFUL_GREP_PATTERN!r}) "
            f"must be a substring of SHUTDOWN_SUCCESS_MARKER "
            f"({SHUTDOWN_SUCCESS_MARKER!r})."
        )
