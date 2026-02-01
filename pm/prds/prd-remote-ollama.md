# PRD: Remote Ollama Server Integration

**Parent Backlog Item**: B-016
**Status**: Active

## Introduction

Configure and verify the Eclipse OBD-II application to connect to **Chi-srv-01**, the dedicated Ollama/LLM server on the home network (DeathStarWiFi). Ollama will **never** run locally on the Pi 5 -- all LLM work is offloaded to Chi-srv-01.

**Key finding from code review**: The Ollama URL is already configurable via `aiAnalysis.ollamaBaseUrl` in `src/obd_config.json`. Health checks, graceful fallback, and timeout handling already exist in `src/ai/ollama.py`. The main work is:

1. Verifying remote connectivity works end-to-end
2. Adding a network reachability pre-check (WiFi may not be available while driving)
3. Adjusting timeouts for network latency vs localhost
4. Writing setup documentation for Chi-srv-01
5. Testing with mocked remote endpoints

**Note**: The companion service on Chi-srv-01 is a separate backlog item (B-022). This PRD covers the EclipseTuner (Pi 5) side only.

## Goals

- Verify remote Ollama works with existing config-driven URL (Chi-srv-01)
- Add network-aware pre-check before AI analysis attempts
- Document Chi-srv-01 Ollama setup for CIO
- Ensure graceful behavior when remote server is unreachable (driving, off DeathStarWiFi)

## Existing Infrastructure

Already implemented -- developer should use, not recreate:

| Component | File | Key Details |
|-----------|------|-------------|
| OllamaManager | `src/ai/ollama.py:88-150` | Constructor reads `ollamaBaseUrl` from config |
| Health check | `src/ai/ollama.py:152-180` | `_checkOllamaAvailable()` hits root endpoint |
| Model verify | `src/ai/ollama.py:286-321` | `verifyModel()` checks model is loaded |
| Timeout constants | `src/ai/types.py:56-60` | Health=5s, API=30s, Pull=600s |
| Graceful fallback | `src/ai/ollama.py:143-150` | Logs warning, disables AI, continues |
| State tracking | `src/ai/types.py:366-373` | `OllamaState` enum (UNAVAILABLE, AVAILABLE, MODEL_READY, etc.) |
| Config | `src/obd_config.json:87-94` | `aiAnalysis.ollamaBaseUrl` default `http://localhost:11434` |
| Factory functions | `src/ai/ollama.py:526-582` | `createOllamaManagerFromConfig()`, `isOllamaAvailable()` |

### Current Config Structure

```json
"aiAnalysis": {
    "enabled": false,
    "model": "${AI_MODEL:gemma2:2b}",
    "ollamaBaseUrl": "http://localhost:11434",
    "maxAnalysesPerDrive": 1,
    "promptTemplate": "${AI_PROMPT_TEMPLATE:}",
    "focusAreas": ["air_fuel_ratio", "timing", "throttle_response"]
}
```

### Architecture

```
EclipseTuner (Pi 5, in car)      Chi-srv-01 (home, DeathStarWiFi)
┌──────────────┐    WiFi/LAN     ┌──────────────────┐
│ Eclipse App  │ ── HTTP ──────> │  Ollama Service   │
│              │    :11434       │  gemma2:2b model  │
│ Post-drive   │ <── JSON ───── │                    │
│ analysis     │                 │                    │
└──────────────┘                 └──────────────────┘
```

AI analysis only runs post-drive (vehicle parked, likely on home WiFi). Network availability during driving is not a concern.

## User Stories

### US-OLL-001: Make Ollama Base URL Environment-Variable Configurable

**Description:** As a developer, I need the Ollama base URL to support environment variable substitution so the Pi can use a different URL than the dev machine without changing config.json.

**Acceptance Criteria:**
- [ ] Change `ollamaBaseUrl` in `src/obd_config.json` from `"http://localhost:11434"` to `"${OLLAMA_BASE_URL:http://localhost:11434}"`
- [ ] Verify `secrets_loader.py` resolves the placeholder correctly (it already supports `${VAR:default}` syntax)
- [ ] Dev machine continues to work with localhost default (no `.env` change needed)
- [ ] Pi can override via `.env`: `OLLAMA_BASE_URL=http://192.168.1.100:11434`
- [ ] All existing tests pass (the default value is unchanged)
- [ ] Typecheck passes

### US-OLL-002: Increase Timeouts for Remote Network Latency

**Description:** As a developer, I need the API timeout to be configurable for remote servers where network latency adds to response time.

**Acceptance Criteria:**
- [ ] Add `aiAnalysis.apiTimeoutSeconds` to `src/obd_config.json` with default `60` (was hardcoded 30s in `types.py`)
- [ ] Add `aiAnalysis.healthTimeoutSeconds` to `src/obd_config.json` with default `10` (was hardcoded 5s in `types.py`)
- [ ] `OllamaManager.__init__` reads these values from config, falling back to the current constants if not present
- [ ] Pass configurable timeout to `urllib.request.urlopen()` calls instead of the constants
- [ ] Existing tests continue to pass (defaults are compatible)
- [ ] Typecheck passes

### US-OLL-003: Add Network Reachability Pre-Check

**Description:** As a developer, I need the AI module to check network reachability to the Ollama host before attempting analysis, so it fails fast when WiFi is unavailable.

**Acceptance Criteria:**
- [ ] Add a `_checkNetworkReachable(self) -> bool` method to `OllamaManager`
- [ ] Method extracts hostname from `self._baseUrl` and attempts a socket connection on the configured port with a 3-second timeout
- [ ] Method is called before `_checkOllamaAvailable()` in the health check flow
- [ ] If network unreachable: sets state to `UNAVAILABLE`, logs `"Network unreachable: <host>:<port>"` at DEBUG level
- [ ] If network reachable: proceeds to normal Ollama health check
- [ ] Does not affect behavior when Ollama is on localhost (socket connect to localhost is fast)
- [ ] All existing tests pass, typecheck passes

### US-OLL-004: Write Tests for Remote Ollama Scenarios

**Description:** As a developer, I need tests that verify the OllamaManager works correctly with remote URLs and handles failure scenarios.

**Acceptance Criteria:**
- [ ] Create `tests/test_remote_ollama.py` with standard file header
- [ ] Test: OllamaManager initializes with a non-localhost URL from config
- [ ] Test: `_checkNetworkReachable` returns `False` for an unreachable host (use a non-routable IP like `192.0.2.1`)
- [ ] Test: `_checkNetworkReachable` returns `True` when socket connects (mock socket)
- [ ] Test: Health check skips Ollama HTTP check when network is unreachable
- [ ] Test: Configurable timeouts are read from config and used in requests (mock urllib)
- [ ] Test: `ollamaBaseUrl` with `${OLLAMA_BASE_URL:default}` resolves correctly through secrets_loader
- [ ] Test: State is `UNAVAILABLE` when remote server is down, with appropriate error message
- [ ] Test: Graceful fallback -- AI analysis returns without crash when remote is unreachable
- [ ] Tests use `monkeypatch` or `unittest.mock` for network operations (no real network calls)
- [ ] All tests pass, typecheck passes

### US-OLL-005: Create Ollama Server Setup Documentation

**Description:** As the CIO, I need documentation on how to set up the Ollama server on my home network so the Pi can connect to it.

**Acceptance Criteria:**
- [ ] Create `docs/ollama-server-setup.md`
- [ ] Document: choosing a host machine (minimum specs: 8GB RAM, GPU recommended)
- [ ] Document: installing Ollama on the server (`curl -fsSL https://ollama.com/install.sh | sh`)
- [ ] Document: configuring Ollama to listen on all interfaces (`OLLAMA_HOST=0.0.0.0`)
- [ ] Document: pulling the required model (`ollama pull gemma2:2b`)
- [ ] Document: verifying the server is accessible (`curl http://<server-ip>:11434/`)
- [ ] Document: firewall rules (allow port 11434 from Pi IP or LAN subnet)
- [ ] Document: Pi-side configuration (set `OLLAMA_BASE_URL` in `.env`)
- [ ] Document: troubleshooting (connection refused, timeout, model not found)
- [ ] Document: optional systemd service for auto-start on the server
- [ ] Typecheck passes (n/a for docs, but no code changes should break typecheck)

## Functional Requirements

- FR-1: Default behavior unchanged -- localhost:11434 continues to work without any `.env` changes
- FR-2: Remote URL fully configurable via environment variable (`OLLAMA_BASE_URL`)
- FR-3: Network pre-check must not add noticeable latency on localhost
- FR-4: All failure modes log clearly and never crash the application
- FR-5: Timeouts configurable in `obd_config.json`, not hardcoded

## Non-Goals

- No auto-discovery of Ollama servers on the network (use explicit IP)
- No VPN or remote-access setup (home network only)
- No model management UI (use `ollama` CLI directly on the server)
- No changes to AI analysis logic, prompts, or recommendation ranking

## Design Considerations

- The `OllamaManager` already handles localhost gracefully. Changes should be minimal -- mainly making hardcoded values configurable and adding the network pre-check.
- Socket-level reachability check is faster than HTTP health check and avoids long timeouts when the network is down entirely.
- The `${VAR:default}` pattern is already used for `AI_MODEL` in the config. Extending it to `ollamaBaseUrl` is consistent.
- Keep the existing `OllamaState` enum -- no new states needed. `UNAVAILABLE` covers both "localhost down" and "remote unreachable".

## Success Metrics

- Pi connects to remote Ollama and generates AI recommendations post-drive
- Application starts cleanly when remote Ollama is unreachable (driving, no WiFi)
- Developer can switch between localhost and remote by changing one `.env` variable

## Open Questions

- None
