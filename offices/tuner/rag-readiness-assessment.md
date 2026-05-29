# Eclipse Knowledge — RAG-Readiness Assessment & Organization Plan

**Author**: Spool (Tuning SME)
**Date**: 2026-05-29 (Session 22)
**Status**: Phase-0 blueprint — prep for the upcoming "MrSpool" RAG sprint (not-now per CIO; sequencing after good data collection)
**Purpose**: Organize Spool's Eclipse knowledge so it can feed the MrSpool RAG/Ollama layer cleanly. See `knowledge/mrspool-vision.md` for the vision this serves.

---

## 1. What MrSpool needs from this corpus

Per `knowledge/mrspool-vision.md`: MrSpool is a **digital extension of Spool**, persona-matched, grounded in `knowledge.md` (primary) + session logs + inbox notes + DSM refs + mod/maintenance history. The corpus must supply MrSpool with:
- **Interpretation, thresholds, and persona** (what Spool *knows* and *how Spool talks*).
- NOT raw telemetry — that lives in the server DB (`chi-srv-01:obd2db`, `realtime_data`). Clean split: **corpus = judgment; DB = data.** MrSpool retrieves prose/thresholds from the corpus AND queries the DB for raw values. The corpus must not try to be a data store (don't bloat it with raw sample tables).

## 2. Corpus inventory (2026-05-29)

| Source | Lines | RAG value | Notes |
|---|---|---|---|
| `knowledge.md` | 1627 | **PRIMARY** | The bible. ~50 sections. Mixed content types. |
| `sessions.md` + archive | ~2000 | Secondary | Process + vehicle facts interleaved; high noise-to-signal for tuning retrieval. |
| `drive-annotations.md` | 283 | High | Per-drive metadata sidecar — already structured. |
| `drain-test-procedure.md` | 344 | Low (infra, not tuning) | UPS/power — not Eclipse tuning knowledge. |
| `drive-review-checklist.md` | 240 | Medium | Human-judgment methodology. |
| `knowledge/*.md` (13 files) | ~350 | Mixed | Persona/process/followups; mostly NOT vehicle facts. |

## 3. RAG-readiness gaps (the chunk-hostile patterns)

1. **Stale-as-current risk (HIGHEST).** Archived/superseded facts live inline next to current ones: Drive 11 ARCHIVED (still in baseline section), the corrected "modified EPROM" reads, the 91→93 fuel-grade correction, the run-on changelog header at `knowledge.md:4`. A retriever will serve these as authoritative.
2. **No per-fact ECU attribution.** A chunk "idle timing 5–7° BTDC" doesn't carry *which ECU*. Post-2026-05-22 there are TWO tune regimes (stock MD346675 ≤24 vs ECMLink MD335287 ≥25). Without an `ecu:` tag, retrieval conflates them — a safety problem.
3. **Cross-references break under chunking** ("see ECU Identity", "use Drive 5 as baseline"). Retrieved fragments lose the pointer.
4. **`[EXACT: …]` sacred values** must survive chunking with guards intact and rank as highest authority.
5. **Duplication across files** (knowledge.md / sessions.md / `specs/grounded-knowledge.md` / shared MEMORY.md) → conflicting/redundant retrievals. No declared SSOT for a given fact.
6. **Non-tuning content pollutes the tuning corpus**: UPS HAT / Drain-test / Regression-fixture sections (`knowledge.md:1499–1617`) are infrastructure, not Eclipse tuning.
7. **Authority is a human convention** (PM Rule 7: CIO/real-data > community) — not machine-readable for retrieval ranking.

**Strengths to keep**: clean `##`/`###` hierarchy + TOC (natural chunk boundaries); consistent drive-observation template (Drive N → Interpretation Anchors → Diagnostic Gaps); `[EXACT]` markers already exist; `mod_state` enum concept already exists.

## 4. Proposed metadata schema (the foundational artifact)

Every RAG chunk/card carries front-matter. Controlled vocabulary is the load-bearing part:

```yaml
---
id: <stable-kebab-id>          # e.g. ecu-prior-md346675-stock
topic: ecu | timing-knock | fuel-trim | cooling | boost | fuel-system |
       obd2-capability | safe-ranges | failure-mode | mod-path |
       empirical-drive | methodology | glossary
ecu: prior | new | both | n/a  # CRITICAL — prevents cross-ECU contamination
mod_state: premod | <future enums as mods land>
fuel: 93-octane | n/a          # [EXACT-locked] where applicable
confidence: authoritative | observed | community | hypothesis
  # authoritative = CIO / manufacturer / [EXACT]; observed = this car's data;
  # community = DSMTuners consensus; hypothesis = unverified inference
status: current | superseded | archived-historical
  # retriever serves `current` only by default; others excluded unless the
  # query is explicitly historical ("what did we used to think…")
source: <drive_id | session | CIO-directive | DSMTuners-thread | ECMLink-doc | manufacturer-spec>
date: YYYY-MM-DD
exact_locked: true | false     # carries an [EXACT: …] DO-NOT-CHANGE value
supersedes: [<id>…]            # optional
superseded_by: <id>            # optional
---
```

`ecu` + `status` + `confidence` are the three fields that most directly prevent MrSpool from giving dangerous advice (wrong-ECU baseline, stale fact, or community-guess dressed as gospel).

## 5. Organization options (the decision for CIO)

| | Approach | Effort | Pro | Con |
|---|---|---|---|---|
| **A** | In-place enrichment — add front-matter + status tags to `knowledge.md` sections; pull stale facts to an appendix | Low | Preserves my human workflow; one file | Big sections still chunk imperfectly |
| **B** | Atomic cards — decompose corpus into many single-fact cards with front-matter; `knowledge.md` becomes an index | High | RAG-native (1 card = 1 clean chunk) | Changes my working workflow; lots of files |
| **C** ⭐ | Hybrid — keep `knowledge.md` as the human doc; generate a curated `offices/tuner/rag/` corpus (atomic, current-only, de-duped) that the RAG ingests | Medium | Clean separation (Spool's notes vs MrSpool's retrieval set); human doc unchanged | Two corpora to keep in sync |

**DECISION (CIO, 2026-05-29): Option B.** C was rejected — two hand-maintained corpora = duplication, which violates one-version-of-the-truth ([[ssot-design-pattern]]). Final architecture:

- **`cards/*.md`** — atomic, one-fact-per-card, the **SSOT** for THIS-car facts. (Schema: `cards/README.md`.)
- **`vehicle.md`** — a **generated quick-reference index** into the cards (NOT a copy; authoritative values live in the cards).
- **`knowledge.md`** — keeps general 4G63 / DSM / tuning craft + a pointer to `vehicle.md`.
- **SSOT rule**: any readable view (`vehicle.md`, or a regenerated bible) is *generated one-directionally* from the cards — never hand-maintained in parallel.

## 6. Phased plan

- **Phase 0 (done)** — assessment + schema + decision (Option B). ✅
- **Phase 1 (done, 2026-05-29)** — scaffolding + two vertical slices:
  - **ECU slice**: `cards/README.md` (schema), `vehicle.md` (index + migration manifest), ECU cards (`ecu-prior-md346675`, `ecu-new-md335287`) as SSOT, `knowledge.md` ECU Identity collapsed to a pointer. ✅
  - **Safe-ranges slice**: 7 `safe-range-*` cards as SSOT (coolant-temp, timing-knock, fuel-trims, afr, boost, battery-voltage, engine-envelope); `knowledge.md` Safe Operating Ranges section collapsed to a pointer. ✅ *(Reconciliation TODO: this-car threshold mentions still inline in the Cooling / Timing sections of knowledge.md — fold to these cards when those sections migrate.)*
- **Phase 2 (next, the RAG sprint)** — work the `vehicle.md` migration manifest: extract each remaining THIS-car section of `knowledge.md` into a card with front-matter; collapse each migrated section to a pointer; tag `status` (`current`/`superseded`/`archived-historical`) as it goes. De-dup vs sessions / `specs/grounded-knowledge.md` / MEMORY (cards become SSOT; others link).
- **Phase 3** — generate `vehicle.md` automatically from card front-matter (retire hand-seeding); optionally regenerate a readable bible from cards.
- **Phase 4** — define the retrieval contract: cards (judgment/thresholds/persona) vs DB (raw telemetry); how MrSpool joins them. Persona overlay per `knowledge/mrspool-vision.md`.

## 7. Open decisions for CIO

1. **Option A / B / C** (Spool recommends C).
2. **Corpus scope** — knowledge.md only, or also ingest sessions + inbox + drive-annotations? (Vision says all of them eventually; suggest knowledge.md + drive-annotations first, sessions later — sessions are noisy.)
3. **Non-tuning sections** (UPS/drain/regression) — these aren't mine to relocate (infra/dev lane). Flag to PM/Atlas for a home, or leave and exclude via `topic`/`status`?
