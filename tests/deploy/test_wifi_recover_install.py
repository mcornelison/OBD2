################################################################################
# File Name: test_wifi_recover_install.py
# Purpose/Description: US-925-a pin 7 -- eclipse-wifi-recover.service is a
#   sandboxed ROOT unit on the system python, and deploy-pi.sh installs it on
#   every deploy (cmp-guarded, dpkg -s check first, enable + start) without
#   ever restarting NetworkManager, reloading brcmfmac or calling apt.
#   US-925-c: the script runs from a root-owned copy outside /home, the unit is
#   Type=notify, and the step gates on restart + NRestarts + the journal line.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-25    | Rex (US-925-a) | Initial
# 2026-10-26    | Rex (US-925-b) | psk-flags != 0 -> one WARNING per Wi-Fi profile
# 2026-10-26    | Rex (US-925-c) | MOVED PIN: root-owned script path, ProtectHome=yes,
#               |                | Type=notify, and the restart/NRestarts/journal gate
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
# US-925-c (Atlas RULED): root with an empty capability set cannot enter
# /home/mcornelison (Errno 13), so the unit runs a root-owned copy.
SCRIPT_DIR = "/usr/local/lib/eclipse"
SCRIPT_NAME = "wifi_recover.py"
SCRIPT_SOURCE = REPO_ROOT / "src" / "pi" / "network" / SCRIPT_NAME
EXEC_START = f"/usr/bin/python3 {SCRIPT_DIR}/{SCRIPT_NAME}"  # MOVED PIN (US-925-c)
WATCHING_LINE = "INFO wifi-recover: watching wlan0 for NetworkManager no-secrets failures"
INVOCATION_ID = "0123456789abcdef0123456789abcdef"

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
        ("ProtectHome", "yes"),  # MOVED PIN (US-925-c): was read-only
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


def test_unit_execStartIsTheSystemPythonOnTheRootOwnedCopy():
    """MOVED PIN (US-925-c): /usr/bin/python3 on the copy the deploy step installs.
    The module stays live for the dead-code lint through its __main__ block."""
    assert _value("Service", "ExecStart") == [EXEC_START]
    assert SCRIPT_SOURCE.is_file()


def test_unit_execStartIsNotUnderHome():
    """US-925-c: ProtectHome=yes + an empty capability set cannot reach /home."""
    (execStart,) = _value("Service", "ExecStart")
    assert not execStart.split()[-1].startswith("/home/")


def test_unit_hasNoWorkingDirectory():
    assert _value("Service", "WorkingDirectory") == []


def test_unit_namesNoHomePathAnywhere():
    """`grep -n '/home/' deploy/eclipse-wifi-recover.service` returns nothing."""
    assert "/home/" not in UNIT_FILE.read_text(encoding="utf-8")


def test_unit_isTypeNotify_mainPidOnly():
    """READY=1 from the main PID only, so `systemctl restart` waits for the subscription."""
    assert _value("Service", "Type") == ["notify"]
    assert _value("Service", "NotifyAccess") == ["main"]


def test_unit_addsNoDacCapability():
    keys = _unitKeys()
    assert not [v for _, k, v in keys if "CAP_DAC" in v]
    assert [k for _, k, _ in keys if k == "AmbientCapabilities"] == []


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


_Profile = tuple[str, str, str, str]  # (uuid, type, connection.id, psk-flags as nmcli prints it)


def _nmcliFake(log: Path, profiles: list[_Profile] | None, listFails: bool) -> str:
    """A bash `nmcli` that answers only the read-only `-g` reads; None defines none."""
    if profiles is None:
        return ""
    rows = " ".join(f"{uuid}:{kind}" for uuid, kind, _, _ in profiles)
    listing = "return 10" if listFails else f"printf '%s\\n' {rows}"
    cases = [f'"-g UUID,TYPE connection show") {listing} ;;']
    for uuid, _, name, flags in profiles:
        cases.append(f"\"-g connection.id connection show uuid {uuid}\") echo '{name}' ;;")
        cases.append(
            f"\"-g 802-11-wireless-security.psk-flags connection show uuid {uuid}\") echo '{flags}' ;;"
        )
    return (
        f"nmcli() {{ echo \"nmcli $*\" >> '{log.as_posix()}'; case \"$*\" in\n"
        + "\n".join(cases)
        + "\n*) return 1 ;;\nesac; }\n"
    )


def _systemctlFake(log: Path, restartExit: int, nRestarts: str) -> str:
    """A bash `systemctl` that logs every call and answers the gate's two reads."""
    return (
        f"systemctl() {{ echo \"systemctl $*\" >> '{log.as_posix()}'; case \"$*\" in\n"
        f"\"restart {UNIT_NAME}\") return {restartExit} ;;\n"
        f"\"show -p NRestarts --value {UNIT_NAME}\") echo '{nRestarts}' ;;\n"
        f"\"show -p InvocationID --value {UNIT_NAME}\") echo '{INVOCATION_ID}' ;;\n"
        "esac; }\n"
    )


def _journalctlFake(log: Path, journal: list[str]) -> str:
    """A bash `journalctl` holding ``journal`` for INVOCATION_ID only."""
    lines = " ".join(f"'{line}'" for line in journal) or "''"
    return (
        f"journalctl() {{ echo \"journalctl $*\" >> '{log.as_posix()}'; case \"$1\" in\n"
        f"_SYSTEMD_INVOCATION_ID={INVOCATION_ID}) printf '%s\\n' {lines} ;;\n"
        "esac; }\n"
    )


def _runStep(
    tmp_path: Path,
    dryRun: bool,
    missingPkg: str = "",
    profiles: list[_Profile] | None = None,
    listFails: bool = False,
    restartExit: int = 0,
    nRestarts: str = "0",
    journal: list[str] | None = None,
    withScript: bool = True,
    cmpFailsFor: str = "",
) -> subprocess.CompletedProcess[str]:
    """Run the shipped step body: `remote` evals locally, sudo passes through,
    dpkg / systemctl / journalctl / nmcli are logging fakes, and /etc/systemd/system
    and /usr/local/lib/eclipse are temp dirs. With no profiles there is no nmcli
    at all (as on this desk). `cmpFailsFor` makes every cmp naming it report a
    difference (a copy that never verifies)."""
    piPath = tmp_path / "pi"
    (piPath / "deploy").mkdir(parents=True, exist_ok=True)
    shutil.copy(UNIT_FILE, piPath / "deploy" / UNIT_NAME)
    if withScript:
        (piPath / "src" / "pi" / "network").mkdir(parents=True, exist_ok=True)
        shutil.copy(SCRIPT_SOURCE, piPath / "src" / "pi" / "network" / SCRIPT_NAME)
    unitDir = tmp_path / "units"
    unitDir.mkdir(exist_ok=True)
    scriptDir = tmp_path / "lib" / "eclipse"
    log = tmp_path / "calls.txt"
    step = _stepBody(_deployText()) + "\n}\n"
    step = step.replace(f"{UNIT_DIR}/", f"{unitDir.as_posix()}/")
    step = step.replace(SCRIPT_DIR, scriptDir.as_posix())
    cmpFake = (
        f"cmp() {{ case \"$*\" in *'{cmpFailsFor}'*) return 1 ;; esac; command cmp \"$@\"; }}\n"
        if cmpFailsFor
        else ""
    )
    script = (
        "sudo() { \"$@\"; }\n"
        "remote() { eval \"$1\"; }\n"
        f"dpkg() {{ echo \"dpkg $*\" >> '{log.as_posix()}'; "
        f"[ \"$2\" != '{missingPkg}' ]; }}\n"
        + _systemctlFake(log, restartExit, nRestarts)
        + _journalctlFake(log, [WATCHING_LINE] if journal is None else journal)
        + cmpFake
        + _nmcliFake(tmp_path / "nmcli.txt", profiles, listFails)
        + f"DRY_RUN={'true' if dryRun else 'false'}\n"
        f"PI_PATH='{piPath.as_posix()}'\n"
        f"{step}\n"
        f"{STEP_NAME}\n"
    )
    return subprocess.run(
        ["bash", "-s"],
        input=script,
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
    assert firstCalls == [  # MOVED PIN (US-925-c): + the gate's reads
        "dpkg -s python3-dbus",
        "dpkg -s python3-gi",
        "systemctl daemon-reload",
        f"systemctl enable {UNIT_NAME}",
        f"systemctl restart {UNIT_NAME}",
        f"systemctl show -p NRestarts --value {UNIT_NAME}",
        f"systemctl show -p InvocationID --value {UNIT_NAME}",
        f"journalctl _SYSTEMD_INVOCATION_ID={INVOCATION_ID} --output cat --no-pager",
    ]
    copied = tmp_path / "lib" / "eclipse" / SCRIPT_NAME
    assert copied.read_bytes() == SCRIPT_SOURCE.read_bytes()
    assert "cmp-verified" in first.stdout
    assert GATE_PASSED in first.stdout

    (tmp_path / "calls.txt").unlink()
    second = _runStep(tmp_path, dryRun=False)
    assert second.returncode == 0, second.stdout
    assert f"{UNIT_NAME} already up-to-date" in second.stdout
    assert f"{SCRIPT_NAME} already up-to-date" in second.stdout
    assert "systemctl daemon-reload" not in _calls(tmp_path)
    assert f"systemctl restart {UNIT_NAME}" in _calls(tmp_path)


# ================================================================================
# US-925-c: the root-owned script copy and the restart / NRestarts / journal gate
# ================================================================================

GATE_PASSED = "gate passed: restart READY, NRestarts=0, watching wlan0"


def _restarted(tmp_path: Path) -> bool:
    return f"systemctl restart {UNIT_NAME}" in _calls(tmp_path)


def test_step_copiesTheScriptBeforeTheRestart_cmpVerified():
    code = _code(_stepBody(_deployText()))
    remote = code[code.index('remote "') :]
    copyAt = remote.index('sudo install -m 0644 \\"\\$PY_SRC\\" \\"\\$PY_DST\\"')
    verifyAt = remote.index('sudo cmp -s \\"\\$PY_SRC\\" \\"\\$PY_DST\\"', copyAt)
    assert copyAt < verifyAt < remote.index(f"systemctl restart {UNIT_NAME}")
    assert f'local scriptDir="{SCRIPT_DIR}"' in code
    assert "PY_DIR='${scriptDir}'" in remote
    assert "src/pi/network/wifi_recover.py" in remote
    assert 'sudo install -d -m 0755 \\"\\$PY_DIR\\"' in remote


def test_step_hasNoInertEnabledActiveEcho():
    """The old 'enabled + active' echo claimed success it never checked (V0.30.15)."""
    assert "enabled + active" not in _code(_stepBody(_deployText()))


@needsBash
def test_dryRun_printsTheCopyAndTheGate(tmp_path: Path):
    result = _runStep(tmp_path, dryRun=True)

    assert result.returncode == 0, result.stdout
    assert f"{(tmp_path / 'lib' / 'eclipse').as_posix()}/{SCRIPT_NAME}" in result.stdout
    assert "NRestarts" in result.stdout and "watching wlan0" in result.stdout


@needsBash
def test_realRun_scriptDirAbsent_isCreated(tmp_path: Path):
    result = _runStep(tmp_path, dryRun=False)

    assert result.returncode == 0, result.stdout
    assert (tmp_path / "lib" / "eclipse").is_dir()
    assert "(root:root 0755)" in result.stdout


@needsBash
def test_realRun_nRestartsOne_failsNamingTheCheck(tmp_path: Path):
    result = _runStep(tmp_path, dryRun=False, nRestarts="1")

    assert result.returncode != 0
    assert "ERROR: wifi-recover gate: NRestarts=1 (expected 0)" in result.stdout
    assert GATE_PASSED not in result.stdout


@needsBash
def test_realRun_journalLineMissing_failsNamingTheCheck(tmp_path: Path):
    result = _runStep(
        tmp_path, dryRun=False, journal=["INFO wifi-recover: all Wi-Fi secrets system-owned"]
    )

    assert result.returncode != 0
    assert (
        f"ERROR: wifi-recover gate: no 'watching wlan0' line in the journal of invocation "
        f"{INVOCATION_ID}" in result.stdout
    )
    assert GATE_PASSED not in result.stdout


@needsBash
def test_realRun_restartFails_failsNamingTheCheck_readsNothingElse(tmp_path: Path):
    result = _runStep(tmp_path, dryRun=False, restartExit=1)

    assert result.returncode != 0
    assert "ERROR: wifi-recover gate: systemctl restart" in result.stdout
    assert not [c for c in _calls(tmp_path) if c.startswith(("systemctl show", "journalctl"))]


@needsBash
def test_realRun_nRestartsZeroAndLinePresent_passes(tmp_path: Path):
    result = _runStep(tmp_path, dryRun=False, nRestarts="0", journal=[WATCHING_LINE])

    assert result.returncode == 0, result.stdout
    assert GATE_PASSED in result.stdout
    assert "ERROR" not in result.stdout


@needsBash
def test_realRun_scriptMissingOnThePi_failsWithError_noRestart(tmp_path: Path):
    result = _runStep(tmp_path, dryRun=False, withScript=False)

    assert result.returncode != 0
    assert f"ERROR: {(tmp_path / 'pi').as_posix()}/src/pi/network/{SCRIPT_NAME}" in result.stdout
    assert not _restarted(tmp_path)
    assert not (tmp_path / "units" / UNIT_NAME).exists()


@needsBash
def test_realRun_copyNeverVerifies_failsWithError_noRestart(tmp_path: Path):
    result = _runStep(tmp_path, dryRun=False, cmpFailsFor=SCRIPT_NAME)

    assert result.returncode != 0
    assert "does not match" in result.stdout and "after install" in result.stdout
    assert result.stdout.count("ERROR:") == 1
    assert not _restarted(tmp_path)


@needsBash
@pytest.mark.parametrize("missing", ["python3-dbus", "python3-gi"])
def test_realRun_missingPackage_failsLoudNamingIt_installsNothing(tmp_path: Path, missing: str):
    result = _runStep(tmp_path, dryRun=False, missingPkg=missing)

    assert result.returncode != 0
    assert f"ERROR: Debian package {missing} is not installed" in result.stdout
    assert not (tmp_path / "units" / UNIT_NAME).exists()
    assert not [c for c in _calls(tmp_path) if c.startswith("systemctl")]


# ================================================================================
# US-925-b: the read-only psk-flags check
# ================================================================================

UUID_HOME = "3f0c2b1e-8d9a-4c55-9e3e-1a2b3c4d5e6f"
UUID_PHONE = "7d1e0a42-55b0-4e7e-8a19-0f9e8d7c6b5a"
UUID_ETH = "11111111-2222-4333-8444-555555555555"
ALL_SYSTEM_OWNED = "all Wi-Fi secrets system-owned (psk-flags=0)"


def _nmcliLines(body: str) -> list[str]:
    return [ln for ln in _code(body).splitlines() if "nmcli" in ln]


def test_pskCheck_neverModifiesAProfile_neverShowsSecrets():
    """Static pin: the step contains no modify and never requests or reads a psk value."""
    code = _code(_stepBody(_deployText()))
    nmcli = _nmcliLines(_stepBody(_deployText()))

    assert nmcli, "the step has no nmcli psk-flags read"
    assert not re.search(r"nmcli[^\n]*\bcon(nection)?[ \t]+mod(ify)?\b", code)
    assert not [ln for ln in nmcli if re.search(r"(^|[ \t])(-s|--show-secrets)\b", ln)]
    assert not re.search(r"802-11-wireless-security\.psk\b(?!-)", code)
    assert not re.search(r"(^|[ \t,])psk([ \t,:]|$)", code, re.MULTILINE)
    assert "802-11-wireless-security.psk-flags" in code


def test_pskCheck_readsWithNmcliGetValues():
    reads = [ln for ln in _nmcliLines(_stepBody(_deployText())) if "connection show" in ln]
    assert reads and all(" -g " in ln for ln in reads)


@needsBash
def test_dryRun_printsThePskFlagsCheck(tmp_path: Path):
    result = _runStep(tmp_path, dryRun=True)

    assert result.returncode == 0, result.stdout
    assert "psk-flags check" in result.stdout
    assert "802-11-wireless-security.psk-flags" in result.stdout


@needsBash
def test_realRun_pskFlagsZeroEverywhere_oneAllSystemOwnedLine_noWarning(tmp_path: Path):
    profiles = [
        (UUID_HOME, "802-11-wireless", "Home", "0"),
        (UUID_ETH, "802-3-ethernet", "eth", "1"),
    ]

    result = _runStep(tmp_path, dryRun=False, profiles=profiles)

    assert result.returncode == 0, result.stdout
    assert result.stdout.count(ALL_SYSTEM_OWNED) == 1
    assert "WARNING" not in result.stdout and "WARN:" not in result.stdout
    assert UUID_ETH not in (tmp_path / "nmcli.txt").read_text(encoding="utf-8")


@needsBash
@pytest.mark.parametrize("flags", ["1", "2"])
def test_realRun_agentOwnedProfile_oneWarningNamingIt(tmp_path: Path, flags: str):
    profiles = [
        (UUID_HOME, "802-11-wireless", "Home", "0"),
        (UUID_PHONE, "802-11-wireless", "Phone", flags),
    ]

    result = _runStep(tmp_path, dryRun=False, profiles=profiles)

    assert result.returncode == 0, result.stdout
    warnings = [ln for ln in result.stdout.splitlines() if ln.startswith("WARNING:")]
    assert warnings == [
        f"WARNING: Wi-Fi profile Phone psk-flags={flags} (agent-owned): "
        "no-secrets recovery cannot reuse its key"
    ]
    assert ALL_SYSTEM_OWNED not in result.stdout


@needsBash
def test_realRun_twoAgentOwnedProfiles_oneWarningEach(tmp_path: Path):
    profiles = [
        (UUID_HOME, "802-11-wireless", "Home", "1"),
        (UUID_PHONE, "802-11-wireless", "Phone", "2"),
    ]

    result = _runStep(tmp_path, dryRun=False, profiles=profiles)

    warnings = [ln for ln in result.stdout.splitlines() if ln.startswith("WARNING:")]
    assert [w.split()[3] for w in warnings] == ["Home", "Phone"]


@needsBash
def test_realRun_everyNmcliCallIsAReadOnlyGet(tmp_path: Path):
    profiles = [(UUID_PHONE, "802-11-wireless", "Phone", "1")]

    _runStep(tmp_path, dryRun=False, profiles=profiles)

    calls = (tmp_path / "nmcli.txt").read_text(encoding="utf-8").splitlines()
    assert calls and all(c.startswith("nmcli -g ") and " connection show" in c for c in calls)
    assert not [c for c in calls if "modify" in c or "-s " in c or "--show-secrets" in c]


@needsBash
def test_realRun_nmcliAbsent_oneWarn_deployContinues(tmp_path: Path):
    result = _runStep(tmp_path, dryRun=False)

    assert result.returncode == 0, result.stdout
    assert result.stdout.count("the Wi-Fi psk-flags check could not run") == 1
    assert GATE_PASSED in result.stdout  # MOVED PIN (US-925-c): was "enabled + active"
    assert ALL_SYSTEM_OWNED not in result.stdout


@needsBash
def test_realRun_nmcliListFails_oneWarn_deployContinues(tmp_path: Path):
    result = _runStep(tmp_path, dryRun=False, profiles=[], listFails=True)

    assert result.returncode == 0, result.stdout
    assert result.stdout.count("the Wi-Fi psk-flags check could not run") == 1
    assert ALL_SYSTEM_OWNED not in result.stdout
