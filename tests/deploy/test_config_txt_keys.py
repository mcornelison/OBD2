################################################################################
# File Name: test_config_txt_keys.py
# Purpose/Description: Behaviour + static guards for the ONE config.txt key
#                      writer (deploy/lib/config-txt-keys.sh, US-926-b). Drives
#                      the sourced functions through bash against fixture
#                      config.txt files: in-place rewrite, section-aware append,
#                      byte-identical idempotence and round trip, the refusal,
#                      and the guard that no other writer exists under deploy/.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-25    | Rex          | Initial implementation (Sprint 115 US-926-b)
# ================================================================================
################################################################################

"""Tests for deploy/lib/config-txt-keys.sh, the one config.txt key writer.

Each case writes a fixture config.txt into tmp_path, sources the library in a
bash subprocess and calls one of its functions. Assertions are on the file's
exact bytes, the backup and the return code.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LIB = REPO_ROOT / "deploy" / "lib" / "config-txt-keys.sh"
DEPLOY_DIR = REPO_ROOT / "deploy"
SET_BOOT_SCREEN = DEPLOY_DIR / "set-boot-screen.sh"
RTC_SCRIPT = DEPLOY_DIR / "enable-rtc-charging.sh"

MARKER = "# eclipse test marker"

# Raspberry Pi OS (bookworm) /boot/firmware/config.txt as shipped: the camera
# and DSI-display auto-detect sit in the unsectioned top block.
STOCK_CONFIG = """\
# For more options and information see
# http://rptl.io/configtxt
# Some settings may impact device functionality. See link above for details

# Uncomment some or all of these to enable the optional hardware interfaces
#dtparam=i2c_arm=on
#dtparam=i2s=on
#dtparam=spi=on

# Enable audio (loads snd_bcm2835)
dtparam=audio=on

# Additional overlays and parameters are documented
# /boot/firmware/overlays/README

# Automatically load overlays for detected cameras
camera_auto_detect=1

# Automatically load overlays for detected DSI displays
display_auto_detect=1

# Automatically load initramfs files, if found
auto_initramfs=1

# Enable DRM VC4 V3D driver
dtoverlay=vc4-kms-v3d
max_framebuffers=2

# Don't have the firmware create an initial video= setting in cmdline.txt.
# Use the kernel's default instead.
disable_fw_kms_setup=1

# Run in 64-bit mode
arm_64bit=1

# Disable compensation for displays with overscan
disable_overscan=1

# Run as fast as firmware / board allows
arm_boost=1

[cm4]
# Enable host mode on the 2711 built-in XHCI USB controller.
# This line should be removed if the legacy DWC2 controller is required
# (e.g. for USB device mode) or if USB support is not required.
otg_mode=1

[cm5]
dtoverlay=dwc2,dr_mode=host

[all]
"""

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available on PATH")


def _codeLines(text: str) -> list[str]:
    """Return executable-looking lines only: comments and blanks stripped."""
    out = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


def _lib(*args: str) -> subprocess.CompletedProcess[str]:
    """Source the library and run one of its functions with ARGS."""
    return subprocess.run(
        ["bash", "-c", '. "$0"; "$@"', LIB.as_posix(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def _setKey(config: Path, key: str, value: str) -> subprocess.CompletedProcess[str]:
    """config_txt_set_key CONFIG KEY VALUE <config>.bak MARKER."""
    return _lib(
        "config_txt_set_key", config.as_posix(), key, value, _backup(config).as_posix(), MARKER
    )


def _backup(config: Path) -> Path:
    return config.with_name(config.name + ".bak")


def _effective(config: Path, key: str) -> str:
    return _lib("config_txt_effective", config.as_posix(), key).stdout.strip()


def _write(tmp_path: Path, text: str) -> Path:
    config = tmp_path / "config.txt"
    config.write_bytes(text.encode("utf-8"))
    return config


# ---- the stock file ----


def test_stockConfig_autoDetectKeysRewrittenInPlace_everyOtherLineIdentical(tmp_path):
    """
    Given: stock RPi OS config.txt (camera_auto_detect=1, display_auto_detect=1 at the top)
    When: both keys are set to 0, then disable_splash to 1
    Then: the two lines read =0 on the SAME lines, disable_splash=1 sits under
          the marker at the end (the file ends in [all], so no header), and
          every other line is identical
    """
    config = _write(tmp_path, STOCK_CONFIG)

    for key in ("camera_auto_detect", "display_auto_detect"):
        assert _setKey(config, key, "0").returncode == 0
    assert _setKey(config, "disable_splash", "1").returncode == 0

    expected = (
        STOCK_CONFIG.replace("camera_auto_detect=1", "camera_auto_detect=0").replace(
            "display_auto_detect=1", "display_auto_detect=0"
        )
        + f"{MARKER}\ndisable_splash=1\n"
    )
    assert config.read_text(encoding="utf-8") == expected
    assert _effective(config, "camera_auto_detect") == "0"
    assert _effective(config, "display_auto_detect") == "0"
    assert _effective(config, "disable_splash") == "1"


def test_stockConfig_secondRunIsByteIdenticalAndTakesNoBackup(tmp_path):
    """
    Given: the stock file after one run of the three keys, its backup removed
    When: the three keys are set again
    Then: every call says no change, the bytes are identical, no backup is taken
    """
    config = _write(tmp_path, STOCK_CONFIG)
    for key, value in (
        ("camera_auto_detect", "0"),
        ("display_auto_detect", "0"),
        ("disable_splash", "1"),
    ):
        _setKey(config, key, value)
    _backup(config).unlink()
    after1 = config.read_bytes()

    for key, value in (
        ("camera_auto_detect", "0"),
        ("display_auto_detect", "0"),
        ("disable_splash", "1"),
    ):
        result = _setKey(config, key, value)
        assert result.returncode == 0
        assert "already effective" in result.stdout

    assert config.read_bytes() == after1
    assert not _backup(config).exists()


def test_backupIsFirstWriteWins_holdingThePristineFile(tmp_path):
    """
    Given: the stock file
    When: two keys are written one after the other
    Then: ONE backup exists and it holds the file as it was before the first write
    """
    config = _write(tmp_path, STOCK_CONFIG)
    _setKey(config, "camera_auto_detect", "0")
    _setKey(config, "display_auto_detect", "0")
    assert _backup(config).read_text(encoding="utf-8") == STOCK_CONFIG
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("config.txt.")] == [
        "config.txt.bak"
    ]


# ---- sections ----


def test_fileEndingInCm4_keysAppendedUnderAnOpenedAll(tmp_path):
    """
    Given: a config.txt whose last section is [cm4] and no auto-detect lines
    When: both auto-detect keys are set to 0
    Then: the first append opens [all] under its marker; the second, already in
          [all], adds none; both are effective
    """
    config = _write(tmp_path, "dtparam=audio=on\n[cm4]\notg_mode=1\n")

    _setKey(config, "camera_auto_detect", "0")
    _setKey(config, "display_auto_detect", "0")

    assert config.read_text(encoding="utf-8") == (
        "dtparam=audio=on\n[cm4]\notg_mode=1\n"
        f"{MARKER}\n[all]\ncamera_auto_detect=0\n"
        f"{MARKER}\ndisplay_auto_detect=0\n"
    )
    assert _effective(config, "camera_auto_detect") == "0"
    assert _effective(config, "display_auto_detect") == "0"


def test_keyInANonPi5Section_isIgnored_theTopLineIsRewritten(tmp_path):
    """
    Given: camera_auto_detect=0 only inside [cm4] (a Pi 5 never reads it) and
          camera_auto_detect=1 at the top
    When: camera_auto_detect is set to 0
    Then: the TOP line (the effective one) is rewritten; the [cm4] line is untouched
    """
    config = _write(tmp_path, "camera_auto_detect=1\n[cm4]\ncamera_auto_detect=0\n[all]\n")

    assert _setKey(config, "camera_auto_detect", "0").returncode == 0

    assert config.read_text(encoding="utf-8") == (
        "camera_auto_detect=0\n[cm4]\ncamera_auto_detect=0\n[all]\n"
    )


def test_lastEffectiveLineIsTheOneRewritten_neverShadowed(tmp_path):
    """
    Given: camera_auto_detect=1 at the top and again under [pi5]
    When: it is set to 0
    Then: the LAST applicable line (the [pi5] one) is rewritten in place and no
          line is added
    """
    config = _write(tmp_path, "camera_auto_detect=1\n[pi5]\ncamera_auto_detect=1\n")

    _setKey(config, "camera_auto_detect", "0")

    assert config.read_text(encoding="utf-8") == (
        "camera_auto_detect=1\n[pi5]\ncamera_auto_detect=0\n"
    )
    assert _effective(config, "camera_auto_detect") == "0"


# ---- byte-exact round trips ----


@pytest.mark.parametrize(
    "start",
    [
        pytest.param(
            STOCK_CONFIG.replace("camera_auto_detect=1", "camera_auto_detect=0"), id="in-place"
        ),
        pytest.param(STOCK_CONFIG.replace("camera_auto_detect=1\n", ""), id="appended"),
        pytest.param("[cm4]\notg_mode=1", id="cm4-tail-no-final-newline"),
    ],
)
def test_roundTrip_zeroOneZero_isByteIdenticalToTheFirstZeroState(tmp_path, start):
    """
    Given: a config.txt brought to camera_auto_detect=0 by the writer
    When: the writer sets it to 1 (the documented undo) and then back to 0
    Then: the file is byte-identical to that first 0 state (Atlas 2026-10-25)
    """
    config = _write(tmp_path, start)
    assert _setKey(config, "camera_auto_detect", "0").returncode == 0
    firstZero = config.read_bytes()

    assert _setKey(config, "camera_auto_detect", "1").returncode == 0
    assert _effective(config, "camera_auto_detect") == "1"
    assert _setKey(config, "camera_auto_detect", "0").returncode == 0

    assert config.read_bytes() == firstZero


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (b"camera_auto_detect=1\narm_boost=1", b"camera_auto_detect=0\narm_boost=1"),
        (b"arm_boost=1\ncamera_auto_detect=1", b"arm_boost=1\ncamera_auto_detect=0"),
    ],
)
def test_inPlaceRewrite_keepsAMissingFinalNewline(tmp_path, before, after):
    """
    Given: a config.txt whose last byte is not a newline
    When: the key is rewritten in place (on the last line or an earlier one)
    Then: only that line changes and the file still has no final newline
    """
    config = tmp_path / "config.txt"
    config.write_bytes(before)

    _setKey(config, "camera_auto_detect", "0")

    assert config.read_bytes() == after


# ---- refusals ----


def test_missingConfig_isRefused_nothingWritten(tmp_path):
    """
    Given: no config.txt at the path
    When: a key is set
    Then: rc 1, the existing refusal text, no file and no backup created
    """
    config = tmp_path / "config.txt"

    result = _setKey(config, "camera_auto_detect", "0")

    assert result.returncode == 1
    assert "config.txt not found or unreadable" in result.stderr
    assert not config.exists()
    assert not _backup(config).exists()


def test_directoryInPlaceOfConfig_isRefused_nothingWritten(tmp_path):
    """
    Given: a directory where config.txt should be
    When: a key is set
    Then: rc 1, the refusal, nothing written
    """
    config = tmp_path / "config.txt"
    config.mkdir()

    result = _setKey(config, "camera_auto_detect", "0")

    assert result.returncode == 1
    assert "not found or unreadable" in result.stderr
    assert list(config.iterdir()) == []
    assert not _backup(config).exists()


def test_unreadableConfig_isRefused_nothingWritten(tmp_path):
    """
    Given: a config.txt with no read permission
    When: a key is set
    Then: rc 1, the refusal, the file unchanged, no backup
    """
    config = _write(tmp_path, STOCK_CONFIG)
    os.chmod(config, 0)
    try:
        if os.access(config, os.R_OK):
            pytest.skip("this filesystem cannot make a file unreadable to its owner")
        result = _setKey(config, "camera_auto_detect", "0")
    finally:
        os.chmod(config, 0o644)

    assert result.returncode == 1
    assert "not found or unreadable" in result.stderr
    assert config.read_text(encoding="utf-8") == STOCK_CONFIG
    assert not _backup(config).exists()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("camera auto", "0"),
        ("camera_auto_detect", "0 # x"),
        ("camera_auto_detect", r"0\n1"),
        ("", "0"),
    ],
)
def test_aKeyOrValueThatIsNotAPlainWord_isRefused(tmp_path, key, value):
    """
    Given: a key or value with spaces, a comment or a backslash escape
    When: it is passed to the writer
    Then: rc 1, nothing written, no backup
    """
    config = _write(tmp_path, STOCK_CONFIG)

    result = _setKey(config, key, value)

    assert result.returncode == 1
    assert config.read_text(encoding="utf-8") == STOCK_CONFIG
    assert not _backup(config).exists()


# ---- block removal ----


def test_removeBlock_atEof_dropsMarkerAllAndLine_installingTheBackupsBytes(tmp_path):
    """
    Given: a file with no final newline that got an [all]-opening block appended
    When: config_txt_remove_block removes it
    Then: the file is the backup's exact bytes again
    """
    config = _write(tmp_path, "[cm4]\notg_mode=1")
    _setKey(config, "disable_splash", "1")

    result = _lib(
        "config_txt_remove_block",
        config.as_posix(),
        MARKER,
        "disable_splash=1",
        _backup(config).as_posix(),
    )

    assert result.returncode == 0
    assert config.read_bytes() == b"[cm4]\notg_mode=1"


def test_removeBlock_keepsTheAllItOpened_whenLaterLinesFollow(tmp_path):
    """
    Given: an [all]-opening disable_splash block with another key's block after it
    When: the disable_splash block is removed
    Then: its [all] stays, so the later key is still effective
    """
    config = _write(tmp_path, "[cm4]\notg_mode=1\n")
    _setKey(config, "disable_splash", "1")
    _lib(
        "config_txt_set_key",
        config.as_posix(),
        "camera_auto_detect",
        "0",
        _backup(config).as_posix(),
        "# other",
    )

    _lib(
        "config_txt_remove_block",
        config.as_posix(),
        MARKER,
        "disable_splash=1",
        _backup(config).as_posix(),
    )

    assert config.read_text(encoding="utf-8") == (
        "[cm4]\notg_mode=1\n[all]\n# other\ncamera_auto_detect=0\n"
    )
    assert _effective(config, "camera_auto_detect") == "0"
    assert _effective(config, "disable_splash") == ""


# ---- static guards ----


def test_validation_oneConfigTxtKeyWriterUnderDeploy():
    """
    Given: Atlas Q6 -- one config.txt key writer
    When: every file under deploy/ is scanned for the writer's function definitions
    Then: config_txt_set_key / config_txt_effective / config_txt_section_at_eof are
          defined only in the lib, and the only other sectionAtEof is
          enable-rtc-charging.sh's own (the recorded dtparam-token debt)
    """
    defs: dict[str, list[str]] = {}
    pattern = re.compile(
        r"^\s*(config_txt_\w+|sectionAtEof|effectiveDisableSplash|applyConfig)\s*\(\)"
    )
    for path in DEPLOY_DIR.rglob("*"):
        if not path.is_file() or path.suffix not in ("", ".sh"):
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = pattern.match(line)
            if match:
                rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
                defs.setdefault(match.group(1), []).append(rel)

    lib = "deploy/lib/config-txt-keys.sh"
    for name in ("config_txt_set_key", "config_txt_effective", "config_txt_section_at_eof"):
        assert defs.get(name) == [lib], (name, defs.get(name))
    assert defs.get("sectionAtEof") == ["deploy/enable-rtc-charging.sh"], defs.get("sectionAtEof")
    assert "effectiveDisableSplash" not in defs
    # set-boot-screen.sh keeps an applyConfig, but it only calls the lib.
    assert defs.get("applyConfig") == ["deploy/set-boot-screen.sh"]


def test_setBootScreen_carriesNoAwkConfigTxtWriter():
    """
    Given: the writer moved (not copied) into the lib
    When: set-boot-screen.sh's code lines are scanned
    Then: its only awk is the plymouthd.conf Theme= reader, and it composes no
          config.txt temp file of its own
    """
    text = SET_BOOT_SCREEN.read_text(encoding="utf-8")
    lines = _codeLines(text)
    awkLines = [ln for ln in lines if re.search(r"\bawk\b", ln)]
    assert awkLines == ["awk -F= '"], awkLines
    assert ".config.txt." not in text


def test_neverTouched_maxFramebuffersAndRtcLine():
    """
    Given: the scope fence (max_framebuffers, the rtc dtparam token, set-gpu-cma's overlay)
    When: the lib and set-boot-screen.sh are read
    Then: neither names max_framebuffers, rtc_bbat_vchg or vc4-kms-v3d
    """
    for path in (LIB, SET_BOOT_SCREEN):
        code = "\n".join(_codeLines(path.read_text(encoding="utf-8")))
        for needle in ("max_framebuffers", "rtc_bbat_vchg", "vc4-kms-v3d"):
            assert needle not in code, (path.name, needle)
    assert "max_framebuffers" not in LIB.read_text(encoding="utf-8")
    assert "max_framebuffers" not in SET_BOOT_SCREEN.read_text(encoding="utf-8")


def test_lib_isALibraryThatNeverExits_andHasNoTimedWait():
    """
    Given: the lib is SOURCED and the CIO's NO TIMER rule (2026-10-23)
    When: its code lines are scanned
    Then: no exit, no shell-option change, no sleep/wait/timeout
    """
    lines = _codeLines(LIB.read_text(encoding="utf-8"))
    assert not [ln for ln in lines if re.search(r"(^|[;&|]\s*)exit\b", ln)]
    assert not [ln for ln in lines if re.match(r"set\s+[-+]", ln)]
    assert not [ln for ln in lines if re.search(r"\b(sleep|wait|timeout)\b", ln)]


def test_rtcChargingScript_isUntouchedByThisStory():
    """
    Given: enable-rtc-charging.sh's own writer is recorded, out-of-scope debt
    When: it is read
    Then: it still carries its own sectionAtEof and never sources the lib
    """
    text = RTC_SCRIPT.read_text(encoding="utf-8")
    assert "sectionAtEof()" in text
    assert "config-txt-keys.sh" not in text
