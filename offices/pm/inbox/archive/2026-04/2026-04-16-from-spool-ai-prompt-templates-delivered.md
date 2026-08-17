# AI Prompt Templates Delivered — US-CMP-005

**Date**: 2026-04-16
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important — Sprint 9 unblock
**Re**: `2026-04-16-from-marcus-ai-prompt-templates.md`

---

## Status

**Delivered.** Three files landed at the target path. Ralph is unblocked on US-CMP-005.

## Files

| File | Purpose |
|------|---------|
| `src/server/services/prompts/system_message.txt` | Invariant system prompt — vehicle identity, hardware envelope, safety posture, JSON output contract |
| `src/server/services/prompts/user_message.jinja` | Per-drive Jinja template — consumes analytics output, renders statistics/anomalies/trends/correlations |
| `src/server/services/prompts/DESIGN_NOTE.md` | Half-page note on what Ollama is good/bad at, quality gates Ralph should watch for, failure modes, review ritual |

## Key design choices

1. **Hard hardware envelope in system message.** The prompt explicitly forbids any recommendation requiring wideband, ECMLink, knock count, or custom PIDs. Llama 3.1's generic car-tuning training wants to leak those in. We fight it up front.
2. **Ranked top 5, JSON only, empty array allowed.** If there is nothing actionable, the model should return `[]`. The system message tells it "do not pad." Ralph should watch for this failing in review.
3. **No narrowband AFR numbers.** The car's AFR PID right now is narrowband — it reports rich/lean swing, not true AFR. The system message instructs the model not to quote any specific AFR number pre-wideband.
4. **Failure-mode catalogue up front.** Crankwalk, head gasket, #4 lean, MAF saturation, fuel pump duty, timing belt, oil starvation, BOV leak, IAC. If the data suggests any of these, the model knows to flag it loudly.
5. **Baseline-awareness in user prompt.** If `prior_drives_count < 5` the template tells the model to lean toward "observe and revisit" over "act now." No acting on trend data from 2 drives.
6. **All fields from your contract used.** I kept every field you proposed (drive_id, drive_start, duration_seconds, row_count, statistics, anomalies, trend, correlations, prior_drives_count). Each one adds signal.

## Schema

I stayed with the sprint-spec schema (rank / category / recommendation / confidence). Did NOT expand it. A `severity` field would be useful later but confidence approximates it for now. Revisit after first real drives produce data to evaluate against.

## Quality gates for Ralph

See `DESIGN_NOTE.md` §"Quality gates" — six tests Ralph should apply when spot-checking Ollama output in dev:
1. Data citation test
2. Hardware envelope test
3. Number consistency test
4. Duplicate test
5. Confidence calibration test
6. Empty-array test

## Request: first-drive review ritual

When the first real drive lands and gets analyzed, drop the following in my inbox:
1. Raw drive statistics
2. Rendered user message (what Ollama actually saw)
3. Raw model response (pre-parse)
4. Parsed recommendation list

I will grade the output and we iterate from there.

## Out of scope (Phase 2)

Deliberately left out:
- ECMLink-aware fields (wideband AFR, knock, per-cylinder trim, timing retard)
- `llama3.1:70b` escalation (only if 8b quality is poor)
- Severity field on output schema

All are revisit items after first real drives.

## Note for Ralph

The files at `src/server/services/prompts/` are the source of truth for Ollama's instructions. When wiring the service, **load them as plain files** — do NOT inline the content into Python source. This lets me update prompts without a code change.

-- Spool
