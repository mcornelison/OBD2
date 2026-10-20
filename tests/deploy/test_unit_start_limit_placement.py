################################################################################
# File Name: test_unit_start_limit_placement.py
# Purpose/Description: US-908 -- every StartLimit* key in every systemd unit file
#                      the repo ships sits in [Unit], the only section where
#                      systemd reads it. Under [Service] systemd logs 'Unknown
#                      key' and the rate limit is silently off (systemd-analyze
#                      verify on the Pi, 2026-10-16, rfcomm-bind.service).
#
#                      Parses every *.service and *.service.* file under deploy/
#                      and src/ by section: section headers match only at line
#                      start; only non-comment 'key=' lines count.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-19    | Rex          | Initial implementation (US-908)
# ================================================================================
################################################################################

"""StartLimit* keys live in [Unit] in every shipped unit file (US-908)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCAN_ROOTS = (REPO_ROOT / "deploy", REPO_ROOT / "src")
ALLOWED_SECTION = "Unit"

_SECTION_HEADER = re.compile(r"^\[([^\]]+)\]\s*$")
_START_LIMIT_KEY = re.compile(r"^\s*(StartLimit\w*)\s*=")


def _unitFiles() -> list[Path]:
    found: set[Path] = set()
    for root in SCAN_ROOTS:
        found.update(p for p in root.rglob("*.service") if p.is_file())
        found.update(p for p in root.rglob("*.service.*") if p.is_file())
    return sorted(found)


def _startLimitPlacements(text: str) -> list[tuple[int, str, str | None]]:
    """Return (lineNumber, key, section) for every StartLimit* key line.

    Comment lines (first non-blank character '#' or ';') never count, and a
    section header counts only when the '[' is the first character of the line.
    A key before any header reports section None.
    """
    placements: list[tuple[int, str, str | None]] = []
    section: str | None = None
    for lineNumber, line in enumerate(text.splitlines(), start=1):
        header = _SECTION_HEADER.match(line)
        if header:
            section = header.group(1)
            continue
        if line.lstrip().startswith(("#", ";")):
            continue
        key = _START_LIMIT_KEY.match(line)
        if key:
            placements.append((lineNumber, key.group(1), section))
    return placements


def _violations(text: str) -> list[tuple[int, str, str | None]]:
    return [p for p in _startLimitPlacements(text) if p[2] != ALLOWED_SECTION]


def _unitValues(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    section: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        header = _SECTION_HEADER.match(line)
        if header:
            section = header.group(1)
            continue
        if section != ALLOWED_SECTION or line.lstrip().startswith(("#", ";")):
            continue
        key = _START_LIMIT_KEY.match(line)
        if key:
            values[key.group(1)] = line.split("=", 1)[1].strip()
    return values


# ---- the scan ---------------------------------------------------------------


def test_scan_findsTheUnitFilesItGuards():
    """The walker must see both suffix shapes, or an empty scan passes vacuously."""
    names = {p.name for p in _unitFiles()}
    assert {"rfcomm-bind.service", "obd2-server.service", "eclipse-obd.service"} <= names
    assert "dashboard.service.wayland" in names
    assert "splash-boot.service.x11" in names


@pytest.mark.parametrize("unitFile", _unitFiles(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_unitFile_startLimitKeysOnlyInUnitSection(unitFile: Path):
    """Given a shipped unit file, every StartLimit* key line sits under [Unit]."""
    violations = _violations(unitFile.read_text(encoding="utf-8"))
    assert violations == [], (
        f"{unitFile.relative_to(REPO_ROOT).as_posix()}: StartLimit* outside [Unit] "
        f"(systemd ignores it there): {violations}"
    )


# ---- the two files US-908 moved: values unchanged -----------------------------


@pytest.mark.parametrize(
    ("fileName", "expected"),
    [
        # Values as they stood under [Service] before US-908 (scopeFence: no value changes).
        ("rfcomm-bind.service", {"StartLimitBurst": "5", "StartLimitIntervalSec": "30"}),
        ("obd2-server.service", {"StartLimitIntervalSec": "300", "StartLimitBurst": "5"}),
    ],
)
def test_movedUnit_keepsItsValuesInUnitSection(fileName: str, expected: dict[str, str]):
    assert _unitValues(REPO_ROOT / "deploy" / fileName) == expected


# ---- parser controls -----------------------------------------------------------


def test_parser_plantedServiceStartLimit_isCaught():
    """Negative control: the defect US-908 fixes is reported, with its section."""
    planted = (
        "[Unit]\n"
        "Description=planted\n"
        "\n"
        "[Service]\n"
        "Restart=on-failure\n"
        "StartLimitIntervalSec=30\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )
    assert _violations(planted) == [(6, "StartLimitIntervalSec", "Service")]


def test_parser_unitPlacement_isClean():
    good = "[Unit]\nStartLimitIntervalSec=30\nStartLimitBurst=5\n[Service]\nType=simple\n"
    assert _violations(good) == []
    assert [p[1] for p in _startLimitPlacements(good)] == [
        "StartLimitIntervalSec",
        "StartLimitBurst",
    ]


def test_parser_commentedKeys_doNotCount():
    """A key named in a comment is not a key (eclipse-obd/obd-server name them so)."""
    text = (
        "[Unit]\n"
        "# Allow up to StartLimitBurst restarts; see [Service] below\n"
        "StartLimitBurst=5\n"
        "StartLimitIntervalSec=30\n"
        "[Service]\n"
        "# StartLimitBurst=10 lives in [Unit]\n"
        "; StartLimitIntervalSec=300\n"
    )
    assert _violations(text) == []


def test_parser_keyBeforeAnyHeader_isAViolation():
    assert _violations("StartLimitBurst=5\n[Unit]\n") == [(1, "StartLimitBurst", None)]
