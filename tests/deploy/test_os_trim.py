################################################################################
# File Name: test_os_trim.py
# Purpose/Description: Desk tests for the US-866 reversible OS-trim manifest
#                      (deploy/os-trim.manifest) and its applier
#                      (deploy/os-trim.sh). Drives the script against a fake
#                      systemctl recorder and a temp root, so no Pi, no ssh and
#                      no real systemd are touched.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex          | Initial implementation (Sprint 101 US-866)
# ================================================================================
################################################################################

"""Desk tests for deploy/os-trim.manifest + deploy/os-trim.sh (US-866).

Three halves:

* The MANIFEST: exactly Atlas's 13 entries (pm/inbox/2026-10-14-from-atlas-RULED-
  S101-OS-designs-...), each with unit, a valid action, reason and evidence; no
  entry shares a name with the NEVER list; no entry is a dependency of any
  deploy/*.service.
* The SCRIPT, behaviourally: apply/revert/--dry-run against a fake systemctl that
  records every call and keeps per-unit state, including Atlas G3's pre-state
  file (first apply records, later applies never overwrite, revert restores the
  recorded state then deletes it; no state file -> fixed inverse + one WARN).
* FAIL LOUD: a missing or unparseable manifest, or an absent state dir, exits
  non-zero with one ERROR line naming the path and never calls systemctl.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST = REPO_ROOT / "deploy" / "os-trim.manifest"
SCRIPT = REPO_ROOT / "deploy" / "os-trim.sh"
DEPLOY_DIR = REPO_ROOT / "deploy"

VALID_ACTIONS = {"mask", "disable", "flagfile"}

# Atlas's list, verbatim (US-866 AC1). unit -> action.
EXPECTED_ENTRIES = {
    "cloud-init": "flagfile",
    "cups.service": "mask",
    "cups.socket": "mask",
    "cups.path": "mask",
    "cups-browsed.service": "mask",
    "NetworkManager-wait-online.service": "disable",
    "nfs-client.target": "disable",
    "apt-daily.timer": "mask",
    "apt-daily-upgrade.timer": "mask",
    "dpkg-db-backup.timer": "mask",
    "udisks2.service": "mask",
    "ModemManager.service": "mask",
    "e2scrub_reap.service": "mask",
}
CLOUD_INIT_FLAG = "/etc/cloud/cloud-init.disabled"

# Atlas's MUST-NOT-GO list (US-866 AC2).
EXPECTED_NEVER = {
    "bluetooth",
    "NetworkManager",
    "dbus",
    "polkit",
    "lightdm",
    "accounts-daemon",
    "avahi-daemon",
    "rpi-eeprom-update",
    "netplan",
    "systemd-timesyncd",
    "plymouth",
    "systemd-journald",
}

UNIT_SUFFIXES = (".service", ".socket", ".timer", ".path", ".target")
DEPENDENCY_KEYS = ("Wants", "Requires", "After", "BindsTo")

# A stateful systemctl stand-in. Each unit's enablement lives in
# $FAKE_SYSTEMCTL_DIR/units/<unit>; a mask remembers the state underneath it so
# an unmask lands back where real systemd would (the [Install] symlinks survive
# a mask). Every invocation is appended to calls.log.
FAKE_SYSTEMCTL = r"""#!/usr/bin/env bash
dir="$FAKE_SYSTEMCTL_DIR"
echo "$*" >> "$dir/calls.log"
cmd="$1"; unit="$2"
f="$dir/units/$unit"
case "$cmd" in
    is-enabled)
        if [ ! -f "$f" ]; then echo "not-found"; exit 1; fi
        s="$(cat "$f")"
        echo "$s"
        case "$s" in enabled|static|indirect|alias|generated) exit 0 ;; *) exit 1 ;; esac
        ;;
    mask)
        [ -f "$f" ] && [ "$(cat "$f")" != masked ] && cp "$f" "$f.under"
        echo masked > "$f"
        ;;
    unmask)
        if [ "$(cat "$f" 2>/dev/null)" = masked ]; then
            if [ -f "$f.under" ]; then mv "$f.under" "$f"; else echo disabled > "$f"; fi
        fi
        ;;
    enable)
        if [ "$(cat "$f" 2>/dev/null)" = masked ]; then
            echo "Failed to enable unit: Unit file $unit is masked." >&2; exit 1
        fi
        echo enabled > "$f"
        ;;
    disable)
        if [ "$(cat "$f" 2>/dev/null)" = masked ]; then echo disabled > "$f.under"
        else echo disabled > "$f"; fi
        ;;
    *) echo "fake systemctl: unsupported '$cmd'" >&2; exit 64 ;;
esac
"""


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


requiresBash = pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")


def _baseName(unit: str) -> str:
    """Strip a systemd unit-type suffix: 'cups.service' -> 'cups'."""
    for suffix in UNIT_SUFFIXES:
        if unit.endswith(suffix):
            return unit[: -len(suffix)]
    return unit


def _parseManifest(text: str) -> list[dict[str, str]]:
    """Parse the manifest the way os-trim.sh does: 4 '|' fields, # comments."""
    entries = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = [f.strip() for f in line.split("|")]
        assert len(fields) == 4, f"expected 4 fields, got {len(fields)}: {raw!r}"
        unit, action, reason, evidence = fields
        actionWords = action.split()
        entries.append(
            {
                "unit": unit,
                "action": actionWords[0] if actionWords else "",
                "arg": " ".join(actionWords[1:]),
                "reason": reason,
                "evidence": evidence,
            }
        )
    return entries


def _manifestEntries() -> list[dict[str, str]]:
    return _parseManifest(MANIFEST.read_text(encoding="utf-8"))


def _scriptNeverList() -> set[str]:
    match = re.search(r'^NEVER_UNITS="([^"]+)"', SCRIPT.read_text(encoding="utf-8"), re.M)
    assert match, "os-trim.sh must declare NEVER_UNITS=\"...\""
    return set(match.group(1).split())


# --------------------------------------------------------------------------
# Rig
# --------------------------------------------------------------------------


class Rig:
    """A temp Pi: fake systemctl, a root for flag files, a state dir."""

    def __init__(self, base: Path, manifest: Path = MANIFEST) -> None:
        self.base = base
        self.fakeDir = base / "fake"
        (self.fakeDir / "units").mkdir(parents=True)
        self.systemctl = base / "systemctl"
        self.systemctl.write_text(FAKE_SYSTEMCTL, encoding="utf-8", newline="\n")
        self.systemctl.chmod(0o755)
        self.root = base / "root"
        (self.root / "etc" / "cloud").mkdir(parents=True)
        self.stateDir = base / "var-lib-eclipse-obd"
        self.stateDir.mkdir()
        self.manifest = manifest
        for unit, action in EXPECTED_ENTRIES.items():
            if action != "flagfile":
                self.setState(unit, "enabled")

    @property
    def stateFile(self) -> Path:
        return self.stateDir / "os-trim.state"

    @property
    def flagFile(self) -> Path:
        return self.root / CLOUD_INIT_FLAG.lstrip("/")

    def setState(self, unit: str, state: str) -> None:
        (self.fakeDir / "units" / unit).write_text(state + "\n", encoding="utf-8", newline="\n")

    def state(self, unit: str) -> str:
        return (self.fakeDir / "units" / unit).read_text(encoding="utf-8").strip()

    def calls(self) -> list[str]:
        log = self.fakeDir / "calls.log"
        if not log.exists():
            return []
        return [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln]

    def clearCalls(self) -> None:
        log = self.fakeDir / "calls.log"
        if log.exists():
            log.unlink()

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.update(
            {
                "SYSTEMCTL_BIN": self.systemctl.as_posix(),
                "FAKE_SYSTEMCTL_DIR": self.fakeDir.as_posix(),
                "OS_TRIM_MANIFEST": self.manifest.as_posix(),
                "OS_TRIM_STATE_DIR": self.stateDir.as_posix(),
                "OS_TRIM_ROOT": self.root.as_posix(),
            }
        )
        return subprocess.run(
            ["bash", SCRIPT.as_posix(), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=120,
        )


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def _mutating(calls: list[str]) -> list[str]:
    return [c for c in calls if not c.startswith("is-enabled")]


def _errorLines(stderr: str) -> list[str]:
    return [ln for ln in stderr.splitlines() if ln.startswith("ERROR")]


def _warnLines(stderr: str) -> list[str]:
    return [ln for ln in stderr.splitlines() if ln.startswith("WARN")]


# --------------------------------------------------------------------------
# The manifest
# --------------------------------------------------------------------------


def test_manifest_hasExactlyAtlasThirteenEntries():
    """
    Given: deploy/os-trim.manifest
    When: it is parsed
    Then: 13 entries, exactly Atlas's units and actions, each with a reason and evidence
    """
    entries = _manifestEntries()
    assert len(entries) == 13, [e["unit"] for e in entries]
    assert {e["unit"]: e["action"] for e in entries} == EXPECTED_ENTRIES
    for entry in entries:
        assert entry["action"] in VALID_ACTIONS, entry
        assert entry["reason"], f"{entry['unit']} has no reason"
        assert entry["evidence"], f"{entry['unit']} has no evidence"


def test_manifest_cloudInitFlagFileIsTheDocumentedOffSwitch():
    """The cloud-init entry names /etc/cloud/cloud-init.disabled; mask/disable carry no arg."""
    for entry in _manifestEntries():
        if entry["action"] == "flagfile":
            assert entry["arg"] == CLOUD_INIT_FLAG, entry
        else:
            assert entry["arg"] == "", entry


def test_neverList_isAtlasListAndSharesNoEntryWithManifest():
    """
    Given: the NEVER list declared in os-trim.sh
    When: compared with Atlas's MUST-NOT-GO list and the manifest
    Then: it is exactly Atlas's list, and no manifest unit shares a name with it
    """
    never = _scriptNeverList()
    assert never == EXPECTED_NEVER
    manifestNames = {e["unit"] for e in _manifestEntries()}
    manifestBases = {_baseName(u) for u in manifestNames}
    assert not (manifestNames | manifestBases) & never


def test_manifest_noUnitIsADependencyOfAnyDeployService():
    """No manifest unit is named in Wants=/Requires=/After=/BindsTo= of deploy/*.service."""
    entries = _manifestEntries()
    offenders = []
    services = sorted(DEPLOY_DIR.glob("*.service"))
    assert services, "no deploy/*.service found -- the scan would be vacuous"
    for service in services:
        for raw in service.read_text(encoding="utf-8").splitlines():
            key, sep, value = raw.strip().partition("=")
            if not sep or key.strip() not in DEPENDENCY_KEYS:
                continue
            for token in value.split():
                tokenBase = _baseName(token)
                for entry in entries:
                    unit = entry["unit"]
                    if token == unit or tokenBase == _baseName(unit):
                        offenders.append(f"{service.name}: {raw.strip()}")
                    elif entry["action"] == "flagfile" and tokenBase.startswith(unit):
                        offenders.append(f"{service.name}: {raw.strip()}")
    assert not offenders, offenders


# --------------------------------------------------------------------------
# --dry-run
# --------------------------------------------------------------------------


@requiresBash
@pytest.mark.parametrize("mode", ["apply", "revert"])
def test_dryRun_printsOneLinePerEntryAndChangesNothing(rig: Rig, mode: str):
    """
    Given: a Pi with every manifest unit enabled and no state file
    When: os-trim.sh <mode> --dry-run
    Then: exactly 13 stdout lines (one per entry), exit 0, no systemctl call,
          no state file, no flag file
    """
    result = rig.run(mode, "--dry-run")
    assert result.returncode == 0, result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 13, result.stdout
    named = [re.match(rf"^DRY-RUN {mode} (\S+): ", ln) for ln in lines]
    assert all(named), result.stdout
    assert sorted(m.group(1) for m in named if m) == sorted(EXPECTED_ENTRIES)
    assert rig.calls() == []
    assert not rig.stateFile.exists()
    assert not rig.flagFile.exists()


# --------------------------------------------------------------------------
# apply / revert
# --------------------------------------------------------------------------


@requiresBash
def test_applyThenRevert_everyActionIsInverted(rig: Rig):
    """
    Given: every manifest unit enabled, no flag file
    When: apply, then revert
    Then: every mask has an unmask, every disable an enable, the flag file is
          created then deleted, and every unit is back to enabled
    """
    applied = rig.run("apply")
    assert applied.returncode == 0, applied.stderr
    applyCalls = _mutating(rig.calls())
    assert rig.flagFile.exists()
    assert rig.stateFile.exists()
    for unit, action in EXPECTED_ENTRIES.items():
        if action == "mask":
            assert f"mask {unit}" in applyCalls
            assert rig.state(unit) == "masked"
        elif action == "disable":
            assert f"disable {unit}" in applyCalls
            assert rig.state(unit) == "disabled"

    rig.clearCalls()
    reverted = rig.run("revert")
    assert reverted.returncode == 0, reverted.stderr
    revertCalls = _mutating(rig.calls())
    for unit, action in EXPECTED_ENTRIES.items():
        if action == "mask":
            assert f"unmask {unit}" in revertCalls
        elif action == "disable":
            assert f"enable {unit}" in revertCalls
        if action != "flagfile":
            assert rig.state(unit) == "enabled", unit
    assert not rig.flagFile.exists()
    assert not rig.stateFile.exists()
    assert _warnLines(reverted.stderr) == []


@requiresBash
def test_apply_isIdempotent_secondApplyChangesNothing(rig: Rig):
    """A second apply issues no mask/disable and never rewrites the state file."""
    assert rig.run("apply").returncode == 0
    recorded = rig.stateFile.read_bytes()
    rig.clearCalls()
    again = rig.run("apply")
    assert again.returncode == 0, again.stderr
    assert _mutating(rig.calls()) == []
    assert rig.stateFile.read_bytes() == recorded


@requiresBash
def test_preDisabledUnit_staysDisabledThroughApplyApplyRevert(rig: Rig):
    """
    Given: one disable entry and one mask entry already disabled before the first apply
    When: apply, apply again, revert
    Then: those units are still disabled; every other entry is back to
          enabled/unmasked; the state file is deleted (Atlas G3)
    """
    preDisabled = {"NetworkManager-wait-online.service", "udisks2.service"}
    for unit in preDisabled:
        rig.setState(unit, "disabled")

    assert rig.run("apply").returncode == 0
    firstState = rig.stateFile.read_text(encoding="utf-8")
    assert rig.run("apply").returncode == 0
    assert rig.stateFile.read_text(encoding="utf-8") == firstState
    reverted = rig.run("revert")
    assert reverted.returncode == 0, reverted.stderr

    for unit, action in EXPECTED_ENTRIES.items():
        if action == "flagfile":
            continue
        expected = "disabled" if unit in preDisabled else "enabled"
        assert rig.state(unit) == expected, unit
    assert "enable NetworkManager-wait-online.service" not in rig.calls()
    assert not rig.flagFile.exists()
    assert not rig.stateFile.exists()


@requiresBash
def test_preExistingFlagFile_survivesRevert(rig: Rig):
    """A flag file present before the first apply is recorded and left in place by revert."""
    rig.flagFile.write_text("", encoding="utf-8")
    assert rig.run("apply").returncode == 0
    assert rig.run("revert").returncode == 0
    assert rig.flagFile.exists()


@requiresBash
def test_revertWithoutStateFile_appliesFixedInverseWithOneWarn(rig: Rig):
    """
    Given: a trimmed Pi whose state file is gone
    When: revert
    Then: the fixed inverse (unmask / enable / delete flag file) and exactly one WARN
    """
    assert rig.run("apply").returncode == 0
    rig.stateFile.unlink()
    rig.clearCalls()
    reverted = rig.run("revert")
    assert reverted.returncode == 0, reverted.stderr
    assert len(_warnLines(reverted.stderr)) == 1, reverted.stderr
    calls = _mutating(rig.calls())
    for unit, action in EXPECTED_ENTRIES.items():
        if action == "mask":
            assert f"unmask {unit}" in calls
        elif action == "disable":
            assert f"enable {unit}" in calls
    assert not rig.flagFile.exists()


def test_stateFile_isWrittenViaTempThenRename():
    """The pre-state file is written to a temp file in the same dir, then renamed."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert re.search(r'tmp="\$\{?STATE_FILE\}?\.tmp', text) or "mktemp" in text
    assert re.search(r'\bmv\b[^\n]*"\$\{?STATE_FILE\}?"', text), "state file must be installed by mv"


# --------------------------------------------------------------------------
# FAIL LOUD
# --------------------------------------------------------------------------


@requiresBash
@pytest.mark.parametrize("args", [("apply",), ("revert",), ("apply", "--dry-run")])
def test_missingManifest_failsLoudWithoutCallingSystemctl(tmp_path: Path, args: tuple[str, ...]):
    """
    Given: no manifest at the configured path
    When: os-trim.sh runs in any mode
    Then: non-zero exit, exactly one ERROR naming the path, no systemctl call
    """
    missing = tmp_path / "nope" / "os-trim.manifest"
    rig = Rig(tmp_path, manifest=missing)
    result = rig.run(*args)
    assert result.returncode != 0
    errors = _errorLines(result.stderr)
    assert len(errors) == 1, result.stderr
    assert missing.as_posix() in errors[0]
    assert rig.calls() == []


@requiresBash
@pytest.mark.parametrize(
    "body",
    [
        "cups.service | purge | reason | evidence\n",
        "cups.service | mask | reason\n",
        "cups.service | mask |  | evidence\n",
        "cloud-init | flagfile | reason | evidence\n",
        "# only comments\n\n",
        "bluetooth.service | mask | reason | evidence\n",
    ],
    ids=["bad-action", "three-fields", "empty-reason", "flagfile-no-path", "empty", "never-unit"],
)
def test_unparseableManifest_failsLoudWithoutCallingSystemctl(tmp_path: Path, body: str):
    """An unparseable manifest is an ERROR naming its path -- never 'nothing to trim'."""
    bad = tmp_path / "os-trim.manifest"
    bad.write_text(body, encoding="utf-8", newline="\n")
    rig = Rig(tmp_path, manifest=bad)
    result = rig.run("apply")
    assert result.returncode != 0
    errors = _errorLines(result.stderr)
    assert len(errors) == 1, result.stderr
    assert bad.as_posix() in errors[0]
    assert rig.calls() == []


@requiresBash
@pytest.mark.parametrize("mode", ["apply", "revert"])
def test_absentStateDir_failsLoudAndNeverCreatesIt(rig: Rig, mode: str):
    """
    Given: /var/lib/eclipse-obd absent (the deploy, US-667, owns it)
    When: apply or revert
    Then: non-zero, one ERROR naming the dir, no systemctl call, the dir is not created
    """
    rig.stateDir.rmdir()
    result = rig.run(mode)
    assert result.returncode != 0
    errors = _errorLines(result.stderr)
    assert len(errors) == 1, result.stderr
    assert rig.stateDir.as_posix() in errors[0]
    assert rig.calls() == []
    assert not rig.stateDir.exists()


@requiresBash
@pytest.mark.parametrize("args", [(), ("bogus",), ("apply", "--force")])
def test_badArguments_exitNonZero(rig: Rig, args: tuple[str, ...]):
    """Usage errors exit non-zero and touch nothing."""
    result = rig.run(*args)
    assert result.returncode != 0
    assert rig.calls() == []


def test_script_defaultsToThePiPaths():
    """Production defaults: manifest beside the script, state in /var/lib/eclipse-obd."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'OS_TRIM_STATE_DIR:-/var/lib/eclipse-obd}' in text
    assert "os-trim.state" in text
    assert re.search(r'OS_TRIM_MANIFEST:-\$\{?SCRIPT_DIR\}?/os-trim\.manifest', text)
    assert 'SYSTEMCTL_BIN:-systemctl}' in text
