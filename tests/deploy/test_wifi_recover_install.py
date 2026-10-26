################################################################################
# File Name: test_wifi_recover_install.py
# Purpose/Description: US-925-a pin 7 -- eclipse-wifi-recover.service is a
#   sandboxed ROOT unit on the system python, and deploy-pi.sh installs it on
#   every deploy (cmp-guarded, dpkg -s check first, enable + start) without
#   ever restarting NetworkManager, reloading brcmfmac or calling apt.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-25    | Rex (US-925-a) | Initial
# ================================================================================
################################################################################

"""The Wi-Fi recovery unit and its deploy step (US-925-a)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_NAME = "eclipse-wifi-recover.service"
UNIT_FILE = REPO_ROOT / "deploy" / UNIT_NAME
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"
STEP_NAME = "step_install_wifi_recover_unit"
UNIT_DIR = "/etc/systemd/system"
PI_PATH = "/home/mcornelison/Projects/Eclipse-01"
EXEC_START = f"/usr/bin/python3 {PI_PATH}/src/pi/network/wifi_recover.py"

needsBash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def _deployText() -> str:
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


def _stepBody(text: str) -> str:
    start = text.index(f"{STEP_NAME}() {{")
    return text[start : text.index("\n}\n", start)]


def _code(body: str) -> str:
    """Without comment lines -- prose is not behaviour."""
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))


def _unitKeys() -> list[tuple[str | None, str, str]]:
    """(section, key, value) for every non-comment key line of the unit."""
    keys: list[tuple[str | None, str, str]] = []
    section: str | None = None
    for line in UNIT_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        header = re.fullmatch(r"\[([^\]]+)\]", stripped)
        if header:
            section = header.group(1)
            continue
        key, _, value = stripped.partition("=")
        keys.append((section, key, value))
    return keys


def _value(section: str, key: str) -> list[str]:
    return [v for s, k, v in _unitKeys() if s == section and k == key]


# ================================================================================
# (7) the unit, statically
# ================================================================================


def test_unit_existsWithTheProjectHeader():
    text = UNIT_FILE.read_text(encoding="utf-8")
    assert text.startswith("# ===")
    assert "US-925-a" in text


def test_unit_hasNoUserLine_runsAsRoot():
    assert [k for _, k, _ in _unitKeys() if k == "User"] == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("NoNewPrivileges", "yes"),
        ("ProtectSystem", "strict"),
        ("ProtectHome", "read-only"),
        ("PrivateTmp", "yes"),
        ("RestrictAddressFamilies", "AF_UNIX"),
        ("Restart", "on-failure"),
    ],
)
def test_unit_sandboxAndRestart(key: str, value: str):
    assert _value("Service", key) == [value]


def test_unit_capabilityBoundingSetIsEmpty():
    assert _value("Service", "CapabilityBoundingSet") == [""]


def test_unit_followsNetworkManager():
    assert _value("Unit", "After") == ["NetworkManager.service"]
    assert _value("Unit", "PartOf") == ["NetworkManager.service"]


def test_unit_execStartIsTheSystemPythonOnTheModule():
    """The dead-code lint's `python src/<path>.py` service-entry shape, on /usr/bin/python3."""
    assert _value("Service", "ExecStart") == [EXEC_START]
    assert (REPO_ROOT / "src/pi/network/wifi_recover.py").is_file()


def test_unit_wantedByMultiUser():
    assert _value("Install", "WantedBy") == ["multi-user.target"]


def test_unit_addsNoPolkitRule():
    assert not list((REPO_ROOT / "deploy" / "polkit-rules").glob("*wifi-recover*"))


# ================================================================================
# (7) the deploy step, statically
# ================================================================================


def test_step_existsAndIsCalledAtColumnZero():
    text = _deployText()
    assert f"\n{STEP_NAME}() {{" in text
    assert re.search(rf"^{STEP_NAME}$", text, re.MULTILINE), "the step is never invoked"


def test_step_isCalledOnceRightAfterTheNmPowersaveStep():
    """Column 0 (every deploy, both display modes -- the installer rule of
    test_every_unit_has_an_installer), once, after sync_tree's NM sibling."""
    calls = [
        ln for ln in _deployText().splitlines() if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", ln)
    ]
    assert calls.count(STEP_NAME) == 1
    assert calls[calls.index(STEP_NAME) - 1] == "step_install_nm_wifi_powersave"


def test_step_isCmpGuarded_daemonReloadOnlyOnChange():
    code = _code(_stepBody(_deployText()))
    remote = code[code.index('remote "') :]
    cmpAt = remote.index("cmp -s")
    elseAt = remote.index("else", cmpAt)
    assert remote.index("install -m 644", elseAt) > elseAt
    fiAt = re.compile(r"\n[ \t]*fi\n").search(remote, elseAt)
    assert fiAt is not None
    assert elseAt < remote.index("daemon-reload", elseAt) < fiAt.start()


def test_step_checksDpkgBeforeTheInstall():
    code = _code(_stepBody(_deployText()))
    remote = code[code.index('remote "') :]
    assert "for pkg in python3-dbus python3-gi" in remote
    assert remote.index("dpkg -s") < remote.index("install -m 644")
    assert "exit 1" in remote[remote.index("dpkg -s") : remote.index("install -m 644")]


def test_step_enablesAndStartsTheUnit():
    code = _code(_stepBody(_deployText()))
    assert f"sudo systemctl enable {UNIT_NAME}" in code
    assert f"sudo systemctl restart {UNIT_NAME}" in code
    assert f"{UNIT_DIR}/{UNIT_NAME}" in code


def test_step_neverRestartsNetworkManager_reloadsBrcmfmac_orCallsApt():
    code = _code(_stepBody(_deployText()))
    executable = "\n".join(
        ln for ln in code.splitlines() if "DRY-RUN" not in ln and "echo" not in ln
    )
    assert not re.search(
        r"systemctl[ \t]+(restart|reload|stop|try-restart|reload-or-restart)[ \t]+NetworkManager",
        code,
    )
    assert "brcmfmac" not in executable
    assert "modprobe" not in code and "rmmod" not in code
    assert not re.search(r"\bapt(-get)?\b", code)


# ================================================================================
# The step, run on the desk: dry-run text, and the real remote body
# ================================================================================


def _runStep(tmp_path: Path, dryRun: bool, missingPkg: str = "") -> subprocess.CompletedProcess[str]:
    """Run the shipped step body: `remote` evals locally, sudo passes through,
    dpkg / systemctl are logging fakes, and /etc/systemd/system is a temp dir."""
    piPath = tmp_path / "pi"
    (piPath / "deploy").mkdir(parents=True, exist_ok=True)
    shutil.copy(UNIT_FILE, piPath / "deploy" / UNIT_NAME)
    unitDir = tmp_path / "units"
    unitDir.mkdir(exist_ok=True)
    log = tmp_path / "calls.txt"
    step = _stepBody(_deployText()) + "\n}\n"
    step = step.replace(f"{UNIT_DIR}/", f"{unitDir.as_posix()}/")
    script = (
        "sudo() { \"$@\"; }\n"
        "remote() { eval \"$1\"; }\n"
        f"dpkg() {{ echo \"dpkg $*\" >> '{log.as_posix()}'; "
        f"[ \"$2\" != '{missingPkg}' ]; }}\n"
        f"systemctl() {{ echo \"systemctl $*\" >> '{log.as_posix()}'; }}\n"
        f"DRY_RUN={'true' if dryRun else 'false'}\n"
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


def _calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "calls.txt"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


@needsBash
def test_dryRun_printsInstallEnableStart_andNoNetworkManagerRestart(tmp_path: Path):
    result = _runStep(tmp_path, dryRun=True)

    assert result.returncode == 0, result.stdout
    out = result.stdout
    assert "dpkg -s python3-dbus python3-gi" in out
    assert "cmp -s" in out and "install + daemon-reload" in out
    assert f"systemctl enable {UNIT_NAME}" in out
    assert f"systemctl restart {UNIT_NAME} (start" in out
    assert not re.search(r"systemctl[ \t]+restart[ \t]+NetworkManager", out)
    assert _calls(tmp_path) == []


@needsBash
def test_realRun_installsEnablesStarts_secondRunWritesNothing(tmp_path: Path):
    installed = tmp_path / "units" / UNIT_NAME

    first = _runStep(tmp_path, dryRun=False)
    assert first.returncode == 0, first.stdout
    assert installed.read_bytes() == UNIT_FILE.read_bytes()
    firstCalls = _calls(tmp_path)
    assert firstCalls == [
        "dpkg -s python3-dbus",
        "dpkg -s python3-gi",
        "systemctl daemon-reload",
        f"systemctl enable {UNIT_NAME}",
        f"systemctl restart {UNIT_NAME}",
    ]

    (tmp_path / "calls.txt").unlink()
    second = _runStep(tmp_path, dryRun=False)
    assert second.returncode == 0, second.stdout
    assert "already up-to-date" in second.stdout
    assert "systemctl daemon-reload" not in _calls(tmp_path)


@needsBash
@pytest.mark.parametrize("missing", ["python3-dbus", "python3-gi"])
def test_realRun_missingPackage_failsLoudNamingIt_installsNothing(tmp_path: Path, missing: str):
    result = _runStep(tmp_path, dryRun=False, missingPkg=missing)

    assert result.returncode != 0
    assert f"ERROR: Debian package {missing} is not installed" in result.stdout
    assert not (tmp_path / "units" / UNIT_NAME).exists()
    assert not [c for c in _calls(tmp_path) if c.startswith("systemctl")]
