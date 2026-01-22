################################################################################
# File Name: run_tests_ollama_manager.py
# Purpose/Description: Test suite for OllamaManager - ollama installation and model management
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-018
# ================================================================================
################################################################################

"""
Test suite for OllamaManager class.

Tests cover:
- Ollama installation detection
- Model verification and download
- Graceful fallback when ollama unavailable
- Configuration integration
- Logging and error handling

Run with: python tests/run_tests_ollama_manager.py
"""

import json
import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, Mock, patch, call

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from obd.ollama_manager import (
    OllamaManager,
    OllamaStatus,
    OllamaState,
    ModelInfo,
    OllamaError,
    OllamaNotAvailableError,
    OllamaModelError,
    createOllamaManagerFromConfig,
    isOllamaAvailable,
    getOllamaConfig,
    OLLAMA_DEFAULT_BASE_URL,
    OLLAMA_AVAILABLE,
)


# =============================================================================
# Test Configuration
# =============================================================================

def createTestConfig(
    enabled: bool = True,
    model: str = "gemma2:2b",
    baseUrl: str = "http://localhost:11434"
) -> Dict[str, Any]:
    """Create a test configuration dictionary."""
    return {
        "aiAnalysis": {
            "enabled": enabled,
            "model": model,
            "ollamaBaseUrl": baseUrl,
            "maxAnalysesPerDrive": 1,
            "promptTemplate": "",
            "focusAreas": ["air_fuel_ratio", "timing"]
        }
    }


# =============================================================================
# Test Classes
# =============================================================================

class TestOllamaStateEnum(unittest.TestCase):
    """Tests for OllamaState enum."""

    def test_values_exist(self):
        """Verify all expected state values exist."""
        self.assertEqual(OllamaState.UNAVAILABLE.value, "unavailable")
        self.assertEqual(OllamaState.AVAILABLE.value, "available")
        self.assertEqual(OllamaState.MODEL_READY.value, "model_ready")
        self.assertEqual(OllamaState.MODEL_DOWNLOADING.value, "model_downloading")
        self.assertEqual(OllamaState.ERROR.value, "error")


class TestOllamaStatusDataclass(unittest.TestCase):
    """Tests for OllamaStatus dataclass."""

    def test_defaultValues(self):
        """Test default status values."""
        status = OllamaStatus()
        self.assertEqual(status.state, OllamaState.UNAVAILABLE)
        self.assertIsNone(status.version)
        self.assertIsNone(status.model)
        self.assertFalse(status.modelReady)
        self.assertEqual(status.availableModels, [])
        self.assertIsNone(status.errorMessage)

    def test_toDict(self):
        """Test serialization to dictionary."""
        status = OllamaStatus(
            state=OllamaState.MODEL_READY,
            version="0.3.0",
            model="gemma2:2b",
            modelReady=True,
            availableModels=["gemma2:2b", "llama2:7b"]
        )
        result = status.toDict()

        self.assertEqual(result['state'], "model_ready")
        self.assertEqual(result['version'], "0.3.0")
        self.assertEqual(result['model'], "gemma2:2b")
        self.assertTrue(result['modelReady'])
        self.assertEqual(result['availableModels'], ["gemma2:2b", "llama2:7b"])


class TestModelInfoDataclass(unittest.TestCase):
    """Tests for ModelInfo dataclass."""

    def test_creation(self):
        """Test ModelInfo creation."""
        info = ModelInfo(
            name="gemma2:2b",
            size=2_000_000_000,
            digest="abc123",
            modifiedAt=datetime.now()
        )
        self.assertEqual(info.name, "gemma2:2b")
        self.assertEqual(info.size, 2_000_000_000)
        self.assertEqual(info.digest, "abc123")

    def test_toDict(self):
        """Test serialization to dictionary."""
        now = datetime.now()
        info = ModelInfo(
            name="gemma2:2b",
            size=2_000_000_000,
            digest="abc123",
            modifiedAt=now
        )
        result = info.toDict()

        self.assertEqual(result['name'], "gemma2:2b")
        self.assertEqual(result['size'], 2_000_000_000)
        # Size in GB is 2000000000 / (1024^3) = ~1.86
        self.assertAlmostEqual(result['sizeGb'], 1.86, places=1)
        self.assertEqual(result['digest'], "abc123")


class TestOllamaManagerInit(unittest.TestCase):
    """Tests for OllamaManager initialization."""

    @patch('obd.ollama_manager.OllamaManager._checkOllamaAvailable')
    def test_init_withConfig(self, mockCheck):
        """Test initialization with configuration."""
        mockCheck.return_value = False
        config = createTestConfig(enabled=True, model="qwen2.5:3b")

        manager = OllamaManager(config=config)

        self.assertEqual(manager._model, "qwen2.5:3b")
        self.assertTrue(manager._enabled)

    @patch('obd.ollama_manager.OllamaManager._checkOllamaAvailable')
    def test_init_disabled(self, mockCheck):
        """Test initialization when disabled in config."""
        mockCheck.return_value = False
        config = createTestConfig(enabled=False)

        manager = OllamaManager(config=config)

        self.assertFalse(manager._enabled)

    @patch('obd.ollama_manager.OllamaManager._checkOllamaAvailable')
    def test_init_defaultConfig(self, mockCheck):
        """Test initialization with no config."""
        mockCheck.return_value = False

        manager = OllamaManager()

        self.assertFalse(manager._enabled)
        self.assertEqual(manager._baseUrl, OLLAMA_DEFAULT_BASE_URL)


class TestOllamaManagerCheckAvailable(unittest.TestCase):
    """Tests for checking ollama availability."""

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_checkAvailable_running(self, mockUrlopen):
        """Test detection when ollama is running."""
        mockResponse = MagicMock()
        mockResponse.read.return_value = b'Ollama is running'
        mockResponse.__enter__ = Mock(return_value=mockResponse)
        mockResponse.__exit__ = Mock(return_value=False)
        mockUrlopen.return_value = mockResponse

        manager = OllamaManager(config=createTestConfig())

        self.assertTrue(manager._ollamaAvailable)
        self.assertEqual(manager._state, OllamaState.AVAILABLE)

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_checkAvailable_notRunning(self, mockUrlopen):
        """Test detection when ollama is not running."""
        mockUrlopen.side_effect = Exception("Connection refused")

        manager = OllamaManager(config=createTestConfig())

        self.assertFalse(manager._ollamaAvailable)
        self.assertEqual(manager._state, OllamaState.UNAVAILABLE)


class TestOllamaManagerGetVersion(unittest.TestCase):
    """Tests for getting ollama version."""

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_getVersion_success(self, mockUrlopen):
        """Test successful version retrieval."""
        # First call for availability check
        availResponse = MagicMock()
        availResponse.read.return_value = b'Ollama is running'
        availResponse.__enter__ = Mock(return_value=availResponse)
        availResponse.__exit__ = Mock(return_value=False)

        # Second call for version
        versionResponse = MagicMock()
        versionResponse.read.return_value = json.dumps({"version": "0.3.0"}).encode()
        versionResponse.__enter__ = Mock(return_value=versionResponse)
        versionResponse.__exit__ = Mock(return_value=False)

        mockUrlopen.side_effect = [availResponse, versionResponse]

        manager = OllamaManager(config=createTestConfig())
        version = manager.getVersion()

        self.assertEqual(version, "0.3.0")

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_getVersion_unavailable(self, mockUrlopen):
        """Test version when ollama not available."""
        mockUrlopen.side_effect = Exception("Connection refused")

        manager = OllamaManager(config=createTestConfig())
        version = manager.getVersion()

        self.assertIsNone(version)


class TestOllamaManagerListModels(unittest.TestCase):
    """Tests for listing available models."""

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_listModels_success(self, mockUrlopen):
        """Test successful model listing."""
        # First call for availability check
        availResponse = MagicMock()
        availResponse.read.return_value = b'Ollama is running'
        availResponse.__enter__ = Mock(return_value=availResponse)
        availResponse.__exit__ = Mock(return_value=False)

        # Second call for models
        modelsResponse = MagicMock()
        modelsResponse.read.return_value = json.dumps({
            "models": [
                {
                    "name": "gemma2:2b",
                    "size": 2000000000,
                    "digest": "abc123",
                    "modified_at": "2026-01-01T00:00:00Z"
                },
                {
                    "name": "llama2:7b",
                    "size": 7000000000,
                    "digest": "def456",
                    "modified_at": "2026-01-01T00:00:00Z"
                }
            ]
        }).encode()
        modelsResponse.__enter__ = Mock(return_value=modelsResponse)
        modelsResponse.__exit__ = Mock(return_value=False)

        mockUrlopen.side_effect = [availResponse, modelsResponse]

        manager = OllamaManager(config=createTestConfig())
        models = manager.listModels()

        self.assertEqual(len(models), 2)
        self.assertEqual(models[0].name, "gemma2:2b")
        self.assertEqual(models[1].name, "llama2:7b")

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_listModels_empty(self, mockUrlopen):
        """Test when no models installed."""
        availResponse = MagicMock()
        availResponse.read.return_value = b'Ollama is running'
        availResponse.__enter__ = Mock(return_value=availResponse)
        availResponse.__exit__ = Mock(return_value=False)

        modelsResponse = MagicMock()
        modelsResponse.read.return_value = json.dumps({"models": []}).encode()
        modelsResponse.__enter__ = Mock(return_value=modelsResponse)
        modelsResponse.__exit__ = Mock(return_value=False)

        mockUrlopen.side_effect = [availResponse, modelsResponse]

        manager = OllamaManager(config=createTestConfig())
        models = manager.listModels()

        self.assertEqual(models, [])


class TestOllamaManagerVerifyModel(unittest.TestCase):
    """Tests for verifying model availability."""

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_verifyModel_exists(self, mockUrlopen):
        """Test verification when model exists."""
        availResponse = MagicMock()
        availResponse.read.return_value = b'Ollama is running'
        availResponse.__enter__ = Mock(return_value=availResponse)
        availResponse.__exit__ = Mock(return_value=False)

        modelsResponse = MagicMock()
        modelsResponse.read.return_value = json.dumps({
            "models": [{"name": "gemma2:2b", "size": 2000000000,
                       "digest": "abc", "modified_at": "2026-01-01T00:00:00Z"}]
        }).encode()
        modelsResponse.__enter__ = Mock(return_value=modelsResponse)
        modelsResponse.__exit__ = Mock(return_value=False)

        mockUrlopen.side_effect = [availResponse, modelsResponse]

        manager = OllamaManager(config=createTestConfig(model="gemma2:2b"))
        result = manager.verifyModel()

        self.assertTrue(result)
        self.assertEqual(manager._state, OllamaState.MODEL_READY)

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_verifyModel_notExists(self, mockUrlopen):
        """Test verification when model doesn't exist."""
        availResponse = MagicMock()
        availResponse.read.return_value = b'Ollama is running'
        availResponse.__enter__ = Mock(return_value=availResponse)
        availResponse.__exit__ = Mock(return_value=False)

        modelsResponse = MagicMock()
        modelsResponse.read.return_value = json.dumps({
            "models": [{"name": "llama2:7b", "size": 7000000000,
                       "digest": "abc", "modified_at": "2026-01-01T00:00:00Z"}]
        }).encode()
        modelsResponse.__enter__ = Mock(return_value=modelsResponse)
        modelsResponse.__exit__ = Mock(return_value=False)

        mockUrlopen.side_effect = [availResponse, modelsResponse]

        manager = OllamaManager(config=createTestConfig(model="gemma2:2b"))
        result = manager.verifyModel()

        self.assertFalse(result)


class TestOllamaManagerPullModel(unittest.TestCase):
    """Tests for pulling/downloading models."""

    @patch('obd.ollama_manager.urllib.request.urlopen')
    @patch('obd.ollama_manager.urllib.request.Request')
    def test_pullModel_success(self, mockRequest, mockUrlopen):
        """Test successful model pull."""
        # Availability check response
        availResponse = MagicMock()
        availResponse.read.return_value = b'Ollama is running'
        availResponse.__enter__ = Mock(return_value=availResponse)
        availResponse.__exit__ = Mock(return_value=False)

        # Pull response
        pullResponse = MagicMock()
        pullResponse.read.return_value = json.dumps({
            "status": "success"
        }).encode()
        pullResponse.__enter__ = Mock(return_value=pullResponse)
        pullResponse.__exit__ = Mock(return_value=False)

        mockUrlopen.side_effect = [availResponse, pullResponse]

        manager = OllamaManager(config=createTestConfig(model="gemma2:2b"))
        result = manager.pullModel("gemma2:2b")

        self.assertTrue(result)

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_pullModel_unavailable(self, mockUrlopen):
        """Test pull when ollama not available."""
        mockUrlopen.side_effect = Exception("Connection refused")

        manager = OllamaManager(config=createTestConfig())
        result = manager.pullModel("gemma2:2b")

        self.assertFalse(result)


class TestOllamaManagerGetStatus(unittest.TestCase):
    """Tests for getting overall status."""

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_getStatus_available(self, mockUrlopen):
        """Test status when ollama available with model."""
        # Create consistent mock responses
        def createMockResponse(content):
            resp = MagicMock()
            resp.read.return_value = content
            resp.status = 200
            resp.__enter__ = Mock(return_value=resp)
            resp.__exit__ = Mock(return_value=False)
            return resp

        availContent = b'Ollama is running'
        versionContent = json.dumps({"version": "0.3.0"}).encode()
        modelsContent = json.dumps({
            "models": [{"name": "gemma2:2b", "size": 2000000000,
                       "digest": "abc", "modified_at": "2026-01-01T00:00:00Z"}]
        }).encode()

        # Make urlopen return appropriate response based on URL
        def sideEffect(*args, **kwargs):
            url = args[0].full_url if hasattr(args[0], 'full_url') else str(args[0])
            if '/api/version' in url:
                return createMockResponse(versionContent)
            elif '/api/tags' in url:
                return createMockResponse(modelsContent)
            else:
                return createMockResponse(availContent)

        mockUrlopen.side_effect = sideEffect

        manager = OllamaManager(config=createTestConfig(model="gemma2:2b"))
        manager.verifyModel()  # Explicitly verify model
        status = manager.getStatus()

        # After verifyModel succeeds, state should be MODEL_READY
        self.assertEqual(status.state, OllamaState.MODEL_READY)
        self.assertEqual(status.version, "0.3.0")
        self.assertTrue(status.modelReady)

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_getStatus_unavailable(self, mockUrlopen):
        """Test status when ollama not available."""
        mockUrlopen.side_effect = Exception("Connection refused")

        manager = OllamaManager(config=createTestConfig())
        status = manager.getStatus()

        self.assertEqual(status.state, OllamaState.UNAVAILABLE)
        self.assertFalse(status.modelReady)


class TestOllamaManagerGracefulFallback(unittest.TestCase):
    """Tests for graceful fallback when ollama unavailable."""

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_aiDisabledWhenUnavailable(self, mockUrlopen):
        """Test AI features disabled when ollama unavailable."""
        mockUrlopen.side_effect = Exception("Connection refused")

        manager = OllamaManager(config=createTestConfig(enabled=True))

        self.assertFalse(manager.isReady())
        self.assertEqual(manager._state, OllamaState.UNAVAILABLE)

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_noExceptionOnUnavailable(self, mockUrlopen):
        """Test no exception raised when ollama unavailable."""
        mockUrlopen.side_effect = Exception("Connection refused")

        # Should not raise
        manager = OllamaManager(config=createTestConfig(enabled=True))
        version = manager.getVersion()
        models = manager.listModels()

        self.assertIsNone(version)
        self.assertEqual(models, [])


class TestOllamaManagerCallbacks(unittest.TestCase):
    """Tests for callback functionality."""

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_onStateChange(self, mockUrlopen):
        """Test state change callback."""
        # First call fails (init), second succeeds (refresh triggers state change)
        availResponse = MagicMock()
        availResponse.read.return_value = b'Ollama is running'
        availResponse.__enter__ = Mock(return_value=availResponse)
        availResponse.__exit__ = Mock(return_value=False)

        modelsResponse = MagicMock()
        modelsResponse.read.return_value = json.dumps({"models": []}).encode()
        modelsResponse.__enter__ = Mock(return_value=modelsResponse)
        modelsResponse.__exit__ = Mock(return_value=False)

        # Init fails, then refresh succeeds (triggering state change)
        mockUrlopen.side_effect = [
            Exception("Connection refused"),  # init check
            availResponse,                     # refresh check
            modelsResponse                     # verifyModel in refresh
        ]

        stateChanges = []

        def onStateChange(state):
            stateChanges.append(state)

        manager = OllamaManager(config=createTestConfig())
        manager.onStateChange(onStateChange)

        # Trigger state change by refreshing - state goes from UNAVAILABLE to AVAILABLE
        manager.refresh()

        self.assertTrue(len(stateChanges) >= 1)


class TestOllamaManagerLogging(unittest.TestCase):
    """Tests for logging functionality."""

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_logsAvailabilityCheck(self, mockUrlopen):
        """Test that availability checks are logged."""
        mockUrlopen.side_effect = Exception("Connection refused")

        with patch('obd.ollama_manager.logger') as mockLogger:
            manager = OllamaManager(config=createTestConfig())

            # Should log the unavailability
            self.assertTrue(mockLogger.warning.called or mockLogger.info.called)


class TestHelperFunctions(unittest.TestCase):
    """Tests for module helper functions."""

    @patch('obd.ollama_manager.OllamaManager')
    def test_createOllamaManagerFromConfig(self, mockManager):
        """Test factory function."""
        config = createTestConfig()

        manager = createOllamaManagerFromConfig(config)

        mockManager.assert_called_once_with(config=config)

    def test_isOllamaAvailable_disabled(self):
        """Test availability check when disabled in config."""
        config = createTestConfig(enabled=False)

        result = isOllamaAvailable(config)

        # Should return False when AI analysis disabled
        self.assertFalse(result)

    def test_getOllamaConfig_defaults(self):
        """Test config extraction with defaults."""
        config = {}

        result = getOllamaConfig(config)

        self.assertFalse(result['enabled'])
        self.assertEqual(result['model'], "gemma2:2b")
        self.assertEqual(result['baseUrl'], OLLAMA_DEFAULT_BASE_URL)

    def test_getOllamaConfig_custom(self):
        """Test config extraction with custom values."""
        config = createTestConfig(
            enabled=True,
            model="qwen2.5:3b",
            baseUrl="http://custom:11434"
        )

        result = getOllamaConfig(config)

        self.assertTrue(result['enabled'])
        self.assertEqual(result['model'], "qwen2.5:3b")
        self.assertEqual(result['baseUrl'], "http://custom:11434")


class TestOllamaManagerInstallScript(unittest.TestCase):
    """Tests for installation script generation."""

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_generateInstallScript_linux(self, mockUrlopen):
        """Test Linux installation script generation."""
        mockUrlopen.side_effect = Exception("Connection refused")

        manager = OllamaManager(config=createTestConfig())
        script = manager.generateInstallScript(platform="linux")

        self.assertIn("curl", script)
        self.assertIn("ollama", script)

    @patch('obd.ollama_manager.urllib.request.urlopen')
    def test_generateInstallScript_windows(self, mockUrlopen):
        """Test Windows installation script generation."""
        mockUrlopen.side_effect = Exception("Connection refused")

        manager = OllamaManager(config=createTestConfig())
        script = manager.generateInstallScript(platform="windows")

        # Windows uses different installation method
        self.assertIn("ollama", script.lower())


class TestExceptions(unittest.TestCase):
    """Tests for exception classes."""

    def test_OllamaError(self):
        """Test base OllamaError exception."""
        error = OllamaError("Test error", details={'key': 'value'})

        self.assertEqual(str(error), "Test error")
        self.assertEqual(error.details, {'key': 'value'})

    def test_OllamaNotAvailableError(self):
        """Test OllamaNotAvailableError exception."""
        error = OllamaNotAvailableError("Ollama not installed")

        self.assertIsInstance(error, OllamaError)
        self.assertEqual(str(error), "Ollama not installed")

    def test_OllamaModelError(self):
        """Test OllamaModelError exception."""
        error = OllamaModelError("Model not found", details={'model': 'gemma2:2b'})

        self.assertIsInstance(error, OllamaError)
        self.assertEqual(error.details['model'], 'gemma2:2b')


# =============================================================================
# Test Runner
# =============================================================================

if __name__ == '__main__':
    # Configure logging for tests
    logging.basicConfig(
        level=logging.WARNING,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
    )

    # Run tests with verbose output
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    testClasses = [
        TestOllamaStateEnum,
        TestOllamaStatusDataclass,
        TestModelInfoDataclass,
        TestOllamaManagerInit,
        TestOllamaManagerCheckAvailable,
        TestOllamaManagerGetVersion,
        TestOllamaManagerListModels,
        TestOllamaManagerVerifyModel,
        TestOllamaManagerPullModel,
        TestOllamaManagerGetStatus,
        TestOllamaManagerGracefulFallback,
        TestOllamaManagerCallbacks,
        TestOllamaManagerLogging,
        TestHelperFunctions,
        TestOllamaManagerInstallScript,
        TestExceptions,
    ]

    for testClass in testClasses:
        tests = loader.loadTestsFromTestCase(testClass)
        suite.addTests(tests)

    # Run with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print("=" * 70)

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
