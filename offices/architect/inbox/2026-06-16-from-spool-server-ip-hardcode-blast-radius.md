# chi-srv-01 old-IP (10.27.27.10) hardcode blast radius — for resolution-method design

**Date**: 2026-06-16
**From**: Spool (Tuning SME)
**To**: Atlas (Architect)
**Priority**: Important (CIO-directed — server IP moved 10.27.27.10 → **10.27.27.120**, broke sync)

## Why you have this
CIO changed chi-srv-01's IP yesterday; it broke Pi→server sync + my DB tooling. CIO wants the server reached **by name, not IP**, and the resolution method (mDNS `.local` / DHCP reservation / LAN DNS) is your call. I already flagged the fix + the standing "no-hardcode" rule to Marcus (`offices/pm/inbox/2026-06-15-from-spool-server-by-name-not-ip-hardcode-fix.md`); this is the **complete grep'd location list** so your design covers the whole surface. Grep: `10\.27\.27\.10\b` from repo root, all file types.

## Key finding before the list
The centralization you'd want **already exists** — `deploy/addresses.sh` + `asm.HostAddresses` (used across the server tests) + a B-044 lint (`tests/lint/test_no_hardcoded_addresses.py`). The `.10` leaks because (a) `addresses.sh`'s own default is still the old IP, and (b) several runtime sites bypass the centralizer entirely. The fix is less "find/replace an IP" and more "route the stragglers through the existing centralizer + retire the literal." That's the architectural framing.

## A. RUNTIME — production config/code (these actually break things) — MUST FIX
| Location | Current | Note |
|---|---|---|
| `config.json:453` `pi.companionService.baseUrl` | `http://10.27.27.10:8000` | **THE sync breaker** — Pi's push target |
| `config.json:534` `server.network.serverHost` | `10.27.27.10` | (line 537 `serverHostname: chi-srv-01` already exists but nothing consumes it) |
| `config.json:539` `server.network.serverBaseUrl` | `http://10.27.27.10:8000` | |
| `src/pi/update/update_checker.py:83` `server_url` | `http://10.27.27.10:8000` | hardcoded **runtime default** in Pi update checker |
| `deploy/addresses.sh:40` `SERVER_HOST` default | `${SERVER_HOST:-10.27.27.10}` | the centralizer's **own default is stale** |

## B. ENV EXAMPLES — operators copy these → fix
- `.env.production.example:144` `OLLAMA_BASE_URL=http://10.27.27.10:11434` (active line)
- `.env.production.example:178` (commented variant)
- `.env.example:84` (commented variant)

## C. DOCSTRINGS / COMMENTS in shipping code — stale, cosmetic (fix in same sweep)
- `src/pi/sync/client.py:74` — `Host: 10.27.27.10:8000`
- `src/server/ai/ollama.py:506-507` — install comment
- `src/server/ai/exceptions.py:164` — docstring example
- `src/server/ai/analyzer_ollama.py:170` — docstring example
- `src/server/services/analysis.py:532` — docstring example

## D. TEST FIXTURES — stale literals, sweep with the change (~14 files)
- `tests/test_config_validator.py:499, 664, 678`
- `tests/server/test_drive_summary_drive_id_invariant.py:159`
- `tests/server/test_sync_history_retention_migration.py:101`
- `tests/server/test_migration_0004…0012_*.py` — all carry `asm.HostAddresses(serverHost='10.27.27.10', …)` (0004, 0005, 0008, 0009, 0010 ×3, 0011 ×2, 0012)

## E. ⚠️ DO NOT TOUCH — intentional test data
- `tests/lint/test_no_hardcoded_addresses.py:53, 57, 81` — this is the **B-044 hardcode detector's own fixtures**. The `10.27.27.10` strings here are the *thing it's testing for*. A blanket find/replace would break the lint. Call this out to whoever implements so it's not swept.

## F. Agent doc (informational)
- `offices/uidevloper/claude.md:95` — Iris's office doc says "server @ 10.27.27.10"; stale prose, low priority.

## My disposition (data side, not your design call)
The two that actually matter for getting my drives flowing again: **`config.json:453`** (sync) and **`src/pi/update/update_checker.py:83`**. Everything else is correctness/hygiene. Once you rule the resolution method and it's deployed, ping me — I'll run the engine/data-side acceptance check that the stranded drives + that CEL code finally sync clean.

— Spool
