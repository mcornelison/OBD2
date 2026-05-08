################################################################################
# File Name: test_ollama_generate_timeout_configurable.py
# Purpose/Description: Pin US-290 / TD-007 close -- generateTimeoutSeconds is
#                      readable from config.json under server.ai.* and flows
#                      through AiAnalyzer + callOllama; OLLAMA_GENERATE_TIMEOUT
#                      remains the back-compat fallback.
# Author: Rex (Ralph)
# Creation Date: 2026-05-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-07    | Rex (US-290) | Initial -- 6 tests across 3 classes pin the
#                                config-driven generate-timeout path. Pre-fix
#                                ALL FAIL: AiAnalyzer has no _generateTimeoutSeconds
#                                attr; callOllama has no timeoutSeconds param;
#                                validator DEFAULTS lacks the key.
# ================================================================================
################################################################################

"""
US-290 (TD-007 close) -- ``server.ai.generateTimeoutSeconds`` configurability.

Three concerns covered, each as its own class:

1. ``TestAiAnalyzerReadsTimeoutFromConfig`` -- the Pi/server tier consumer
   (``AiAnalyzer.__init__``) reads the new key from the validated
   ``server.ai`` section and falls back to ``OLLAMA_GENERATE_TIMEOUT`` when
   the key is absent.
2. ``TestCallOllamaAcceptsTimeoutParam`` -- the underlying HTTP transport
   (``analyzer_ollama.callOllama``) accepts a ``timeoutSeconds`` kwarg and
   forwards it to ``urllib.request.urlopen(timeout=...)``. Default still
   the constant for back-compat.
3. ``TestValidatorDefaultsHasGenerateTimeoutKey`` -- the common validator
   ships ``server.ai.generateTimeoutSeconds: 120`` in its DEFAULTS map and
   injects it into a config that omits the key.

These tests fail RED pre-implementation: AiAnalyzer has no
``_generateTimeoutSeconds`` attr; callOllama has no ``timeoutSeconds`` param;
validator DEFAULTS lacks the key. Post-implementation all six pass.
"""

from __future__ import annotations

from typing import Any

import pytest  # noqa: I001 -- isolated import; future-annotations only

# =============================================================================
# Class 1: TestAiAnalyzerReadsTimeoutFromConfig
# =============================================================================


class TestAiAnalyzerReadsTimeoutFromConfig:
    """AiAnalyzer reads server.ai.generateTimeoutSeconds with constant fallback."""

    def test_analyzerReadsCustomGenerateTimeoutFromConfig(self) -> None:
        """
        Given: config has server.ai.generateTimeoutSeconds = 180
        When: AiAnalyzer is constructed
        Then: analyzer._generateTimeoutSeconds == 180
        """
        from src.server.ai.analyzer import AiAnalyzer

        config: dict[str, Any] = {
            'pi': {},
            'server': {
                'ai': {
                    'enabled': True,
                    'generateTimeoutSeconds': 180,
                },
            },
        }

        analyzer = AiAnalyzer(config=config)

        assert analyzer._generateTimeoutSeconds == 180

    def test_analyzerFallsBackToConstantWhenKeyMissing(self) -> None:
        """
        Given: config has no server.ai.generateTimeoutSeconds
        When: AiAnalyzer is constructed
        Then: analyzer._generateTimeoutSeconds == OLLAMA_GENERATE_TIMEOUT (120)
        """
        from src.server.ai.analyzer import AiAnalyzer
        from src.server.ai.types import OLLAMA_GENERATE_TIMEOUT

        config: dict[str, Any] = {
            'pi': {},
            'server': {
                'ai': {
                    'enabled': True,
                },
            },
        }

        analyzer = AiAnalyzer(config=config)

        assert analyzer._generateTimeoutSeconds == OLLAMA_GENERATE_TIMEOUT


# =============================================================================
# Class 2: TestCallOllamaAcceptsTimeoutParam
# =============================================================================


class _FakeUrlopenResponse:
    """Context-managed stand-in for ``urlopen`` return value."""

    def __init__(self, payload: bytes = b'{"response": "ok"}') -> None:
        self._payload = payload

    def __enter__(self) -> _FakeUrlopenResponse:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


class TestCallOllamaAcceptsTimeoutParam:
    """analyzer_ollama.callOllama accepts timeoutSeconds and forwards to urlopen."""

    def test_callOllamaPassesTimeoutToUrlopen(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: callOllama is invoked with timeoutSeconds=42
        When: it dispatches to urlopen
        Then: urlopen receives timeout=42 (kwarg propagation)
        """
        from src.server.ai import analyzer_ollama

        captured: dict[str, Any] = {}

        def _fakeUrlopen(req: Any, timeout: Any = None) -> _FakeUrlopenResponse:
            captured['timeout'] = timeout
            return _FakeUrlopenResponse()

        monkeypatch.setattr(
            'urllib.request.urlopen', _fakeUrlopen
        )

        analyzer_ollama.callOllama(
            'http://localhost:11434', 'gemma2:2b', 'hi', timeoutSeconds=42
        )

        assert captured['timeout'] == 42

    def test_callOllamaDefaultsToConstantWhenTimeoutNotProvided(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: callOllama is invoked without timeoutSeconds
        When: it dispatches to urlopen
        Then: urlopen receives timeout=OLLAMA_GENERATE_TIMEOUT (120)
        """
        from src.server.ai import analyzer_ollama
        from src.server.ai.types import OLLAMA_GENERATE_TIMEOUT

        captured: dict[str, Any] = {}

        def _fakeUrlopen(req: Any, timeout: Any = None) -> _FakeUrlopenResponse:
            captured['timeout'] = timeout
            return _FakeUrlopenResponse()

        monkeypatch.setattr(
            'urllib.request.urlopen', _fakeUrlopen
        )

        analyzer_ollama.callOllama(
            'http://localhost:11434', 'gemma2:2b', 'hi'
        )

        assert captured['timeout'] == OLLAMA_GENERATE_TIMEOUT


# =============================================================================
# Class 3: TestValidatorDefaultsHasGenerateTimeoutKey
# =============================================================================


class TestValidatorDefaultsHasGenerateTimeoutKey:
    """Common validator DEFAULTS declares server.ai.generateTimeoutSeconds: 120."""

    def test_defaultsRegistryDeclaresGenerateTimeoutKey(self) -> None:
        """
        Given: src.common.config.validator.DEFAULTS
        When: looking up 'server.ai.generateTimeoutSeconds'
        Then: value is 120 (matches sibling apiTimeoutSeconds/healthTimeoutSeconds
              pattern + grounded TD-007 suggested fix)
        """
        from src.common.config.validator import DEFAULTS

        assert DEFAULTS.get('server.ai.generateTimeoutSeconds') == 120

    def test_validatorInjectsGenerateTimeoutDefaultWhenAbsent(self) -> None:
        """
        Given: a tier-aware config with server.ai.* but no generateTimeoutSeconds
        When: validateConfig runs
        Then: server.ai.generateTimeoutSeconds is injected with value 120
        """
        from src.common.config.validator import validateConfig

        config: dict[str, Any] = {
            'protocolVersion': '1.0.0',
            'schemaVersion': '1.0.0',
            'deviceId': 'test-device',
            'pi': {},
            'server': {
                'ai': {
                    'enabled': False,
                },
            },
        }

        validated = validateConfig(config)

        assert validated['server']['ai']['generateTimeoutSeconds'] == 120
