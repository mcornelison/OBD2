################################################################################
# File Name: test_shutdown_handler_boot_progress.py
# Purpose/Description: ShutdownHandler emits POWEROFF_INVOKED before
#                      subprocess.run and POWEROFF_RC0 only on returncode 0;
#                      honors config poweroffTimeoutSeconds.
# Author: Plan (T9)
# Creation Date: 2026-05-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-15    | Plan    | Initial -- T9 shutdown_handler boot_progress marks.
# ================================================================================
################################################################################

from unittest.mock import MagicMock, patch

from src.pi.hardware.shutdown_handler import ShutdownHandler


def test_executeShutdown_marksInvokedThenRc0OnSuccess():
    marks = []
    h = ShutdownHandler(suppressLegacyTriggers=True,
                        poweroffTimeoutSeconds=12,
                        bootProgressWriter=lambda s, v: marks.append(s.value))
    with patch("src.pi.hardware.shutdown_handler.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr="")
        h._executeShutdown()
        assert run.call_args.kwargs["timeout"] == 12
    assert marks == ["POWEROFF_INVOKED", "POWEROFF_RC0"]


def test_executeShutdown_marksInvokedButNotRc0OnFailure():
    marks = []
    h = ShutdownHandler(suppressLegacyTriggers=True,
                        bootProgressWriter=lambda s, v: marks.append(s.value))
    with patch("src.pi.hardware.shutdown_handler.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stderr="auth fail")
        try:
            h._executeShutdown()
        except Exception:
            pass
    assert marks == ["POWEROFF_INVOKED"]
