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
# 2026-02-13    | Ralph Agent  | US-OLL-002 - Updated timeout tests to verify
#               |              | configurable timeouts from config
# 2026-02-13    | Ralph Agent  | US-OLL-003 - Updated network reachability tests
#               |              | to test OllamaManager._checkNetworkReachable
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
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

from src.ai.ollama import OllamaManager
from src.ai.types import (
    OllamaState,
    OLLAMA_DEFAULT_BASE_URL,
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

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_init_remoteUrl_usesConfiguredUrl(
        self, mockUrlopen, mockSocket, remoteConfig
    ):
        """
        Given: Config with ollamaBaseUrl pointing to a remote server
        When: OllamaManager is initialized
        Then: The manager uses the remote URL (not localhost)
        """
        # Arrange
        mockSocket.side_effect = OSError('Connection refused')
        mockUrlopen.side_effect = URLError('Connection refused')

        # Act
        manager = OllamaManager(config=remoteConfig)

        # Assert
        assert manager._baseUrl == 'http://10.27.27.100:11434'

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_init_remoteUrl_checksNetworkReachability(
        self, mockUrlopen, mockSocket, remoteConfig
    ):
        """
        Given: Config with a remote Ollama URL
        When: OllamaManager is initialized
        Then: Network reachability is checked via socket to remote host
        """
        # Arrange
        mockSocket.side_effect = OSError('Connection refused')
        mockUrlopen.side_effect = URLError('Connection refused')

        # Act
        OllamaManager(config=remoteConfig)

        # Assert - verify socket was called with remote host
        mockSocket.assert_called_with(('10.27.27.100', 11434), timeout=3)

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
    """Tests for OllamaManager._checkNetworkReachable (US-OLL-003)."""

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_checkNetworkReachable_unreachableHost_returnsFalse(
        self, mockUrlopen, mockSocket
    ):
        """
        Given: A non-routable IP address (192.0.2.1 per RFC 5737)
        When: _checkNetworkReachable is called
        Then: Returns False (socket connection fails)
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')
        mockSocket.side_effect = OSError('Network is unreachable')
        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://192.0.2.1:11434',
            }
        }
        manager = OllamaManager(config=config)

        # Act
        reachable = manager._checkNetworkReachable()

        # Assert
        assert reachable is False

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_checkNetworkReachable_reachableHost_returnsTrue(
        self, mockUrlopen, mockSocket
    ):
        """
        Given: A reachable host (mocked socket connection succeeds)
        When: _checkNetworkReachable is called
        Then: Returns True and closes the socket
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')
        mockConn = MagicMock()
        mockSocket.return_value = mockConn
        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://10.27.27.100:11434',
            }
        }
        manager = OllamaManager(config=config)

        # Reset mock after __init__ calls (which also check reachability)
        mockConn.reset_mock()

        # Act
        reachable = manager._checkNetworkReachable()

        # Assert
        assert reachable is True
        mockConn.close.assert_called_once()

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_checkNetworkReachable_socketTimeout_returnsFalse(
        self, mockUrlopen, mockSocket
    ):
        """
        Given: A host that times out on socket connection
        When: _checkNetworkReachable is called
        Then: Returns False
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')
        mockSocket.side_effect = socket.timeout('timed out')
        config = {
            'aiAnalysis': {
                'enabled': True,
                'ollamaBaseUrl': 'http://10.27.27.100:11434',
            }
        }
        manager = OllamaManager(config=config)

        # Act
        reachable = manager._checkNetworkReachable()

        # Assert
        assert reachable is False


# =============================================================================
# Test: Health check skips Ollama HTTP check when network is unreachable
# =============================================================================

class TestHealthCheckWithNetworkCheck:
    """Tests for health check behavior with network pre-check (US-OLL-003)."""

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_healthCheck_networkUnreachable_skipsHttpCheck(
        self, mockUrlopen, mockSocket
    ):
        """
        Given: Remote server network is unreachable (socket fails)
        When: OllamaManager is initialized
        Then: State is UNAVAILABLE and HTTP health check is never called
        """
        # Arrange
        mockSocket.side_effect = OSError('Network is unreachable')
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
        # HTTP urlopen should NOT have been called since network is unreachable
        mockUrlopen.assert_not_called()

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_healthCheck_networkReachableOllamaRunning_stateAvailable(
        self, mockUrlopen, mockSocket
    ):
        """
        Given: Remote server is reachable and Ollama is running
        When: OllamaManager checks availability
        Then: State is set to AVAILABLE
        """
        # Arrange - network reachable
        mockConn = MagicMock()
        mockSocket.return_value = mockConn

        # Arrange - HTTP health check succeeds
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
    """Tests for configurable timeout values (US-OLL-002)."""

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_healthCheck_defaultConfig_usesDefaultHealthTimeout(
        self, mockUrlopen
    ):
        """
        Given: OllamaManager with no timeout config
        When: Health check is performed
        Then: Uses the default health timeout (10s) for the request
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')

        # Act
        manager = OllamaManager(config={
            'aiAnalysis': {'enabled': True}
        })

        # Assert - default healthTimeoutSeconds is 10
        callArgs = mockUrlopen.call_args
        assert callArgs[1].get('timeout') == 10

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_healthCheck_configuredTimeout_usedInRequest(self, mockUrlopen):
        """
        Given: Config with aiAnalysis.healthTimeoutSeconds set to 15
              and localhost URL (no network pre-check)
        When: Health check is performed
        Then: The configured timeout (15) is used in the urlopen call
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')
        config = {
            'aiAnalysis': {
                'enabled': True,
                'healthTimeoutSeconds': 15,
                'ollamaBaseUrl': 'http://localhost:11434',
            }
        }

        # Act
        OllamaManager(config=config)

        # Assert
        callArgs = mockUrlopen.call_args
        assert callArgs[1].get('timeout') == 15

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_apiTimeout_configuredValue_usedInGetVersion(self, mockUrlopen):
        """
        Given: Config with apiTimeoutSeconds set to 90 and localhost URL
        When: getVersion() is called
        Then: The configured API timeout (90) is used in the urlopen call
        """
        # Arrange - first call is health check (succeeds), second is getVersion
        mockResponse = MagicMock()
        mockResponse.read.return_value = b'Ollama is running'
        mockResponse.status = 200
        mockResponse.__enter__ = MagicMock(return_value=mockResponse)
        mockResponse.__exit__ = MagicMock(return_value=False)

        mockVersionResponse = MagicMock()
        mockVersionResponse.read.return_value = b'{"version": "0.1.0"}'
        mockVersionResponse.__enter__ = MagicMock(
            return_value=mockVersionResponse
        )
        mockVersionResponse.__exit__ = MagicMock(return_value=False)

        mockUrlopen.side_effect = [mockResponse, mockVersionResponse]

        config = {
            'aiAnalysis': {
                'enabled': True,
                'apiTimeoutSeconds': 90,
                'ollamaBaseUrl': 'http://localhost:11434',
            }
        }

        # Act
        manager = OllamaManager(config=config)
        manager.getVersion()

        # Assert - second call (getVersion) uses API timeout
        secondCall = mockUrlopen.call_args_list[1]
        assert secondCall[1].get('timeout') == 90

    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_apiTimeout_defaultConfig_usesSixtySeconds(self, mockUrlopen):
        """
        Given: No apiTimeoutSeconds in config
        When: OllamaManager is created with defaults
        Then: API timeout defaults to 60 seconds
        """
        # Arrange
        mockUrlopen.side_effect = URLError('Connection refused')

        # Act
        manager = OllamaManager(config={
            'aiAnalysis': {'enabled': True}
        })

        # Assert
        assert manager._apiTimeout == 60


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

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_remoteDown_state_isUnavailable(self, mockUrlopen, mockSocket):
        """
        Given: Remote Ollama server is down (network unreachable)
        When: OllamaManager is initialized
        Then: State is UNAVAILABLE
        """
        # Arrange
        mockSocket.side_effect = OSError('Connection refused')
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

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_remoteDown_errorMessage_isSet(self, mockUrlopen, mockSocket):
        """
        Given: Remote Ollama server is down (network unreachable)
        When: OllamaManager is initialized
        Then: An appropriate error message is stored
        """
        # Arrange
        mockSocket.side_effect = OSError('Network is unreachable')
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
        assert 'unreachable' in manager._errorMessage.lower()

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_remoteDown_isReady_returnsFalse(self, mockUrlopen, mockSocket):
        """
        Given: Remote Ollama server is down
        When: isReady() is called
        Then: Returns False
        """
        # Arrange
        mockSocket.side_effect = OSError('Connection refused')
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

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_remoteDown_getStatus_containsErrorInfo(
        self, mockUrlopen, mockSocket
    ):
        """
        Given: Remote Ollama server is down
        When: getStatus() is called
        Then: Status contains UNAVAILABLE state and error message
        """
        # Arrange
        mockSocket.side_effect = OSError('Connection refused')
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

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_analyzePostDrive_remoteDown_returnsResultWithoutCrash(
        self, mockUrlopen, mockSocket
    ):
        """
        Given: Remote Ollama server is unreachable
        When: AiAnalyzer.analyzePostDrive is called
        Then: Returns an AnalysisResult without raising an exception
        """
        # Arrange
        mockSocket.side_effect = OSError('Connection refused')
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

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_ollamaManager_refresh_remoteDown_noException(
        self, mockUrlopen, mockSocket
    ):
        """
        Given: Remote Ollama server goes down after initial check
        When: refresh() is called
        Then: Returns status without raising exception
        """
        # Arrange - first init: network reachable + HTTP succeeds
        mockConn = MagicMock()
        mockSocket.side_effect = [
            mockConn,  # Init network check succeeds
            OSError('Network is unreachable'),  # Refresh network check fails
        ]

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
        manager = OllamaManager(config=config)
        assert manager.state == OllamaState.AVAILABLE

        # Act - should not raise
        status = manager.refresh()

        # Assert
        assert status.state == OllamaState.UNAVAILABLE

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_listModels_remoteDown_returnsEmptyList(
        self, mockUrlopen, mockSocket
    ):
        """
        Given: Remote Ollama server is down
        When: listModels() is called
        Then: Returns empty list without exception
        """
        # Arrange
        mockSocket.side_effect = OSError('Connection refused')
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

    @patch('src.ai.ollama.socket.create_connection')
    @patch('src.ai.ollama.urllib.request.urlopen')
    def test_getVersion_remoteDown_returnsNone(
        self, mockUrlopen, mockSocket
    ):
        """
        Given: Remote Ollama server is down
        When: getVersion() is called
        Then: Returns None without exception
        """
        # Arrange
        mockSocket.side_effect = OSError('Connection refused')
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


