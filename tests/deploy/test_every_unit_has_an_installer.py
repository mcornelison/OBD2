################################################################################
# File Name: test_every_unit_has_an_installer.py
# Purpose/Description: US-908-b -- every systemd unit file in deploy/ is installed
#                      by an EVERY-deploy path (deploy-pi.sh or deploy-server.sh),
#                      or is named in a one-entry allow-list. US-908's own shape
#                      (a unit installed only under --init) must fail here.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-10-21    | Rex (US-908-b) | Initial implementation (Atlas REVIEW G1 shapes).
# 2026-10-24    | Rex (US-651-a) | Atlas GAP G1: *.path + *.target units are accounted;
#               |                | inventory 20 -> 23 (the kiosk start latch + the
#               |                | two .path units, installed by the kiosk step).
# 2026-10-25    | Rex (US-925-a) | MOVED PIN (US-925-a): inventory 23 -> 24 (+
#               |                | eclipse-wifi-recover.service, pi-literal via
#               |                | step_install_wifi_recover_unit).
# ================================================================================
################################################################################

"""No ``deploy/*.service`` / ``*.timer`` / ``*.path`` / ``*.target`` is left without an installer.

A unit counts as installed on every deploy when ONE of these holds (Atlas
REVIEW 2026-10-20 G1):

(i-a) deploy-pi.sh: a function that is CALLED at column 0 (so not inside
      ``if $INIT; then``, whose calls are indented) has a body naming
      ``/etc/systemd/system/<unit>`` -- literally, or through ``${VAR}`` /
      ``$VAR`` where VAR is assigned at column 0 of the same script
      (``SERVICE_NAME="eclipse-obd"`` makes ``${SERVICE_NAME}.service`` read
      ``eclipse-obd.service``).  A path that cannot be expanded does not count.
(i-b) deploy-server.sh (no step functions; Steps 4.7/4.8 are inline): a line
      naming ``/etc/systemd/system/<unit>`` at TOP LEVEL, outside any if/fi
      block (if/fi depth is tracked line by line).
(ii)  listed in ``NOT_EVERY_DEPLOY`` -- exactly one entry.

Expected inventory on the real tree (2026-10-24, US-651-a): 23 files = 22 pass
+ 1 allow-listed.  The 22: 20 literal (17 deploy-pi.sh, incl. the US-651-a
kiosk start latch and its two .path units, which step_install_ui_kiosk_units
installs through ``eclipse-display-mode trigger`` and then checks by path;
the 14 earlier deploy-pi.sh steps, incl.
drain-forensics.service, whose .service is still synced every deploy -- only
its timer was retired, US-646 -- plus the 3 deploy-server.sh files via (i-b)),
eclipse-obd.service via SERVICE_NAME, and rfcomm-bind.service via US-908-b's
step_sync_rfcomm_bind_unit.  The allow-listed one: obd2-server.service.
MOVED PIN (US-925-a, 2026-10-25): 24 files -- eclipse-wifi-recover.service is
the 18th deploy-pi.sh literal (step_install_wifi_recover_unit).

Comment lines are dropped before any search: prose about a unit is not an
installer for it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "deploy"
DEPLOY_PI = DEPLOY_DIR / "deploy-pi.sh"
DEPLOY_SERVER = DEPLOY_DIR / "deploy-server.sh"

# Atlas REVIEW 2026-10-20 G1 / PM: this ONE entry only.
NOT_EVERY_DEPLOY = {
    "obd2-server.service": (
        "legacy OBD2v2 unit, installed only by the one-time deploy/install-server.sh; "
        "deploy-server.sh installs obd-server.service"
    ),
}

# The inventory written into the module docstring, pinned so a drift is reported.
EXPECTED_PI_LITERAL = {
    "boot-progress-arm.service",
    "boot-progress-finalize.service",
    "drain-forensics.service",
    "eclipse-bond-selfheal.service",
    "eclipse-boot-state.service",
    "eclipse-kiosk-socket.path",
    "eclipse-kiosk-start.target",
    "eclipse-kiosk-watchdog.service",
    "eclipse-kiosk-watchdog.timer",
    "eclipse-panel-liveness.service",
    "eclipse-panel-liveness.timer",
    "eclipse-powerwatch.service",
    "eclipse-rfkill-unblock.service",
    "eclipse-states-http.service",
    "eclipse-wifi-recover.service",  # MOVED PIN (US-925-a)
    "eclipse-x-ready.path",
    "orphan-cleanup.service",
    "orphan-cleanup.timer",
    "rfcomm-bind.service",
}
EXPECTED_PI_EXPANDED = {"eclipse-obd.service"}
EXPECTED_SERVER_TOP_LEVEL = {
    "obd-server.service",
    "server-analytics-batch.service",
    "server-analytics-batch.timer",
}

_UNIT_DIR = "/etc/systemd/system/"
_UNIT_PATH_RE = re.compile(re.escape(_UNIT_DIR) + r"([A-Za-z0-9_.@-]+\.(?:service|timer|path|target))\b")
_FUNC_DEF_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(\) \{", re.MULTILINE)
_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_IF_OPEN_RE = re.compile(r"(?:^|[;&|]\s*)if\b")
_IF_CLOSE_RE = re.compile(r"(?:^|;\s*)fi\b")


def _codeLines(text: str) -> list[str]:
    """Every line that is not a full-line comment."""
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


def unitFiles(deployDir: Path) -> list[str]:
    """The unit files a deploy has to account for."""
    return sorted(
        path.name
        for pattern in ("*.service", "*.timer", "*.path", "*.target")
        for path in deployDir.glob(pattern)
    )


def functionBodies(text: str) -> dict[str, str]:
    """``name -> body`` for each column-0 function, comment lines dropped."""
    bodies: dict[str, str] = {}
    for match in _FUNC_DEF_RE.finditer(text):
        end = text.find("\n}\n", match.start())
        body = text[match.start() : end + 2 if end > -1 else len(text)]
        bodies[match.group(1)] = "\n".join(_codeLines(body))
    return bodies


def columnZeroCalls(text: str) -> set[str]:
    """Bare, unindented lines -- the every-deploy orchestration's calls."""
    return {line for line in text.splitlines() if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", line)}


def columnZeroAssignments(text: str) -> dict[str, str]:
    """``VAR -> value`` for assignments at column 0 (quotes stripped)."""
    assignments: dict[str, str] = {}
    for line in text.splitlines():
        match = _ASSIGN_RE.match(line)
        if match is None:
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        assignments[match.group(1)] = value
    return assignments


def expandVariables(text: str, assignments: dict[str, str]) -> str:
    """Expand ``${VAR}`` and ``$VAR`` for column-0 VARs only; leave the rest."""

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        return assignments.get(name, match.group(0))

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)", _sub, text)


def piInstallers(piText: str) -> dict[str, str]:
    """``unit -> 'literal:<fn>' | 'expanded:<fn>'`` for column-0-called functions."""
    calls = columnZeroCalls(piText)
    assignments = columnZeroAssignments(piText)
    found: dict[str, str] = {}
    for name, body in functionBodies(piText).items():
        if name not in calls:
            continue
        for unit in _UNIT_PATH_RE.findall(body):
            found.setdefault(unit, f"literal:{name}")
        for unit in _UNIT_PATH_RE.findall(expandVariables(body, assignments)):
            found.setdefault(unit, f"expanded:{name}")
    return found


def serverTopLevelInstalls(serverText: str) -> set[str]:
    """Units named by a line at if/fi depth 0 of deploy-server.sh."""
    found: set[str] = set()
    depth = 0
    for line in _codeLines(serverText):
        stripped = line.strip()
        if depth == 0:
            found.update(_UNIT_PATH_RE.findall(stripped))
        depth += len(_IF_OPEN_RE.findall(stripped)) - len(_IF_CLOSE_RE.findall(stripped))
    return found


def installerFor(unit: str, piText: str, serverText: str) -> str | None:
    """How ``unit`` reaches /etc/systemd/system on every deploy, or None."""
    pi = piInstallers(piText)
    if unit in pi:
        return f"pi-{pi[unit]}"
    if unit in serverTopLevelInstalls(serverText):
        return "server-top-level"
    if unit in NOT_EVERY_DEPLOY:
        return "allow-listed"
    return None


def uncoveredUnits(deployDir: Path, piText: str, serverText: str) -> list[str]:
    return [u for u in unitFiles(deployDir) if installerFor(u, piText, serverText) is None]


@pytest.fixture(scope="module")
def piText() -> str:
    return DEPLOY_PI.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def serverText() -> str:
    return DEPLOY_SERVER.read_text(encoding="utf-8")


# ================================================================================
# The real tree
# ================================================================================


@pytest.mark.parametrize("unit", unitFiles(DEPLOY_DIR))
def test_unit_hasAnEveryDeployInstaller(unit: str, piText: str, serverText: str) -> None:
    """Every deploy/ unit file is installed on every deploy, or allow-listed."""
    assert installerFor(unit, piText, serverText) is not None, (
        f"{unit} is in deploy/ but no every-deploy path installs it -- a fix to it "
        "would never reach the box (the US-908 shape)"
    )


def test_inventory_matchesTheDocumentedTwentyFour(piText: str, serverText: str) -> None:
    """
    Given: the real deploy/ tree
    When: each unit is classified
    Then: 24 files = 19 deploy-pi.sh literal (14 + rfcomm-bind + the US-651-a
          latch and two .path units + the US-925-a wifi-recover unit) + 1
          expanded + 3 deploy-server.sh top-level + 1 allow-listed
    """
    units = unitFiles(DEPLOY_DIR)
    how = {unit: installerFor(unit, piText, serverText) for unit in units}

    assert len(units) == 24  # MOVED PIN (US-925-a): + eclipse-wifi-recover.service
    assert {u for u, h in how.items() if h and h.startswith("pi-literal:")} == EXPECTED_PI_LITERAL
    assert {u for u, h in how.items() if h and h.startswith("pi-expanded:")} == (
        EXPECTED_PI_EXPANDED
    )
    assert {u for u, h in how.items() if h == "server-top-level"} == EXPECTED_SERVER_TOP_LEVEL
    assert {u for u, h in how.items() if h == "allow-listed"} == set(NOT_EVERY_DEPLOY)


def test_rfcommBind_isInstalledByTheNewStep(piText: str) -> None:
    """US-908-b: the every-deploy installer is step_sync_rfcomm_bind_unit."""
    assert piInstallers(piText)["rfcomm-bind.service"] == "literal:step_sync_rfcomm_bind_unit"


def test_eclipseObd_isFoundOnlyThroughServiceName(piText: str) -> None:
    """The SERVICE_NAME expansion is load-bearing: without it eclipse-obd has no installer."""
    assert columnZeroAssignments(piText)["SERVICE_NAME"] == "eclipse-obd"
    assert piInstallers(piText)["eclipse-obd.service"].startswith("expanded:")


def test_kioskStartTrigger_isInstalledByTheKioskStep(piText: str) -> None:
    """US-651-a: the latch and both .path units ride the every-deploy kiosk step."""
    pi = piInstallers(piText)
    for unit in ("eclipse-kiosk-start.target", "eclipse-kiosk-socket.path", "eclipse-x-ready.path"):
        assert pi[unit] == "literal:step_install_ui_kiosk_units", unit


def test_control_aPlantedPathUnitWithNoInstallerFails(
    tmp_path: Path, piText: str, serverText: str
) -> None:
    """*.path is globbed: an unaccounted .path is reported (the G1 gap)."""
    (tmp_path / "zz-test.path").write_text("[Path]\nPathExists=/x\n", encoding="utf-8")

    assert uncoveredUnits(tmp_path, piText, serverText) == ["zz-test.path"]


def test_allowList_holdsExactlyOneEntry() -> None:
    assert list(NOT_EVERY_DEPLOY) == ["obd2-server.service"]


# ================================================================================
# Negative controls -- the checker can fail
# ================================================================================

_ZZ = "zz-test.service"


def test_control_b_aPlantedUnitWithNoInstallerFails(
    tmp_path: Path, piText: str, serverText: str
) -> None:
    """(b) deploy/zz-test.service with no installer is reported uncovered."""
    (tmp_path / _ZZ).write_text("[Unit]\nDescription=planted\n", encoding="utf-8")

    assert uncoveredUnits(tmp_path, piText, serverText) == [_ZZ]


_ZZ_STEP = (
    "\nstep_install_zz_test() {\n"
    f"    DST='/etc/systemd/system/{_ZZ}'\n"
    "    sudo install -m 644 \"$SRC\" \"$DST\"\n"
    "}\n"
)


def test_control_c_aUnitInstalledOnlyUnderInitFails(piText: str, serverText: str) -> None:
    """(c) the US-908 shape: a step called only inside ``if $INIT; then`` does not count."""
    planted = piText + _ZZ_STEP + "if $INIT; then\n    step_install_zz_test\nfi\n"

    assert installerFor(_ZZ, planted, serverText) is None


def test_control_c_positive_theSameStepAtColumnZeroPasses(piText: str, serverText: str) -> None:
    """Control for (c): the identical step called at column 0 IS an installer."""
    planted = piText + _ZZ_STEP + "step_install_zz_test\n"

    assert installerFor(_ZZ, planted, serverText) == "pi-literal:step_install_zz_test"


def test_control_c_server_anInstallInsideAnIfFails(piText: str, serverText: str) -> None:
    """(c), deploy-server.sh shape: an install inside an if/fi block does not count."""
    planted = serverText + (
        f"\nif [ \"$INIT\" = true ]; then\n    DST='/etc/systemd/system/{_ZZ}'\nfi\n"
    )

    assert installerFor(_ZZ, piText, planted) is None
    assert installerFor(_ZZ, piText, serverText + f"\nDST='/etc/systemd/system/{_ZZ}'\n") == (
        "server-top-level"
    )


_ZZ_VAR_STEP = (
    "\nstep_install_zz_var() {\n"
    "    ZZ_NAME=\"zz-test\"\n"
    "    DST=\"/etc/systemd/system/${ZZ_NAME}.service\"\n"
    "}\n"
    "step_install_zz_var\n"
)


def test_control_d_aVariableNotAssignedAtColumnZeroFails(piText: str, serverText: str) -> None:
    """(d) ``${VAR}`` whose VAR is assigned only inside the function cannot be expanded."""
    assert installerFor(_ZZ, piText + _ZZ_VAR_STEP, serverText) is None


def test_control_d_positive_aColumnZeroAssignmentExpands(piText: str, serverText: str) -> None:
    """Control for (d): the same path with ZZ_NAME assigned at column 0 IS an installer."""
    planted = piText + '\nZZ_NAME="zz-test"\n' + _ZZ_VAR_STEP

    assert installerFor(_ZZ, planted, serverText) == "pi-expanded:step_install_zz_var"


def test_control_aCommentedInstallDoesNotCount(piText: str, serverText: str) -> None:
    """Prose naming a unit path is not an installer, in either script."""
    commentedStep = (
        f"\nstep_install_zz_doc() {{\n    # DST='/etc/systemd/system/{_ZZ}'\n}}\n"
        "step_install_zz_doc\n"
    )

    assert installerFor(_ZZ, piText + commentedStep, serverText) is None
    assert installerFor(_ZZ, piText, serverText + f"\n# /etc/systemd/system/{_ZZ}\n") is None
