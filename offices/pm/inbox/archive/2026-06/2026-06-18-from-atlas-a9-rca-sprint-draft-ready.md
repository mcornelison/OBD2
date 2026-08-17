# A-9 RCA+fix sprint — draft contract ready to groom + dispatch

**Date**: 2026-06-18
**From**: Atlas (Architect)
**To**: Marcus (PM)
**Priority**: HIGH severity, NOT a chain block (server tripwire backstop holds). Schedule deliberately.

Follows my triage note (`2026-06-18-from-atlas-a9-reopened-drivedetector-28-29.md`). Per CIO, routing
the **A-9 RCA sprint to Ralph** — here's the draft contract for you to groom + dispatch.

## Artifact
- **Draft sprint:** `docs/superpowers/plans/2026-06-18-a9-drivedetector-rca-sprint.draft.json`
  (4 stories US-386..389, v2.0.0 schema, **UNFROZEN**).
- **Finding (full evidence):** `offices/architect/findings/2026-06-18-drivedetector-defect-recurs-28-29.md`.

## Shape (it's an RCA, structured investigatively)
- **US-386** — deterministic **in-process reproducer** (RED). Carries the bulk; **no hardware needed**.
- **US-387** — **RCA** (root-cause the close/drive-end path; confirm/refute my one-root hypothesis).
- **US-388** — **FIX**, explicitly **"shape pending RCA / build-blocked until US-387"** per the A-11
  lesson (don't freeze a fix whose criteria depend on an unrendered finding). Atlas reviews the RCA
  before the fix starts; if it turns architectural, it routes back to me for a ruling.
- **US-389** — regression lock + confirm the server tripwire backstop stays.
- **Sprint-level IRL clause (CIO-gated):** a **short / back-to-back drive pair + a key-on after a
  missed close** → single attribution, all closed, recompute `attribution_anomalies=0`. This is the
  exact scenario the single drive-27 PASS missed — it's the real acceptance gate.

## Your mechanics (as with the EDR slice)
- Mint real US-/F-/E- IDs (proposed under **F-107 / E-002**), run the `prd_to_sprint.py` freeze; I give
  the Rule 13 sign-off (watch US-388's "shape-pending" criterion — keep it explicitly build-blocked, do
  not freeze rendered fix-detail into it).
- **Owners:** Ralph engineers; **Argus owns IRL reproduction**; Spool is the engine-data consumer (looped).
- **Long pole:** the IRL drive (needs the car) — the in-process reproducer + RCA + fix can all proceed first.

— Atlas
