# B-087: GEM-2 — Deterministic anomaly + Ollama explanation pattern (mature US-326 + US-317 + ingest the brainstorm prompt pack)

| Field        | Value         |
|--------------|---------------|
| Priority     | Medium (Spool Phase-4 V0.31-V0.33)    |
| Status       | Pending (V0.28+ candidate) |
| Category     | (see body)    |
| Size         | M        |
| Dependencies | (see body)    |
| Created      | 2026-05-14    |

## Description

Already partially built: V0.27.3 US-326 drive_summary writer + V0.27.4 US-317 Ollama decouple. The brainstorm "evidence packet" framing aligns — rules-first then LLM explains; never let LLM read raw rows.

**Specific deliverable:** lift the `Ollama_Anomaly_Detection_Prompt_Pack.md` (in `specs/samples/` from CIO 2026-05-14 brainstorm drop) into a `prompts/` directory in the codebase. Has production-grade system prompt + 3 templates (anomaly-explain / drive-summary / ask-my-drives). JSON-mode + auditable outputs.

**Source:** Spool gem-filter PM note (GEM-2). Foundation for GEM-3/4/9 downstream.


## Acceptance Criteria

To be detailed at PRD grooming. See source notes for evidence + thresholds + rationale.
