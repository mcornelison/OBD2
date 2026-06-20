# TD-007: OLLAMA_GENERATE_TIMEOUT Not Configurable from Config

**Filed by**: Ralph Agent
**Date**: 2026-02-05
**Related Story**: US-OLL-002 (Increase Timeouts for Remote Network Latency)
**Priority**: Medium

## Problem

US-OLL-002 makes `apiTimeoutSeconds` (30s) and `healthTimeoutSeconds` (5s) configurable via `obd_config.json`. However, `OLLAMA_GENERATE_TIMEOUT` (120s, used for model inference in `analyzer.py`) remains hardcoded in `src/ai/types.py` line 54.

For remote servers with network latency, the generate timeout may also need adjustment.

## Current State

- `src/ai/types.py` line 54: `OLLAMA_GENERATE_TIMEOUT = 120`
- `src/ai/types.py` line 57: `OLLAMA_HEALTH_TIMEOUT = 5` (US-OLL-002 will make configurable)
- `src/ai/types.py` line 58: `OLLAMA_API_TIMEOUT = 30` (US-OLL-002 will make configurable)

## Suggested Fix

Add `aiAnalysis.generateTimeoutSeconds` to `obd_config.json` with default 120. Have `OllamaManager.__init__` or `AiAnalyzer.__init__` read it from config, falling back to the constant.

## Impact

Medium — 120s is generous for localhost but may be tight for a remote server under load. Should be configurable for consistency with the other two timeouts.
