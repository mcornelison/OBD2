################################################################################
# File Name: test_arch065_iso_format_owner.py
# Purpose/Description: ARCH-065a Ruling 19 (SSOT1) -- the canonical ISO-8601 UTC
#                      second format has ONE owner (src.common.time.helper.
#                      CANONICAL_ISO_FORMAT); the modules ARCH-065 added or
#                      changed import it rather than restating the literal.
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author             | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a)  | Ruling 19: created.
################################################################################
from __future__ import annotations

from pathlib import Path

import pytest

from src.common.time.helper import CANONICAL_ISO_FORMAT

_REPO = Path(__file__).resolve().parents[3]

_ARCH065_MODULES = (
    "src/pi/power/battery_health_verdict.py",
    "src/pi/power/battery_health_finalize.py",
    "src/pi/power/power_watch/tasks/monthly_test_hold.py",
    "src/pi/diagnostics/boot_progress.py",
    "tools/power/drain_calibration.py",
)


@pytest.mark.parametrize("relPath", _ARCH065_MODULES)
def test_theIsoFormat_isImported_neverRestated(relPath: str) -> None:
    source = (_REPO / relPath).read_text(encoding="utf-8")
    assert CANONICAL_ISO_FORMAT not in source
    assert "%Y-%m-%dT%H:%M:%S" not in source
    assert "CANONICAL_ISO_FORMAT" in source
