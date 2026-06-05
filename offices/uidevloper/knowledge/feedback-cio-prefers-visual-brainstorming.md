---
name: feedback-cio-prefers-visual-brainstorming
description: CIO is a strongly visual thinker — HTML mockups / the visual-companion mode resonate far more than text for design work. Default to showing, not telling. RATIFIED as standing default (CIO 2026-06-05 DTC session: "that is my preference going forward. 100% proceed with using a browser") — no need to re-offer the companion each session for UI work.
metadata:
  type: feedback
---

# CIO is a visual thinker — show mockups, don't just describe

During F-092/F-097 brainstorming (2026-06-05) the CIO volunteered, unprompted:
*"I really like this way of interacting with you. I am a very visual person and
seeing your thoughts is on target."* This was in response to the **superpowers
brainstorming visual companion** (HTML mockups served to his browser, one design
question per screen, clickable A/B options).

**Why:** the CIO processes layout/UX decisions far better by SEEING them than by
reading prose or ASCII. Concrete rendered mockups with side-by-side options let him
react fast and accurately ("on target"). This matches the whole project history —
he responds best to rendered enclosure images, ASCII layout sketches, and now live
HTML mockups.

**How to apply:**
- For any UI/UX or layout design work, **default to the visual companion** (HTML
  mockups in the browser) or, if remote/unavailable, rich ASCII mockups in the
  terminal. Offer the companion early.
- Show 2–4 concrete options side-by-side with real(istic) data, not abstract
  descriptions. Let him click/choose.
- One design question per screen; advance only when the current one is settled.
- This pairs with [[feedback-brainstorming-stall-nudge-pattern]] (keep momentum,
  don't stall) and [[feedback-cio-clarifying-questions-always-welcome]].
- Enclosure/3D work: keep sending rendered images (same principle, different medium).

## Tooling gotcha — companion server idle-times-out between turns

On this Windows + shared-checkout setup, the superpowers visual-companion server
(`start-server.sh --project-dir … ` run with `run_in_background:true`) **can't anchor
to the parent process** ("owner-pid-invalid … dead at startup") and so falls back to a
short idle timeout — it shuts itself down during the gap while the CIO is reading/deciding.
Symptom: CIO reports "localhost:PORT not showing up." Each relaunch gets a **new port +
new session dir**, so the URL changes.

**How to apply:** when it dies, just relaunch and **re-push the current screen** into the
NEW session's `content/` dir (the server only serves files in its own session dir), then
give the CIO the new URL. Keep turns tight so the read happens before idle fires. Mockups
persist under `offices/uidevloper/.superpowers/brainstorm/` (gitignored via a `*`
`.gitignore` I dropped there). Stop the server cleanly at closeout (`stop-server.sh
<session-dir>`); a SIGTERM "failed exit 143" notification on the background task is the
expected stop, not an error.

See also: [[pattern-defects-first-existing-artifact-review]], [[pattern-ground-in-existing-implementation]].
