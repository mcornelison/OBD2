# TD-008: _checkNetworkReachable Placement Design Decision

**Filed by**: Ralph Agent
**Date**: 2026-02-05
**Related Story**: US-OLL-003 (Add Network Reachability Pre-Check)
**Priority**: Low

## Problem

US-OLL-003 says to call `_checkNetworkReachable()` "before `_checkOllamaAvailable()` in the health check flow." However, `_checkOllamaAvailable()` is called in two places:

1. `OllamaManager.__init__()` — `src/ai/ollama.py` line 137
2. `OllamaManager.refresh()` — `src/ai/ollama.py` line 209

The story doesn't specify whether the network check should be:
- **(A)** Inside `_checkOllamaAvailable()` as an early-return pre-check (single call site, DRY)
- **(B)** Called separately by each caller before `_checkOllamaAvailable()` (two call sites)

## Suggested Approach

Option A (inside `_checkOllamaAvailable`) is cleaner:
- Single point of change
- Callers don't need to know about the network pre-check
- Follows the existing pattern where `_checkOllamaAvailable` is the single entry point for availability checking

## Impact

Low — both approaches work. This is a code organization preference. Ralph will implement Option A unless PM directs otherwise.
