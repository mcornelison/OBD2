################################################################################
# File Name: test_platform_utils.py
# Purpose/Description: Tests for platform detection utilities
# Author: Ralph Agent
# Creation Date: 2026-01-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-25    | Ralph Agent  | Initial implementation for US-RPI-003
# ================================================================================
################################################################################

"""
Tests for the platform_utils module.

Tests platform detection functionality for Raspberry Pi and other systems.

Run with:
    pytest tests/test_platform_utils.py -v
"""

import platform
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, mock_open, patch

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from hardware.platform_utils import (
    isRaspberryPi,
    getPlatformInfo,
)


class TestIsRaspberryPi:
    """Tests for isRaspberryPi() function."""

    # =========================================================================
    # Raspberry Pi Detection Tests
    # =========================================================================

    def test_isRaspberryPi_linuxWithRaspberryInModel_returnsTrue(self):
        """
        Given: Linux system with 'Raspberry Pi' in /proc/device-tree/model
        When: isRaspberryPi() is called
        Then: Returns True
        """
        # Arrange
        mockModelContent = "Raspberry Pi 5 Model B Rev 1.0\x00"

        with patch('platform.system', return_value='Linux'):
            with patch('builtins.open', mock_open(read_data=mockModelContent)):
                with patch('os.path.exists', return_value=True):
                    # Act
                    result = isRaspberryPi()

                    # Assert
                    assert result is True

    def test_isRaspberryPi_linuxWithRaspberryPi4_returnsTrue(self):
        """
        Given: Linux system with 'Raspberry Pi 4' in model file
        When: isRaspberryPi() is called
        Then: Returns True
        """
        # Arrange
        mockModelContent = "Raspberry Pi 4 Model B Rev 1.4\x00"

        with patch('platform.system', return_value='Linux'):
            with patch('builtins.open', mock_open(read_data=mockModelContent)):
                with patch('os.path.exists', return_value=True):
                    # Act
                    result = isRaspberryPi()

                    # Assert
                    assert result is True

    def test_isRaspberryPi_linuxNonPi_returnsFalse(self):
        """
        Given: Linux system without Raspberry Pi hardware
        When: isRaspberryPi() is called
        Then: Returns False
        """
        # Arrange
        mockModelContent = "Generic ARM Board\x00"

        with patch('platform.system', return_value='Linux'):
            with patch('builtins.open', mock_open(read_data=mockModelContent)):
                with patch('os.path.exists', return_value=True):
                    # Act
                    result = isRaspberryPi()

                    # Assert
                    assert result is False

    def test_isRaspberryPi_windowsSystem_returnsFalse(self):
        """
        Given: Windows operating system
        When: isRaspberryPi() is called
        Then: Returns False (graceful fallback)
        """
        # Arrange
        with patch('platform.system', return_value='Windows'):
            # Act
            result = isRaspberryPi()

            # Assert
            assert result is False

    def test_isRaspberryPi_macosSystem_returnsFalse(self):
        """
        Given: macOS operating system
        When: isRaspberryPi() is called
        Then: Returns False (graceful fallback)
        """
        # Arrange
        with patch('platform.system', return_value='Darwin'):
            # Act
            result = isRaspberryPi()

            # Assert
            assert result is False

    def test_isRaspberryPi_modelFileNotExists_returnsFalse(self):
        """
        Given: Linux system where model file does not exist
        When: isRaspberryPi() is called
        Then: Returns False
        """
        # Arrange
        with patch('platform.system', return_value='Linux'):
            with patch('os.path.exists', return_value=False):
                # Act
                result = isRaspberryPi()

                # Assert
                assert result is False

    def test_isRaspberryPi_fileReadError_returnsFalse(self):
        """
        Given: Linux system where model file cannot be read
        When: isRaspberryPi() is called
        Then: Returns False (graceful fallback)
        """
        # Arrange
        with patch('platform.system', return_value='Linux'):
            with patch('os.path.exists', return_value=True):
                with patch('builtins.open', side_effect=IOError("Permission denied")):
                    # Act
                    result = isRaspberryPi()

                    # Assert
                    assert result is False

    def test_isRaspberryPi_unexpectedException_returnsFalse(self):
        """
        Given: An unexpected exception during detection
        When: isRaspberryPi() is called
        Then: Returns False (graceful fallback, no crash)
        """
        # Arrange
        with patch('platform.system', side_effect=Exception("Unexpected error")):
            # Act
            result = isRaspberryPi()

            # Assert
            assert result is False


class TestGetPlatformInfo:
    """Tests for getPlatformInfo() function."""

    # =========================================================================
    # Platform Info Tests
    # =========================================================================

    def test_getPlatformInfo_windowsSystem_returnsWindowsInfo(self):
        """
        Given: Windows operating system
        When: getPlatformInfo() is called
        Then: Returns dict with Windows info
        """
        # Arrange
        with patch('platform.system', return_value='Windows'):
            with patch('platform.machine', return_value='AMD64'):
                with patch('platform.release', return_value='10'):
                    # Act
                    result = getPlatformInfo()

                    # Assert
                    assert result['os'] == 'Windows'
                    assert result['architecture'] == 'AMD64'
                    assert result['model'] is None
                    assert result['isRaspberryPi'] is False

    def test_getPlatformInfo_linuxNonPi_returnsLinuxInfo(self):
        """
        Given: Linux system that is not Raspberry Pi
        When: getPlatformInfo() is called
        Then: Returns dict with Linux info
        """
        # Arrange
        with patch('platform.system', return_value='Linux'):
            with patch('platform.machine', return_value='x86_64'):
                with patch('os.path.exists', return_value=False):
                    # Act
                    result = getPlatformInfo()

                    # Assert
                    assert result['os'] == 'Linux'
                    assert result['architecture'] == 'x86_64'
                    assert result['model'] is None
                    assert result['isRaspberryPi'] is False

    def test_getPlatformInfo_raspberryPi5_returnsPiInfo(self):
        """
        Given: Raspberry Pi 5 hardware
        When: getPlatformInfo() is called
        Then: Returns dict with Pi info including model
        """
        # Arrange
        mockModelContent = "Raspberry Pi 5 Model B Rev 1.0\x00"

        with patch('platform.system', return_value='Linux'):
            with patch('platform.machine', return_value='aarch64'):
                with patch('os.path.exists', return_value=True):
                    with patch('builtins.open', mock_open(read_data=mockModelContent)):
                        # Act
                        result = getPlatformInfo()

                        # Assert
                        assert result['os'] == 'Linux'
                        assert result['architecture'] == 'aarch64'
                        assert result['model'] == 'Raspberry Pi 5 Model B Rev 1.0'
                        assert result['isRaspberryPi'] is True

    def test_getPlatformInfo_macosSystem_returnsMacInfo(self):
        """
        Given: macOS operating system
        When: getPlatformInfo() is called
        Then: Returns dict with macOS info
        """
        # Arrange
        with patch('platform.system', return_value='Darwin'):
            with patch('platform.machine', return_value='arm64'):
                # Act
                result = getPlatformInfo()

                # Assert
                assert result['os'] == 'Darwin'
                assert result['architecture'] == 'arm64'
                assert result['model'] is None
                assert result['isRaspberryPi'] is False

    def test_getPlatformInfo_alwaysReturnsRequiredKeys(self):
        """
        Given: Any system
        When: getPlatformInfo() is called
        Then: Returns dict with all required keys
        """
        # Arrange & Act
        result = getPlatformInfo()

        # Assert
        requiredKeys = ['os', 'architecture', 'model', 'isRaspberryPi']
        for key in requiredKeys:
            assert key in result, f"Missing required key: {key}"

    def test_getPlatformInfo_returnTypes_areCorrect(self):
        """
        Given: Any system
        When: getPlatformInfo() is called
        Then: Returns dict with correct types
        """
        # Arrange & Act
        result = getPlatformInfo()

        # Assert
        assert isinstance(result['os'], str)
        assert isinstance(result['architecture'], str)
        assert result['model'] is None or isinstance(result['model'], str)
        assert isinstance(result['isRaspberryPi'], bool)

    def test_getPlatformInfo_unexpectedException_returnsEmptyDict(self):
        """
        Given: An unexpected exception during info gathering
        When: getPlatformInfo() is called
        Then: Returns dict with defaults (graceful fallback)
        """
        # Arrange
        with patch('platform.system', side_effect=Exception("Unexpected error")):
            # Act
            result = getPlatformInfo()

            # Assert
            # Should return safe defaults rather than crash
            assert 'os' in result
            assert 'architecture' in result
            assert 'model' in result
            assert 'isRaspberryPi' in result
            assert result['isRaspberryPi'] is False


class TestPlatformUtilsIntegration:
    """Integration tests for platform_utils module."""

    def test_isRaspberryPi_matchesPlatformInfo(self):
        """
        Given: Current system
        When: Both isRaspberryPi() and getPlatformInfo() are called
        Then: isRaspberryPi result matches platformInfo['isRaspberryPi']
        """
        # Arrange & Act
        isPi = isRaspberryPi()
        info = getPlatformInfo()

        # Assert
        assert isPi == info['isRaspberryPi']

    def test_getPlatformInfo_osMatchesPlatformSystem(self):
        """
        Given: Current system
        When: getPlatformInfo() is called
        Then: OS matches platform.system() or has safe default
        """
        # Arrange & Act
        result = getPlatformInfo()
        expectedOs = platform.system()

        # Assert
        # If there's no exception, should match; otherwise could be 'Unknown'
        assert result['os'] in [expectedOs, 'Unknown']

    def test_getPlatformInfo_architectureMatchesPlatformMachine(self):
        """
        Given: Current system
        When: getPlatformInfo() is called
        Then: Architecture matches platform.machine() or has safe default
        """
        # Arrange & Act
        result = getPlatformInfo()
        expectedArch = platform.machine()

        # Assert
        assert result['architecture'] in [expectedArch, 'Unknown']
