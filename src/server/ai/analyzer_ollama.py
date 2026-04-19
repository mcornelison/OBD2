################################################################################
# File Name: analyzer_ollama.py
# Purpose/Description: Ollama HTTP call + basic prompt fallback for AI analyzer
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-016
# 2026-04-14    | Sweep 5      | Extracted from analyzer.py (task 4 split)
# ================================================================================
################################################################################

"""
Ollama HTTP integration for the AI analyzer.

Provides:
- callOllama(): POST to /api/generate and return the response text
- callOllamaChat(): POST to /api/chat with system + user messages and return
  the response text (US-CMP-005, server spec §3.1)
- buildBasicPrompt(): fallback prompt renderer used when no template is available

These are module-level functions; the AiAnalyzer class delegates to them.
"""

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from .exceptions import AiAnalyzerGenerationError
from .types import OLLAMA_GENERATE_TIMEOUT

logger = logging.getLogger(__name__)


# ---- Sentinel exceptions to distinguish transport vs protocol failures ------

class OllamaUnreachableError(Exception):
    """Raised when the Ollama host is unreachable (connection/timeout).

    Separated from :class:`AiAnalyzerGenerationError` so the API layer can
    surface a 503 (vs 502 for HTTP-level errors). Message carries the
    underlying reason for logging.
    """


class OllamaHttpError(Exception):
    """Raised when Ollama returns a non-2xx HTTP status.

    Carries the HTTP status code on ``code`` so the service layer can log it.
    The API layer maps this to 502.
    """

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def callOllama(baseUrl: str, model: str, prompt: str) -> str:
    """
    Call the ollama /api/generate endpoint and return the generated text.

    Args:
        baseUrl: Ollama base URL (e.g., "http://localhost:11434")
        model: Model name to use (e.g., "llama3.1:8b")
        prompt: Prompt to send to the model

    Returns:
        Generated response text

    Raises:
        AiAnalyzerGenerationError: If generation fails
    """
    url = f"{baseUrl}/api/generate"
    try:
        payload = json.dumps({
            'model': model,
            'prompt': prompt,
            'stream': False,
        }).encode('utf-8')

        request = urllib.request.Request(
            url,
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )

        logger.debug(f"Calling ollama API | model={model}")

        with urllib.request.urlopen(
            request, timeout=OLLAMA_GENERATE_TIMEOUT
        ) as response:
            data = json.loads(response.read().decode('utf-8'))
            generatedText = data.get('response', '')

            if not generatedText:
                raise AiAnalyzerGenerationError(
                    "Empty response from ollama",
                    details={'response': data},
                )

            logger.debug(
                f"Ollama response received | length={len(generatedText)} chars"
            )
            return generatedText

    except urllib.error.HTTPError as e:
        raise AiAnalyzerGenerationError(
            f"Ollama API error: HTTP {e.code}",
            details={'url': url, 'code': e.code},
        ) from e
    except urllib.error.URLError as e:
        raise AiAnalyzerGenerationError(
            f"Failed to connect to ollama: {e.reason}",
            details={'url': url, 'error': str(e)},
        ) from e
    except json.JSONDecodeError as e:
        raise AiAnalyzerGenerationError(
            f"Invalid JSON response from ollama: {e}",
            details={'error': str(e)},
        ) from e
    except AiAnalyzerGenerationError:
        raise
    except Exception as e:
        raise AiAnalyzerGenerationError(
            f"Ollama generation failed: {e}",
            details={'error': str(e)},
        ) from e


def callOllamaChat(
    baseUrl: str,
    model: str,
    systemMessage: str,
    userMessage: str,
    timeoutSeconds: int = OLLAMA_GENERATE_TIMEOUT,
) -> str:
    """
    Call the Ollama ``/api/chat`` endpoint with ``stream: false`` and return
    the assistant content.

    Used by the run-phase analysis service (US-CMP-005). Separating system and
    user messages lets Ollama cache the invariant Spool persona and only
    re-tokenize the per-drive analytics payload on each call.

    Args:
        baseUrl: Ollama base URL (e.g. ``"http://10.27.27.10:11434"``).
        model: Target model (e.g. ``"llama3.1:8b"``).
        systemMessage: System role content (Spool's invariant instructions).
        userMessage: User role content (rendered per-drive analytics).
        timeoutSeconds: Request timeout; defaults to
            :data:`OLLAMA_GENERATE_TIMEOUT` (120 s per server spec §3.1).

    Returns:
        The assistant content string (no parsing applied).

    Raises:
        OllamaUnreachableError: Connection, DNS, or socket-level failure.
        OllamaHttpError: Ollama responded with a non-2xx HTTP status.
        AiAnalyzerGenerationError: Response body cannot be parsed as JSON or
            contains no assistant content.
    """
    url = f"{baseUrl}/api/chat"
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": systemMessage},
                {"role": "user", "content": userMessage},
            ],
            "stream": False,
        },
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeoutSeconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise OllamaHttpError(
            f"Ollama HTTP {e.code}: {e.reason}", code=e.code,
        ) from e
    except urllib.error.URLError as e:
        raise OllamaUnreachableError(f"Ollama unreachable: {e.reason}") from e
    except (TimeoutError, OSError) as e:
        raise OllamaUnreachableError(f"Ollama unreachable: {e}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise AiAnalyzerGenerationError(
            f"Invalid JSON from Ollama /api/chat: {e}",
            details={"raw": raw[:500]},
        ) from e

    message = data.get("message") or {}
    content = message.get("content", "")
    if not content:
        raise AiAnalyzerGenerationError(
            "Ollama /api/chat returned empty message.content",
            details={"response_keys": sorted(data.keys())},
        )
    return content


def buildBasicPrompt(metrics: dict[str, Any]) -> str:
    """
    Build a basic prompt without the template module.

    Used as a fallback when AiPromptTemplate is not available.

    Args:
        metrics: Dictionary of metric values

    Returns:
        Basic prompt string with N/A filled in for missing metrics
    """
    prompt = """You are an automotive performance tuning expert. Based on this drive data:

RPM: avg={rpm_avg}, max={rpm_max}
Fuel Trim: short={short_fuel_trim_avg}%, long={long_fuel_trim_avg}%
Engine Load: avg={engine_load_avg}%, max={engine_load_max}%
Throttle: avg={throttle_pos_avg}%
MAF: avg={maf_avg} g/s

Please provide:
1. Air/fuel ratio assessment
2. Performance optimization recommendations
3. Potential issues to investigate
4. 3-5 actionable recommendations
"""
    # Define all expected placeholders
    allPlaceholders = [
        'rpm_avg', 'rpm_max', 'short_fuel_trim_avg', 'long_fuel_trim_avg',
        'engine_load_avg', 'engine_load_max', 'throttle_pos_avg', 'maf_avg',
    ]

    # Substitute metrics, using N/A for missing ones
    for placeholder in allPlaceholders:
        value = metrics.get(placeholder)
        fullPlaceholder = '{' + placeholder + '}'
        prompt = prompt.replace(
            fullPlaceholder,
            str(value) if value is not None else 'N/A',
        )

    return prompt
