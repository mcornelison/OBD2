#!/usr/bin/env python3
################################################################################
# File Name: verify_hardware.py
# Purpose/Description: Verify all hardware components are working before running
#                      the full Eclipse OBD-II application on Raspberry Pi
# Author: Claude
# Creation Date: 2026-01-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-23    | Claude       | Initial implementation (US-OSC-018)
# ================================================================================
################################################################################

"""
Hardware verification script for Raspberry Pi deployment.

Verifies all hardware components are working before running the full application.
Checks Python version, SQLite, Bluetooth, OBD-II dongle, display, and GPIO.

Usage:
    python scripts/verify_hardware.py
    python scripts/verify_hardware.py --mac AA:BB:CC:DD:EE:FF
    python scripts/verify_hardware.py --display --gpio

Exit Codes:
    0 - All critical checks passed
    1 - One or more critical checks failed
"""

import argparse
import platform
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Optional


# Color codes for terminal output
class Colors:
    """ANSI color codes for terminal output."""

    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


# Minimum Python version required
MIN_PYTHON_VERSION = (3, 11)

# Critical checks that must pass for exit code 0
CRITICAL_CHECKS = ["python_version", "sqlite"]


class HardwareVerifier:
    """Verifies hardware components for Raspberry Pi deployment."""

    def __init__(
        self,
        obdMac: Optional[str] = None,
        checkDisplay: bool = False,
        checkGpio: bool = False,
    ) -> None:
        """
        Initialize the hardware verifier.

        Args:
            obdMac: Optional MAC address of OBD-II Bluetooth dongle
            checkDisplay: Whether to check display hardware
            checkGpio: Whether to check GPIO access
        """
        self._obdMac = obdMac
        self._checkDisplay = checkDisplay
        self._checkGpio = checkGpio
        self._results: dict[str, bool] = {}

    def _printHeader(self, title: str) -> None:
        """Print a formatted section header."""
        print(f"\n{Colors.BLUE}{Colors.BOLD}{'=' * 60}")
        print(f"  {title}")
        print(f"{'=' * 60}{Colors.RESET}")

    def _printResult(
        self, name: str, passed: bool, details: str = "", critical: bool = False
    ) -> None:
        """
        Print a check result with PASS/FAIL indicator.

        Args:
            name: Name of the check
            passed: Whether the check passed
            details: Additional details to display
            critical: Whether this is a critical check
        """
        if passed:
            icon = f"{Colors.GREEN}[PASS]{Colors.RESET}"
        else:
            icon = f"{Colors.RED}[FAIL]{Colors.RESET}"

        criticalMark = " (CRITICAL)" if critical else ""
        print(f"  {icon} {name}{criticalMark}")
        if details:
            print(f"         {details}")

    def verifyPythonVersion(self) -> bool:
        """
        Check that Python version is >= 3.11.

        Returns:
            True if Python version meets minimum requirement
        """
        self._printHeader("Python Version Check")

        currentVersion = sys.version_info[:2]
        passed = currentVersion >= MIN_PYTHON_VERSION

        versionStr = f"{currentVersion[0]}.{currentVersion[1]}"
        minVersionStr = f"{MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}"

        self._printResult(
            f"Python {versionStr}",
            passed,
            f"Required: >= {minVersionStr}",
            critical=True,
        )

        self._results["python_version"] = passed
        return passed

    def verifySqlite(self) -> bool:
        """
        Check SQLite version and connectivity.

        Returns:
            True if SQLite is available and connectable
        """
        self._printHeader("SQLite Check")

        passed = False
        try:
            # Check version
            sqliteVersion = sqlite3.sqlite_version
            self._printResult(
                f"SQLite {sqliteVersion}", True, "Module available", critical=True
            )

            # Check connectivity with in-memory database
            conn = sqlite3.connect(":memory:")
            cursor = conn.cursor()
            cursor.execute("SELECT sqlite_version()")
            result = cursor.fetchone()
            conn.close()

            if result:
                self._printResult(
                    "Database connectivity", True, "In-memory connection successful"
                )
                passed = True
            else:
                self._printResult("Database connectivity", False, "No result returned")

            # Check if data directory exists for file-based database
            projectRoot = Path(__file__).parent.parent
            dataDir = projectRoot / "data"
            if dataDir.exists():
                self._printResult("Data directory", True, str(dataDir))
            else:
                self._printResult(
                    "Data directory", False, f"Create: mkdir {dataDir}"
                )

        except Exception as e:
            self._printResult("SQLite", False, str(e), critical=True)

        self._results["sqlite"] = passed
        return passed

    def verifyBluetooth(self) -> bool:
        """
        Check if Bluetooth adapter is present and enabled.

        Returns:
            True if Bluetooth adapter is available
        """
        self._printHeader("Bluetooth Adapter Check")

        passed = False
        isLinux = platform.system() == "Linux"

        if not isLinux:
            self._printResult(
                "Bluetooth adapter",
                False,
                "Linux only - skipped on Windows/Mac",
            )
            self._results["bluetooth"] = True  # Not critical on non-Linux
            return True

        # Check if Bluetooth service is running
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "bluetooth"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            serviceActive = result.stdout.strip() == "active"
            self._printResult(
                "Bluetooth service",
                serviceActive,
                "systemctl status bluetooth",
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            self._printResult("Bluetooth service", False, str(e))
            serviceActive = False

        # Check if hci0 adapter exists
        try:
            result = subprocess.run(
                ["hciconfig", "hci0"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            adapterExists = result.returncode == 0
            if adapterExists and "UP RUNNING" in result.stdout:
                self._printResult("Bluetooth adapter (hci0)", True, "UP and RUNNING")
                passed = True
            elif adapterExists:
                self._printResult(
                    "Bluetooth adapter (hci0)",
                    False,
                    "Exists but not running. Try: sudo hciconfig hci0 up",
                )
            else:
                self._printResult(
                    "Bluetooth adapter (hci0)",
                    False,
                    "Not found. Check hardware connection.",
                )
        except FileNotFoundError:
            # Try alternative method using bluetoothctl
            try:
                result = subprocess.run(
                    ["bluetoothctl", "show"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if "Controller" in result.stdout:
                    self._printResult(
                        "Bluetooth adapter",
                        True,
                        "Detected via bluetoothctl",
                    )
                    passed = True
                else:
                    self._printResult(
                        "Bluetooth adapter",
                        False,
                        "Not detected. Install: sudo apt install bluetooth",
                    )
            except FileNotFoundError:
                self._printResult(
                    "Bluetooth tools",
                    False,
                    "Not installed. Install: sudo apt install bluetooth bluez",
                )
        except subprocess.TimeoutExpired:
            self._printResult("Bluetooth adapter", False, "Command timed out")

        self._results["bluetooth"] = passed
        return passed

    def verifyObdDongle(self) -> bool:
        """
        Check if OBD-II dongle is discoverable.

        Returns:
            True if OBD-II dongle is found (or MAC not specified)
        """
        self._printHeader("OBD-II Dongle Check")

        if not self._obdMac:
            self._printResult(
                "OBD-II dongle",
                True,
                "No MAC specified, skipping discovery check",
            )
            self._results["obd_dongle"] = True
            return True

        isLinux = platform.system() == "Linux"
        if not isLinux:
            self._printResult(
                "OBD-II dongle",
                False,
                "Linux only - skipped on Windows/Mac",
            )
            self._results["obd_dongle"] = True
            return True

        passed = False
        normalizedMac = self._obdMac.upper()

        # Try to find the device using hcitool
        try:
            # First try paired devices
            result = subprocess.run(
                ["bluetoothctl", "paired-devices"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if normalizedMac in result.stdout.upper():
                self._printResult(
                    f"OBD-II dongle ({normalizedMac})",
                    True,
                    "Found in paired devices",
                )
                passed = True
            else:
                # Try scanning (may require elevated privileges)
                self._printResult(
                    f"OBD-II dongle ({normalizedMac})",
                    False,
                    "Not in paired devices. Pair with: bluetoothctl pair "
                    + normalizedMac,
                )
        except FileNotFoundError:
            self._printResult(
                "OBD-II dongle",
                False,
                "bluetoothctl not found. Install: sudo apt install bluez",
            )
        except subprocess.TimeoutExpired:
            self._printResult("OBD-II dongle", False, "Discovery timed out")

        self._results["obd_dongle"] = passed
        return passed

    def verifyDisplay(self) -> bool:
        """
        Check if display hardware is available.

        Returns:
            True if display hardware is available or check is skipped
        """
        self._printHeader("Display Hardware Check")

        if not self._checkDisplay:
            self._printResult(
                "Display hardware",
                True,
                "Check skipped (use --display to enable)",
            )
            self._results["display"] = True
            return True

        passed = False

        # Check for Adafruit board module
        try:
            import board  # noqa: F401

            self._printResult(
                "adafruit-blinka (board)",
                True,
                "Hardware abstraction available",
            )
            passed = True
        except ImportError:
            self._printResult(
                "adafruit-blinka (board)",
                False,
                "Install: pip install adafruit-blinka",
            )
        except (NotImplementedError, RuntimeError) as e:
            self._printResult(
                "adafruit-blinka (board)",
                False,
                f"Not on Raspberry Pi: {e}",
            )

        # Check for ST7789 display driver
        try:
            from adafruit_rgb_display import st7789  # noqa: F401

            self._printResult(
                "ST7789 display driver",
                True,
                "Driver available",
            )
        except ImportError:
            self._printResult(
                "ST7789 display driver",
                False,
                "Install: pip install adafruit-circuitpython-rgb-display",
            )
        except (NotImplementedError, RuntimeError) as e:
            self._printResult("ST7789 display driver", False, str(e))

        # Check for Pillow
        try:
            from PIL import Image, ImageDraw  # noqa: F401

            self._printResult("Pillow (PIL)", True, "Image library available")
        except ImportError:
            self._printResult(
                "Pillow (PIL)",
                False,
                "Install: pip install Pillow",
            )
            passed = False

        self._results["display"] = passed
        return passed

    def verifyGpio(self) -> bool:
        """
        Check if GPIO access is available.

        Returns:
            True if GPIO is available or check is skipped
        """
        self._printHeader("GPIO Access Check")

        if not self._checkGpio:
            self._printResult(
                "GPIO access",
                True,
                "Check skipped (use --gpio to enable)",
            )
            self._results["gpio"] = True
            return True

        passed = False

        # Check for RPi.GPIO
        try:
            import RPi.GPIO as GPIO  # noqa: F401

            self._printResult("RPi.GPIO", True, "GPIO library available")
            passed = True
        except ImportError:
            self._printResult(
                "RPi.GPIO",
                False,
                "Install: pip install RPi.GPIO",
            )
        except RuntimeError as e:
            self._printResult("RPi.GPIO", False, f"Not on Raspberry Pi: {e}")

        # Check GPIO device files (Linux only)
        if platform.system() == "Linux":
            gpioPath = Path("/sys/class/gpio")
            if gpioPath.exists():
                self._printResult("GPIO sysfs", True, str(gpioPath))
            else:
                self._printResult(
                    "GPIO sysfs",
                    False,
                    "Not available. Check kernel configuration.",
                )

            # Check for gpiochip (modern approach)
            gpiochipPath = Path("/dev/gpiochip0")
            if gpiochipPath.exists():
                self._printResult(
                    "GPIO character device",
                    True,
                    str(gpiochipPath),
                )
            else:
                self._printResult(
                    "GPIO character device",
                    False,
                    "gpiochip0 not found",
                )

        self._results["gpio"] = passed
        return passed

    def runAllChecks(self) -> int:
        """
        Run all hardware verification checks.

        Returns:
            Exit code: 0 if all critical checks pass, 1 otherwise
        """
        print(f"\n{Colors.BOLD}{'=' * 60}")
        print("  Eclipse OBD-II Hardware Verification")
        print(f"{'=' * 60}{Colors.RESET}")

        # Run all checks
        self.verifyPythonVersion()
        self.verifySqlite()
        self.verifyBluetooth()
        self.verifyObdDongle()
        self.verifyDisplay()
        self.verifyGpio()

        # Print summary
        self._printHeader("Summary")

        totalChecks = len(self._results)
        passedChecks = sum(1 for v in self._results.values() if v)
        failedChecks = totalChecks - passedChecks

        print(f"  Total checks: {totalChecks}")
        print(f"  {Colors.GREEN}Passed: {passedChecks}{Colors.RESET}")
        if failedChecks > 0:
            print(f"  {Colors.RED}Failed: {failedChecks}{Colors.RESET}")

        # Check critical failures
        criticalFailed = [
            name for name in CRITICAL_CHECKS if not self._results.get(name, False)
        ]

        if criticalFailed:
            print(
                f"\n  {Colors.RED}{Colors.BOLD}CRITICAL FAILURES: "
                f"{', '.join(criticalFailed)}{Colors.RESET}"
            )
            print(f"  {Colors.RED}Fix critical issues before running application.")
            print(f"{Colors.RESET}")
            return 1

        if failedChecks > 0:
            print(
                f"\n  {Colors.YELLOW}Some non-critical checks failed. "
                f"Application may run with limited functionality.{Colors.RESET}"
            )
        else:
            print(
                f"\n  {Colors.GREEN}{Colors.BOLD}All checks passed! "
                f"Hardware is ready.{Colors.RESET}"
            )

        print()
        return 0


def parseArguments(args: Optional[list[str]] = None) -> argparse.Namespace:
    """
    Parse command line arguments.

    Args:
        args: Command line arguments (defaults to sys.argv[1:])

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Verify Raspberry Pi hardware for Eclipse OBD-II application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/verify_hardware.py
    python scripts/verify_hardware.py --mac AA:BB:CC:DD:EE:FF
    python scripts/verify_hardware.py --display --gpio
    python scripts/verify_hardware.py --mac AA:BB:CC:DD:EE:FF --display --gpio

Exit Codes:
    0 - All critical checks passed
    1 - One or more critical checks failed
        """,
    )

    parser.add_argument(
        "--mac",
        type=str,
        help="MAC address of OBD-II Bluetooth dongle to verify (e.g., AA:BB:CC:DD:EE:FF)",
    )

    parser.add_argument(
        "--display",
        action="store_true",
        help="Check display hardware (Adafruit ST7789)",
    )

    parser.add_argument(
        "--gpio",
        action="store_true",
        help="Check GPIO access (for power monitoring)",
    )

    return parser.parse_args(args)


def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code: 0 if all critical checks pass, 1 otherwise
    """
    args = parseArguments()

    verifier = HardwareVerifier(
        obdMac=args.mac,
        checkDisplay=args.display,
        checkGpio=args.gpio,
    )

    return verifier.runAllChecks()


if __name__ == "__main__":
    sys.exit(main())
