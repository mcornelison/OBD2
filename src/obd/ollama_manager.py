################################################################################
# File Name: ollama_manager.py
# Purpose/Description: Ollama installation and model management for AI analysis
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
Ollama management module for AI-based analysis features.

Provides installation detection, model verification, and download functionality
for the ollama local LLM server. Gracefully disables AI features when ollama
is unavailable to ensure the system continues operating normally.

Supported models (configurable):
- gemma2:2b (default, smaller footprint)
- qwen2.5:3b (alternative, slightly larger)

Key features:
- Installation detection via API health check
- Model verification (check if configured model is installed)
- Model download/pull functionality
- Graceful fallback when unavailable
- Installation script generation

Usage:
    from obd.ollama_manager import OllamaManager

    manager = OllamaManager(config=config)

    # Check if ready for AI analysis
    if manager.isReady():
        status = manager.getStatus()
        print(f"Ollama {status.version} ready with {status.model}")
    else:
        print("AI analysis disabled - ollama not available")

    # List available models
    models = manager.listModels()
    for model in models:
        print(f"{model.name}: {model.sizeGb} GB")

    # Pull a model if needed
    if not manager.verifyModel():
        manager.pullModel("gemma2:2b")
"""

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "gemma2:2b"
OLLAMA_HEALTH_TIMEOUT = 5  # seconds
OLLAMA_API_TIMEOUT = 30  # seconds
OLLAMA_PULL_TIMEOUT = 600  # 10 minutes for model download

# Flag to track if ollama API is importable/usable
OLLAMA_AVAILABLE = True


# =============================================================================
# Enums and Dataclasses
# =============================================================================

class OllamaState(Enum):
    """Ollama service state."""

    UNAVAILABLE = "unavailable"
    AVAILABLE = "available"
    MODEL_READY = "model_ready"
    MODEL_DOWNLOADING = "model_downloading"
    ERROR = "error"


@dataclass
class OllamaStatus:
    """Status information for ollama service."""

    state: OllamaState = OllamaState.UNAVAILABLE
    version: Optional[str] = None
    model: Optional[str] = None
    modelReady: bool = False
    availableModels: List[str] = field(default_factory=list)
    errorMessage: Optional[str] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'state': self.state.value,
            'version': self.version,
            'model': self.model,
            'modelReady': self.modelReady,
            'availableModels': self.availableModels,
            'errorMessage': self.errorMessage
        }


@dataclass
class ModelInfo:
    """Information about an installed model."""

    name: str
    size: int  # bytes
    digest: str
    modifiedAt: Optional[datetime] = None

    @property
    def sizeGb(self) -> float:
        """Get size in gigabytes."""
        return self.size / (1024 * 1024 * 1024)

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'size': self.size,
            'sizeGb': round(self.sizeGb, 2),
            'digest': self.digest,
            'modifiedAt': self.modifiedAt.isoformat() if self.modifiedAt else None
        }


# =============================================================================
# Exceptions
# =============================================================================

class OllamaError(Exception):
    """Base exception for ollama-related errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class OllamaNotAvailableError(OllamaError):
    """Raised when ollama is not installed or not running."""
    pass


class OllamaModelError(OllamaError):
    """Raised when model operations fail."""
    pass


# =============================================================================
# OllamaManager Class
# =============================================================================

class OllamaManager:
    """
    Manages ollama installation, model verification, and AI analysis readiness.

    This class provides a safe interface to the ollama local LLM server,
    gracefully handling cases where ollama is not installed or not running.
    When unavailable, AI features are simply disabled without affecting
    other system functionality.

    Attributes:
        config: Configuration dictionary with aiAnalysis settings
        _enabled: Whether AI analysis is enabled in config
        _ollamaAvailable: Whether ollama service is accessible
        _state: Current state of the ollama service

    Example:
        manager = OllamaManager(config=config)

        if manager.isReady():
            # AI features available
            pass
        else:
            # Continue without AI features
            pass
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize OllamaManager.

        Args:
            config: Optional configuration dictionary with aiAnalysis section
        """
        self._config = config or {}
        self._callbacks: Dict[str, List[Callable]] = {
            'state_change': [],
            'model_progress': [],
        }

        # Extract aiAnalysis config
        aiConfig = self._config.get('aiAnalysis', {})
        self._enabled = aiConfig.get('enabled', False)
        self._model = aiConfig.get('model', OLLAMA_DEFAULT_MODEL)
        self._baseUrl = aiConfig.get('ollamaBaseUrl', OLLAMA_DEFAULT_BASE_URL)

        # State tracking
        self._ollamaAvailable = False
        self._modelReady = False
        self._state = OllamaState.UNAVAILABLE
        self._version: Optional[str] = None
        self._errorMessage: Optional[str] = None

        # Initial availability check
        self._checkOllamaAvailable()

        if self._enabled:
            if self._ollamaAvailable:
                logger.info(f"Ollama available at {self._baseUrl}")
            else:
                logger.warning(
                    f"AI analysis enabled but ollama not available at {self._baseUrl}. "
                    "AI features will be disabled."
                )

    def _checkOllamaAvailable(self) -> bool:
        """
        Check if ollama service is available.

        Returns:
            True if ollama is running and accessible
        """
        try:
            url = f"{self._baseUrl}/"
            request = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(request, timeout=OLLAMA_HEALTH_TIMEOUT) as response:
                content = response.read().decode('utf-8')
                # Ollama returns "Ollama is running" on root endpoint
                if 'Ollama is running' in content or response.status == 200:
                    self._ollamaAvailable = True
                    self._state = OllamaState.AVAILABLE
                    self._errorMessage = None
                    logger.debug("Ollama service is available")
                    return True
        except urllib.error.URLError as e:
            self._errorMessage = f"Connection failed: {e.reason}"
            logger.debug(f"Ollama not available: {e.reason}")
        except Exception as e:
            self._errorMessage = str(e)
            logger.debug(f"Ollama availability check failed: {e}")

        self._ollamaAvailable = False
        self._state = OllamaState.UNAVAILABLE
        return False

    @property
    def isEnabled(self) -> bool:
        """Check if AI analysis is enabled in config."""
        return self._enabled

    def isReady(self) -> bool:
        """
        Check if ollama is ready for AI analysis.

        Returns:
            True if ollama is available and configured model is ready
        """
        if not self._enabled:
            return False
        if not self._ollamaAvailable:
            return False
        return self._modelReady

    @property
    def state(self) -> OllamaState:
        """Get current ollama state."""
        return self._state

    def refresh(self) -> OllamaStatus:
        """
        Refresh status by re-checking ollama availability.

        Returns:
            Updated OllamaStatus
        """
        oldState = self._state
        self._checkOllamaAvailable()

        if self._ollamaAvailable:
            self.verifyModel()

        if self._state != oldState:
            self._triggerCallbacks('state_change', self._state)

        return self.getStatus()

    def getVersion(self) -> Optional[str]:
        """
        Get ollama version.

        Returns:
            Version string or None if unavailable
        """
        if not self._ollamaAvailable:
            return None

        try:
            url = f"{self._baseUrl}/api/version"
            request = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(request, timeout=OLLAMA_API_TIMEOUT) as response:
                data = json.loads(response.read().decode('utf-8'))
                self._version = data.get('version')
                return self._version
        except Exception as e:
            logger.warning(f"Failed to get ollama version: {e}")
            return None

    def listModels(self) -> List[ModelInfo]:
        """
        List installed models.

        Returns:
            List of ModelInfo objects for installed models
        """
        if not self._ollamaAvailable:
            return []

        try:
            url = f"{self._baseUrl}/api/tags"
            request = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(request, timeout=OLLAMA_API_TIMEOUT) as response:
                data = json.loads(response.read().decode('utf-8'))
                models = []

                for model in data.get('models', []):
                    modifiedAt = None
                    if model.get('modified_at'):
                        try:
                            # Parse ISO format timestamp
                            modifiedAt = datetime.fromisoformat(
                                model['modified_at'].replace('Z', '+00:00')
                            )
                        except (ValueError, AttributeError):
                            pass

                    models.append(ModelInfo(
                        name=model.get('name', ''),
                        size=model.get('size', 0),
                        digest=model.get('digest', ''),
                        modifiedAt=modifiedAt
                    ))

                logger.debug(f"Found {len(models)} installed models")
                return models

        except Exception as e:
            logger.warning(f"Failed to list models: {e}")
            return []

    def verifyModel(self, modelName: Optional[str] = None) -> bool:
        """
        Verify that the specified model is installed.

        Args:
            modelName: Model name to verify (defaults to configured model)

        Returns:
            True if model is installed and ready
        """
        targetModel = modelName or self._model

        if not self._ollamaAvailable:
            self._modelReady = False
            return False

        models = self.listModels()
        modelNames = [m.name for m in models]

        # Check for exact match or prefix match (e.g., "gemma2:2b" matches "gemma2:2b")
        modelFound = False
        for name in modelNames:
            if name == targetModel or name.startswith(f"{targetModel}"):
                modelFound = True
                break

        self._modelReady = modelFound

        if modelFound:
            self._state = OllamaState.MODEL_READY
            logger.info(f"Model {targetModel} is ready")
        else:
            self._state = OllamaState.AVAILABLE
            logger.info(f"Model {targetModel} not found. Available: {modelNames}")

        return modelFound

    def pullModel(self, modelName: Optional[str] = None) -> bool:
        """
        Pull/download a model from ollama registry.

        Args:
            modelName: Model name to pull (defaults to configured model)

        Returns:
            True if pull was successful
        """
        targetModel = modelName or self._model

        if not self._ollamaAvailable:
            logger.warning("Cannot pull model - ollama not available")
            return False

        logger.info(f"Pulling model: {targetModel}")
        self._state = OllamaState.MODEL_DOWNLOADING
        self._triggerCallbacks('state_change', self._state)

        try:
            url = f"{self._baseUrl}/api/pull"
            payload = json.dumps({'name': targetModel}).encode('utf-8')
            request = urllib.request.Request(
                url,
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )

            with urllib.request.urlopen(
                request, timeout=OLLAMA_PULL_TIMEOUT
            ) as response:
                # Read the streaming response
                # Ollama returns JSON lines with progress
                content = response.read().decode('utf-8')

                # Check for success - the last line should indicate completion
                lines = content.strip().split('\n')
                for line in lines:
                    try:
                        data = json.loads(line)
                        status = data.get('status', '')
                        if 'success' in status.lower() or 'digest' in data:
                            logger.info(f"Successfully pulled model: {targetModel}")
                            self._modelReady = True
                            self._state = OllamaState.MODEL_READY
                            self._triggerCallbacks('state_change', self._state)
                            return True

                        # Report progress
                        if 'completed' in data and 'total' in data:
                            progress = data['completed'] / data['total'] * 100
                            self._triggerCallbacks('model_progress', {
                                'model': targetModel,
                                'progress': progress,
                                'status': status
                            })
                    except json.JSONDecodeError:
                        continue

                # Check if model is now available
                if self.verifyModel(targetModel):
                    return True

                logger.warning(f"Model pull completed but model not verified")
                return False

        except urllib.error.HTTPError as e:
            self._errorMessage = f"HTTP error: {e.code}"
            logger.error(f"Failed to pull model {targetModel}: {e}")
            self._state = OllamaState.ERROR
            return False
        except Exception as e:
            self._errorMessage = str(e)
            logger.error(f"Failed to pull model {targetModel}: {e}")
            self._state = OllamaState.ERROR
            return False

    def getStatus(self) -> OllamaStatus:
        """
        Get comprehensive status information.

        Returns:
            OllamaStatus object with current state
        """
        availableModels = []
        if self._ollamaAvailable:
            models = self.listModels()
            availableModels = [m.name for m in models]

            # Get version if not cached
            if not self._version:
                self.getVersion()

        return OllamaStatus(
            state=self._state,
            version=self._version,
            model=self._model,
            modelReady=self._modelReady,
            availableModels=availableModels,
            errorMessage=self._errorMessage
        )

    def generateInstallScript(self, platform: Optional[str] = None) -> str:
        """
        Generate installation script for ollama.

        Args:
            platform: Target platform ('linux', 'macos', 'windows')
                     Defaults to current platform if not specified

        Returns:
            Installation script as string
        """
        if platform is None:
            platform = sys.platform
            if platform.startswith('linux'):
                platform = 'linux'
            elif platform == 'darwin':
                platform = 'macos'
            elif platform == 'win32':
                platform = 'windows'

        if platform == 'linux':
            return """#!/bin/bash
# Ollama installation script for Linux
# Run with: bash install_ollama.sh

echo "Installing ollama..."
curl -fsSL https://ollama.com/install.sh | sh

# Start ollama service
ollama serve &

# Wait for service to start
sleep 5

# Pull the default model
echo "Pulling model: {model}..."
ollama pull {model}

echo "Installation complete!"
echo "Ollama is running at http://localhost:11434"
""".format(model=self._model)

        elif platform == 'macos':
            return """#!/bin/bash
# Ollama installation script for macOS
# Run with: bash install_ollama.sh

echo "Installing ollama..."
curl -fsSL https://ollama.com/install.sh | sh

# Pull the default model
echo "Pulling model: {model}..."
ollama pull {model}

echo "Installation complete!"
echo "Ollama is running at http://localhost:11434"
""".format(model=self._model)

        elif platform == 'windows':
            return """@echo off
REM Ollama installation script for Windows
REM Run from PowerShell or Command Prompt

echo Installing ollama...
REM Download from: https://ollama.com/download/windows
echo Please download and install from: https://ollama.com/download/windows
echo.
echo After installation, run:
echo   ollama pull {model}
echo.
echo Ollama will run at http://localhost:11434
""".format(model=self._model)

        else:
            return f"# Unsupported platform: {platform}\n# Visit https://ollama.com for installation instructions"

    def onStateChange(self, callback: Callable[[OllamaState], None]) -> None:
        """Register callback for state changes."""
        self._callbacks['state_change'].append(callback)

    def onModelProgress(
        self, callback: Callable[[Dict[str, Any]], None]
    ) -> None:
        """Register callback for model download progress."""
        self._callbacks['model_progress'].append(callback)

    def _triggerCallbacks(self, eventType: str, data: Any) -> None:
        """Trigger callbacks for an event type."""
        for callback in self._callbacks.get(eventType, []):
            try:
                callback(data)
            except Exception as e:
                logger.error(f"Callback error for {eventType}: {e}")


# =============================================================================
# Helper Functions
# =============================================================================

def createOllamaManagerFromConfig(config: Dict[str, Any]) -> OllamaManager:
    """
    Create an OllamaManager from configuration.

    Args:
        config: Configuration dictionary with aiAnalysis section

    Returns:
        Configured OllamaManager instance
    """
    return OllamaManager(config=config)


def isOllamaAvailable(config: Dict[str, Any]) -> bool:
    """
    Quick check if ollama is available and enabled.

    Args:
        config: Configuration dictionary

    Returns:
        True if AI analysis is enabled AND ollama is available
    """
    aiConfig = config.get('aiAnalysis', {})
    if not aiConfig.get('enabled', False):
        return False

    baseUrl = aiConfig.get('ollamaBaseUrl', OLLAMA_DEFAULT_BASE_URL)

    try:
        url = f"{baseUrl}/"
        request = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(request, timeout=OLLAMA_HEALTH_TIMEOUT) as response:
            return response.status == 200
    except Exception:
        return False


def getOllamaConfig(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract ollama configuration with defaults.

    Args:
        config: Configuration dictionary

    Returns:
        Ollama config section with defaults applied
    """
    aiConfig = config.get('aiAnalysis', {})
    return {
        'enabled': aiConfig.get('enabled', False),
        'model': aiConfig.get('model', OLLAMA_DEFAULT_MODEL),
        'baseUrl': aiConfig.get('ollamaBaseUrl', OLLAMA_DEFAULT_BASE_URL),
        'maxAnalysesPerDrive': aiConfig.get('maxAnalysesPerDrive', 1),
        'promptTemplate': aiConfig.get('promptTemplate', ''),
        'focusAreas': aiConfig.get('focusAreas', [])
    }
