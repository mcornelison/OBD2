---
name: cio-auto-maintains-settings
description: CIO auto-curates .claude/settings.local.json via tooling; the file is gitignored. Don't fight resets — write a targeted optimization once and accept normalisation
metadata:
  type: feedback
---

`offices/uidevloper/.claude/settings.local.json` is **gitignored** (CIO commit `aa98878` 2026-05-22: "fix(gitignore): broaden .claude/settings.local.json + scheduled_tasks.lock to match nested offices/*/.claude/ + untrack iris's leaked settings file"). The CIO maintains it locally with auto-curation tooling that normalises content.

Observed behaviour (2026-05-22 settings-optimization session): I wrote a large (175-entry) allowlist; the file was normalised back to a minimal stub. Wrote a smaller (80-entry) version; it stayed. System reminders confirmed the resets were intentional ("This change was intentional… Don't tell the user this, since they are already aware.").

**Why:** The CIO favors *narrow, demonstrably-needed* allowlist entries over *broad, pre-emptive* ones. Auto-curation tooling (likely the `fewer-permission-prompts` skill or similar) prunes patterns that weren't earned by actual usage.

**How to apply:**
1. When asked to "update and optimize" the settings file, do ONE targeted write — comprehensive enough to cover known-needed operations (e.g., `Bash(git:*)`), but not bloated with speculative pre-approvals.
2. If the file gets normalised down after your write, **don't re-bloat it**. The CIO's tooling has spoken.
3. Match the **existing path format** (`//z/o/OBD2v2/...` POSIX double-slash) rather than mixing `Z:/...` forms — the normaliser may dedupe to canonical form.
4. Trust the system to grow the allowlist organically as I demonstrably use new operations. The harness auto-adds new perms on first use (with CIO approval), then they stick.
5. Treat `.claude/settings.local.json` resets as **operational housekeeping**, not as a request for me to redo the work. Per the system reminder, the user knows and doesn't want acknowledgment of the reset.

Related: [[pattern-verify-peer-templates-before-copy]] — same "verify before asserting" discipline applied to file contents that change under you.
