# TD-006: .env.example Missing OLLAMA_BASE_URL Documentation

**Filed by**: Ralph Agent
**Date**: 2026-02-05
**Related Story**: US-OLL-001 (Make Ollama Base URL Environment-Variable Configurable)
**Priority**: Low

## Problem

US-OLL-001 changes `ollamaBaseUrl` in `obd_config.json` from a hardcoded URL to `${OLLAMA_BASE_URL:http://localhost:11434}`. However, the story does not include updating `.env.example` to document this new environment variable.

Without documentation in `.env.example`, developers and the Pi deployment won't know this override exists.

## Current State

- `obd_config.json` line 90: `"ollamaBaseUrl": "http://localhost:11434"` (hardcoded)
- `.env.example`: Does not list `OLLAMA_BASE_URL`

## Suggested Fix

Add to `.env.example`:
```
# Ollama AI server URL (default: http://localhost:11434)
# Set for remote server (e.g., Chi-Srv-01):
# OLLAMA_BASE_URL=http://10.27.27.100:11434
```

## Impact

Low — defaults work without it. But documentation prevents confusion during Pi deployment.
