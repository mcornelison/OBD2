# Design Note — AI Prompt Templates for US-CMP-005

**Author**: Spool (Tuning SME)
**Date**: 2026-04-16
**Sprint**: 9 (Server Run)
**Audience**: Ralph (implementing), Marcus (reviewing), CIO (final call)

---

## What these prompts are trying to do

Replace the Sprint 8 stub analyzer with a real Ollama-backed analysis that
the CIO can actually trust. The prompt is the discipline — everything the
system does downstream (storage, reporting, alerting) is only as good as
what Ollama sees and how we constrain its reply.

There are two halves: a **system message** that is invariant (loaded on
every call, never templated), and a **user message** that is rendered fresh
per drive from the analytics output. The split matters: Ollama caches the
system message across calls, which saves tokens and keeps the model's
"personality" consistent even if the per-drive data changes shape.

## What Ollama is GOOD at on OBD-II data

- **Pattern summarization.** Fed 8 stat rows and 3 anomalies, it will
  organize them into a coherent ranked list. This is the real value.
- **Category assignment.** Given clear category labels ("Cooling",
  "Fueling", etc.), it will bucket things correctly most of the time.
- **Plain-English translation.** Takes "coolant_temp avg 210°F, σ=4.2,
  +12% trend" and turns it into "your engine is running hotter than it
  was two weeks ago — check the thermostat and radiator."
- **Catching things a busy driver misses.** The human looking at a dash
  sees the present. The AI looking at 10 drives sees drift.

## What Ollama is BAD at on OBD-II data

- **Physics reasoning.** It does not actually know that a 4G63's #4
  cylinder runs lean because of exhaust-manifold thermal distribution. If
  you ask it to explain "why," it may hallucinate plausible-sounding
  mechanisms that aren't right.
- **Numerical accuracy.** An LLM will sometimes "remember" a number
  differently than the input said. If the prompt shows avg RPM = 2750,
  the output may report 2400 — especially after many tokens of context.
- **Consistency across calls.** Same drive fed twice may return different
  rankings. This is a known LLM property. We mitigate with structured
  output and strict categories, but expect some jitter.
- **Knowing the hardware envelope.** A base Llama 3.1 has internet-average
  car advice baked in. It will happily suggest "check your wideband" or
  "retard timing 2°" because most of its training data assumed those mods
  existed. The system message fights this — hard — but watch for leaks.
- **2G DSM specifics.** The model has seen SOME DSM forum content, but
  not enough to be an authority. If it volunteers an exact value for a
  4G63 spec, verify it against `offices/tuner/knowledge.md`.

## Quality gates Ralph should watch for during review

Apply these when spot-checking Ollama output in dev:

1. **Data citation test.** Does every recommendation cite a specific
   number or observation from the input? If it could apply to any car,
   it is noise — kill it.
2. **Hardware envelope test.** Does any recommendation require wideband
   AFR, ECMLink, knock count, or custom PIDs? If yes, the system message
   leaked and the model is off-envelope.
3. **Number consistency test.** Sample a recommendation that cites a
   number. Does that number match the prompt input? If not, the model
   hallucinated — discard the whole analysis for that drive.
4. **Duplicate test.** Are two items saying the same thing in different
   words? ("Monitor coolant temp" + "watch ECT trends" = one item.)
5. **Confidence calibration test.** Is the model saying 0.9+ on things
   that are actually speculative? Expect Ollama to over-confidence. As a
   rule of thumb: trust confidence >= 0.7 only when the recommendation
   also passes the data citation test.
6. **Empty-array test.** When fed a completely normal drive with no
   anomalies and no trends, does the model return `[]`, or does it
   manufacture 5 generic items? The former is correct. The latter means
   the system message's "do not pad" instruction failed.

## Failure modes — what to do when they happen

- **Ollama down / timeout** — fall back to the Sprint 8 stub response
  shape. Log WARNING. Do not 500 the request.
- **Malformed JSON in response** — the story scope says we store the
  model output somewhere; please store the raw text alongside the parsed
  recommendations so we can debug. Log ERROR. Return empty recommendations
  array to the client.
- **Hallucinated numbers** — cannot be detected at runtime, only in
  review. Flag in the design note as a known risk; add a CLI flag to
  `scripts/report.py` later that diffs claimed numbers vs. actual stats.
- **All recommendations are off-envelope** — indicates the system prompt
  is being ignored by the model. Increase temperature penalty, or switch
  to a larger model (llama3.1:70b) for a test comparison.

## Suggested review ritual (post-first-real-drive)

When the first real drive data lands and gets analyzed, I want to see:

1. The raw drive statistics (for my own review)
2. The rendered user message (what Ollama actually saw)
3. The raw model response (pre-parse)
4. The parsed recommendation list

Drop those in my inbox and I will grade the output against the quality
gates above. If the model is producing good work, we relax. If it is
producing generic advice, we tighten the system message and iterate.

## Scope notes

- **Schema**: I stayed with the sprint-spec schema (rank / category /
  recommendation / confidence). A `severity` field would be useful but
  confidence approximates it for now. Revisit after first real drives.
- **Fields consumed from Marcus's proposal**: all of them. Each one adds
  signal.
- **Extensions I am NOT asking for yet**: ECMLink-aware fields, per-cylinder
  data, knock events, wideband AFR. All are Phase 2. Add when hardware
  arrives.
- **Model size**: `llama3.1:8b` is sufficient for this prompt. If quality
  is poor in testing, the next escalation is `llama3.1:70b`. Do not need
  to go there yet.

— Spool
