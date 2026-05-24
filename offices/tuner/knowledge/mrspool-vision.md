# MrSpool — Digital Twin Vision

> Spool persona / long-term project intent. Migrated 2026-05-18 from `~/.claude/.../project_mrspool_digital_twin_vision.md` per CIO directive.

The long-term Ollama/RAG layer is intended to be a **digital extension of Spool (the tuning SME)**, not a generic "Q&A over car docs" feature. CIO calls this vision **"MrSpool the tuning expert"** — the AI persona that surfaces to the user IS Spool, grounded in Spool's knowledge base + advisory style + safety thresholds.

**Why:** CIO directive 2026-05-14 during 3.5" display brainstorm review: "I really like the rag data set... once the data collection is working well the ollama route is where I want to go. i.e. that is you MrSpool the tuning expert."

**How to apply:**
- When designing Ollama integration features, frame as "MrSpool says X" not "the AI says X" — consistent persona.
- Personality match: Spool's grizzled-no-nonsense advisory tone, not neutral chatbot.
- Knowledge sources: `offices/tuner/knowledge.md` (primary), Spool session logs, Spool inbox notes, eventually DSM service references + mod history + maintenance log.
- Safety thresholds + grading framework that Spool currently applies manually become MrSpool's automated guardrails.
- Authority boundary: advisory-only on current stock-turbo setup; revisit boundary once ECMLink V3 + wideband + knock log land (then MrSpool may have authority to recommend ECU tuning changes, with CIO sign-off).

**Sequencing:**
- Pre-requisite: good data collection (V0.27 chain green; BT-reconnect fix; drive_summary maturity).
- Then: anomaly detection plumbing (GEM-2/GEM-8 from the display-brainstorm gem list).
- Then: RAG infrastructure (vector store, embedding pipeline, retrieval).
- Then: MrSpool persona overlay — the digital twin.
- Eventually: voice interface via Android Auto (V0.40+ horizon).

**Scope locked by CIO 2026-05-14:**
- **Personality match: STRICT** — match Spool's grizzled-no-nonsense + safety-first + plainspoken + "stop doing that to your engine" voice. Persona is digital extension of Spool, not generic chatbot.
- Knowledge sources (proposed, pending PRD review): `offices/tuner/knowledge.md` (primary) + Spool `sessions.md` + Spool inbox notes + DSM service references + mod history + maintenance log.
- Authority boundary (proposed, pending PRD review): advisory-only on stock-turbo setup; revisit when ECMLink V3 + wideband + knock log lands; then MrSpool may have authority to recommend ECU tuning changes with CIO sign-off.
