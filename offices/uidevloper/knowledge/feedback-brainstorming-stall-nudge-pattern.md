---
name: feedback-brainstorming-stall-nudge-pattern
description: The brainstorming skill (superpowers:brainstorming) sometimes stalls 30-60 min mid-flow on CIO's machine — nudge with ESC + "continue" rather than waiting silently
metadata:
  type: feedback
---

CIO observation (2026-05-22, submitted via `/feedback` to Anthropic):
"There have been many times that during a brainstorming session that the
process stalls. no activity for 30-60 minutes at a time. I then hit the
ESC a few times and then say 'continue' and it picks up where it left
off. and the remote-control experience for brainstorming is not the
best either."

**Why:** The `superpowers:brainstorming` skill is a process skill with
multiple sequential gates (clarifying questions → propose approaches →
present sections → write design → review → invoke writing-plans). At
each gate the assistant waits for user input. On CIO's setup the wait
state occasionally becomes a stall — assistant doesn't produce output,
CIO doesn't see prompting, time passes. ESC + "continue" recovers it.
Remote-control session (the `/remote-control` slash) compounds the
problem.

**How to apply (for future-me invoking the brainstorming skill):**
- **Don't wait silently.** Always end my message with a clear "what I
  need from you next" — explicit prompt for the next input. Reduce the
  chance CIO is unclear whether it's his turn.
- **Compress brainstorming pacing on CIO's signal.** When CIO says
  "proceed" or "rough draft" or otherwise signals fast-collaborative
  mode, bundle related decisions in a single AskUserQuestion call (up
  to 4 questions). The skill's "one question at a time" is a default,
  not a hard rule — user instructions override (per
  `using-superpowers` hierarchy).
- **Use `AskUserQuestion` with previews** for visual / option-grid
  decisions — it renders better than free-text Q&A and reduces
  ambiguity that triggers stalls.
- **If a stall is detected mid-session** (long silence with no clear
  block) — assume it's the harness, not the CIO. Resume work
  proactively (e.g., commit, write, or present next phase).
- **Heads-up to CIO on long-running renders** — if I start a render
  that takes >30s, note it in chat so CIO doesn't interpret silence
  as a stall.

Related:
- [[user_mike_collaborative_advisor]] — CIO steers in real-time via
  short directives. Pace matches that.
- [[feedback-cio-clarifying-questions-always-welcome]] — clarifying
  questions are explicitly welcome; never substitute waiting for asking.
