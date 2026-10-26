################################################################################
# File Name: test_local_login_lockdown.py
# Purpose/Description: US-652-c -- logind opens no text consoles. Covers the
#                      deploy/eclipse-kiosk-vt.conf content (NAutoVTs=0,
#                      ReserveVT=0 only), that the existing eclipse-*.conf sync
#                      include ships it, and the deploy-pi.sh install step
#                      (sync-if-changed, never restarts/reloads logind, called
#                      outside any display-mode branch, dry-run target, and a
#                      second run that writes nothing).
#
#                      Offline-safe: static file reads, `bash -n`, the script's
#                      --dry-run from an isolated temp copy, and the step body
#                      run against a temp target with a pass-through sudo (no
#                      SSH, no root).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-25    | Rex          | Initial implementation (US-652-c)
# ================================================================================
################################################################################

"""The logind no-text-console drop-in and its deploy install step (US-652-c)."""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"
DEPLOY_SCRIPT = DEPLOY_DIR / "deploy-pi.sh"
CONF_NAME = "eclipse-kiosk-vt.conf"
CONF_FILE = DEPLOY_DIR / CONF_NAME
SOURCE_PATH = f"deploy/{CONF_NAME}"
# Target named by the story acceptance.
TARGET_DIR = "/etc/systemd/logind.conf.d"
TARGET_PATH = f"{TARGET_DIR}/51-eclipse-kiosk-vt.conf"
STEP_NAME = "step_install_logind_kiosk_vt"
POWERKEY_STEP = "step_install_logind_powerkey"

needsBash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def _deployText() -> str:
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


def _stepBody(text: str, stepName: str) -> str:
    """Return the body of `<stepName>() { ... }` so a check stays scoped to it."""
    start = text.index(f"{stepName}() {{")
    return text[start : text.index("\n}\n", start)]


def _code(body: str) -> str:
    """The step body without its comment lines -- prose is not behaviour."""
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))


# ---------------------------------------------------------------------------
# The drop-in: a # header, then exactly [Login] + the two keys at 0.
# ---------------------------------------------------------------------------


def test_kioskVtConf_headerCitesItsSources():
    lines = CONF_FILE.read_text(encoding="utf-8").splitlines()
    header = "\n".join(ln for ln in lines if ln.startswith("#"))

    assert lines[0].startswith("#"), "the file must open with its # header"
    assert "Atlas 2026-10-24" in header
    assert "CIO" in header
    assert "logind.conf(5)" in header
    assert TARGET_PATH in header


def test_kioskVtConf_settingsAreExactlyNAutoVTsAndReserveVTAtZero():
    """Everything that is not a comment or blank is the section and the two keys."""
    lines = CONF_FILE.read_text(encoding="utf-8").splitlines()
    settings = [ln for ln in lines if ln.strip() and not ln.startswith("#")]

    assert settings[0] == "[Login]"
    assert sorted(settings[1:]) == ["NAutoVTs=0", "ReserveVT=0"]


def test_kioskVtConf_leavesThePowerKeyAlone():
    """Scope fence: HandlePowerKey stays the power-key drop-in's alone."""
    assert "HandlePowerKey" not in _code(CONF_FILE.read_text(encoding="utf-8"))


def test_kioskVtConf_isShippedByTheExistingEclipseConfInclude():
    """No allowlist change: the rsync include deploy/eclipse-*.conf already matches it."""
    text = _deployText()
    start = text.index("--include=config.json")
    block = text[start : text.index("--exclude=* ", start)]
    includes = re.findall(r"--include=(\S+)", block)

    assert "deploy/eclipse-*.conf" in includes
    assert fnmatch.fnmatch(SOURCE_PATH, "deploy/eclipse-*.conf")
    assert f"--include={SOURCE_PATH}" not in block, "a dedicated include is an allowlist change"


def test_kioskVtConf_isShippedByTheTarFallback():
    """The tar fallback ships ./deploy whole, which carries the drop-in."""
    text = _deployText()
    tarStart = text.index("tar -cz")
    tarList = text[tarStart : text.index(")", tarStart)]
    assert re.search(r"\s\./deploy\s*$", tarList), "tar fallback no longer ships ./deploy whole"
    assert CONF_NAME not in tarList, "the tar fallback excludes the drop-in"


# ---------------------------------------------------------------------------
# The install step: the posture of step_install_logind_powerkey.
# ---------------------------------------------------------------------------


def test_kioskVtStep_installsSyncIfChanged():
    body = _code(_stepBody(_deployText(), STEP_NAME))

    assert f"mkdir -p {TARGET_DIR}" in body
    assert SOURCE_PATH in body
    assert TARGET_PATH in body
    assert "cmp -s" in body
    assert "install -m 644" in body


def test_kioskVtStep_neverRestartsReloadsOrKillsLogind():
    """
    Given: a live logind restart can drop the kiosk session
    When:  the step body is read, comments included
    Then:  'systemd-logind' never appears in it, and no systemctl restart,
           reload or kill does -- the drop-in takes effect on the next boot
    """
    body = _stepBody(_deployText(), STEP_NAME)

    assert "systemd-logind" not in body
    for verb in ("restart", "reload", "kill"):
        assert not re.search(rf"systemctl\s+(?:\S+\s+)*{verb}", _code(body)), verb


def test_kioskVtStep_isDryRunAware():
    body = _stepBody(_deployText(), STEP_NAME)
    dryRunIndex = body.index("$DRY_RUN")

    assert body.index("return 0", dryRunIndex) < body.index("remote", dryRunIndex)


def test_kioskVtStep_isCalledOnceAtTopLevel_rightAfterThePowerKeyStep():
    """
    Given: the lockdown must hold in BOTH display modes
    When:  the main sequence is read
    Then:  the step is called exactly once, un-indented, with every top-level
           if/case closed before it, next to the power-key step
    """
    lines = _deployText().splitlines()
    calls = [i for i, ln in enumerate(lines) if ln.strip() == STEP_NAME]
    powerkeyCalls = [i for i, ln in enumerate(lines) if ln == POWERKEY_STEP]

    assert len(calls) == 1, f"expected one call to {STEP_NAME}, found {len(calls)}"
    assert lines[calls[0]] == STEP_NAME, "the call is indented -- it sits inside a block"
    before = lines[: calls[0]]
    opened = sum(1 for ln in before if re.match(r"(if|case)\b", ln))
    closed = sum(1 for ln in before if re.match(r"(fi|esac)\b", ln))
    assert opened == closed, "the call sits inside a top-level if/case"
    between = lines[powerkeyCalls[0] + 1 : calls[0]]
    assert powerkeyCalls[0] < calls[0]
    assert all(not ln.strip() or ln.startswith("#") for ln in between), (
        "the step is not wired next to step_install_logind_powerkey"
    )


# ---------------------------------------------------------------------------
# Behaviour: the step body run against a temp target.
# ---------------------------------------------------------------------------


def _runStep(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """
    Run the real step body with DRY_RUN=false: `remote` evals its script
    locally, `sudo` passes through, and the logind.conf.d dir is redirected to
    a temp dir. Everything else is the shipped text.
    """
    piPath = tmp_path / "pi"
    (piPath / "deploy").mkdir(parents=True, exist_ok=True)
    shutil.copy(CONF_FILE, piPath / "deploy" / CONF_NAME)
    targetDir = tmp_path / "logind.conf.d"
    step = _stepBody(_deployText(), STEP_NAME) + "\n}\n"
    step = step.replace(TARGET_DIR, targetDir.as_posix())
    script = (
        "sudo() { \"$@\"; }\n"
        "remote() { eval \"$1\"; }\n"
        "DRY_RUN=false\n"
        f"PI_PATH='{piPath.as_posix()}'\n"
        f"{step}\n"
        f"{STEP_NAME}\n"
    )
    return subprocess.run(
        ["bash", "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


@needsBash
def test_kioskVtStep_firstRunInstalls_secondRunWritesNothing(tmp_path: Path):
    """
    Given: no drop-in installed
    When:  the step runs twice
    Then:  the first run installs it (effective next boot); the second prints
           'already current (no change)' and leaves the installed file untouched
    """
    target = tmp_path / "logind.conf.d" / "51-eclipse-kiosk-vt.conf"

    first = _runStep(tmp_path)
    assert first.returncode == 0, first.stdout
    assert "installed" in first.stdout and "effective next boot" in first.stdout
    assert target.read_bytes() == CONF_FILE.read_bytes()

    # A sentinel mtime: a second install would reset it.
    os.utime(target, (1_000_000_000, 1_000_000_000))
    second = _runStep(tmp_path)
    assert second.returncode == 0, second.stdout
    assert "already current" in second.stdout and "(no change)" in second.stdout
    assert "installed" not in second.stdout
    assert target.stat().st_mtime == 1_000_000_000


@needsBash
def test_deployDryRun_namesTheKioskVtTarget_andNoLogindRestart(tmp_path: Path):
    """
    Given: an isolated tree (as tests/deploy/test_deploy_pi.sh builds)
    When:  deploy-pi.sh --dry-run runs
    Then:  a DRY-RUN line installs the drop-in to 51-eclipse-kiosk-vt.conf and
           nothing restarts logind
    """
    deployDir = tmp_path / "deploy"
    deployDir.mkdir()
    for name in ("deploy-pi.sh", "addresses.sh", "os-trim.manifest"):
        shutil.copy(DEPLOY_DIR / name, deployDir / name)
    shutil.copytree(DEPLOY_DIR / "labwc", deployDir / "labwc")
    (deployDir / "deploy.conf").write_text(
        "PI_HOST=192.0.2.1\nPI_USER=nobody\nPI_PATH=/tmp/will-never-exist\nPI_PORT=22\n",
        encoding="utf-8",
        newline="\n",
    )

    result = subprocess.run(
        ["bash", (deployDir / "deploy-pi.sh").as_posix(), "--dry-run"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        timeout=120,
    )

    out = result.stdout
    assert result.returncode == 0, out[-2000:]
    installLines = [
        ln for ln in out.splitlines() if ln.startswith("DRY-RUN would install") and SOURCE_PATH in ln
    ]
    assert installLines, out[-2000:]
    assert installLines[0].endswith(f"-> {TARGET_PATH}")
    assert not re.search(r"systemctl\s+(?:\S+\s+)*(restart|reload)\s+\S*logind", out)


@needsBash
def test_deployPiSh_bashSyntaxValid():
    result = subprocess.run(
        ["bash", "-n", str(DEPLOY_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
