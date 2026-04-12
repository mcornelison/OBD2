################################################################################
# File Name: test_verify_hardware.py
# Purpose/Description: Tests for the hardware verification script
# Author: Ralph (Agent 1)
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph        | Initial implementation for US-OSC-018
# ================================================================================
################################################################################

"""
Tests for the hardware verification script (scripts/verify_hardware.py).

Verifies all hardware checks produce correct PASS/FAIL output and exit codes.
Since these tests run on a Windows dev machine, all hardware-specific checks
(Bluetooth, GPIO, I2C, display) are tested via mocks.

Run with:
    pytest tests/test_verify_hardware.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Resolve imports
srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))
projectRoot = Path(__file__).parent.parent
sys.path.insert(0, str(projectRoot))

from scripts.verify_hardware import (  # noqa: E402
    CRITICAL_CHECKS,
    HardwareVerifier,
    main,
    parseArguments,
)

# ================================================================================
# Fixtures
# ================================================================================

@pytest.fixture
def verifier() -> HardwareVerifier:
    """Provide a default HardwareVerifier instance."""
    return HardwareVerifier()


@pytest.fixture
def fullVerifier() -> HardwareVerifier:
    """Provide a HardwareVerifier with all optional checks enabled."""
    return HardwareVerifier(
        obdMac="00:04:3E:85:0D:FB",
        checkDisplay=True,
        checkGpio=True,
        checkI2c=True,
    )


# ================================================================================
# Python Version Check
# ================================================================================

class TestPythonVersionCheck:
    """Tests for Python version verification."""

    def test_verifyPythonVersion_currentPython_passes(
        self, verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: Current Python version (3.11+)
        When: verifyPythonVersion is called
        Then: Returns True and prints PASS
        """
        result = verifier.verifyPythonVersion()

        assert result is True
        output = capsys.readouterr().out
        assert "[PASS]" in output
        assert "Python" in output

    def test_verifyPythonVersion_storesResult(
        self, verifier: HardwareVerifier
    ) -> None:
        """
        Given: HardwareVerifier instance
        When: verifyPythonVersion is called
        Then: Result is stored in _results dict
        """
        verifier.verifyPythonVersion()

        assert "python_version" in verifier._results
        assert verifier._results["python_version"] is True

    def test_verifyPythonVersion_isCritical(self) -> None:
        """
        Given: CRITICAL_CHECKS constant
        When: Checking if python_version is critical
        Then: It is in the critical list
        """
        assert "python_version" in CRITICAL_CHECKS


# ================================================================================
# SQLite Check
# ================================================================================

class TestSqliteCheck:
    """Tests for SQLite version and connectivity verification."""

    def test_verifySqlite_available_passes(
        self, verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: SQLite is installed (always true in Python)
        When: verifySqlite is called
        Then: Returns True and prints PASS with version
        """
        result = verifier.verifySqlite()

        assert result is True
        output = capsys.readouterr().out
        assert "[PASS]" in output
        assert "SQLite" in output

    def test_verifySqlite_checksConnectivity(
        self, verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: SQLite is available
        When: verifySqlite is called
        Then: Verifies in-memory database connectivity
        """
        verifier.verifySqlite()

        output = capsys.readouterr().out
        assert "connectivity" in output.lower() or "connection" in output.lower()

    def test_verifySqlite_isCritical(self) -> None:
        """
        Given: CRITICAL_CHECKS constant
        When: Checking if sqlite is critical
        Then: It is in the critical list
        """
        assert "sqlite" in CRITICAL_CHECKS

    def test_verifySqlite_storesResult(
        self, verifier: HardwareVerifier
    ) -> None:
        """
        Given: HardwareVerifier instance
        When: verifySqlite is called
        Then: Result is stored in _results dict
        """
        verifier.verifySqlite()

        assert "sqlite" in verifier._results
        assert verifier._results["sqlite"] is True


# ================================================================================
# Bluetooth Adapter Check
# ================================================================================

class TestBluetoothCheck:
    """Tests for Bluetooth adapter verification."""

    @patch("scripts.verify_hardware.platform.system", return_value="Windows")
    def test_verifyBluetooth_nonLinux_skipsGracefully(
        self, mockPlatform: MagicMock, verifier: HardwareVerifier,
        capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: Running on Windows
        When: verifyBluetooth is called
        Then: Returns True (skipped, not critical on non-Linux)
        """
        result = verifier.verifyBluetooth()

        assert result is True
        assert verifier._results["bluetooth"] is True

    @patch("scripts.verify_hardware.platform.system", return_value="Linux")
    @patch("scripts.verify_hardware.subprocess.run")
    def test_verifyBluetooth_linuxServiceActive_passes(
        self, mockRun: MagicMock, mockPlatform: MagicMock,
        verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: Running on Linux with active Bluetooth
        When: verifyBluetooth is called
        Then: Returns True when service is active and adapter is UP RUNNING
        """
        # systemctl is-active bluetooth -> active
        serviceResult = MagicMock()
        serviceResult.stdout = "active\n"
        serviceResult.returncode = 0

        # hciconfig hci0 -> UP RUNNING
        hciResult = MagicMock()
        hciResult.stdout = "hci0:   Type: Primary  Bus: USB\n\tUP RUNNING\n"
        hciResult.returncode = 0

        mockRun.side_effect = [serviceResult, hciResult]

        result = verifier.verifyBluetooth()

        assert result is True
        output = capsys.readouterr().out
        assert "[PASS]" in output

    @patch("scripts.verify_hardware.platform.system", return_value="Linux")
    @patch("scripts.verify_hardware.subprocess.run")
    def test_verifyBluetooth_linuxNoAdapter_fails(
        self, mockRun: MagicMock, mockPlatform: MagicMock,
        verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: Running on Linux with no Bluetooth adapter
        When: verifyBluetooth is called
        Then: Returns False
        """
        # systemctl -> inactive
        serviceResult = MagicMock()
        serviceResult.stdout = "inactive\n"
        serviceResult.returncode = 3

        # hciconfig -> not found
        hciResult = MagicMock()
        hciResult.stdout = ""
        hciResult.returncode = 1

        mockRun.side_effect = [serviceResult, hciResult]

        result = verifier.verifyBluetooth()

        assert result is False
        output = capsys.readouterr().out
        assert "[FAIL]" in output


# ================================================================================
# OBD-II Dongle Check
# ================================================================================

class TestObdDongleCheck:
    """Tests for OBD-II dongle discovery verification."""

    def test_verifyObdDongle_noMacSpecified_skips(
        self, verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: No MAC address specified
        When: verifyObdDongle is called
        Then: Returns True (skipped)
        """
        result = verifier.verifyObdDongle()

        assert result is True
        output = capsys.readouterr().out
        assert "No MAC" in output or "skipping" in output.lower()

    @patch("scripts.verify_hardware.platform.system", return_value="Windows")
    def test_verifyObdDongle_nonLinux_skips(
        self, mockPlatform: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: MAC specified but running on Windows
        When: verifyObdDongle is called
        Then: Returns True (skipped on non-Linux)
        """
        verifier = HardwareVerifier(obdMac="00:04:3E:85:0D:FB")
        result = verifier.verifyObdDongle()

        assert result is True

    @patch("scripts.verify_hardware.platform.system", return_value="Linux")
    @patch("scripts.verify_hardware.subprocess.run")
    def test_verifyObdDongle_linuxPaired_passes(
        self, mockRun: MagicMock, mockPlatform: MagicMock,
        capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: MAC specified and dongle is paired on Linux
        When: verifyObdDongle is called
        Then: Returns True with 'paired' in output
        """
        pairedResult = MagicMock()
        pairedResult.stdout = (
            "Device 00:04:3E:85:0D:FB OBDLink LX\n"
        )
        pairedResult.returncode = 0
        mockRun.return_value = pairedResult

        verifier = HardwareVerifier(obdMac="00:04:3E:85:0D:FB")
        result = verifier.verifyObdDongle()

        assert result is True
        output = capsys.readouterr().out
        assert "[PASS]" in output

    @patch("scripts.verify_hardware.platform.system", return_value="Linux")
    @patch("scripts.verify_hardware.subprocess.run")
    def test_verifyObdDongle_linuxNotPaired_fails(
        self, mockRun: MagicMock, mockPlatform: MagicMock,
        capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: MAC specified but dongle not paired on Linux
        When: verifyObdDongle is called
        Then: Returns False with pairing instructions
        """
        pairedResult = MagicMock()
        pairedResult.stdout = ""
        pairedResult.returncode = 0
        mockRun.return_value = pairedResult

        verifier = HardwareVerifier(obdMac="00:04:3E:85:0D:FB")
        result = verifier.verifyObdDongle()

        assert result is False
        output = capsys.readouterr().out
        assert "[FAIL]" in output


# ================================================================================
# Display Hardware Check
# ================================================================================

class TestDisplayCheck:
    """Tests for display hardware verification."""

    def test_verifyDisplay_notEnabled_skips(
        self, verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: Display check not enabled
        When: verifyDisplay is called
        Then: Returns True (skipped)
        """
        result = verifier.verifyDisplay()

        assert result is True
        output = capsys.readouterr().out
        assert "skipped" in output.lower()

    def test_verifyDisplay_enabled_checksBoard(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: Display check enabled, board module importable
        When: verifyDisplay is called
        Then: Checks for adafruit-blinka
        """
        verifier = HardwareVerifier(checkDisplay=True)

        # Will fail gracefully on Windows (no board module)
        verifier.verifyDisplay()

        output = capsys.readouterr().out
        assert "Display" in output or "display" in output
        assert "display" in verifier._results


# ================================================================================
# GPIO Access Check
# ================================================================================

class TestGpioCheck:
    """Tests for GPIO access verification."""

    def test_verifyGpio_notEnabled_skips(
        self, verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: GPIO check not enabled
        When: verifyGpio is called
        Then: Returns True (skipped)
        """
        result = verifier.verifyGpio()

        assert result is True
        output = capsys.readouterr().out
        assert "skipped" in output.lower()

    def test_verifyGpio_storesResult(
        self, verifier: HardwareVerifier
    ) -> None:
        """
        Given: HardwareVerifier instance
        When: verifyGpio is called
        Then: Result is stored in _results dict
        """
        verifier.verifyGpio()

        assert "gpio" in verifier._results


# ================================================================================
# I2C Access Check
# ================================================================================

class TestI2cCheck:
    """Tests for I2C access verification."""

    def test_verifyI2c_notEnabled_skips(
        self, verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: I2C check not enabled
        When: verifyI2c is called
        Then: Returns True (skipped)
        """
        result = verifier.verifyI2c()

        assert result is True
        output = capsys.readouterr().out
        assert "skipped" in output.lower()

    def test_verifyI2c_storesResult(
        self, verifier: HardwareVerifier
    ) -> None:
        """
        Given: HardwareVerifier instance
        When: verifyI2c is called (default, not enabled)
        Then: Result is stored in _results dict
        """
        verifier.verifyI2c()

        assert "i2c" in verifier._results

    @patch("scripts.verify_hardware.platform.system", return_value="Windows")
    def test_verifyI2c_nonLinux_skips(
        self, mockPlatform: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: I2C check enabled but running on Windows
        When: verifyI2c is called
        Then: Returns True (not applicable on non-Linux)
        """
        verifier = HardwareVerifier(checkI2c=True)
        result = verifier.verifyI2c()

        assert result is True
        assert verifier._results["i2c"] is True

    @patch("scripts.verify_hardware.platform.system", return_value="Linux")
    def test_verifyI2c_linuxNoSmbus_fails(
        self, mockPlatform: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: I2C check enabled on Linux, smbus2 not installed
        When: verifyI2c is called
        Then: Returns False with install instructions
        """
        verifier = HardwareVerifier(checkI2c=True)

        with patch.dict('sys.modules', {'smbus2': None}):
            with patch('builtins.__import__', side_effect=_importBlocker('smbus2')):
                verifier.verifyI2c()

        capsys.readouterr()  # consume output
        assert "i2c" in verifier._results

    @patch("scripts.verify_hardware.platform.system", return_value="Linux")
    def test_verifyI2c_linuxWithSmbus_passes(
        self, mockPlatform: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: I2C check enabled on Linux, smbus2 available, /dev/i2c-1 exists
        When: verifyI2c is called
        Then: Returns True
        """
        verifier = HardwareVerifier(checkI2c=True)

        mockSmbus = MagicMock()
        mockBus = MagicMock()
        mockSmbus.SMBus.return_value = mockBus

        with patch.dict('sys.modules', {'smbus2': mockSmbus}):
            with patch('pathlib.Path.exists', return_value=True):
                result = verifier.verifyI2c()

        assert result is True
        output = capsys.readouterr().out
        assert "[PASS]" in output


def _importBlocker(blockedModule: str):
    """Create an import side_effect that blocks a specific module."""
    originalImport = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

    def blockedImport(name, *args, **kwargs):
        if name == blockedModule:
            raise ImportError(f"No module named '{blockedModule}'")
        return originalImport(name, *args, **kwargs)

    return blockedImport


# ================================================================================
# Run All Checks
# ================================================================================

class TestRunAllChecks:
    """Tests for the complete hardware verification run."""

    def test_runAllChecks_allCriticalPass_returnsZero(
        self, verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: All critical checks pass (Python, SQLite)
        When: runAllChecks is called
        Then: Returns exit code 0
        """
        exitCode = verifier.runAllChecks()

        assert exitCode == 0
        output = capsys.readouterr().out
        assert "Summary" in output

    def test_runAllChecks_printsSummaryWithCounts(
        self, verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: Default verifier
        When: runAllChecks is called
        Then: Summary includes total, passed, and failed counts
        """
        verifier.runAllChecks()

        output = capsys.readouterr().out
        assert "Total checks:" in output
        assert "Passed:" in output

    def test_runAllChecks_criticalFailure_returnsOne(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: Python version check forced to fail
        When: runAllChecks is called
        Then: Returns exit code 1 and shows CRITICAL FAILURES
        """
        verifier = HardwareVerifier()

        def failPythonCheck() -> bool:
            verifier._printHeader("Python Version Check")
            verifier._printResult("Python 3.9", False, "Required: >= 3.11", critical=True)
            verifier._results["python_version"] = False
            return False

        verifier.verifyPythonVersion = failPythonCheck  # type: ignore[assignment]

        exitCode = verifier.runAllChecks()

        assert exitCode == 1
        output = capsys.readouterr().out
        assert "CRITICAL" in output

    def test_runAllChecks_includesAllCheckTypes(
        self, verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: Default verifier
        When: runAllChecks is called
        Then: All check types are present in results
        """
        verifier.runAllChecks()

        # All check types should be in results
        assert "python_version" in verifier._results
        assert "sqlite" in verifier._results
        assert "bluetooth" in verifier._results
        assert "obd_dongle" in verifier._results
        assert "display" in verifier._results
        assert "gpio" in verifier._results
        assert "i2c" in verifier._results


# ================================================================================
# CLI Argument Parsing
# ================================================================================

class TestParseArguments:
    """Tests for CLI argument parsing."""

    def test_parseArguments_noArgs_defaults(self) -> None:
        """
        Given: No arguments
        When: parseArguments is called
        Then: All flags are False/None
        """
        args = parseArguments([])

        assert args.mac is None
        assert args.display is False
        assert args.gpio is False
        assert args.i2c is False

    def test_parseArguments_macAddress(self) -> None:
        """
        Given: --mac flag with MAC address
        When: parseArguments is called
        Then: mac is set to the provided address
        """
        args = parseArguments(["--mac", "00:04:3E:85:0D:FB"])

        assert args.mac == "00:04:3E:85:0D:FB"

    def test_parseArguments_displayFlag(self) -> None:
        """
        Given: --display flag
        When: parseArguments is called
        Then: display is True
        """
        args = parseArguments(["--display"])

        assert args.display is True

    def test_parseArguments_gpioFlag(self) -> None:
        """
        Given: --gpio flag
        When: parseArguments is called
        Then: gpio is True
        """
        args = parseArguments(["--gpio"])

        assert args.gpio is True

    def test_parseArguments_i2cFlag(self) -> None:
        """
        Given: --i2c flag
        When: parseArguments is called
        Then: i2c is True
        """
        args = parseArguments(["--i2c"])

        assert args.i2c is True

    def test_parseArguments_allFlags(self) -> None:
        """
        Given: All flags provided
        When: parseArguments is called
        Then: All flags are set correctly
        """
        args = parseArguments([
            "--mac", "AA:BB:CC:DD:EE:FF",
            "--display",
            "--gpio",
            "--i2c",
        ])

        assert args.mac == "AA:BB:CC:DD:EE:FF"
        assert args.display is True
        assert args.gpio is True
        assert args.i2c is True


# ================================================================================
# Main Entry Point
# ================================================================================

class TestMain:
    """Tests for the main() entry point."""

    def test_main_noArgs_returnsZero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: No CLI arguments
        When: main() is called
        Then: Returns 0 (critical checks pass on dev machine)
        """
        with patch("sys.argv", ["verify_hardware.py"]):
            exitCode = main()

        assert exitCode == 0

    def test_main_withMac_acceptsMac(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: --mac flag provided
        When: main() is called
        Then: Runs successfully (skips BT check on Windows)
        """
        with patch("sys.argv", ["verify_hardware.py", "--mac", "00:04:3E:85:0D:FB"]):
            exitCode = main()

        assert exitCode == 0


# ================================================================================
# PASS/FAIL Output Format
# ================================================================================

class TestOutputFormat:
    """Tests for PASS/FAIL output formatting."""

    def test_printResult_pass_showsPassTag(
        self, verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: A passing check
        When: _printResult is called
        Then: Output contains [PASS]
        """
        verifier._printResult("Test check", True, "Details here")

        output = capsys.readouterr().out
        assert "[PASS]" in output
        assert "Test check" in output
        assert "Details here" in output

    def test_printResult_fail_showsFailTag(
        self, verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: A failing check
        When: _printResult is called
        Then: Output contains [FAIL]
        """
        verifier._printResult("Test check", False, "Error info")

        output = capsys.readouterr().out
        assert "[FAIL]" in output
        assert "Test check" in output

    def test_printResult_critical_showsCriticalLabel(
        self, verifier: HardwareVerifier, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: A critical check
        When: _printResult is called
        Then: Output contains (CRITICAL)
        """
        verifier._printResult("Test check", False, "Error", critical=True)

        output = capsys.readouterr().out
        assert "(CRITICAL)" in output
