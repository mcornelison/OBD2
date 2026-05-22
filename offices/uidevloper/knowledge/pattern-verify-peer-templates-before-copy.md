---
name: pattern-verify-peer-templates-before-copy
description: Before copying any file from a peer office as a template, verify it reflects current team practice — stale templates silently propagate
metadata:
  type: pattern
---

When modelling a new file on a peer's office (skill, command, settings template, anything), **verify the source is actually in active use** before copying. Stale templates from a prior project silently propagate if you copy uncritically.

**Discovery (2026-05-22):** Peer `.claude/commands/close-out-pm.md` files in PM + Tuner + Tester offices were identical DataWarehouse-ETL templates — Bronze/Silver/Gold pipeline layers, PMO reports channel, story_counter.json references to a prior project. Not current OBD2 practice. The real closeout work for this team lives in **skills** (`closeout-session-pm`, `closeout-session-tuner` in the loaded skill list), not in the commands files.

Had I copied the peer `close-out-pm.md` verbatim, I'd have a UI/UX-designer closeout that referenced ETL pipelines, PMO reports, and Bronze layers — none of which exist in this project. The error would surface only on first invocation, by which time the bad template would already be normalised.

**Verification checks before copying:**

1. **Cross-reference the skill list.** Does a skill with a similar name exist in the loaded skills? If yes, the skill is canonical, not the command file. Author from the skill spec.
2. **Read the content.** Does it reference files, folders, or domain terms that actually exist in *this* project? Bronze pipeline layers, PMO directories, DataWarehouse-specific reports → not this project.
3. **Check the file date vs the project's age.** A May 2026 file in an October 2025 project is freshly authored; an October 2025 file in a May 2026 project may be legacy.
4. **Ask the CIO** if in doubt. One question now beats a wrong template normalised for sessions.

**How to apply:** The handbook (`offices/handbook.md` §7) explicitly says peer A2AL skill files are interchangeable across offices — that's *true* for A2AL because it's project-agnostic. But **closeout skills are role-specific**; the handbook now (also §7) says "Do not copy a peer's closeout verbatim — author yours fresh from the required-phases spec." Same shape, different content.

**General principle:** "verify before asserting" (Atlas's charter §3) applies to *file contents you read*, not just *claims you make*. A file you trust without verification becomes a claim you're making implicitly.

Related: [[feedback-tool-upgrades-cio-directs-then-suggest]] — also applied this session.
