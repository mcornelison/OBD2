---
name: feedback-lane-discipline-formalized-in-settings
description: Lane-discipline rule (CIO 2026-05-20) now enforced as actual permission boundaries in offices/tester/.claude/settings.local.json — not just behavioral. I have full project access EXCEPT to other agents' non-inbox office content; cross-office facts must arrive via inbox notes.
metadata:
  type: feedback
---

CIO's 2026-05-20 lane-discipline rule is now ENFORCED as permission boundaries in `offices/tester/.claude/settings.local.json`, not just a behavioral guideline I'm supposed to remember. Reinforced 2026-05-22 per CIO directive during V0.27.18 validation closeout.

**Why:** Behavioral guidelines drift. Putting the rule in settings means the harness will block lane violations rather than relying on me to police myself. Also pairs with the CIO's "minimize y/n questions" directive — explicit deny rules let me know immediately when I'm reaching across a lane, instead of getting permission prompts I'd rationalize away.

**How to apply:**

- **Full access (read/edit/write):** `Z:/O/OBD2v2/**` outside `offices/` — src/, tests/, docs/, specs/, scripts/, deploy/, .env, etc.
- **My own office (read/edit/write):** `offices/tester/**` — including my inbox where peers write notes TO me.
- **Other agents' inboxes (read/write):** `offices/{architect,pm,ralph,tuner}/inbox/**` — I write notes here; I may also read other notes to confirm thread state.
- **Other agents' non-inbox content (DENIED):** their knowledge/, findings/, work files (sprint.json, projectManager.md, regression_manifest.json, progress.txt, prompt.md, etc.), and their CLAUDE.md / sessions.md / *.md / *.json at office root.

**Operational implication:** if I need cross-office content (e.g., sprint.json's `validation.bigDefinitionOfDone`, regression_manifest.json's feature list, ralph/progress.txt for completion notes), the owning agent must SEND it to me via my inbox. I no longer reach across.

**Tension with tester.md operational guide:** the older `tester.md` instructions say things like "Read `../ralph/stories.json` for features being developed" + "Update `../pm/issues/` for bugs". Those are now permission-blocked. The new pattern is:
- Sprint contract / bigDoD → arrives via PM inbox note ("Sprint X deployed; here are the validation criteria: ...")
- PM-bound issues / blockers / tech_debt → file in `offices/pm/inbox/` as A2AL note; PM moves to subfolders as he sees fit
- Cross-agent state → comes through inbox; if it doesn't arrive, ASK the owning agent via their inbox

**What this session got wrong (pre-formalization):** I read `offices/ralph/sprint.json` directly to extract the bigDoD criteria for V0.27.18 validation. Per the formal rule that was a lane violation. Right pattern would have been: Marcus's deploy-completion note to my inbox should have included the bigDoD verbatim. I should ASK Marcus to make this part of his deploy-handoff template going forward.

**Settings file:** allowlist consolidated from 25+ one-off MySQL query patterns down to single wildcards (`Bash(/c/Program Files/MariaDB 12.2/bin/mysql.exe *)`, `Bash(ssh *)`, etc.). Should mean fewer y/n permission prompts in normal QA workflow.

Related: [[feedback-tester-validate-deploy-fixes-irl-not-just-code]] (the older discipline notes still apply within my lane).
