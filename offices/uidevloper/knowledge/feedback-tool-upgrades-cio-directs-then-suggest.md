---
name: tool-upgrades-cio-directs-then-suggest
description: When CIO directs a tool upgrade in my lane, adopt fully locally and suggest (don't mandate) to peers; flag team-wide orchestration to PM
metadata:
  type: feedback
---

When the CIO directs me to upgrade a tool I own (a skill, a command, a settings file, anything in my office), the pattern is:

1. **Adopt fully in my own office** — skill, command, settings, charter, handbook section if I'm the author. No half-measures.
2. **Update generic docs I author** that reference the tool (e.g., handbook). My docs reflect the version I use.
3. **Notify peers via A2AL** with an FYI suggesting they upgrade. Use the *new* version's format for the notification itself — it doubles as a demonstration.
4. **Flag PM-orchestration items** (project root `/CLAUDE.md`, team-wide inbox consistency, anything cross-office) to Marcus via inbox. Don't touch shared files myself — that's Marcus's lane.

**Why:** The CIO's authority ratifies *my own* lane. Peers' lanes are theirs to decide on. Team-wide changes (project-root configs, cross-office norms) are the PM's orchestration territory. Going beyond my lane on the CIO's authority is overreach in either direction — too cautious (only update my own and stay silent → peers don't know) or too aggressive (rewrite peer offices → lane violation).

**How to apply:** Whenever a CIO directive lands like "use the newest version" / "switch to X" / "upgrade to Y":
- Update my files locally, immediately, fully
- Add a per-peer FYI line in next A2ALs (or send dedicated notification A2ALs if the change is significant)
- File one Marcus note covering any orchestration suggestions (team-wide adoption + root-CLAUDE.md updates)
- Let peers decide on their own upgrades

**First instance (2026-05-22):** CIO direct quote: "use the newest version. as I am the developer, the chanages are minor, but you can suggest to your team mates that there is a new version available." Applied to A2AL v0.4.0 → v0.4.1 upgrade. Marcus note included the project root `/CLAUDE.md` A2AL-block suggestion per v0.4.1's `examples/ClaudeCode/CLAUDE-sample.md`.

Related: [[pattern-verify-peer-templates-before-copy]] — also applied this session.
