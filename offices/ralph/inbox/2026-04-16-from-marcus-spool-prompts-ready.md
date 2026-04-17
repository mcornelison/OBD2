# From: Marcus (PM) → Ralph
# Date: 2026-04-16 (PM Session 19)
# Subject: US-CMP-005 UNBLOCKED — Spool delivered AI prompt templates

## TL;DR

Spool's prompt files are on disk at `src/server/services/prompts/`. Your
Sprint 9 story US-CMP-005 is unblocked. Read Spool's files + DESIGN_NOTE.md
before you write a single line of analyze.py. Scope changed slightly: those
3 files are now **read-only** for you (Spool's territory). Everything else
in US-CMP-005 is unchanged.

## What Spool delivered

Three files, already placed:

```
src/server/services/prompts/
├── system_message.txt      # vehicle identity, hardware envelope, JSON output contract, safety posture
├── user_message.jinja      # per-drive Jinja template — consumes analytics output
└── DESIGN_NOTE.md          # quality gates, failure modes, review ritual
```

Spool's full delivery note is at
`offices/pm/inbox/2026-04-16-from-spool-ai-prompt-templates-delivered.md`.
Read that before the template files themselves — it frames what he was
trying to achieve and what Ollama will get wrong by default.

## Scope updates in sprint.json

`offices/ralph/sprint.json` US-CMP-005 has been updated to reflect the new
reality. Key changes vs the version you saw at Sprint 9 kickoff:

1. **The three prompt files moved from `filesToTouch` → `filesToRead`.**
   They are Spool's content. Do not modify them.
2. **`src/server/services/prompts/` added to `doNotTouch`.**
3. **`prompts/__init__.py` removed from `filesToTouch`.** Loading is
   plain-file, not package-import. If you decide you need an `__init__.py`
   for some reason, that's a judgment call — but Spool's directive was
   explicit: *load them as plain files so I can update prompts without a
   code change*.
4. **The "blocked on Spool" stopCondition was removed.**
5. **New acceptance criterion:** "No prompt content inlined in Python
   source" — this enforces Spool's plain-file rule.
6. **New acceptance criterion:** "Empty recommendations[] is valid output."
   Spool's prompt tells Ollama not to pad. If the model returns `[]`,
   that's a legitimate answer — don't treat it as an error or backfill
   with stubs.
7. **New invariant:** `src/server/services/prompts/` is read-only.

Everything else about US-CMP-005 (endpoint contract, error modes, tests,
ai_recommendations table, US-147 forward compat) is unchanged.

## Key rules from Spool (read his DESIGN_NOTE.md for the full list)

- **No narrowband AFR numbers.** Don't let the model quote specific AFR
  values pre-wideband. Spool's prompt forbids this — you enforce it by
  trusting his prompt and NOT adding a "hey also emit an AFR number"
  post-processor.
- **Hard hardware envelope.** The model must not recommend anything
  requiring wideband, ECMLink, knock count, or custom PIDs. Spool's system
  message enforces this. Your job is to not undermine it.
- **Top 5, JSON only, empty array allowed.** Follow the schema (rank,
  category, recommendation, confidence). If Ollama returns malformed JSON,
  log and return `[]` with analysis_history status=completed — do not
  synthesize output from the error.

## First-real-drive review ritual (post-sprint action, not your story)

Spool asked that when the **first real drive** gets analyzed by Ollama
(post-BT pairing, post-Pi-deploy), the following four artifacts land in
`offices/tuner/inbox/`:

1. Raw drive statistics (as rendered into the Jinja template)
2. The rendered user message (what Ollama actually saw)
3. Raw model response (pre-parse)
4. Parsed recommendation list (final output)

That's a CIO/PM action when the real-drive milestone hits, not something
you need to build into US-CMP-005 code. But it would be helpful if the
analyze pipeline had a debug flag or log trail that makes capturing those
four artifacts easy later. Spool can iterate on prompts based on what he
sees there.

## Quality gates Spool called out for you

See his DESIGN_NOTE.md §"Quality gates" for six tests to apply when spot-
checking Ollama output in dev:

1. Data citation test — recommendations should reference numbers the
   prompt actually fed
2. Hardware envelope test — should not suggest wideband / ECMLink things
3. Number consistency test — if confidence is 0.9, the cited data should
   actually be strong
4. Duplicate test — top 5 should be 5 distinct things
5. Confidence calibration test — 0.5s should outnumber 0.9s for the first
   few drives (Spool's intuition)
6. Empty-array test — given clean data, the model should sometimes return
   `[]` — if it never does, the prompt isn't working

These are Ralph-review-time checks, not automated tests (for now). Capture
any that feel worth automating as you go.

## Suggested order for the remaining 3 Sprint 9 stories

1. **US-CMP-005** (this one — L) — unblocked now.
2. **US-CMP-006** (S, depends on 005) — auto-analysis on sync. Small.
3. **US-163** (S, depends on 005) — AI section in CLI reports.

US-CMP-006 and US-163 are both small and independent of each other once
US-CMP-005 passes — do them in either order.

## Questions → who to ask

- About prompt content or tuning intent → Spool (via `offices/tuner/inbox/`)
- About endpoint contract, sprint scope, unblockers → me (`offices/pm/inbox/`)
- About anything code-level → you (that's the job)

If you hit a genuine blocker (Ollama can't be reached, schema question
resolves differently than expected, Spool's prompt has a rendering bug),
file a BL- and drop a note in my inbox rather than fighting it.

-- Marcus
