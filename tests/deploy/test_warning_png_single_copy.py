################################################################################
# File Name: test_warning_png_single_copy.py
# Purpose/Description: US-785 (Atlas C-Atlas-4) twin pins for the WARNING image.
#   One image, two consumers, no twin (spec §1.2): Plymouth draws
#   deploy/plymouth/eclipse/warning.png in phase 0 and the splash page shows the
#   same file in phase 0b. The deploy copies it into /opt/splash itself, so the
#   repo carries exactly ONE deployed copy -- and that copy is Iris's asset,
#   byte for byte.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-24    | Ralph (Rex)  | Initial -- US-785 twin pins (a) md5, (b) one copy.
# ================================================================================
################################################################################

"""US-785: the WARNING PNG has one deployed copy, equal to the spec asset."""

import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPEC_ASSET = REPO_ROOT / "specs" / "assets" / "boot" / "warning-480x320.png"
DEPLOYED = REPO_ROOT / "deploy" / "plymouth" / "eclipse" / "warning.png"


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def test_theDeployedCopyIsTheSpecAsset_a():
    """
    Given: Iris's asset (specs/assets/boot/warning-480x320.png)
    Then: the one deployed copy has the same md5
    """
    assert _md5(DEPLOYED) == _md5(SPEC_ASSET)


def test_thereIsNoOtherWarningPngUnderSrcOrDeploy_b():
    """
    Given: the deploy copies the Plymouth theme's PNG into /opt/splash itself
    Then: no second warning*.png exists under src/ or deploy/ to drift from it
    """
    found = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for root in ("src", "deploy")
        for path in (REPO_ROOT / root).rglob("warning*.png")
    )
    assert found == ["deploy/plymouth/eclipse/warning.png"], found
