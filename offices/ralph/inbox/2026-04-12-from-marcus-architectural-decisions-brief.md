# Architectural Decisions Brief — For Ralph
**Date**: 2026-04-12
**From**: Marcus (PM)
**To**: Ralph (Developer Agent)
**Priority**: Informational — Read when touching related code
**Subject**: Open architectural decisions and tech debt with architectural scope

---

## Purpose

This brief lists all open architectural decisions and tech debt items with architectural scope that Marcus has been tracking. The CIO will work with Ralph to determine the best solutions when these come up in sprint work. This is NOT a sprint assignment — it's a reference document so Ralph has the full picture of architectural intent and open questions.

**How to use this**: When a sprint touches any of these areas, read the relevant section here first. If a sprint story intersects with one of these open questions, flag it to the CIO before starting implementation — we may need to resolve the architectural question first.

---

## Open Architectural Decisions

### 1. Deprecate Legacy Profile Threshold System? (HIGH PRIORITY)

**Background**: The codebase has two parallel threshold systems running simultaneously:

1. **Tiered threshold system** (new, correct):
   - Config: `src/obd_config.json` → `tieredThresholds` section
   - Code: `src/alert/tiered_thresholds.py`
   - Structure: Normal/Caution/Danger levels with explicit min/max boundaries
   - Status: Implemented in sprint 2, corrected via US-139 hotfix, aligned via sprint 5 (B-033)

2. **Legacy profile threshold system** (older, simpler):
   - Config: `src/obd_config.json` → `profiles.availableProfiles[*].alertThresholds`
   - Code: `src/alert/thresholds.py`, `src/alert/manager.py`, `src/profile/types.py`
   - Structure: Single "critical" values per parameter (e.g., `coolantTempCritical`, `rpmRedline`, `boostPressureMax`)
   - Status: Values now aligned with tuning spec (US-140 through US-144, B-033), but the system itself is redundant

**The question**: Should the legacy profile threshold system be deprecated in favor of the tiered system?

**Source of the question**: Spool raised this in his 2026-04-12 code audit (Variance 1):
> "The legacy profile threshold system was built before the tiered threshold system existed. When the tiered system was added, the legacy values weren't updated to match. Or the `110` is stale placeholder data from very early development."

Spool recommended Option B (deprecate legacy system) as his preference, but deferred the final call:
> "Whether to consolidate/deprecate one of these systems is an architecture call for you and the architect. I'd recommend B, but it's a scope call you should make."

**Considerations:**
- Tiered system is richer (4 levels vs 1), more accurate, and handles bidirectional parameters (battery voltage)
- Legacy profile system may be referenced by `ProfileManager` in ways that aren't immediately obvious — need code audit
- Profiles themselves (daily/performance) may be worth keeping even if their `alertThresholds` section is dropped
- Tests in `tests/test_orchestrator_profiles.py` and `tests/test_orchestrator_alerts.py` will need review
- Migration path: deprecate but keep as a facade during transition, or hard cut?

**Known consumers of legacy system:**
- `src/alert/thresholds.py`
- `src/alert/manager.py`
- `src/profile/types.py`
- `src/obd/obd_config_loader.py:350`
- `src/obd/config/loader.py:350`
- `src/obd/profile_manager.py` (at minimum docstring example, possibly more)
- Tests covering all above

**Proposed backlog item**: B-035 "Deprecate Legacy Profile Threshold System" (not yet created — waiting for architectural decision on approach)

**What Ralph should do if this comes up**: Don't touch the legacy system's structure without CIO direction. Value corrections (like B-033) are fine. Deprecation requires the architectural decision first.

---

### 2. Orchestrator Refactoring Plan (MEDIUM PRIORITY — PLAN EXISTS)

**Background**: `src/obd/orchestrator.py` is 2,500 lines — the single largest file in the codebase. `tests/test_orchestrator.py` would need a parallel split.

**Status**: A detailed refactoring plan already exists at `offices/pm/tech_debt/TD-003-orchestrator-refactoring-plan.md`. It proposes a 7-module split:

```
src/obd/orchestrator/
├── __init__.py                # Re-export ApplicationOrchestrator
├── types.py                   # ShutdownState, HealthCheckStats, exceptions (~100 lines)
├── core.py                    # Main class, __init__, runLoop, getStatus (~750 lines)
├── lifecycle.py               # _initialize*() + _shutdown*() methods (~400 lines)
├── connection_recovery.py     # Reconnect with backoff (~350 lines)
├── event_router.py            # Callback registration, _handle*() methods (~400 lines)
├── backup_coordinator.py      # Init, catchup, scheduling, upload (~300 lines)
├── health_monitor.py          # Health checks, stats, data rate (~200 lines)
└── signal_handler.py          # SIGINT/SIGTERM, double-Ctrl+C (~100 lines)
```

**Critical constraints to preserve during refactor:**

1. **Component init order (dependency chain)**:
   ```
   Database → ProfileManager → Connection → VinDecoder → DisplayManager →
   HardwareManager → StatisticsEngine → DriveDetector → AlertManager →
   DataLogger → ProfileSwitcher → BackupManager
   ```

2. **Shutdown order (reverse of init)**:
   ```
   BackupManager → DataLogger → AlertManager → DriveDetector → StatisticsEngine →
   HardwareManager → DisplayManager → VinDecoder → Connection → ProfileSwitcher →
   ProfileManager → Database
   ```

3. **Backward compat**: `from src.obd.orchestrator import ApplicationOrchestrator` must continue working via `__init__.py` re-export

4. **No behavior change**: This is a pure refactor. All 1,517 tests must continue passing unchanged.

**Backlog item**: B-019 "Split Oversized Files" — XL effort, needs a PRD before execution.

**What Ralph should do**: Don't attempt this refactor as a side effect of other work. It needs a dedicated sprint with the plan reviewed first. When a sprint for B-019 is loaded, read TD-003 plan carefully before touching any orchestrator code.

---

### 3. snake_case Migration (MEDIUM PRIORITY — POLICY DECISION NEEDED)

**Background**: The project currently uses camelCase for Python functions/variables (per `specs/standards.md`). This is non-standard for Python, which normally uses PEP8 snake_case. The project convention was chosen deliberately but is now being reconsidered.

**Scope if executed**: ~31,000 LOC across 120+ files.

**The question**: Keep camelCase (current standard) or migrate to snake_case (Python PEP8 standard)?

**Considerations:**
- **Keep camelCase**: Zero work. Team/tooling already aligned. Internal consistency.
- **Migrate to snake_case**: Massive effort. Better tooling interop. Easier for new contributors familiar with Python conventions. IDE autocomplete behaves better.
- **Hybrid**: Use snake_case for new modules only, leave existing modules alone. Risks inconsistency.

**Related dependencies:**
- TD-002 (backward-compat facade modules from Phase 4 refactor) — can be cleaned up during this migration
- SQL naming already snake_case (tables, columns) — that stays
- Classes already PascalCase — that stays

**Backlog item**: B-006 "Migrate from camelCase to snake_case" — XL, needs dedicated PRD.

**What Ralph should do**: Continue using camelCase per current `specs/standards.md`. Don't mix conventions. If CIO decides to migrate, it'll be a dedicated sprint with a migration script.

---

### 4. Phase 2 ECMLink Data Architecture (DESIGN DONE — NEEDS REVIEW BEFORE IMPLEMENTATION)

**Status**: Design artifacts already exist in `specs/architecture.md` (added in sprint 2 via US-137 and US-138). The architect-level decisions are documented but haven't been reviewed from an architectural correctness standpoint.

**What's designed:**

1. **ECMLink parameter ingestion schema** (US-137):
   - 15 priority parameters across 5 sample rates (20 Hz, 10 Hz, 5 Hz, 1 Hz, 0.5 Hz)
   - Database table design for mixed-rate data
   - Ingestion interface for ECMLink serial stream

2. **Data volume architecture** (US-138):
   - Phase 1 rate: ~5 reads/sec = ~18K rows/hour
   - Phase 2 rate: ~150 reads/sec = ~540K rows/hour (30x increase)
   - Seasonal estimate: ~21.6M rows on ECMLink
   - Pi SQLite storage strategy
   - Chi-Srv-01 MariaDB retention/partitioning/indexing strategy
   - Sync bandwidth estimates

**Open questions for CIO review:**
- Does the proposed Pi SQLite schema handle 21.6M row/season retention, or do we need partitioning?
- Is 90-day Pi retention still viable at Phase 2 volumes?
- Should ECMLink ingestion go through the existing data logger module or have its own pipeline?
- How does the existing sync mechanism handle 540K rows/hour without flooding WiFi?

**Related backlog**:
- B-029: Phase 2 Alert Thresholds (blocked on ECMLink hardware)
- B-025: ECMLink Data Integration (pending, Q2/Q3 2026)
- B-032 complete: Phase 1 polling + design docs for Phase 2

**What Ralph should do**: When B-025 or B-029 sprints load (after ECMLink is installed this summer), read this section and the architecture.md ECMLink section. Flag any architectural concerns before implementing.

---

### 5. Companion Service Architecture (PRD EXISTS — REVIEW BEFORE IMPLEMENTATION)

**Background**: `B-022: Chi-Srv-01 Companion Service (OBD2-Server)` is fully groomed with a 9-story PRD at `offices/pm/prds/prd-companion-service.md`. This lives in a **separate repository** (`OBD2-Server`) which is currently empty.

**Key architectural decisions already made:**
- Framework: FastAPI (async, auto OpenAPI docs)
- Database: MariaDB (schema mirrors Pi SQLite, already installed on Chi-Srv-01 as `obd2db`)
- Auth: API key via `X-API-Key` header, constant-time comparison (`hmac.compare_digest()`)
- Sync model: Push-based delta sync, Pi initiates
- ID mapping: Pi `id` → MySQL `source_id`, MySQL owns primary key, upsert key = `(source_device, source_id)` — multi-device ready
- Ollama endpoint: `/api/chat` (conversational), server owns prompt templates
- Test strategy: All tests hit real MySQL (no SQLite substitutes for companion service tests)
- Backup extensions: `.db`, `.log`, `.json`, `.gz` (restricted set for security)

**Stories (US-CMP-001 through US-CMP-009)**:
1. Project Scaffolding and Configuration
2. API Key Authentication Middleware
3. MariaDB Database Schema and Connection
4. Delta Sync Endpoint
5. AI Analysis Endpoint
6. Auto-Analysis on Drive Data Receipt
7. Backup Receiver Endpoint
8. Health Endpoint with Component Status
9. systemd Service and Deployment

**Open architectural questions:**
- Should US-CMP-003 (MariaDB schema) be frozen now or flexible enough to handle Phase 2 ECMLink volumes (21.6M rows/season)?
- Is the push-based sync model scalable to Phase 2 rates?
- Should the server have a webhook/notification system for flagged alerts to push back to the Pi?
- Repository bootstrap: Ralph will need to initialize OBD2-Server from scratch with its own pyproject.toml, tests, CI, etc.

**Dependencies this unblocks**:
- B-023: WiFi-Triggered Sync (Pi-side, depends B-022)
- B-027: Client-Side Sync to Chi-Srv-01 (Pi-side, depends B-022 + B-023)
- B-031: Server Analysis Pipeline (server-side, depends B-022) — 7 stories from Spool's tuning spec

**What Ralph should do**: When a sprint for B-022 is loaded, read `offices/pm/prds/prd-companion-service.md` in full. The stories have concrete DB validation queries, specific input/output tests, and tightened ACs. Ralph bootstraps a new repo in the `OBD2-Server` directory on Chi-Srv-01 and builds from scratch.

---

## Open Tech Debt with Architectural Scope

### TD-001: Large Files and Empty Packages
- 11 source files exceed 300-line guideline
- `orchestrator.py` (2,500 lines) is the critical one — covered by TD-003/B-019 above
- Others (TBD): need a full audit to identify all 11

### TD-002: Re-export Facade Modules
- Phase 4 refactoring left re-export facades in `src/obd/`
- Can be cleaned up during snake_case migration (B-006)
- Low priority until B-006 is addressed

### TD-003: Orchestrator Refactoring Plan
- Detailed plan exists (see Decision #2 above)
- Blocked on B-019 sprint scheduling

### TD-009: Sprint Stories Need Better Stitching
- Stories modifying `config.json` don't always include corresponding ConfigValidator, docs, or integration test updates
- Process improvement, not code debt
- Affects how future sprints are loaded by Marcus (PM)

---

## Known Non-Variances (For the Record)

From Spool's 2026-04-12 code audit, these values/logic are confirmed correct and need no changes:

- `tieredThresholds.coolantTemp`: 180/210/220 ✓
- `tieredThresholds.stft`: 5/15 ✓
- `tieredThresholds.rpm`: 600/6500/7000 ✓ (after US-139 hotfix)
- `tieredThresholds.batteryVoltage`: 13.5-14.5 normal, 12.5 caution low, 12.0 danger low ✓
- `tieredThresholds.iat`: 130/160 ✓ (after corrections)
- `tieredThresholds.timingAdvance`: 5° drop, 0° under load ✓
- All 4 polling tiers with correct PIDs at correct frequencies ✓
- PID 0x0B MDP caveat correctly documented ✓
- `src/obd/simulator/profiles/eclipse_gst.json`: `redlineRpm: 7000` ✓
- Display thermal trend thresholds: 60-sec window, ±0.5°F/min slope, 200°F time-at-temp ✓
- `src/analysis/calculations.py`: standard deviation and outlier formulas correct
- `src/ai/data_preparation.py`: O2 rich/lean thresholds (0.5V/0.4V) correct for narrowband
- Drive detection: 500 RPM start threshold, 60-second idle end threshold ✓
- Timing advance baseline learning: 500 RPM bins, 10% load bins ✓

---

## Process Note — Review Gate

From sprint 3 onward, every sprint runs through Spool's `/review-stories-tuner` skill BEFORE stories enter a sprint. This catches threshold errors, spec gaps, and vehicle-specific value issues before Ralph writes code. Sprints 1 and 2 ran without this gate, which is why US-139 (sprint 4 hotfix) and B-033 (sprint 5 audit cleanup) were needed.

**Ralph should expect**: Tuning-related stories will come pre-reviewed by Spool. Architecture-related stories do NOT have an equivalent gate yet — the CIO will work with Ralph directly on those.

---

## Summary of Open Questions for CIO + Ralph Discussion

1. **Should we deprecate the legacy profile threshold system?** (Decision #1)
2. **When should B-019 (orchestrator refactor) sprint run?** (Decision #2)
3. **Should we migrate to snake_case, and when?** (Decision #3)
4. **Does the Phase 2 data architecture handle 21.6M rows/season retention?** (Decision #4)
5. **Can B-022 companion service start, and does its MariaDB schema need to accommodate Phase 2?** (Decision #5)

These are not sprint assignments. They're open questions that need CIO + Ralph collaboration to resolve. Marcus will NOT create backlog items for these until direction is decided.

---

## Reference Files

| File | Purpose |
|---|---|
| `offices/pm/tech_debt/TD-003-orchestrator-refactoring-plan.md` | Detailed orchestrator split plan |
| `offices/pm/prds/prd-companion-service.md` | B-022 companion service PRD (9 stories) |
| `specs/architecture.md` | System architecture, Phase 2 ECMLink schema, data volume strategy |
| `specs/standards.md` | Current camelCase convention (Decision #3) |
| `offices/pm/inbox/2026-04-12-from-spool-code-audit-variances.md` | Spool's source analysis for Decision #1 |
| `offices/pm/inbox/2026-04-10-from-spool-system-tuning-specifications.md` | Original Spool tuning spec |
| `offices/pm/backlog/B-019.md` | Split oversized files backlog item |
| `offices/pm/backlog/B-022.md` | Companion service backlog item |

---

**Ralph**: No action required unless a sprint story touches one of these areas. When that happens, read the relevant section above and flag to the CIO if the architectural question needs to be resolved first.

— Marcus

*"Architectural decisions are best made once, explicitly, with all the context. Not accidentally while implementing a story."*
