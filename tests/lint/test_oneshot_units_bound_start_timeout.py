################################################################################
# File Name: test_oneshot_units_bound_start_timeout.py
# Purpose/Description: Standing-rule lint -- every Type=oneshot unit we ship must
#     set a finite TimeoutStartSec. systemd's DEFAULT start timeout for oneshot is
#     INFINITY, so one hung invocation holds a `start` job forever and every unit
#     ordered After= it waits forever as well.
#     Found the hard way on 2026-08-27: drain-forensics.service (oneshot, no
#     timeout, timer firing every 5s) hung ~4 hours when the UPS fuel gauge at
#     0x36 stopped answering on wall power. It blocked
#     boot-progress-finalize.service, which blocked `systemctl enable --now` in
#     deploy-pi.sh, which hung the DEPLOY at step 18 of 28 -- twice, with no error
#     anywhere. A hang must be bounded so it becomes a loud failed unit.
# Author: Claude (post-incident)
# Creation Date: 2026-08-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-27    | Claude       | Initial -- oneshot units must bound their start.
# ================================================================================
################################################################################

"""Lint: shipped Type=oneshot units must bound TimeoutStartSec."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DEPLOY_DIR = Path(__file__).resolve().parents[2] / "deploy"

# A oneshot whose ExecStart cannot hang -- pure systemd/coreutils with no I/O to a
# device or network -- does not need a ceiling. Each entry must say WHY.
EXEMPT: dict[str, str] = {}


def _oneshotUnits() -> list[Path]:
    out = []
    for p in sorted(DEPLOY_DIR.glob("*.service")):
        text = p.read_text(encoding="utf-8")
        # Match the SETTING, not the word in a comment: several units discuss
        # "Type=oneshot" in their header prose.
        if re.search(r"^\s*Type\s*=\s*oneshot\s*$", text, re.MULTILINE):
            out.append(p)
    return out


def test_thereAreOneshotUnitsToCheck() -> None:
    """Guard the guard: an empty glob would pass every case below."""
    assert _oneshotUnits(), f"no Type=oneshot units found under {DEPLOY_DIR}"


@pytest.mark.parametrize("path", _oneshotUnits(), ids=lambda p: p.name)
def test_oneshotUnit_boundsItsStartTimeout(path: Path) -> None:
    """
    Given: a shipped Type=oneshot unit
    When: its [Service] section is read
    Then: TimeoutStartSec is set to a finite value

    Unset means INFINITY for oneshot. `infinity` written explicitly is also a
    failure: it is the same hazard, just deliberate.
    """
    if path.name in EXEMPT:
        pytest.skip(f"exempt: {EXEMPT[path.name]}")

    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"^\s*TimeoutStartSec\s*=\s*(\S+)\s*$", text, re.MULTILINE,
    )

    assert match, (
        f"{path.name} is Type=oneshot with no TimeoutStartSec. systemd defaults "
        f"that to INFINITY, so a hang holds a start job forever and blocks every "
        f"unit ordered After= it -- including, in 2026-08-27's case, the deploy."
    )

    value = match.group(1).lower()
    assert value not in ("infinity", "0", "0s"), (
        f"{path.name} sets TimeoutStartSec={match.group(1)!r}, which is unbounded. "
        f"Use a finite ceiling generous enough for a healthy run."
    )
