################################################################################
# File Name: test_shutdown_handler_poweroff_auth.py
# Purpose/Description: Regression tests for I-036 (PolicyKit poweroff fail)
#                      and Bug #2 success-marker emission (US-341 / US-342
#                      crossover). Mocks subprocess so the suite runs cross-
#                      platform. Pins:
#                        (1) success path (returncode==0) emits the canary
#                            substring verbatim;
#                        (2) failure path (returncode!=0 with PolicyKit
#                            stderr) logs ERROR and raises ShutdownHandlerError
#                            -- never silently swallowed (the I-036 anti-
#                            pattern that masked the bug for 11 days).
# Author: Ralph
# Creation Date: 2026-05-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-15    | Ralph (US-341/US-342) | Initial -- V0.27.11 regression gate.
# ================================================================================
################################################################################

"""Regression tests for V0.27.11 shutdown-path hardening.

I-036: ``systemctl poweroff`` failed with PolicyKit "Interactive
authentication required" on every drain since V0.24.1 deploy
(2026-05-04). The handler silently swallowed the non-zero exit and
returned; the Pi continued running until buck-dropout hard-crash.
Fix: ERROR-log the failure and raise so the failure mode is loud.

I-037 / Bug #2: The boot_reason canary's ladder probe matched an
*intent* marker emitted *before* the subprocess.run call -- the marker
fired even when poweroff failed. Fix: emit a NEW success marker AFTER
subprocess.run returncode==0; canary probe re-points at this marker
(see test_boot_reason_canary.py).
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.pi.hardware.shutdown_handler import (
    SHUTDOWN_SUCCESS_MARKER,
    ShutdownHandler,
    ShutdownHandlerError,
)


class TestExecuteShutdownSuccessPath:
    """returncode==0 -> emit the canary substring; do NOT raise."""

    def test_returncodeZero_emitsSuccessMarkerVerbatim(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        handler = ShutdownHandler(shutdownDelay=30, lowBatteryThreshold=10)
        mockResult = MagicMock(returncode=0, stderr="", stdout="")
        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run",
            return_value=mockResult,
        ):
            with caplog.at_level(logging.WARNING):
                handler._executeShutdown()
        emitted = "\n".join(record.getMessage() for record in caplog.records)
        assert SHUTDOWN_SUCCESS_MARKER in emitted, (
            "Success-path emit must contain the canary substring "
            f"{SHUTDOWN_SUCCESS_MARKER!r} so boot_reason._probeLadderGraceful "
            "can recognize the prior boot as cleanly shut down."
        )
        handler.close()


class TestExecuteShutdownFailurePath:
    """returncode!=0 with PolicyKit stderr -> ERROR + raise (I-036)."""

    def test_policyKitDenial_raisesShutdownHandlerErrorWithStderr(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        handler = ShutdownHandler(shutdownDelay=30, lowBatteryThreshold=10)
        mockResult = MagicMock(
            returncode=1,
            stderr="Call to PowerOff failed: Interactive authentication required.",
            stdout="",
        )
        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run",
            return_value=mockResult,
        ):
            with caplog.at_level(logging.ERROR):
                with pytest.raises(ShutdownHandlerError) as excinfo:
                    handler._executeShutdown()
        assert "Interactive authentication required" in str(excinfo.value)
        errorRecords = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errorRecords, (
            "Failure path must log at ERROR level -- the I-036 anti-pattern "
            "was that this was logged at WARNING and silently swallowed."
        )
        handler.close()

    def test_policyKitDenial_doesNotEmitSuccessMarker(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        handler = ShutdownHandler(shutdownDelay=30, lowBatteryThreshold=10)
        mockResult = MagicMock(
            returncode=1,
            stderr="Call to PowerOff failed: Interactive authentication required.",
            stdout="",
        )
        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run",
            return_value=mockResult,
        ):
            with caplog.at_level(logging.DEBUG):
                with pytest.raises(ShutdownHandlerError):
                    handler._executeShutdown()
        emitted = "\n".join(record.getMessage() for record in caplog.records)
        assert SHUTDOWN_SUCCESS_MARKER not in emitted, (
            "Failure path MUST NOT emit the success marker -- that would "
            "let the next-boot canary lie 'clean' on a hard-crash, "
            "which is exactly the I-037 regression we are closing."
        )
        handler.close()
