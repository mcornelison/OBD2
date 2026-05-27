---
id: F-094
parent: E-003
status: pending
renamedFrom: B-094
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-094: GEM-9 — MrSpool digital twin: RAG over Spool knowledge + DSM references + mod/maintenance log

| Field        | Value         |
|--------------|---------------|
| Priority     | High (CIO A3 = full vision; Spool Phase-5 V0.34+; biggest infra investment)    |
| Status       | Pending (V0.28+ candidate) |
| Category     | (see body)    |
| Size         | XL (likely multi-sprint epic)        |
| Dependencies | (see body)    |
| Created      | 2026-05-14    |

## Description

**The CIO's full Ollama-depth vision (CIO A3, 2026-05-14): digital extension of Spool the tuning SME.**

**Knowledge sources (proposed):** `offices/tuner/knowledge.md` (primary) + Spool `sessions.md` + Spool inbox notes + DSM service references + mod history + maintenance log.

**Capabilities:** "Ask my car" Q&A — "what does this code mean on MY car?", "when did we last see voltage dip like this?", grounded in OUR data not training-data hallucinations.

**Persona (CIO A7):** match Spool tone — grizzled-no-nonsense + safety-first + plainspoken + "stop doing that to your engine" voice.

**Authority boundary (CIO A7):** advisory-only on stock-turbo setup; revisit when ECMLink V3 + wideband + knock log lands.

**Dependencies:** Ollama embeddings infra (currently we have generation but not vector-search wiring). Likely warrants its own epic.

**Source:** Spool gem-filter PM note (GEM-9 + CIO A3 + CIO A7). Long-term project vision per `[[project_mrspool_digital_twin_vision]]`.


## Acceptance Criteria

To be detailed at PRD grooming. See source notes for evidence + thresholds + rationale.
