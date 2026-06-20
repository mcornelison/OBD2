# PRD: Remove Local Ollama References from Codebase

**Parent Backlog Item**: B-024
**Status**: Active
**Dependencies**: B-016 (complete)

## Introduction

The codebase contains references suggesting Ollama runs locally on the Pi 5 (localhost:11434). Per CIO decision (Session 6), Ollama **always** runs on Chi-Srv-01 (10.27.27.10). The Pi connects remotely over DeathStarWiFi. This PRD cleans up misleading references while preserving the functional `${OLLAMA_BASE_URL}` env var mechanism from B-016.

## Goals

- Remove misleading "local Ollama" language from docs, comments, and docstrings
- Fix stale IPs (10.27.27.100 → 10.27.27.10) in agent knowledge bases
- Correct Pi 5 hardware description (8GB RAM is for app headroom, not AI)
- Zero functional code changes — this is documentation/comment cleanup only

## Scope

### What to Clean Up

| File | Line(s) | Issue | Action |
|------|---------|-------|--------|
| `specs/architecture.md:90` | "8GB RAM for AI inference" | Pi doesn't do AI inference | Change to "8GB RAM for application headroom" |
| `specs/glossary.md:122` | "A local LLM inference server" | Says "local" without context | Clarify remote on Chi-Srv-01 in production |
| `src/ai/ollama.py:25,92` | "ollama local LLM server" | Describes as "local" | Change to "ollama LLM server (local dev or remote production)" |
| `src/ai/ollama.py:520,536,551` | localhost:11434 in setup guide comments | Suggests local install | Update comments to reference Chi-Srv-01 remote setup |
| `src/ai/analyzer.py:21,77` | "through a local ollama model" | Suggests local | Clarify remote in production |
| `src/ai/exceptions.py:162` | "default: http://localhost:11434" | Suggests localhost is normal | Clarify this is dev default; production uses remote |
| `src/obd/ai_analyzer.py:24` | "through a local ollama model" | Legacy re-export, same issue | Same fix |
| `src/obd/ollama_manager.py:24` | "ollama local LLM server" | Legacy re-export, same issue | Same fix |
| `ralph/agent.md:490` | IP 10.27.27.100 | Stale IP | Fix to 10.27.27.10 |
| `ralph/agent-pi.md:20` | IP 10.27.27.100 | Stale IP | Fix to 10.27.27.10 |

### What NOT to Change

- `src/ai/types.py:55` — `OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"` — this is a valid dev default
- `src/obd_config.json:90` — `${OLLAMA_BASE_URL:http://localhost:11434}` — env var mechanism from B-016, correct as-is
- `src/obd/config/loader.py:120` — fallback default, functional code
- `src/obd/obd_config_loader.py:125` — fallback default, functional code
- Test files — mocks are fine regardless of localhost/remote
- Ralph archive files — historical records

## User Stories

### US-104: Clean Up Documentation and Architecture References

**Description:** As a developer, I need architecture docs and agent knowledge bases to accurately reflect that Ollama is remote-only, with correct IPs.

**Acceptance Criteria:**
- [ ] `specs/architecture.md:90`: Change "8GB RAM for AI inference" to "8GB RAM for application headroom"
- [ ] `specs/glossary.md:122`: Update ollama definition to clarify remote on Chi-Srv-01 in production
- [ ] `ralph/agent.md:490`: Fix IP from 10.27.27.100 to 10.27.27.10
- [ ] `ralph/agent-pi.md:20`: Fix IP from 10.27.27.100 to 10.27.27.10
- [ ] Scan all `specs/*.md` and `ralph/*.md` for any remaining "local ollama" or stale IP references
- [ ] All tests pass, typecheck passes

### US-105: Clean Up Source Code Comments and Docstrings

**Description:** As a developer, I need code comments and docstrings to stop suggesting Ollama runs locally on the Pi.

**Acceptance Criteria:**
- [ ] `src/ai/ollama.py:25,92`: Change "ollama local LLM server" to "ollama LLM server (local dev or remote production)"
- [ ] `src/ai/ollama.py:520,536,551`: Update setup guide comments to reference remote Chi-Srv-01 or clarify dev-only
- [ ] `src/ai/analyzer.py:21,77`: Change "local ollama model" to clarify remote in production
- [ ] `src/ai/exceptions.py:162`: Update docstring to clarify localhost is dev default, production uses `OLLAMA_BASE_URL` env var
- [ ] `src/obd/ai_analyzer.py:24` and `src/obd/ollama_manager.py:24`: Update legacy re-export module docstrings to match
- [ ] Do NOT change any functional code, constants, or config defaults
- [ ] Do NOT change test files
- [ ] All tests pass, typecheck passes

### US-106: Verify No Remaining Local Ollama References

**Description:** As a developer, I need a verification pass confirming no misleading "local Ollama on Pi" references remain.

**Acceptance Criteria:**
- [ ] Run `grep -r "local.*ollama\|ollama.*local" src/ specs/ ralph/*.md` (case-insensitive) — no misleading hits
- [ ] Run `grep -r "10\.27\.27\.100" specs/ ralph/ pm/` — no stale IP hits (archive/ excluded)
- [ ] Document any intentional localhost references that remain (dev defaults) in a brief note in the PR/commit message
- [ ] All tests pass, typecheck passes

## Functional Requirements

- FR-1: Zero functional code changes — only comments, docstrings, and documentation
- FR-2: All 408 tests must still pass after cleanup
- FR-3: Typecheck must pass

## Non-Goals

- No refactoring of OllamaManager (it already works with remote URLs)
- No changes to config defaults (env var override from B-016 handles this)
- No changes to test mocking patterns

## Success Metrics

- `grep -ri "local.*ollama\|ollama.*local" src/ specs/ ralph/*.md` returns zero misleading results
- `grep -r "10.27.27.100" specs/ ralph/ pm/prds/ pm/backlog/` returns zero results
- All tests pass
