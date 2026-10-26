################################################################################
# File Name: test_set_boot_screen.py
# Purpose/Description: pytest wrapper + static guards for the power-on WARNING
#                      screen (deploy/set-boot-screen.sh + deploy/plymouth/
#                      eclipse/). Drives tests/deploy/test_set_boot_screen.sh via
#                      subprocess so the bash scenarios run in the fast suite,
#                      and adds the guards bash cannot express: the theme carries
#                      Iris's image byte-for-byte, the script edits the boot line
#                      only through the shared helper, and nothing waits.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-24    | Rex          | Initial implementation (Sprint 113 US-885-b)
# 2026-10-25    | Rex          | US-885-c: full-frame scale pin
# 2026-10-25    | Rex          | US-926-b: config.txt through the shared key writer
# ================================================================================
################################################################################

"""pytest wrapper around tests/deploy/test_set_boot_screen.sh + static guards.

The .sh script is the behavioural catalog: apply on a fixture boot dir, the
token union with set-display-mode.sh in either order, a byte-identical revert,
the idempotent second apply (no backup, no -R), .bak retention beside a foreign
pair, the failed-rebuild restore, the failing-cmp abort, and the revert's theme
choice. This file is the pytest entry point plus the static guards.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_SCRIPT = REPO_ROOT / "tests" / "deploy" / "test_set_boot_screen.sh"
SCRIPT = REPO_ROOT / "deploy" / "set-boot-screen.sh"
THEME_DIR = REPO_ROOT / "deploy" / "plymouth" / "eclipse"
WARNING_ASSET = REPO_ROOT / "specs" / "assets" / "boot" / "warning-480x320.png"
ARCHITECTURE = REPO_ROOT / "specs" / "architecture.md"


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


def _codeLines(text: str) -> list[str]:
    """Return executable-looking lines only: comments and blanks stripped."""
    out = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_setBootScreen_allScenariosPass():
    """
    Given: a fixture /boot/firmware, plymouthd.conf, themes dir and PATH stubs
    When: the bash catalog drives apply, --revert and set-display-mode against it
    Then: every scenario's exit code, file bytes and stub call holds
    """
    assert TEST_SCRIPT.exists(), f"missing bash catalog: {TEST_SCRIPT}"
    result = subprocess.run(
        ["bash", str(TEST_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        # A hang guard, not a budget: ~190 s alone on the Windows desk since
        # US-926-b's scenarios, and past 300 s under a loaded chunked run.
        timeout=600,
    )
    assert result.returncode == 0, (
        f"set-boot-screen bash catalog failed (exit {result.returncode}):\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert re.search(r"===\s*Results:\s*\d+\s*passed,\s*0\s*failed", result.stdout), (
        f"expected a zero-failure summary, got:\n{result.stdout[-600:]}"
    )


def test_theme_carriesIrisWarningImageByteForByte():
    """
    Given: Iris's WARNING asset (specs/assets/boot/warning-480x320.png, PR #130)
    When: the theme's image is compared to it
    Then: they are byte-identical -- the theme never carries a re-rendered copy
    """
    assert (THEME_DIR / "warning.png").read_bytes() == WARNING_ASSET.read_bytes()


def test_theme_isAScriptThemeInstalledUnderItsOwnName():
    """
    Given: the theme descriptor and its script
    When: they are read
    Then: the descriptor names the script module at the install path, and the
          script draws warning.png
    """
    descriptor = (THEME_DIR / "eclipse.plymouth").read_text(encoding="utf-8")
    assert "ModuleName=script" in descriptor
    assert "ScriptFile=/usr/share/plymouth/themes/eclipse/eclipse.script" in descriptor
    assert "ImageDir=/usr/share/plymouth/themes/eclipse" in descriptor
    script = (THEME_DIR / "eclipse.script").read_text(encoding="utf-8")
    assert 'Image("warning.png")' in script
    assert sorted(p.name for p in THEME_DIR.iterdir()) == [
        "eclipse.plymouth",
        "eclipse.script",
        "warning.png",
    ]


def test_theme_stretchesTheWarningToTheFullFrame():
    """
    Given: the Pi scans out 1280x720 to a 480x320 scaler panel (US-885-c)
    When: the theme script's code lines are read
    Then: the warning image is scaled to Window.GetWidth() x Window.GetHeight()
          and placed at the window origin; no half-window centring remains
    """
    themeLines = _codeLines((THEME_DIR / "eclipse.script").read_text(encoding="utf-8"))
    assert any(
        ln.startswith("warning.image")
        and 'Image("warning.png").Scale(Window.GetWidth(), Window.GetHeight())' in ln
        for ln in themeLines
    ), themeLines
    assert "warning.sprite.SetX(Window.GetX());" in themeLines
    assert "warning.sprite.SetY(Window.GetY());" in themeLines
    assert not [ln for ln in themeLines if re.search(r"Get(Width|Height)\(\)\s*/\s*2", ln)]


def test_setBootScreen_hasNoTimedWait():
    """
    Given: the CIO's NO TIMER rule (2026-10-23)
    When: the script's and the theme script's executable lines are scanned
    Then: no sleep, wait or timeout, and no refresh callback in the theme
    """
    lines = _codeLines(SCRIPT.read_text(encoding="utf-8"))
    offenders = [ln for ln in lines if re.search(r"\b(sleep|wait|timeout)\b", ln)]
    assert not offenders, f"set-boot-screen.sh must contain no timed wait: {offenders}"
    themeLines = _codeLines((THEME_DIR / "eclipse.script").read_text(encoding="utf-8"))
    assert not [ln for ln in themeLines if "SetRefreshFunction" in ln]


def test_setBootScreen_editsTheBootLineOnlyThroughTheSharedHelper():
    """
    Given: set-display-mode.sh and this script edit the same one-line cmdline
    When: the script's code is scanned
    Then: it sources deploy/lib/cmdline-tokens.sh and never writes cmdline.txt
          with its own sed/printf/temp file
    """
    lines = _codeLines(SCRIPT.read_text(encoding="utf-8"))
    assert any("lib/cmdline-tokens.sh" in ln for ln in lines)
    assert not [ln for ln in lines if "sed -i" in ln]
    assert not [ln for ln in lines if re.search(r'>\s*"\$CMDLINE"', ln)]
    assert any("cmdline_add_token" in ln for ln in lines)
    assert any("cmdline_remove_token" in ln for ln in lines)


def test_setBootScreen_namesExactlyTheBootScreenTokens():
    """
    Given: the scope fence (video= stays set-display-mode's)
    When: the token constants are read
    Then: they are loglevel=3 + vt.global_cursor_default=0 added, console=tty1
          removed, and the script never names video=
    """
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'ADD_TOKENS="loglevel=3 vt.global_cursor_default=0"' in text
    assert 'REMOVE_TOKEN="console=tty1"' in text
    assert not [ln for ln in _codeLines(text) if "video=" in ln]


def test_setBootScreen_writesConfigTxtOnlyThroughTheSharedKeyWriter():
    """
    Given: Atlas Q6 -- one config.txt key writer, deploy/lib/config-txt-keys.sh
    When: the script's code is read
    Then: it sources the lib (refusing loudly if it is missing, like the cmdline
          helper) and applies disable_splash=1, camera_auto_detect=0 and
          display_auto_detect=0 through config_txt_set_key
    """
    text = SCRIPT.read_text(encoding="utf-8")
    lines = _codeLines(text)
    assert 'CONFIG_TXT_KEYS_LIB="${SELF_DIR}/lib/config-txt-keys.sh"' in lines
    assert 'if [ ! -r "$CONFIG_TXT_KEYS_LIB" ]; then' in lines
    assert '. "$CONFIG_TXT_KEYS_LIB"' in lines
    assert 'AUTODETECT_KEYS="camera_auto_detect=0 display_auto_detect=0"' in lines
    assert 'CONFIG_KEY="disable_splash"' in lines
    applyBody = text[
        text.index("applyConfig() {") : text.index("\n}\n", text.index("applyConfig() {"))
    ]
    assert applyBody.count("config_txt_set_key") == 2
    # The auto-detect keys go first, so an [all] the script opens is theirs.
    assert applyBody.index("AUTODETECT_KEYS") < applyBody.index('"$CONFIG_KEY"')


def test_setBootScreen_revertNeverNamesTheAutoDetectKeys():
    """
    Given: Atlas 2026-10-25 -- one revert per concern
    When: revertConfig's body is read
    Then: it names neither auto-detect key nor AUTODETECT_*
    """
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("revertConfig() {")
    body = text[start : text.index("\n}\n", start)]
    assert "auto_detect" not in body
    assert "AUTODETECT" not in body


def test_noRetainSplashAnywhereInTheShippedTree():
    """
    Given: --retain-splash is stale (Atlas F1: lightdm quits Plymouth itself)
    When: deploy/ and src/ are scanned
    Then: no file carries it
    """
    offenders = []
    for root in (REPO_ROOT / "deploy", REPO_ROOT / "src"):
        for path in root.rglob("*"):
            if path.is_file() and path.suffix != ".png":
                if "--retain-splash" in path.read_text(encoding="utf-8", errors="replace"):
                    offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, offenders


def test_architectureDocumentsTheBootScreen():
    """Rule 10: the display-stack section names the theme, tokens, owner and revert."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    start = text.index("#### The power-on WARNING screen")
    section = text[start : text.index("\n#### ", start + 1)]
    for needle in (
        "deploy/set-boot-screen.sh",
        "deploy/plymouth/eclipse/",
        "plymouth-set-default-theme -R eclipse",
        "disable_splash=1",
        "loglevel=3",
        "vt.global_cursor_default=0",
        "console=tty1",
        "--revert",
        "step_set_boot_screen",
    ):
        assert needle in section, needle


def test_architectureNamesTheOneConfigTxtWriter():
    """Rule 10 (US-926-b): the lib, the three keys, the rtc debt and the auto-detect undo."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    start = text.index("#### The power-on WARNING screen")
    section = text[start : text.index("\n#### ", start + 1)]
    for needle in (
        "deploy/lib/config-txt-keys.sh",
        "ONE config.txt key writer",
        "disable_splash=1",
        "camera_auto_detect=0",
        "display_auto_detect=0",
        "rewritten in",
        "enable-rtc-charging.sh",
        "rtc_bbat_vchg",
        "Not yet migrated",
        "camera_auto_detect 1",
        "HDMI35",
        "leaves",
    ):
        assert needle in section, needle
