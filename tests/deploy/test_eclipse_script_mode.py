################################################################################
# File Name: test_eclipse_script_mode.py
# Purpose/Description: Static pin that the Plymouth theme draws the WARNING only
#                      in boot mode (US-885-d). Plymouth runs the same theme
#                      script for boot, shutdown, reboot and updates; before this
#                      story the sprite was created unconditionally, so a key-off
#                      flashed the hazard WARNING for ~3 s after the shutdown
#                      splash (CIO, on the car 2026-10-26).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-26    | Rex          | Initial implementation (Sprint 118 US-885-d)
# ================================================================================
################################################################################

"""The WARNING image and sprite are created only inside the boot-mode branch.

Atlas VERIFIED the Pi's script.so exports ``Plymouth.GetMode()`` with the modes
boot, shutdown, reboot and updates
(pm/inbox/2026-10-27-from-atlas-DESIGN-S118-producers-and-data.md, S118-8).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
THEME_SCRIPT = REPO_ROOT / "deploy" / "plymouth" / "eclipse" / "eclipse.script"

BOOT_BRANCH = re.compile(r'^if\s*\(\s*Plymouth\.GetMode\(\)\s*==\s*"boot"\s*\)\s*$')
DRAW_MARKERS = ('Image("warning.png")', "Sprite(")


def _codeLines(text: str) -> list[str]:
    """Return executable lines only, stripped: comments and blanks removed."""
    out = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


def _splitAtBootBranch(lines: list[str]) -> tuple[list[str], list[str]]:
    """Split code lines into (inside the boot branch, everywhere else).

    The branch is the line matching BOOT_BRANCH, then a line ``{``, up to the
    brace that closes it. Raises AssertionError when there is no such branch.
    """
    starts = [i for i, ln in enumerate(lines) if BOOT_BRANCH.match(ln)]
    assert len(starts) == 1, f"expected exactly one boot-mode branch, got {starts}: {lines}"
    start = starts[0]
    assert lines[start + 1] == "{", f"boot branch must open with a brace line: {lines}"
    depth = 0
    for end in range(start + 1, len(lines)):
        depth += lines[end].count("{") - lines[end].count("}")
        if depth == 0:
            break
    else:
        raise AssertionError(f"boot branch is never closed: {lines}")
    inside = lines[start + 2 : end]
    outside = lines[:start] + lines[end + 1 :]
    return inside, outside


def test_eclipseScript_drawsTheWarningOnlyInBootMode():
    """
    Given: the eclipse theme script Plymouth runs in every mode
    When: its code lines are split at the Plymouth.GetMode() == "boot" branch
    Then: the warning Image and Sprite are created inside that branch and
          nowhere else, so shutdown/reboot/updates draw nothing (black)
    """
    inside, outside = _splitAtBootBranch(_codeLines(THEME_SCRIPT.read_text(encoding="utf-8")))

    for marker in DRAW_MARKERS:
        assert any(marker in ln for ln in inside), f"{marker} missing from boot branch: {inside}"
        assert not [ln for ln in outside if marker in ln], (
            f"{marker} drawn outside the boot branch: {outside}"
        )
    assert not [ln for ln in outside if ln.startswith("warning.")], outside


def test_eclipseScript_bootPathIsUnchanged():
    """
    Given: the boot-mode branch
    When: its statements are read
    Then: they are the US-885-c draw verbatim: same image, full-frame scale,
          window-origin position
    """
    inside, _ = _splitAtBootBranch(_codeLines(THEME_SCRIPT.read_text(encoding="utf-8")))

    assert inside == [
        'warning.image = Image("warning.png").Scale(Window.GetWidth(), Window.GetHeight());',
        "warning.sprite = Sprite(warning.image);",
        "warning.sprite.SetX(Window.GetX());",
        "warning.sprite.SetY(Window.GetY());",
    ]


def test_eclipseScript_keepsTheBackgroundBlackInEveryMode():
    """
    Given: the theme script
    When: the lines outside the boot branch are read
    Then: the black background is set unconditionally, so a non-boot mode
          shows a black screen
    """
    _, outside = _splitAtBootBranch(_codeLines(THEME_SCRIPT.read_text(encoding="utf-8")))

    assert "Window.SetBackgroundTopColor(0, 0, 0);" in outside
    assert "Window.SetBackgroundBottomColor(0, 0, 0);" in outside
