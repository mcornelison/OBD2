################################################################################
# File Name: battery_capacity.py
# Purpose/Description: SSOT for the monthly capacity test's timings
#                      (specs/battery-health-design.md sec 6 and 15). One owner
#                      per value: the hold task, isMonthlyTestDue, the boot
#                      finaliser, the verdict and the calibration tool import
#                      these; no literal 60 / 600 / 660 lives anywhere else.
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author             | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a)  | ARCH-065 T5: created (controller ruling 8).
################################################################################
"""Monthly capacity test timings -- see specs/battery-health-design.md sec 6, 15."""

from __future__ import annotations

__all__ = ['TEST_HOLD_S', 'WINDOW_S', 'WINDOW_SKIP_S']

#: Skip the post-cut rebound (seconds after the cut).
WINDOW_SKIP_S: int = 60
#: The measured window (seconds).
WINDOW_S: int = 600
#: Hold the Pi on battery this long after the cut.
TEST_HOLD_S: int = WINDOW_SKIP_S + WINDOW_S
