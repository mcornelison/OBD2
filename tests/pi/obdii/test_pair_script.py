################################################################################
# File Name: test_pair_script.py
# Purpose/Description: Smoke tests for scripts/pair_obdlink.sh (US-196)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Ralph Agent  | Initial (US-196 — pair script smoke + dry-run)
# ================================================================================
################################################################################

"""
Smoke tests for ``scripts/pair_obdlink.sh``.

These tests exercise the surface properties the repo can verify on
Windows without a real Bluetooth dongle:

- The script exists and is executable (mode bit relevant on Linux; on
  Windows git-bash we just assert the repo file is present).
- The script is shellcheck-clean (only if shellcheck is on PATH; skipped
  otherwise so the test suite stays green on vanilla Windows).
- The script accepts ``--help`` and ``--dry-run`` without invoking
  ``bluetoothctl`` or any real BT stack.
- The MAC comes from argv / environment, never hardcoded (Invariant from
  B-044 / US-196).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "pair_obdlink.sh"


# ================================================================================
# File presence + surface
# ================================================================================


class TestScriptFile:

    def test_script_exists(self) -> None:
        assert SCRIPT_PATH.is_file(), (
            f"Expected pair script at {SCRIPT_PATH} — US-196 requires it be committed."
        )

    def test_script_has_bash_shebang(self) -> None:
        first = SCRIPT_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        assert first.startswith("#!"), "pair_obdlink.sh must have a shebang"
        assert "bash" in first or "sh" in first, (
            "pair_obdlink.sh should invoke via bash (outer wrapper)"
        )

    def test_script_does_not_hardcode_mac(self) -> None:
        """B-044 invariant — MAC comes from argv / env, never baked in."""
        body = SCRIPT_PATH.read_text(encoding="utf-8", errors="replace")
        # The real MAC from Session 23 must only appear in a comment/docstring,
        # not as a literal assignment or positional arg default.
        ciolessMac = "00:04:3E:85:0D:FB"
        for lineNumber, line in enumerate(body.splitlines(), start=1):
            if ciolessMac in line:
                # Allow it inside comments ONLY.
                stripped = line.lstrip()
                assert stripped.startswith("#"), (
                    f"pair_obdlink.sh line {lineNumber}: "
                    f"MAC must not be a literal — move to comment or remove: {line!r}"
                )

    def test_script_references_bluetoothctl_and_pexpect(self) -> None:
        """Design marker: script drives bluetoothctl via pexpect (see MEMORY.md)."""
        body = SCRIPT_PATH.read_text(encoding="utf-8", errors="replace")
        assert "bluetoothctl" in body, "pair script must drive bluetoothctl"
        assert "pexpect" in body, "pair script must use pexpect for passkey confirm"


# ================================================================================
# --help / --dry-run
# ================================================================================


def _canRunBashScripts() -> bool:
    """Best-effort: skip invocation tests on systems that can't run bash .sh files."""
    return shutil.which("bash") is not None


@pytest.mark.skipif(not _canRunBashScripts(), reason="bash not on PATH")
class TestScriptFlags:

    def test_help_flag_exits_zero_and_prints_usage(self) -> None:
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"--help should exit 0, got {result.returncode}. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        combined = (result.stdout + result.stderr).lower()
        assert "usage" in combined or "pair_obdlink" in combined

    def test_dry_run_does_not_invoke_bluetoothctl(self) -> None:
        """
        --dry-run must print what it would do without touching the BT stack.

        Strategy: prepend a fake `bluetoothctl` shim that WRITES a sentinel file
        to $PWD if called. Assert the sentinel does not appear after a dry run.
        """
        # Create a PATH override with a fake bluetoothctl that would leave evidence.
        import tempfile

        with tempfile.TemporaryDirectory() as tmpRoot:
            binDir = Path(tmpRoot) / "bin"
            binDir.mkdir()
            sentinel = Path(tmpRoot) / "bluetoothctl_was_called"
            shimPath = binDir / "bluetoothctl"
            shimBody = (
                "#!/usr/bin/env bash\n"
                f'echo called > "{sentinel}"\n'
                "exit 0\n"
            )
            shimPath.write_text(shimBody, encoding="utf-8")
            shimPath.chmod(0o755)

            env = dict(os.environ)
            env["PATH"] = f"{binDir}{os.pathsep}{env['PATH']}"

            result = subprocess.run(
                ["bash", str(SCRIPT_PATH), "--dry-run", "AA:BB:CC:DD:EE:FF"],
                capture_output=True,
                text=True,
                timeout=10,
                env=env,
            )

            assert result.returncode == 0, (
                f"--dry-run should exit 0, got rc={result.returncode}. "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            assert not sentinel.exists(), (
                "--dry-run invoked bluetoothctl; it must be preview-only"
            )

    def test_missing_mac_exits_nonzero(self) -> None:
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0, (
            "pair_obdlink.sh with no args should fail with usage"
        )

    def test_invalid_mac_exits_nonzero(self) -> None:
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "--dry-run", "not-a-mac"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0, (
            "pair_obdlink.sh must validate MAC format before doing anything"
        )


# ================================================================================
# shellcheck (optional — only if on PATH)
# ================================================================================


@pytest.mark.skipif(
    shutil.which("shellcheck") is None,
    reason="shellcheck not installed on this host",
)
def test_shellcheck_clean() -> None:
    result = subprocess.run(
        ["shellcheck", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"shellcheck surfaced issues:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


# ================================================================================
# verify_bt_pair.sh — sibling script
# ================================================================================


VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify_bt_pair.sh"


class TestVerifyScript:

    def test_verify_script_exists(self) -> None:
        assert VERIFY_SCRIPT.is_file(), (
            f"Expected verify script at {VERIFY_SCRIPT} — US-196 requires it."
        )

    @pytest.mark.skipif(not _canRunBashScripts(), reason="bash not on PATH")
    def test_verify_help_exits_zero(self) -> None:
        result = subprocess.run(
            ["bash", str(VERIFY_SCRIPT), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"verify_bt_pair.sh --help should exit 0, got rc={result.returncode}. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )


# ================================================================================
# systemd unit file — presence + sanity
# ================================================================================


SERVICE_UNIT = REPO_ROOT / "deploy" / "rfcomm-bind.service"


class TestRfcommBindSystemdUnit:

    def test_unit_file_exists(self) -> None:
        assert SERVICE_UNIT.is_file(), (
            f"Expected systemd unit at {SERVICE_UNIT} — US-196 requires reboot-survive."
        )

    def test_unit_has_required_sections(self) -> None:
        body = SERVICE_UNIT.read_text(encoding="utf-8", errors="replace")
        assert "[Unit]" in body, "unit file must declare [Unit]"
        assert "[Service]" in body, "unit file must declare [Service]"
        assert "[Install]" in body, "unit file must declare [Install]"

    def test_unit_starts_after_bluetooth(self) -> None:
        body = SERVICE_UNIT.read_text(encoding="utf-8", errors="replace")
        # stopCondition #1: must be ordered after bluetooth.service/.target.
        assert "bluetooth" in body, (
            "rfcomm-bind.service must order After=/Wants= bluetooth to avoid "
            "bindings racing the BT stack on boot (US-196 stopCondition #1)."
        )

    def test_unit_does_not_hardcode_mac(self) -> None:
        """Unit file should pull MAC from a sourced env file / script, not literal."""
        body = SERVICE_UNIT.read_text(encoding="utf-8", errors="replace")
        literalMac = "00:04:3E:85:0D:FB"
        for lineNumber, line in enumerate(body.splitlines(), start=1):
            if literalMac in line and not line.lstrip().startswith("#"):
                pytest.fail(
                    f"rfcomm-bind.service line {lineNumber}: MAC must not be a "
                    f"literal (B-044) — source from connect_obdlink.sh + env: {line!r}"
                )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
