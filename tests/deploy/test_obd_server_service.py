################################################################################
# File Name: test_obd_server_service.py
# Purpose/Description: Static-content assertions on deploy/obd-server.service.
#                      US-231 (Sprint 18) creates the chi-srv-01 systemd unit
#                      mirroring eclipse-obd.service: Restart=always, RestartSec=5,
#                      After=network.target mariadb.service, User=mcornelison,
#                      EnvironmentFile=/mnt/projects/O/OBD2v2/.env, ExecStart with
#                      the absolute server-venv uvicorn path. These tests pin the
#                      invariants so a future edit cannot silently regress (e.g.,
#                      drop Restart=always, hardcode secrets, lose the EnvironmentFile,
#                      or revert the dependency ordering).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-27    | Rex          | Initial implementation (Sprint 18 US-231)
# ================================================================================
################################################################################

"""Static unit-file assertions for deploy/obd-server.service (US-231)."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SERVICE_FILE = REPO_ROOT / "deploy" / "obd-server.service"


def _serviceText() -> str:
    assert SERVICE_FILE.is_file(), f"Service file missing: {SERVICE_FILE}"
    return SERVICE_FILE.read_text(encoding="utf-8")


def test_obdServerService_exists():
    assert SERVICE_FILE.is_file()


def test_obdServerService_descriptionPresent():
    text = _serviceText()
    assert re.search(r"^Description=.+$", text, re.MULTILINE), (
        "Unit must declare a Description= for systemctl status output"
    )


def test_obdServerService_afterIncludesMariadb():
    """US-231 invariant: server depends on MariaDB being up."""
    text = _serviceText()
    after = re.search(r"^After=(.+)$", text, re.MULTILINE)
    assert after is not None, "Missing After= directive"
    deps = after.group(1)
    assert "network.target" in deps, f"After must include network.target: {deps}"
    assert "mariadb.service" in deps, (
        f"After must include mariadb.service (Debian convention): {deps}"
    )


def test_obdServerService_typeSimple():
    text = _serviceText()
    assert re.search(r"^Type=simple\s*$", text, re.MULTILINE), (
        "Type=simple is required (uvicorn is the main process)"
    )


def test_obdServerService_userMcornelison():
    """US-231 invariant: never run as root."""
    text = _serviceText()
    user = re.search(r"^User=(.+)$", text, re.MULTILINE)
    assert user is not None, "Missing User= directive"
    assert user.group(1).strip() == "mcornelison", (
        f"User MUST be mcornelison (security posture): {user.group(1)!r}"
    )


def test_obdServerService_workingDirectoryMatchesServerPath():
    """US-231 invariant: WorkingDirectory matches the actual server checkout."""
    text = _serviceText()
    wd = re.search(r"^WorkingDirectory=(.+)$", text, re.MULTILINE)
    assert wd is not None, "Missing WorkingDirectory= directive"
    # Pinned to the SERVER_PROJECT_PATH default in deploy/addresses.sh.
    assert wd.group(1).strip() == "/mnt/projects/O/OBD2v2", (
        f"WorkingDirectory must match SERVER_PROJECT_PATH: {wd.group(1)!r}"
    )


def test_obdServerService_environmentFileSetToServerEnv():
    """US-231 invariant: secrets via EnvironmentFile, never inline."""
    text = _serviceText()
    envFile = re.search(r"^EnvironmentFile=(.+)$", text, re.MULTILINE)
    assert envFile is not None, "Missing EnvironmentFile= directive"
    assert envFile.group(1).strip() == "/mnt/projects/O/OBD2v2/.env", (
        f"EnvironmentFile must reference the server .env: {envFile.group(1)!r}"
    )


def test_obdServerService_execStartUsesServerVenvAndHostBindAndPort():
    """US-231 invariant: ExecStart uses the absolute venv path + 0.0.0.0:8000."""
    text = _serviceText()
    execStart = re.search(r"^ExecStart=(.+)$", text, re.MULTILINE)
    assert execStart is not None, "Missing ExecStart= directive"
    cmd = execStart.group(1)
    assert "/home/mcornelison/obd2-server-venv/bin/uvicorn" in cmd, (
        f"ExecStart must use absolute server-venv uvicorn path: {cmd}"
    )
    assert "src.server.main:app" in cmd, (
        f"ExecStart must launch src.server.main:app: {cmd}"
    )
    assert "--host 0.0.0.0" in cmd, (
        f"ExecStart must bind 0.0.0.0 (sync from Pi requires it): {cmd}"
    )
    assert "--port 8000" in cmd, (
        f"ExecStart must use port 8000 (matches addresses.sh SERVER_PORT default): {cmd}"
    )


def test_obdServerService_restartAlways():
    """US-231 invariant: Restart=always (mirror of US-210 Pi-side policy)."""
    text = _serviceText()
    assert re.search(r"^Restart=always\s*$", text, re.MULTILINE), (
        "Restart policy MUST be `always` per US-231 spec; on-failure is wrong"
    )


def test_obdServerService_restartSec5():
    """US-231 invariant: RestartSec=5 (mirror of US-210 Pi-side delay)."""
    text = _serviceText()
    rs = re.search(r"^RestartSec=(\d+)\s*$", text, re.MULTILINE)
    assert rs is not None, "RestartSec= missing"
    assert int(rs.group(1)) == 5, (
        f"RestartSec MUST be 5 (mirror of US-210): {rs.group(1)}"
    )


def test_obdServerService_flapProtectionInUnitSection():
    """Flap-protection caps must live in [Unit] (modern systemd warns if in [Service])."""
    text = _serviceText()
    # Locate [Unit] start and the next section header to bound the search window.
    unitStart = text.find("[Unit]")
    nextSection = text.find("\n[", unitStart + 1)
    assert unitStart >= 0 and nextSection > unitStart, "[Unit] block not found"
    unitBlock = text[unitStart:nextSection]
    assert "StartLimitIntervalSec=" in unitBlock, (
        "StartLimitIntervalSec belongs in [Unit] block (per modern systemd)"
    )
    assert "StartLimitBurst=" in unitBlock, (
        "StartLimitBurst belongs in [Unit] block (per modern systemd)"
    )
    interval = re.search(r"^StartLimitIntervalSec=(\d+)\s*$", text, re.MULTILINE)
    assert interval is not None and int(interval.group(1)) == 300, (
        f"StartLimitIntervalSec MUST be 300 (mirror of US-210): {interval}"
    )
    burst = re.search(r"^StartLimitBurst=(\d+)\s*$", text, re.MULTILINE)
    assert burst is not None and int(burst.group(1)) >= 5, (
        f"StartLimitBurst must cap restarts (>=5; US-210 uses 10): {burst}"
    )


def test_obdServerService_wantedByMultiUser():
    """[Install] block must enable autostart on normal boot."""
    text = _serviceText()
    assert re.search(r"^WantedBy=multi-user.target\s*$", text, re.MULTILINE), (
        "WantedBy=multi-user.target is required for autostart on boot"
    )


def test_obdServerService_doesNotInlineSecrets():
    """US-231 invariant: no inline secrets in the unit file."""
    text = _serviceText()
    # Common secret-y patterns. Catches accidental inlining in Environment= lines.
    forbidden = ("API_KEY=", "DATABASE_URL=", "PASSWORD=", "SECRET=")
    for needle in forbidden:
        # An Environment= line containing a literal key=value with secrets is forbidden.
        # EnvironmentFile=/path is fine -- secrets live in the .env, not the unit.
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("Environment=") and needle in stripped:
                raise AssertionError(
                    f"Unit must NOT inline secrets (found {needle!r}): {stripped!r}",
                )


def test_obdServerService_doesNotCarryDebugFlags():
    """ExecStart MUST NOT carry --reload, --debug, etc. (those are dev-only)."""
    text = _serviceText()
    execStart = re.search(r"^ExecStart=(.+)$", text, re.MULTILINE)
    assert execStart is not None
    cmd = execStart.group(1)
    for forbidden in ("--reload", "--debug", "--log-level debug", "--loop debug"):
        assert forbidden not in cmd, (
            f"ExecStart MUST NOT carry dev-only flag {forbidden!r}: {cmd}"
        )
