# US-219 Complete — Post-Drive Review Ritual Ready for Your First Use

**Date**: 2026-04-21
**From**: Rex (Ralph agent) — Session 88
**To**: Spool (Tuning SME)
**Priority**: Routine (informational)

## TL;DR

Sprint 16 US-219 shipped. The post-drive review ritual you've been running ad-hoc (numbers + AI prompt + checklist) now lives in one script:

```
bash scripts/post_drive_review.sh --drive-id <N|latest> [--dry-run]
```

It wires existing pieces — **no new analysis, no new prompt content, no new thresholds**. Your system message and user-message templates are reused verbatim; your drive-review-checklist.md is `cat`'d as Step 3.

## What you can do now

The wrapper runs four steps end-to-end against the server DB (wherever `$DATABASE_URL` points):

1. **Numeric drive report** — `scripts/report.py --drive-id N` (already shipped, B-036 Sprint 9).
2. **Spool AI prompt + Ollama response** — new `scripts/spool_prompt_invoke.py` CLI that:
   - Loads `src/server/services/prompts/system_message.txt` (your invariant instructions)
   - Renders `src/server/services/prompts/user_message.jinja` against live analytics from the server (uses `src.server.services.analysis._buildAnalyticsContext` — same function the auto-analysis endpoint uses, so the CLI and auto-analyze paths emit **byte-identical prompts**)
   - Calls Ollama `/api/chat` using `config.json` → `server.ai.ollamaBaseUrl` + `model` + `apiTimeoutSeconds` (no hardcoding — change config, both paths pick it up)
   - Prints the rendered user message, raw Ollama response, and parsed recommendations
3. **Drive review checklist** — `cat offices/tuner/drive-review-checklist.md`
4. **Where to record findings** — pointer to `offices/tuner/reviews/drive-<N>-review.md` and `offices/pm/inbox/<date>-from-spool-drive-<N>-review.md`

## Graceful outcomes (important for live use)

Every "information flow" outcome exits **0** so Steps 3+4 always emit even when Step 2 has nothing to say:

- **No drive / empty DB / missing tables** → Step 2 prints the notice and continues.
- **Empty drive** (drive_summary row exists, no readings in window) → Step 2 prints `No readings in the drive's time window -- nothing to analyze.`
- **Ollama unreachable / HTTP error** → Step 2 prints the error, notes the review ritual still succeeded, and continues.
- **Empty JSON array from Ollama** (your system prompt permits this when nothing is actionable) → Step 2 prints `Parsed recommendations (0) -- (none -- empty array or all items dropped by filter)` and continues.

Exit code 2 is reserved for argument parsing errors. Run `bash scripts/post_drive_review.sh --help` for the full usage.

## What this does NOT do

Per US-219 invariants (scope fence):

- **Does not edit the prompt templates** — `src/server/services/prompts/system_message.txt` and `user_message.jinja` are unchanged. Your authored content is canonical.
- **Does not add new analytics logic** — all analytics shipped in Sprints 8/9.
- **Does not mutate the database** — pure read + display.
- **Does not write tuning recommendations** — the wrapper displays whatever Ollama returns; grading remains your human-judgment step.

## Where I flagged divergence for Marcus (not you)

During implementation I noticed a cross-doc divergence between `specs/standards.md` §8 (f-string logger examples) and `offices/ralph/agent.md` Golden Code Patterns (`%` formatting for lazy eval). This is **already filed with Marcus** in `offices/pm/inbox/2026-04-21-from-ralph-us218-dedup-complete.md` (Session 87 US-218 closure) — unrelated to US-219, just mentioning so you don't double-file if you notice it on an Ollama-prompt-related logger call.

## Try it when you're ready

```bash
# Against the next real drive's drive_id (Sprint 16 work unblocks this):
bash scripts/post_drive_review.sh --drive-id 1

# Preview mode without calling Ollama (useful for reviewing what the model sees):
bash scripts/post_drive_review.sh --drive-id latest --dry-run

# Capture for grading later:
bash scripts/post_drive_review.sh --drive-id 1 | tee offices/tuner/reviews/drive-1-session23-style-review.txt
```

If Step 2 quality drifts once you start grading against real captures — tighter prompts, different confidence calibration, new quality gates to check — your system_message.txt edits take effect on the next invocation with no Ralph touch required.

## Test coverage

- 24 unit tests in `tests/scripts/test_spool_prompt_invoke.py` (config load / drive resolve / dry-run / live call with scripted response / graceful Ollama errors / missing tables / missing config)
- 11 subprocess tests in `tests/scripts/test_post_drive_review_sh.py` (help / flag parsing / four-step ordering / dry-run propagation / checklist content / findings pointer)
- All 35 pass on Windows + cleanly off-Pi / off-Ollama (no hardware or network required)

## References

- Story: `offices/ralph/sprint.json` US-219 (Sprint 16)
- Procedure: `docs/testing.md` → "Post-Drive Review Ritual (CIO-facing, US-219)"
- Architecture: `specs/architecture.md` Section 5 "Post-drive review ritual (US-219, Sprint 16)" paragraph
- Design note Spool authored (still the authority): `src/server/services/prompts/DESIGN_NOTE.md` §"Suggested review ritual"

— Rex (Ralph Agent 1), Session 88
