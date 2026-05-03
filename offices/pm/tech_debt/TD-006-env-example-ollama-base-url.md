# TD-006: .env.example Missing OLLAMA_BASE_URL Documentation

**Filed by**: Ralph Agent
**Date**: 2026-02-05
**Related Story**: US-OLL-001 (Make Ollama Base URL Environment-Variable Configurable)
**Priority**: Low
**Status**: Resolved (2026-05-03, Sprint 23 US-271, Rex Session 149)

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
# OLLAMA_BASE_URL=http://10.27.27.10:11434
```

## Impact

Low — defaults work without it. But documentation prevents confusion during Pi deployment.

## Closure (2026-05-03, Sprint 23 US-271, Rex Session 149)

**Status**: Resolved.

### What was found at story-execution time
The TD-006 record (filed 2026-02-05) cited `obd_config.json` line 90 with a hardcoded `ollamaBaseUrl` and `.env.example` not listing `OLLAMA_BASE_URL` at all. Both premises were partially falsified by intervening work:

- `obd_config.json` was reorganized into the tier-aware `config.json`. The `ollamaBaseUrl` placeholder is in place at `config.json:547` -- `"ollamaBaseUrl": "${OLLAMA_BASE_URL:http://localhost:11434}"`. Original concern is satisfied.
- `.env.example` was reorganized into a "Server Configuration (Chi-Srv-01)" section and `OLLAMA_BASE_URL=http://localhost:11434` was added at line 81 with a one-line description. The variable IS documented; only the **remote-server example** from this TD's Suggested Fix was missing.

### What shipped
Three commented lines added after the existing OLLAMA_BASE_URL stanza in `.env.example` (additive per spec invariant):

```
# For Pi deployment, point at the remote Chi-Srv-01 instance instead:
# OLLAMA_BASE_URL=http://10.27.27.10:11434
# Resolved at runtime via the ${OLLAMA_BASE_URL:http://localhost:11434}
# placeholder in config.json (server.ai.ollamaBaseUrl).  See US-OLL-001.
```

This honors the original Suggested Fix's intent (commented remote-server example pointing Pi deployers at Chi-Srv-01) while preserving the existing uncommented default per US-271 invariant `Existing .env.example variable docs left untouched (additive only)`.

### Verification
- `grep -A4 OLLAMA_BASE_URL .env.example` -- shows existing default + new commented remote-server example + placeholder explanation
- `python offices/pm/scripts/sprint_lint.py` -- 0 errors / 0 warnings
- No source code, env-var-loading code, or `config.json` changes (doc-only per spec invariant)

### Pattern note
The TD record's premise was partially correct (remote-server example missing) but partially falsified (variable IS documented). Same shape as US-272/273 deliberate-divergence pattern — Refusal Rule 1 (ambiguity = blocker) does NOT apply because intent was unambiguous; the right move was to ship the functionally-correct subset of the spec and document the divergence.
