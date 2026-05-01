# PRD: <Feature Name>

**Parent Backlog Item**: B-XXX
**Status**: Draft / Active / Shipped
**Owner**: <PM agent name>
**Created**: <YYYY-MM-DD>

---

## Schema Impact (gate this BEFORE writing user stories)

Mark exactly one. Drives whether server migration must be authored alongside Pi work.

- [ ] **Server migration required: yes** — this PRD adds, removes, or modifies columns on a Pi capture table that is mirrored to the server (`realtime_data`, `statistics`, `profiles`, `vehicle_info`, `ai_recommendations`, `connection_log`, `alert_log`, `calibration_sessions`, `dtc_log`, `battery_health_log`, `drive_summary`). A `src/server/migrations/versions/v00NN_*.py` migration MUST be authored in the same sprint and validated by `scripts/apply_server_migrations.py --dry-run`. Confirm with `python scripts/schema_diff.py` post-implementation; output must be drift-free for any newly-touched table.
- [ ] **Server migration required: no** — Pi schema unchanged, OR the change is on a Pi-only operational table (`static_data`, `power_log`, `drive_counter`, `pi_state`, `sync_log`, `calibration_data`).
- [ ] **Server migration required: N/A** — this PRD does not touch persistent storage.

> **Why this gate exists** (TD-039): Sprint 16 US-213 shipped a server schema migration gate, but it was a silent no-op for the `drive_summary` table because no v0004 migration was ever authored to match the Sprint 15 US-206 cold-start metadata columns. The drift went undetected for weeks until Sprint 19 US-237 emergency-authored v0004. The checkbox above forces the question at grooming time; `scripts/schema_diff.py` is the runtime verifier.

---

## Introduction

<2-4 paragraphs: what problem does this solve, why now, what's the scope boundary>

## Goals

- <Outcome 1 -- user-visible or operator-visible>
- <Outcome 2>
- <Outcome 3>

## Non-Goals

- <Out-of-scope item 1 -- explicit so reviewers can refute scope creep>
- <Out-of-scope item 2>

## Existing Infrastructure

The developer does NOT need to create these -- they already exist:

| Component | File | Status |
|-----------|------|--------|
| <Existing piece 1> | `path/to/file` | Done |
| <Existing piece 2> | `path/to/file` | Done |

## Dependencies

- **Upstream (must ship first)**: <PRD / story IDs>
- **Downstream (waits on this)**: <PRD / story IDs>

## User Stories

### US-XXX-001: <Story title>

**Description:** As a <role>, I want <capability> so I can <outcome>.

**Acceptance Criteria:**
- [ ] <Criterion 1 -- verifiable, no weasel words>
- [ ] <Criterion 2>
- [ ] Tests pass (`pytest tests/ -v`)
- [ ] `make lint` clean

### US-XXX-002: <Story title>

(repeat as needed)

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| <Risk 1> | low/med/high | low/med/high | <How we handle it> |

## Verification

- `pytest tests/ -m 'not slow' -q` (full fast suite)
- `make lint` (ruff)
- `python validate_config.py` (if config touched)
- `python scripts/schema_diff.py` (if schema touched -- assert drift-free for new/changed tables)
- `python offices/pm/scripts/sprint_lint.py` (if sprint.json touched)

## Out of Scope (deferred to future PRDs)

- <Future work item 1>
- <Future work item 2>
