################################################################################
# File Name: test_eclipse_obd_service.py
# Purpose/Description: Static-content assertions on deploy/eclipse-obd.service.
#                      Guards the BL-004 resolution (US-185): ExecStart must
#                      invoke src/pi/main.py with --simulate until real OBD
#                      hardware is wired in the Run phase. Also locks down the
#                      other unit fields that US-179/US-181 depend on.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation (Sprint 11 US-185)
# ================================================================================
################################################################################

"""Static unit-file assertions for deploy/eclipse-obd.service.

We deliberately keep these as plain text-content checks rather than parsing
the file as INI — systemd unit files are close to INI but have enough quirks
(drop-in directive lists, continuation lines, comments mid-section) that a
full parser would be overkill for the handful of invariants we care about.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SERVICE_FILE = REPO_ROOT / "deploy" / "eclipse-obd.service"


def _serviceText() -> str:
    assert SERVICE_FILE.is_file(), f"Service file missing: {SERVICE_FILE}"
    return SERVICE_FILE.read_text(encoding="utf-8")


def test_eclipseObdService_exists():
    assert SERVICE_FILE.is_file()


def test_eclipseObdService_execStartPassesSimulateFlag():
    """BL-004 resolution: ExecStart must pass --simulate for Sprint 10/11 bench mode."""
    text = _serviceText()
    match = re.search(r"^ExecStart=(.+)$", text, re.MULTILINE)
    assert match is not None, "No ExecStart= directive found"
    execStart = match.group(1)
    assert "src/pi/main.py" in execStart, f"ExecStart missing main.py entry point: {execStart}"
    assert "--simulate" in execStart, (
        f"ExecStart missing --simulate flag (BL-004 regression): {execStart}"
    )


def test_eclipseObdService_preservesRequiredUnitFields():
    """US-179/US-181 invariants — keep the rest of the unit contract intact."""
    text = _serviceText()
    # [Unit] must keep flap-protection in the right section (systemd warns if
    # these live in [Service] — see agent.md systemd notes).
    assert re.search(r"^\[Unit\]", text, re.MULTILINE)
    assert re.search(r"^StartLimitIntervalSec=\d+", text, re.MULTILINE)
    assert re.search(r"^StartLimitBurst=\d+", text, re.MULTILINE)
    # [Service] core fields
    assert re.search(r"^\[Service\]", text, re.MULTILINE)
    assert re.search(r"^User=mcornelison", text, re.MULTILINE)
    assert re.search(
        r"^WorkingDirectory=/home/mcornelison/Projects/Eclipse-01", text, re.MULTILINE
    )
    assert re.search(r"^Environment=PATH=", text, re.MULTILINE)
    assert re.search(r"^Environment=PYTHONUNBUFFERED=1", text, re.MULTILINE)
    assert re.search(r"^Restart=on-failure", text, re.MULTILINE)
    assert re.search(r"^RestartSec=\d+", text, re.MULTILINE)
    # [Install] wiring
    assert re.search(r"^\[Install\]", text, re.MULTILINE)
    assert re.search(r"^WantedBy=multi-user\.target", text, re.MULTILINE)


def test_eclipseObdService_flapProtectionInUnitNotService():
    """Regression guard: modern systemd ignores flap-protection keys in [Service].

    Uses line-anchored regex to locate section headers — the literal strings
    `[Service]` and `[Unit]` appear inside comments elsewhere in the file.
    """
    text = _serviceText()
    headers = {
        m.group(1): m.start() for m in re.finditer(r"^\[(Unit|Service|Install)\]", text, re.MULTILINE)
    }
    assert {"Unit", "Service", "Install"}.issubset(headers), f"Missing sections: {headers}"
    unitBlock = text[headers["Unit"]:headers["Service"]]
    serviceBlock = text[headers["Service"]:headers["Install"]]
    assert re.search(r"^StartLimitIntervalSec=", unitBlock, re.MULTILINE) is not None
    assert re.search(r"^StartLimitBurst=", unitBlock, re.MULTILINE) is not None
    # These would be silently dropped if placed under [Service]. Guard anyway.
    assert re.search(r"^StartLimitIntervalSec=", serviceBlock, re.MULTILINE) is None
    assert re.search(r"^StartLimitBurst=", serviceBlock, re.MULTILINE) is None
