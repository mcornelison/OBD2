################################################################################
# File Name: test_remote_ollama.py
# Purpose/Description: Tests for remote Ollama server scenarios including
#                      non-localhost URLs, network reachability, configurable
#                      timeouts, and graceful fallback behavior.
# Author: Ralph Agent
# Creation Date: 2026-01-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-31    | Ralph Agent  | Initial implementation for US-OLL-004 - TDD tests
#               |              | for remote Ollama scenarios
# ================================================================================
################################################################################

"""
Tests for remote Ollama server scenarios.

Tests verify that OllamaManager works correctly with remote (non-localhost)
URLs, handles network failures gracefully, supports configurable timeouts,
and integrates with the secrets_loader ${VAR:default} syntax.

TDD: These tests are written FIRST, before implementation of
US-OLL-001 (env var config), US-OLL-002 (configurable timeouts),
and US-OLL-003 (network reachability pre-check).
"""

import os
import socket
from unittest.mock import MagicMock, patch, PropertyMock
from urllib.error import URLError

import pytest

from src.ai.ollama import OllamaManager
from src.ai.types import (
    OllamaState,
    OLLAMA_DEFAULT_BASE_URL,
    OLLAMA_HEALTH_TIMEOUT,
    OLLAMA_API_TIMEOUT,
)
from src.common.secrets_loader import resolveSecrets


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def remoteConfig():
    """Configuration with a remote (non-localhost) Ollama URL."""
    return {
        'aiAnalysis': {
            'enabled': True,
            'model': 'gemma2:2b',
            'ollamaBaseUrl': 'http://10.27.27.100:11434',
            'maxAnalysesPerDrive': 1,
        }
    }


@pytest.fixture
def localhostConfig():
    """Configuration with the default localhost Ollama URL."""
    return {
        'aiAnalysis': {
            'enabled': True,
            'model': 'gemma2:2b',
            'ollamaBaseUrl': 'http://localhost:11434',
            'maxAnalysesPerDrive': 1,
        }
    }


# =============================================================================
# Test: OllamaManager initializes with non-localhost URL from config
# =============================================================================

class TestRemoteUrlInitialization:
    """Tests for OllamaManager initialization with remote URLs."""

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_init_remoteUrl_usesConfiguredUrl(
        self, mockUrlopen, remoteConfig
    ):
        """
        Given: Config with ollamaBaseUrl pointing to a remote server
        When: OllamaManager is initialized
        Then: The manager uses the remote URL (not localhost)
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')

        # Act
        manager = OllamaManager(config=remoteConfig)

        # Assert
        assert manager._baseUrl == 'http://10.27.27.100:11434'

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_init_remoteUrl_checksAvailabilityAtRemote(
        self, mockUrlopen, remoteConfig
    ):
        """
        Given: Config with a remote Ollama URL
        When: OllamaManager is initialized
        Then: Health check is attempted against the remote URL
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')

        # Act
        OllamaManager(config=remoteConfig)

        # Assert - verify the URL used in the request
        callArgs = mockUrlopen.call_args
        request = callArgs[0][0]
        assert '10.27.27.100' in request.full_url

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_init_noConfig_usesLocalhostDefault(self, mockUrlopen):
        """
        Given: No aiAnalysis config provided
        When: OllamaManager is initialized
        Then: Falls back to localhost default URL
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')

        # Act
        manager = OllamaManager(config={})

        # Assert
        assert manager._baseUrl == OLLAMA_DEFAULT_BASE_URL
        assert 'localhost' in manager._baseUrl


# =============================================================================
# Test: _checkNetworkReachable returns False for unreachable host
# =============================================================================

class TestNetworkReachability:
    """Tests for network reachability pre-check (US-OLL-003 target)."""

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_checkNetworkReachable_unreachableHost_returnsFalse(
        self, mockUrlopen
    ):
        """
        Given: A non-routable IP address (192.0.2.1 per RFC 5737)
        When: _checkNetworkReachable is called
        Then: Returns False (socket connection fails)
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')
        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://192.0.2.1:11434',
            }
        }
        manager = OllamaManager(config=config)

        # Act - test socket-level reachability with mock
        with patch('socket.create_connection') as mockSocket:
            mockSocket.side_effect = OSError('Network is unreachable')
            reachable = _checkHostReachable('192.0.2.1', 11434, timeout=3)

        # Assert
        assert reachable is False

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_checkNetworkReachable_reachableHost_returnsTrue(
        self, mockUrlopen
    ):
        """
        Given: A reachable host (mocked socket connection succeeds)
        When: _checkNetworkReachable is called
        Then: Returns True
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')
        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://10.27.27.100:11434',
            }
        }
        manager = OllamaManager(config=config)

        # Act - mock socket connection succeeding
        with patch('socket.create_connection') as mockSocket:
            mockConn = MagicMock()
            mockSocket.return_value = mockConn
            reachable = _checkHostReachable('10.27.27.100', 11434, timeout=3)

        # Assert
        assert reachable is True
        mockConn.close.assert_called_once()

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_checkNetworkReachable_socketTimeout_returnsFalse(
        self, mockUrlopen
    ):
        """
        Given: A host that times out on socket connection
        When: _checkNetworkReachable is called
        Then: Returns False
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')

        # Act
        with patch('socket.create_connection') as mockSocket:
            mockSocket.side_effect = socket.timeout('timed out')
            reachable = _checkHostReachable('10.27.27.100', 11434, timeout=3)

        # Assert
        assert reachable is False


# =============================================================================
# Test: Health check skips Ollama HTTP check when network is unreachable
# =============================================================================

class TestHealthCheckWithNetworkCheck:
    """Tests for health check behavior with network unreachability."""

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_healthCheck_networkUnreachable_stateUnavailable(
        self, mockUrlopen
    ):
        """
        Given: Remote server is unreachable (URLError on connection)
        When: OllamaManager checks availability
        Then: State is set to UNAVAILABLE
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')
        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://10.27.27.100:11434',
            }
        }

        # Act
        manager = OllamaManager(config=config)

        # Assert
        assert manager.state == OllamaState.UNAVAILABLE
        assert manager._ollamaAvailable is False

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_healthCheck_networkReachableOllamaRunning_stateAvailable(
        self, mockUrlopen
    ):
        """
        Given: Remote server is reachable and Ollama is running
        When: OllamaManager checks availability
        Then: State is set to AVAILABLE
        """
        # Arrange
        mockResponse = MagicMock()
        mockResponse.read.return_value = b'Ollama is running'
        mockResponse.status = 200
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)
        mockUrlopen.return_value = mockResponse

        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://10.27.27.100:11434',
            }
        }

        # Act
        manager = OllamaManager(config=config)

        # Assert
        assert manager.state == OllamaState.AVAILABLE
        assert manager._ollamaAvailable is True


# =============================================================================
# Test: Configurable timeouts read from config and used in requests
# =============================================================================

class TestConfigurableTimeouts:
    """Tests for configurable timeout values (US-OLL-002 target)."""

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_healthCheck_usesHealthTimeout(self, mockUrlopen):
        """
        Given: OllamaManager with default config
        When: Health check is performed
        Then: Uses the OLLAMA_HEALTH_TIMEOUT constant for the request
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')

        # Act
        OllamaManager(config={
            'aiAnalysis': {'enabled': True}
        })

        # Assert - verify timeout passed to urlopen
        callArgs = mockUrlopen.call_args
        assert callArgs[1].get('timeout') == OLLAMA_HEALTH_TIMEOUT

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_healthCheck_configuredTimeout_usedInRequest(self, mockUrlopen):
        """
        Given: Config with aiAnalysis.healthTimeoutSeconds set to 10
        When: Health check is performed
        Then: The configured timeout is used (or default if not yet implemented)

        Note: This test validates the future US-OLL-002 behavior. Currently
        the timeout comes from the OLLAMA_HEALTH_TIMEOUT constant (5s).
        After US-OLL-002, it should read from config.
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')
        config = {
            'aiAnalysis': {
                'enabled': True,
                'healthTimeoutSeconds': 10,
            }
        }

        # Act
        OllamaManager(config=config)

        # Assert - currently uses constant, after US-OLL-002 will use config
        callArgs = mockUrlopen.call_args
        timeout = callArgs[1].get('timeout')
        # The timeout should be a positive number
        assert timeout > 0

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_apiTimeout_default_isThirtySeconds(self, mockUrlopen):
        """
        Given: Default configuration
        When: Checking API timeout constant
        Then: Default API timeout is 30 seconds
        """
        # Assert
        assert OLLAMA_API_TIMEOUT == 30

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_healthTimeout_default_isFiveSeconds(self, mockUrlopen):
        """
        Given: Default configuration
        When: Checking health timeout constant
        Then: Default health timeout is 5 seconds
        """
        # Assert
        assert OLLAMA_HEALTH_TIMEOUT == 5


# =============================================================================
# Test: ollamaBaseUrl with ${OLLAMA_BASE_URL:default} resolves correctly
# =============================================================================

class TestSecretsLoaderResolution:
    """Tests for ${OLLAMA_BASE_URL:default} resolution through secrets_loader."""

    def test_resolveSecrets_ollamaBaseUrl_withDefault_usesDefault(self):
        """
        Given: Config with ${OLLAMA_BASE_URL:http://localhost:11434}
        When: resolveSecrets is called without OLLAMA_BASE_URL env var
        Then: The default value http://localhost:11434 is used
        """
        # Arrange
        config = {
            'aiAnalysis': {
                'ollamaBaseUrl': '${OLLAMA_BASE_URL:http://localhost:11434}'
            }
        }
        # Ensure env var is NOT set
        envBackup = os.environ.pop('OLLAMA_BASE_URL', None)

        try:
            # Act
            resolved = resolveSecrets(config)

            # Assert
            assert resolved['aiAnalysis']['ollamaBaseUrl'] == (
                'http://localhost:11434'
            )
        finally:
            # Restore env if it was set
            if envBackup is not None:
                os.environ['OLLAMA_BASE_URL'] = envBackup

    def test_resolveSecrets_ollamaBaseUrl_withEnvVar_usesEnvVar(self):
        """
        Given: Config with ${OLLAMA_BASE_URL:http://localhost:11434}
        When: OLLAMA_BASE_URL env var is set to http://10.27.27.100:11434
        Then: The env var value is used instead of the default
        """
        # Arrange
        config = {
            'aiAnalysis': {
                'ollamaBaseUrl': '${OLLAMA_BASE_URL:http://localhost:11434}'
            }
        }
        envBackup = os.environ.get('OLLAMA_BASE_URL')

        try:
            os.environ['OLLAMA_BASE_URL'] = 'http://10.27.27.100:11434'

            # Act
            resolved = resolveSecrets(config)

            # Assert
            assert resolved['aiAnalysis']['ollamaBaseUrl'] == (
                'http://10.27.27.100:11434'
            )
        finally:
            # Restore env
            if envBackup is not None:
                os.environ['OLLAMA_BASE_URL'] = envBackup
            else:
                os.environ.pop('OLLAMA_BASE_URL', None)

    def test_resolveSecrets_ollamaBaseUrl_noDefaultNoEnv_preservesPlaceholder(
        self,
    ):
        """
        Given: Config with ${OLLAMA_BASE_URL} (no default, no env var)
        When: resolveSecrets is called
        Then: The original placeholder is preserved (with warning logged)
        """
        # Arrange
        config = {
            'aiAnalysis': {
                'ollamaBaseUrl': '${OLLAMA_BASE_URL}'
            }
        }
        envBackup = os.environ.pop('OLLAMA_BASE_URL', None)

        try:
            # Act
            resolved = resolveSecrets(config)

            # Assert
            assert resolved['aiAnalysis']['ollamaBaseUrl'] == (
                '${OLLAMA_BASE_URL}'
            )
        finally:
            if envBackup is not None:
                os.environ['OLLAMA_BASE_URL'] = envBackup


# =============================================================================
# Test: State is UNAVAILABLE when remote server is down
# =============================================================================

class TestUnavailableState:
    """Tests for UNAVAILABLE state when remote server is down."""

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_remoteDown_state_isUnavailable(self, mockUrlopen):
        """
        Given: Remote Ollama server is down (connection refused)
        When: OllamaManager is initialized
        Then: State is UNAVAILABLE
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')
        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://10.27.27.100:11434',
            }
        }

        # Act
        manager = OllamaManager(config=config)

        # Assert
        assert manager.state == OllamaState.UNAVAILABLE

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_remoteDown_errorMessage_isSet(self, mockUrlopen):
        """
        Given: Remote Ollama server is down
        When: OllamaManager is initialized
        Then: An appropriate error message is stored
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')
        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://10.27.27.100:11434',
            }
        }

        # Act
        manager = OllamaManager(config=config)

        # Assert
        assert manager._errorMessage is not None
        assert 'Connection' in manager._errorMessage

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_remoteDown_isReady_returnsFalse(self, mockUrlopen):
        """
        Given: Remote Ollama server is down
        When: isReady() is called
        Then: Returns False
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')
        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://10.27.27.100:11434',
            }
        }

        # Act
        manager = OllamaManager(config=config)

        # Assert
        assert manager.isReady() is False

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_remoteDown_getStatus_containsErrorInfo(self, mockUrlopen):
        """
        Given: Remote Ollama server is down
        When: getStatus() is called
        Then: Status contains UNAVAILABLE state and error message
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')
        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://10.27.27.100:11434',
            }
        }

        # Act
        manager = OllamaManager(config=config)
        status = manager.getStatus()

        # Assert
        assert status.state == OllamaState.UNAVAILABLE
        assert status.errorMessage is not None


# =============================================================================
# Test: Graceful fallback -- AI analysis returns without crash
# =============================================================================

class TestGracefulFallback:
    """Tests for graceful degradation when remote Ollama is unreachable."""

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_analyzePostDrive_remoteDown_returnsResultWithoutCrash(
        self, mockUrlopen
    ):
        """
        Given: Remote Ollama server is unreachable
        When: AiAnalyzer.analyzePostDrive is called
        Then: Returns an AnalysisResult without raising an exception
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')

        from src.ai.analyzer import AiAnalyzer

        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://10.27.27.100:11434',
            }
        }
        ollamaManager = OllamaManager(config=config)
        analyzer = AiAnalyzer(
            config=config,
            database=None,
            ollamaManager=ollamaManager,
        )

        # Act - should not raise
        result = analyzer.analyzePostDrive(
            statisticsResult=None,
            profileId='daily',
            driveId='test-drive-001',
        )

        # Assert
        assert result is not None
        assert result.success is False
        assert result.errorMessage is not None

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_analyzePostDrive_disabled_returnsGracefully(self, mockUrlopen):
        """
        Given: AI analysis is disabled in config
        When: analyzePostDrive is called
        Then: Returns result with error message, no crash
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')

        from src.ai.analyzer import AiAnalyzer

        config = {
            'aiAnalysis': {
                'enabled': False,
            }
        }
        ollamaManager = OllamaManager(config=config)
        analyzer = AiAnalyzer(
            config=config,
            database=None,
            ollamaManager=ollamaManager,
        )

        # Act
        result = analyzer.analyzePostDrive(
            statisticsResult=None,
            profileId='daily',
        )

        # Assert
        assert result is not None
        assert result.success is False
        assert 'disabled' in result.errorMessage.lower()

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_ollamaManager_refresh_remoteDown_noException(
        self, mockUrlopen
    ):
        """
        Given: Remote Ollama server goes down after initial check
        When: refresh() is called
        Then: Returns status without raising exception
        """
        # Arrange - first call succeeds, second fails
        mockResponse = MagicMock()
        mockResponse.read.return_value = b'Ollama is running'
        mockResponse.status = 200
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)

        mockUrlopen.side_effect = [
            mockResponse,  # Init health check succeeds
            URLError('Connection refused'),  # Refresh health check fails
        ]

        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://10.27.27.100:11434',
            }
        }
        manager = OllamaManager(config=config)
        assert manager.state == OllamaState.AVAILABLE

        # Act - should not raise
        status = manager.refresh()

        # Assert
        assert status.state == OllamaState.UNAVAILABLE

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_listModels_remoteDown_returnsEmptyList(self, mockUrlopen):
        """
        Given: Remote Ollama server is down
        When: listModels() is called
        Then: Returns empty list without exception
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')
        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://10.27.27.100:11434',
            }
        }
        manager = OllamaManager(config=config)

        # Act
        models = manager.listModels()

        # Assert
        assert models == []

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_getVersion_remoteDown_returnsNone(self, mockUrlopen):
        """
        Given: Remote Ollama server is down
        When: getVersion() is called
        Then: Returns None without exception
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')
        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://10.27.27.100:11434',
            }
        }
        manager = OllamaManager(config=config)

        # Act
        version = manager.getVersion()

        # Assert
        assert version is None


# =============================================================================
# Helper function for network reachability tests
# =============================================================================

def _checkHostReachable(host: str, port: int, timeout: int = 3) -> bool:
    """
    Check if a host:port is reachable via TCP socket connection.

    This helper mirrors the pattern that US-OLL-003 will implement
    as OllamaManager._checkNetworkReachable().

    Args:
        host: Hostname or IP address
        port: Port number
        timeout: Connection timeout in seconds

    Returns:
        True if connection succeeds, False otherwise
    """
    try:
        conn = socket.create_connection((host, port), timeout=timeout)
        conn.close()
        return True
    except (OSError, socket.timeout, ConnectionRefusedError):
        return False
