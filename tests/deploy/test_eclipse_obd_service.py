################################################################################
# File Name: test_eclipse_obd_service.py
# Purpose/Description: Static-content assertions on deploy/eclipse-obd.service.
#                      Sprint 16 US-210 FLIPPED the BL-004 bench-mode carveout:
#                      production ExecStart must NOT carry --simulate, Restart
#                      must be 'always' (not on-failure), and the US-192 X11
#                      display environment must be preserved. Also locks down
#                      the other unit fields that US-179/US-181 depend on.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation (Sprint 11 US-185)
# 2026-04-20    | Rex          | US-210: FLIP simulate-present -> simulate-absent;
#                                Restart=on-failure -> Restart=always; RestartSec=5;
#                                StartLimitBurst>=10; assert DISPLAY/XAUTHORITY/
#                                SDL_VIDEODRIVER env preserved (US-192).
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


def test_eclipseObdService_execStartOmitsSimulateFlag():
    """US-210 (CIO Session 6 directive 1): production ExecStart MUST NOT carry --simulate.

    The BL-004 carveout from Sprint 10/11 is closed. --simulate remains a
    developer flag (banner warning in src/pi/main.py) but never appears in
    the production systemd unit's ExecStart. This is a regression guard
    against Sprint 15-era state being restored accidentally.
    """
    text = _serviceText()
    match = re.search(r"^ExecStart=(.+)$", text, re.MULTILINE)
    assert match is not None, "No ExecStart= directive found"
    execStart = match.group(1)
    assert "src/pi/main.py" in execStart, f"ExecStart missing main.py entry point: {execStart}"
    assert "--simulate" not in execStart, (
        f"ExecStart MUST NOT contain --simulate (US-210 regression): {execStart}"
    )


def test_eclipseObdService_restartPolicyAlways():
    """US-210: Restart=always with RestartSec=5 and StartLimitBurst>=10 over 300s.

    Flipped from on-failure to always: combined with the BT-resilient
    collector (US-211), the collector absorbs transient drops in-process;
    Restart=always is the backstop for genuine FATAL paths that re-raise
    into systemd. Burst >= 10 tolerates the flap window during initial
    BT pair-up; the 300s interval preserves the emergency stop.
    """
    text = _serviceText()
    assert re.search(r"^Restart=always\s*$", text, re.MULTILINE), (
        "Restart policy must be `always` (US-210); `on-failure` is the pre-Sprint-16 state"
    )
    restartSecMatch = re.search(r"^RestartSec=(\d+)", text, re.MULTILINE)
    assert restartSecMatch is not None, "RestartSec directive missing"
    assert int(restartSecMatch.group(1)) == 5, (
        f"RestartSec must be 5s per US-210 grounding ref; got {restartSecMatch.group(1)}"
    )
    burstMatch = re.search(r"^StartLimitBurst=(\d+)", text, re.MULTILINE)
    assert burstMatch is not None, "StartLimitBurst directive missing"
    assert int(burstMatch.group(1)) >= 10, (
        f"StartLimitBurst must be >=10 per US-210 grounding ref; got {burstMatch.group(1)}"
    )
    intervalMatch = re.search(r"^StartLimitIntervalSec=(\d+)", text, re.MULTILINE)
    assert intervalMatch is not None, "StartLimitIntervalSec directive missing"
    assert int(intervalMatch.group(1)) == 300, (
        f"StartLimitIntervalSec must be 300s per US-210 grounding ref; got {intervalMatch.group(1)}"
    )


def test_eclipseObdService_preservesUs192DisplayEnvironment():
    """US-210 invariant: preserve US-192/US-198 X11 display env so pygame HDMI still renders.

    The DISPLAY/XAUTHORITY/SDL_VIDEODRIVER trio is the Sprint 14 US-192
    state required for scripts/render_primary_screen_live.py. US-210's
    ExecStart edit MUST NOT collaterally drop these (stopCondition #4 on
    the story prevents silent removal during `--simulate` sunset).
    """
    text = _serviceText()
    assert re.search(r"^Environment=DISPLAY=:0\s*$", text, re.MULTILINE), (
        "DISPLAY=:0 missing (US-192 regression)"
    )
    assert re.search(
        r"^Environment=XAUTHORITY=/home/mcornelison/\.Xauthority\s*$", text, re.MULTILINE
    ), "XAUTHORITY path missing (US-192 regression)"
    assert re.search(r"^Environment=SDL_VIDEODRIVER=x11\s*$", text, re.MULTILINE), (
        "SDL_VIDEODRIVER=x11 missing (US-192 regression)"
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
    # Restart policy + timing checked in dedicated test above.
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
