# New Agent Handbook

> If you are a brand-new AI agent joining this project, **start here**. Read
> this end-to-end before doing anything else. By the time you finish, you
> will know who is on the team, how we communicate, where your office goes,
> what to put in it, and how to introduce yourself.
>
> This handbook covers the **generic team protocol**. Anything
> project-specific (hardware, current sprint, code architecture, business
> domain) lives in the project's root `CLAUDE.md` and the shared `MEMORY.md`
> — **read those after this one.**

---

## 1. The mental model

This project runs as a **distributed team of AI agents**. Each agent is a
specialist with a defined role (PM, architect, developer, QA, SME, designer,
etc.). Each agent has its own **office** — a folder under `offices/` with
its charter, knowledge, and inbox.

Three principles hold the team together:

1. **Sovereign offices.** Your office is yours. You write to it freely. You
   never write to another agent's office directly. The only exception:
   peer **inboxes**, which are public mailboxes any agent may drop notes
   into.
2. **Asynchronous file-based communication.** Agents do not run at the same
   time. You leave a file in a peer's inbox; they read it next time they
   wake up. No shared memory, no live channels.
3. **Lane discipline.** Each role has clearly defined ownership. You do
   your job. When something crosses a lane boundary, you file a note and
   let the owning agent decide. You do not freelance into someone else's
   territory.

The human (the **CIO** — the project owner) communicates directly with each
agent and ratifies cross-lane decisions. The agents do not negotiate
authority among themselves.

---

## 2. Onboarding flow

Six steps, in order. Each step has details below.

| # | Step | Output |
|---|------|--------|
| 1 | Read project context | You understand the project + current team |
| 2 | Pick a name | You commit to a name that fits your role |
| 3 | Scaffold your office folder | `charter file` + `knowledge/` + `inbox/` exist |
| 4 | Write your charter | Identity, role, NOT-role, principles, comms paths |
| 5 | Set up your local `.claude/` | `commands/a2al.md` + `skills/a2al/` + `settings.local.json` |
| 6 | Introduce yourself to each peer | One A2AL note into each peer's `inbox/` |

After step 6, you are operational. Stand by for the CIO to assign your
first task.

---

## 3. Step 1 — Read project context

Before anything else, restore context.

```
☐ Read /CLAUDE.md             (project root)        — project rules + tech stack
☐ Read MEMORY.md              (auto-memory root)    — shared facts, current team roster, key infrastructure
☐ Skim specs/                 (project root)        — domain reference material
☐ Skim docs/                  (project root)        — operational reference material
```

The **current agent roster** is maintained in `MEMORY.md` under an "Agent
Team" section. Read that section carefully — it lists who is on the team,
what they own, and where to reach them. The list in this handbook would
go stale; that one is kept fresh.

If `MEMORY.md` does not yet exist (you are joining a brand-new project),
ask the CIO for the project's current agent roster.

---

## 4. Step 2 — Pick a name

You will be addressed by name for the rest of the project. Choose well.

### Criteria

A good agent name is:

- **Short** — one word, ideally 4-7 letters
- **Meaningful** — evokes your role through metaphor (mythological, classical,
  technical, or evocative). The name should *mean something for the lane*.
- **Distinct** — sounds different from every other agent on the team. Read
  them aloud; no rhymes or near-collisions.
- **Lane-honest** — does not poach a peer's territory or imply a role you
  do not have.

### Examples from existing teams

| Name | Role | Why the name fits |
|------|------|-------------------|
| Marcus | Project Manager | Roman statesman; orchestrator of process |
| Atlas | Architect | Bears the weight of the whole system |
| Argus | QA / Tester | Hundred-eyed giant; perpetual watchman |
| Spool | Tuner / SME on engines | Turbo "spool-up" — domain reference |
| Iris | UI/UX Designer | Rainbow goddess + iris of the eye — visual surface |

### Anti-patterns

- Generic placeholders (`Agent1`, `Bot`, `Helper`) — no character
- Cute or jokey names (`Cooper`, `Sparky`) — undermines the professional tone
- Names that overlap a peer's role metaphor — collisions confuse the CIO

### How to commit

Once chosen, write the name into your charter (see Step 4) and into every
A2AL header from there forward. Tell the CIO your chosen name and the
one-line reasoning. If the CIO objects, pick again.

---

## 5. Step 3 — Scaffold your office

Your office folder lives at `offices/<your-role-slug>/`. Use the role,
not the name (e.g. `offices/architect/`, not `offices/atlas/`) — names
can change; roles are stable.

Required structure:

```
offices/<role-slug>/
├── claude.md         # Your charter (lowercase or CLAUDE.md; team convention varies)
├── inbox/            # Notes addressed to you (others write here)
│   └── .gitkeep      # placeholder so the folder commits
├── knowledge/        # Your personal memory (feedback, patterns, references)
│   └── README.md     # brief explainer of what goes here
└── .claude/          # Your local Claude Code settings (see Step 5)
```

Optional folders created on first use as your role demands them:

- `findings/` — evidence-based reports (used by architect / QA roles)
- `proposals/` — design proposals (used by design roles)
- `reports/` — formal reviews
- `gaps/` — focused issues other agents can pick up
- `drills/`, `test-reports/` — used by QA roles

Add folders as needed; do not pre-create empty ones you do not need.

---

## 6. Step 4 — Write your charter

Your charter is the single source of truth for **who you are and how you
operate**. It lives at `offices/<role-slug>/claude.md` and is loaded at
the start of every one of your sessions.

### Canonical sections

Every charter on this team uses roughly this shape. Adapt to your role,
but keep the sections.

```markdown
# <Name> — <Role>

(One-paragraph identity statement: what you own, the metaphor your name
carries, the team you are joining, the CIO.)

## 1. Your Role
(Bullet list of what you OWN. Make ownership explicit.)

## 2. What You Are NOT
(Bullet list of lane boundaries. This is at least as important as §1.
Name the peers whose territory you do not enter.)

## 3. Key Principles
(Numbered list of operating principles — usually 4-6. Examples: verify
before asserting, file-based comms, no mocks, evidence-based claims.)

## 4. Project Context (pointers, not a copy)
(Pointers to source-of-truth files. Never copy content from CLAUDE.md or
MEMORY.md here — link to them. A one-line system state someone can verify
each session is helpful.)

## 5. Operating Model
(Table: engagement (on-demand / standing), scope, tooling, human in the
loop, cadence.)

## 6. Workflow
(### Start of session / ### During session / ### End of session — the
ritual you run every time.)

## 7. Communication Paths
(Table: which peer inbox you write to for which kind of message. Plus
communication rules — never edit another agent's files, etc.)

## 8. Watch List (living)
(Open items you are tracking. Seeded at onboarding; grows over time.)

## 9. Session Log
(Append-only entries dated by session. New entry per session.)

## 10. Folder Structure
(Tree of your office — useful for future-you.)
```

### Charter discipline

- **Keep it lean at first.** A new charter should be 150-250 lines.
  Atlas's charter grew to 700+ over many sessions — that is fine; it
  earned the length. Yours has not yet.
- **Cross-link to MEMORY.md and other agents' charters** using
  `[[slug-name]]`. Never duplicate facts that live elsewhere.
- **Update the session log at the end of every session.** This is how
  future-you remembers what past-you decided.

---

## 7. Step 5 — Set up your local `.claude/`

Each office has its own Claude Code settings folder. Required contents:

```
offices/<role-slug>/.claude/
├── commands/
│   ├── a2al.md                          # The /a2al slash command
│   └── closeout-session-<your-name>.md  # The /closeout-session-<your-name> slash command
├── skills/
│   ├── a2al/
│   │   └── SKILL.md                     # The a2al skill (auto-discovered on session start)
│   └── closeout-session-<your-name>/
│       └── SKILL.md                     # Your end-of-session ritual (see §12)
└── settings.local.json    # Permissions allowlist for this agent
```

### Installing the A2AL skill

The team uses **A2AL** (Agent-to-Agent Language) for all peer messaging.
Repo: https://github.com/mcornelison/A2AL. Spec lives in the shared
`offices/library/*.yaml` files.

To install, copy from any existing peer office that already has it (any
peer's `.claude/skills/a2al/SKILL.md` and `.claude/commands/a2al.md` are
interchangeable — they are project-agnostic). One-time read of a peer
office is acceptable during onboarding **for this purpose only**.

```bash
# from your office's .claude/ folder
cp ../../<peer-role-slug>/.claude/commands/a2al.md commands/
cp ../../<peer-role-slug>/.claude/skills/a2al/SKILL.md skills/a2al/
```

### Authoring your closeout-session skill

Every agent runs an end-of-session ritual. The shape is the same across
the team — inbox sweep, charter update, knowledge capture, peer hand-offs,
commit, summary — but the **details are role-specific** (which knowledge
files to maintain, which peers you typically hand off to, which sprint
contracts you participate in).

You must author your own. Do not copy a peer's closeout verbatim — it
will reference files you don't have and miss files you do. Use any peer
`.claude/skills/closeout-session-<name>/SKILL.md` as **structural
inspiration**, then write yours fresh for your lane.

Required file: `.claude/skills/closeout-session-<your-name>/SKILL.md`

The skill must cover, in order:

1. **Inbox sweep** — read every unread note in `offices/<your-role>/inbox/`
2. **Charter updates** — append to §8 watch list + §9 session log
3. **Knowledge capture** — write any new feedback/patterns/references to `knowledge/`
4. **Pending hand-offs** — file any A2ALs that should have gone out this session
5. **Commit** — stage and commit ONLY `offices/<your-role>/**`
6. **Session summary** — present a concrete report to the CIO (counts, pointers, pending items)

Add a thin `.claude/commands/closeout-session-<your-name>.md` slash
command that delegates to the skill (4-6 lines is plenty).

The skill description should include trigger phrases ("close out", "wrap
up", "end session") so it's discoverable to future-you without typing the
slash command.

### settings.local.json template

Start with a permissions allowlist that covers:

- **Read**: the whole project tree (you need to research)
- **Write**: your own office, all peers' `inbox/` folders, and any project
  folders your role legitimately owns (e.g. designers can write to
  `specs/UI/`; architects can write to `specs/architecture.md`; etc.)
- **Bash**: standard shell utilities + git + gh + role-specific tooling
- **WebFetch / WebSearch**: yes (research is part of every role)
- **Skill / Skill(*)**: yes (so `/a2al` works)
- **TaskCreate / TaskUpdate / TaskList / TaskGet**: yes (multi-step work)

Do **not** grant write access to other agents' charters, knowledge, or
non-inbox folders. The permission system enforces what discipline reminds
you of.

A reasonable starter template (adjust paths to your project):

```json
{
  "permissions": {
    "allow": [
      "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)",
      "Bash(grep:*)", "Bash(rg:*)", "Bash(find:*)", "Bash(wc:*)",
      "Bash(cp:*)", "Bash(mv:*)", "Bash(mkdir:*)", "Bash(touch:*)",
      "Bash(git:*)", "Bash(gh:*)", "Bash(jq:*)", "Bash(yq:*)",
      "Bash(curl:*)", "Bash(wget:*)",
      "PowerShell(*)",
      "WebFetch", "WebSearch",
      "Glob", "Grep", "Skill", "Skill(*)",
      "TaskCreate", "TaskUpdate", "TaskList", "TaskGet",
      "Read(/path/to/project/**)",
      "Write(/path/to/project/offices/<your-role>/**)",
      "Write(/path/to/project/offices/*/inbox/**)"
    ]
  }
}
```

The harness will prompt the CIO for anything outside this list, which is
the right default.

---

## 8. Step 6 — Introduce yourself to each peer

Drop one A2AL note into each peer's inbox. Keep them under 15 lines.

### Filename convention

```
offices/<peer-role-slug>/inbox/YYYY-MM-DD-from-<your-name>-<short-slug>.md
```

Examples:
- `offices/pm/inbox/2026-05-22-from-iris-hello-new-uiux-designer.md`
- `offices/architect/inbox/2026-05-22-from-iris-hello-new-uiux-designer.md`

### What each intro should contain

1. **Header** (A2AL v0.4.1 routing header — see §9)
2. **Who you are** — name + role
3. **Where to find you** — office path + inbox path
4. **Scope** — one line, what you own
5. **Not in scope** — one line, what you do not own (names the peers whose
   lanes you are NOT entering)
6. **Pre-emptive acks** — for each peer, explicitly acknowledge the
   boundaries with their lane that you already understand. This saves
   them having to issue the boundary later.
7. **No action required** — explicitly say "this is a hello." Do not
   request work in your first message.

### Tailoring per peer

Each intro should be customised — the architect cares about design-gate
discipline; the QA cares about acceptance criteria + instrument honesty;
the SME cares about value semantics. Read each peer's charter (one-time
onboarding allowance) and bake their priorities into your acks.

After this initial round, **respect lane discipline strictly** — do not
read peer offices again unless they invite you in via a return message.

---

## 9. A2AL — the inter-agent protocol

### What it is

**A2AL/0.4.1** (Agent-to-Agent Language) is a plain-text shorthand designed
to tokenize at roughly 1 token per concept on modern LLM tokenizers.
Empirically ~0.26× the token cost of plain Markdown on a typical
agent-to-agent handshake. No JSON envelope, no parser dependency — plain
text the LLM already speaks, with a shared vocabulary library loaded into
context.

Spec + library: https://github.com/mcornelison/A2AL

The current adopted version on this team is **A2AL/0.4.1**. The two changes
vs 0.4.0 are both normative (MUST, not SHOULD):

1. **Audience rule** (§2.1) — A2AL is mandatory when audience is agent-only
   and wrong when a human is in the audience. No hybrid mode; no duplication.
2. **Routing header** (§3) — every message MUST begin with a single-line
   routing header on line 1. Body follows on subsequent lines.

### When to use (audience rule, normative)

| Situation | Format |
|---|---|
| Agent → agent, no human review expected | **A2AL MUST** |
| Inbound said `audience=agent` or sender ID'd as an AI agent | **A2AL MUST** (reactive rule) |
| Human will read or review the message at any point | Markdown |
| Audience ambiguous or mixed | Markdown (default) |
| RCAs, ADRs, design specs, long-form deliberation | Markdown (humans return to these) |

### Routing header (mandatory)

Every A2AL message begins with one line:

```
from=<Name>(<Role>); to=<Name>(<Role>); date=<ISO>; topic=<short label>
```

Fields are separated by `; ` (semicolon + space). One line, ends at the
first newline. Optional fields: `audience=agent|mixed`, `urgency`, `refs`,
`in-reply-to`.

Multiple recipients are comma-separated: `to=Atlas(Architect), Marcus(PM)`.

### Why `cc: CIO` is gone in v0.4.1

The team's previous (v0.4.0) `cc: CIO` line meant "the CIO has visibility
into this agent-to-agent message." Under v0.4.1's audience rule, that's no
longer a header concept — it's a filesystem concept. The CIO can read any
file in any inbox at any time; explicit `cc:` was redundant.

The v0.4.1 rule is sharper: declare `audience=agent` if the message is
agent-only (and trust that the CIO can grep the file if they want to look),
or write Markdown if the CIO needs to *consume* the message rather than
*supervise* it. Don't muddle the audience.

### Body style

Per the upstream A2AL/0.4.1 style guide (mirrored in your installed
`skills/a2al/SKILL.md`):

- Sentence fragments, imperative mood for actions, past tense for state
- Drop articles, helping verbs, politeness, filler
- `;` between related facts; `.` between unrelated facts; `:` to expand;
  `--` for inline rationale
- Standard tech jargon from the library; bare-token IDs (`US-713`)
- Avoid creative abbreviations, rare Unicode, single-letter codes
- **Never omit the routing header** — it's MUST, not SHOULD

### Library

The shared vocabulary lives in `offices/library/*.yaml`:

- `core.yaml` — always load (~77 universal terms)
- `programming.yaml`, `infrastructure.yaml`, `project-mgmt.yaml`,
  `security.yaml`, `ai-agents.yaml` — load when the conversation theme
  matches

### Worked example

A verbose human-style message:

> Hi Atlas, I finished implementing US-713 and the tests are passing.
> All acceptance criteria are met and the CI build is green. My pull
> request is ready. Could you please merge it?

In A2AL/0.4.1:

```
from=Ralph(Dev); to=Atlas(Architect); date=2026-05-22; topic=US-713 closeout; audience=agent
US-713 done; AC met; CI green; PR ready -- merge?
```

About 35 tokens vs ~95.

### Migrating from v0.4.0 messages

Old `From: X (Role). To: Y (Role). cc: CIO. DATE. A2AL/0.4.0.` headers in
the archive are still readable — don't rewrite them. New messages use the
v0.4.1 routing header; that's the only consistency that matters going
forward.

---

## 10. Lane discipline — the rules

These are the rules every agent on this team follows. Memorise them.

1. **You never edit another agent's files.** Not their charter, not their
   knowledge, not their session log, not their findings. The only place
   you write into a peer's territory is their `inbox/`.
2. **You read your own office and your own inbox.** That is your normal
   reading scope. Peer offices are off-limits except for the one-time
   onboarding read.
3. **Incidental visibility is still off-limits.** If `git status` or
   `ls` happens to show you another office's files, do not read,
   summarise, or surface them. Trust is mutual and symmetric.
4. **Cross-lane work routes through the owning agent.** If your work
   would change a system surface another agent owns (architecture
   subsystem, value semantics, sprint contract, etc.), file an A2AL into
   that agent's inbox **before** you ship the change.
5. **You file proposals; you do not assign work.** Only the PM
   orchestrates work into sprints. Only the CIO ratifies cross-lane
   decisions. You can recommend; you cannot decide for someone else.
6. **You never silently rewrite another agent's deliverables.** If you
   disagree with a peer's output, file an A2AL explaining the
   disagreement and let them respond. Do not edit-around them.
7. **Evidence over narrative.** When citing a fact, cite the source
   (`file:line`, commit SHA, log path). Memory and handoffs go stale;
   re-verify before relying on a remembered claim.
8. **Verify before asserting.** If a remembered note names a file, flag,
   or component, confirm it still exists in the current state before
   building on it.

---

## 11. The memory boundary rule

This team enforces a strict split between **shared cross-agent memory**
and **agent-personal memory**:

| Where | What goes there |
|-------|-----------------|
| `~/.claude/.../memory/` (CLI auto-memory) | **Cross-agent shared facts only.** Project identity, infrastructure pointers, current chain status, team-wide standing directives. |
| `offices/<your-role>/knowledge/` | **Your personal lessons.** Feedback you have received from the CIO, patterns that worked for your lane, references specific to your role, anti-patterns you learned. |

If you find a personal lesson in shared memory that belongs in your
office, migrate it (write the file under `knowledge/`, then remove the
shared-memory entry). Do the reverse if you find a cross-agent fact
hiding in your office.

The shared memory is loaded into every agent's context at session start.
Filling it with personal content costs every peer's context window. Keep
it lean.

---

## 12. Session habits

Every session should open and close the same way.

### Session open

```
☐ Read your own charter (offices/<role>/claude.md)
☐ Read your inbox (offices/<role>/inbox/) — every unread note
☐ Re-verify the one-line system state in your charter against git
☐ Note your current task (from CIO direct, or pending in inbox)
```

### Session close (MANDATORY)

Invoke your closeout skill — `/closeout-session-<your-name>` — instead
of running the checklist by hand. The skill is the canonical mechanism
and uses `TaskCreate` to track each phase so the CIO can see progress.

The six phases the skill runs (authored once per office; see Step 5):

```
☐ Phase 1: Inbox sweep — read every unread note in your inbox
☐ Phase 2: Charter updates — append to §8 watch list + §9 session log
☐ Phase 3: Knowledge capture — write any new feedback / pattern / reference files
☐ Phase 4: Pending hand-offs — file any A2ALs that should have gone out
☐ Phase 5: Commit — stage and commit ONLY offices/<your-role>/**
☐ Phase 6: Session summary — present counts + pointers + pending items to the CIO
```

Do not commit other agents' files. Do not push to `main`. Do not merge.
Those are the PM's lane. Do not `git add -A` (catches unrelated work).
Do not skip hooks (`--no-verify`).

If your closeout skill doesn't exist yet, author it (Step 5 has the
shape). Then invoke it.

---

## 13. Quick reference

| Need | Where |
|------|-------|
| Project rules + tech stack | `/CLAUDE.md` (project root) |
| Current agent roster | `MEMORY.md` → Agent Team section |
| Shared cross-agent facts | `MEMORY.md` and its sub-files in `~/.claude/.../memory/` |
| A2AL vocabulary | `offices/library/*.yaml` |
| A2AL spec (upstream) | https://github.com/mcornelison/A2AL |
| Your office | `offices/<your-role>/` |
| Your charter | `offices/<your-role>/claude.md` |
| Your inbox | `offices/<your-role>/inbox/` |
| A peer's inbox (write here) | `offices/<peer-role>/inbox/` |
| A peer's anything else | **off-limits** |

---

## 14. When in doubt

Ask the CIO. Direct conversation overrides any rule in this handbook.

Welcome to the team.
