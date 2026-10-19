################################################################################
# File Name: test_logind_powerkey_install.py
# Purpose/Description: US-649-f -- the power key's poweroff is pinned by a logind
#                      drop-in in both display modes. Covers the
#                      deploy/eclipse-powerkey.conf content, that the existing
#                      eclipse-*.conf sync include ships it, and the deploy-pi.sh
#                      install step (sync-if-changed, dry-run target, never
#                      restarts/reloads/kills systemd-logind, called outside any
#                      display-mode branch).
#
#                      Offline-safe: static file reads, `bash -n`, and the
#                      script's --dry-run from an isolated temp copy (no SSH,
#                      no root).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-19    | Rex          | Initial implementation (US-649-f)
# ================================================================================
################################################################################

"""The logind power-key drop-in and its deploy install step (US-649-f)."""

from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"
DEPLOY_SCRIPT = DEPLOY_DIR / "deploy-pi.sh"
CONF_NAME = "eclipse-powerkey.conf"
CONF_FILE = DEPLOY_DIR / CONF_NAME
SOURCE_PATH = f"deploy/{CONF_NAME}"
# Target named by the design note 2026-10-16 part 4 and the story acceptance.
TARGET_DIR = "/etc/systemd/logind.conf.d"
TARGET_PATH = f"{TARGET_DIR}/50-eclipse-powerkey.conf"
STEP_NAME = "step_install_logind_powerkey"

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
# The drop-in: a # header, then exactly [Login] + HandlePowerKey=poweroff.
# ---------------------------------------------------------------------------


def test_powerkeyConf_headerCitesTheCioRuling():
    lines = CONF_FILE.read_text(encoding="utf-8").splitlines()
    header = [ln for ln in lines if ln.startswith("#")]

    assert lines[0].startswith("#"), "the file must open with its # header"
    assert any("CIO 2026-10-16" in ln for ln in header)
    assert any("clean shutdown" in ln for ln in header)


def test_powerkeyConf_settingsAreExactlyLoginHandlePowerKeyPoweroff():
    """Everything that is not a comment or blank is the two pinned lines, in order."""
    lines = CONF_FILE.read_text(encoding="utf-8").splitlines()
    settings = [ln for ln in lines if ln.strip() and not ln.startswith("#")]

    assert settings == ["[Login]", "HandlePowerKey=poweroff"]


def test_powerkeyConf_isShippedByTheExistingEclipseConfInclude():
    """No allowlist change: the rsync include deploy/eclipse-*.conf already matches it."""
    text = _deployText()
    start = text.index("--include=config.json")
    block = text[start : text.index("--exclude=* ", start)]
    includes = re.findall(r"--include=(\S+)", block)

    assert "deploy/eclipse-*.conf" in includes
    assert fnmatch.fnmatch(SOURCE_PATH, "deploy/eclipse-*.conf")
    assert f"--include={SOURCE_PATH}" not in block, "a dedicated include is an allowlist change"


# ---------------------------------------------------------------------------
# The install step: modelled on step_install_journald_persistent.
# ---------------------------------------------------------------------------


def test_powerkeyStep_installsSyncIfChanged():
    body = _code(_stepBody(_deployText(), STEP_NAME))

    assert f"mkdir -p {TARGET_DIR}" in body
    assert SOURCE_PATH in body
    assert TARGET_PATH in body
    assert "cmp -s" in body
    assert "install -m 644" in body


def test_powerkeyStep_neverRestartsReloadsOrKillsLogind():
    """
    Given: a live logind restart can drop the kiosk session (scope fence)
    When:  the step body is read, comments included
    Then:  'systemd-logind' never appears in it at all -- the drop-in takes
           effect on the next boot
    """
    body = _stepBody(_deployText(), STEP_NAME)

    assert "systemd-logind" not in body
    for verb in ("restart", "reload", "kill"):
        assert not re.search(rf"systemctl\s+(?:\S+\s+)*{verb}", _code(body)), verb


def test_powerkeyStep_isDryRunAware():
    body = _stepBody(_deployText(), STEP_NAME)
    dryRunIndex = body.index("$DRY_RUN")

    assert body.index("return 0", dryRunIndex) < body.index("remote", dryRunIndex)


def test_powerkeyStep_isCalledOnceAtTopLevel_outsideEveryBranch():
    """
    Given: the pin must hold in BOTH display modes
    When:  the main sequence is read
    Then:  the step is called exactly once, un-indented, with every top-level
           if/case closed before it
    """
    lines = _deployText().splitlines()
    calls = [i for i, ln in enumerate(lines) if ln.strip() == STEP_NAME]

    assert len(calls) == 1, f"expected one call to {STEP_NAME}, found {len(calls)}"
    assert lines[calls[0]] == STEP_NAME, "the call is indented -- it sits inside a block"
    before = lines[: calls[0]]
    opened = sum(1 for ln in before if re.match(r"(if|case)\b", ln))
    closed = sum(1 for ln in before if re.match(r"(fi|esac)\b", ln))
    assert opened == closed, "the call sits inside a top-level if/case"


@needsBash
def test_deployDryRun_namesTheLogindTarget(tmp_path: Path):
    """
    Given: an isolated tree (as tests/deploy/test_deploy_pi.sh builds)
    When:  deploy-pi.sh --dry-run runs
    Then:  a DRY-RUN line installs the drop-in to 50-eclipse-powerkey.conf
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
