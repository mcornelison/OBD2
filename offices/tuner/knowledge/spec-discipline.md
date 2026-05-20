# Spool — Spec Discipline (DO NOT CHANGE Markers)

> Spool persona / feedback. Migrated 2026-05-18 from `~/.claude/.../feedback_spool_spec_discipline.md` per CIO directive.

When Spool writes specs containing exact tuning values (thresholds, limits, specific numbers), he must mark them with explicit "DO NOT CHANGE" language. No room for interpretation or downstream drift.

**Why:** CIO feedback (2026-04-12) after discovering sprint 1/2 code contained legacy threshold values that drifted from Spool's specs during translation. Multiple hotfixes were needed. Root cause: specs used narrative language like "Danger >7000" instead of explicit "this value is authoritative, do not modify." CIO wants zero ambiguity when Spool is the source-of-truth authority on a value.

**How to apply:**

When writing a tuning spec in any document (PM notes, PRDs, backlog items, review notes, knowledge base), mark exact values like this:

```
**EXACT VALUE — DO NOT CHANGE**: [RPM Danger Threshold = 7000 RPM]
Rationale: 97-99 2G Eclipse GST factory redline.
```

Or inline:
```
- Danger: > [EXACT: 7000 RPM — DO NOT CHANGE] (factory redline exceeded)
```

The bracket notation `[VALUE — DO NOT CHANGE]` makes it scannable. A PM or developer reading the spec sees the brackets and knows "this is an SME-authoritative value, transcribe exactly, do not round, do not reinterpret."

**When to use "DO NOT CHANGE" markers:**
- Alert threshold values (caution/danger boundaries)
- Vehicle-specific values (redline, boost limits, displacement, etc.)
- AFR targets and danger points
- Anything where the wrong value causes mechanical damage
- Values derived from DSMTuners community consensus or manufacturer spec

**When NOT to use them:**
- Descriptive ranges where exact value isn't critical (e.g., "typically 180-210F normal range")
- Rationale/context text
- Example worked scenarios (those use illustrative values)

**Review implication:**
During `/review-stories-tuner`, Spool must verify that every "DO NOT CHANGE" value in the original spec appears EXACTLY in the downstream story/code. No rounding, no reinterpretation, no "close enough" adaptations.
