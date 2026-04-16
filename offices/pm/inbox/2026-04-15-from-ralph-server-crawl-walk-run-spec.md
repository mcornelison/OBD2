# From Ralph: Server-Side Crawl/Walk/Run Architecture Spec Ready

**Date**: 2026-04-15
**From**: Ralph
**To**: Marcus (PM)
**Priority**: High
**Type**: New spec for backlog processing

---

## Summary

CIO-approved design spec for the Chi-Srv-01 server side, structured as a crawl/walk/run progression:

- **Crawl**: Server consumes simulator-generated fake data, produces real analytics via CLI reports
- **Walk**: Pi sends simulated data through real sync endpoints, same analytics validated
- **Run**: Real OBD-II data, calibrated baselines, Spool AI tuning recommendations

## Spec Location

`docs/superpowers/specs/2026-04-15-server-crawl-walk-run-design.md`

Committed at `5f7459d`.

## What This Supersedes

- **`prd-infrastructure-pipeline-mvp.md`** (DRAFT) — fully absorbed and restructured
- **`prd-companion-service.md`** (B-022) — all 9 stories absorbed into crawl/walk/run phases
- **B-027 stories** (US-148, US-149, US-150, US-151) — absorbed into walk/run phases

The original PRDs remain as-is for reference, but this spec is now the source of truth for server-side work.

## Action Items for Marcus

1. **Assign story IDs** to the 8 NEW stories (NEW-01 through NEW-08). Next available per story_counter.json.
2. **Write full acceptance criteria** for the 8 NEW stories. The spec provides detailed descriptions, expected behavior, and output formats. The absorbed stories (US-CMP-001 through US-CMP-009, US-147 through US-154) already have ACs in their original PRDs.
3. **Create sprint(s)** per the sprint contract spec. Natural sprint boundaries:
   - Sprint A: Crawl phase (9 stories — scaffold, schema, deploy, analytics, reports)
   - Sprint B: Walk phase (8 stories — auth, sync, Pi client, parity validation)
   - Sprint C: Run phase (6 stories — real AI, auto-analysis, backup, calibration)
4. **Update backlog.json** with the new story structure
5. **Mark `prd-infrastructure-pipeline-mvp.md`** as superseded (it was DRAFT, never promoted)
6. **Coordinate with Spool** for US-CMP-005 (run phase) — Spool should review/author AI prompt templates

## Key Design Decisions (CIO-Approved)

- Server code lives in `src/server/` within existing OBD2v2 repo (not separate repo as B-022 proposed)
- Fake data via export-import from existing simulator (no server-side data generator)
- CLI reports over SSH as primary output (no web dashboard)
- Three analytics tiers: basic (per-drive stats), advanced (trends/correlations), AI (Spool/Ollama)
- Baselines always human-approved, never auto-applied

## Story Count

23 total: 14 absorbed from existing PRDs + 8 new + 1 from pipeline MVP draft.
