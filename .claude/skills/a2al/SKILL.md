---
name: a2al
description: Use when an AI agent needs to send a short message to a peer agent, write a status update, ack a peer, compress a verbose report into shorthand, or read an A2AL message from another agent. A2AL is plain-text shorthand designed to tokenize as 1 token per concept on modern LLM tokenizers. Triggers on phrases like "send a quick update to agent2", "ack that", "compress this for agent X", "what does this A2AL message say", "tell agent2 X". NOT for messages to humans — write Markdown for that.
---

# A2AL Skill

A2AL/0.4.1 is a plain-text shorthand for agent-to-agent communication, paired with an open vocabulary library. This skill teaches the audience rule (normative), the mandatory routing header (normative), the body style guide, and how to load the right vocabulary for your domain.

Reference: https://github.com/mcornelison/A2AL — `specs/A2A-Core.md`, `library/`, `examples/`.

Vocabulary library on this project: `offices/library/*.yaml`.

## When to use (audience rule, §2.1+§2.2 normative)

The audience determines the format. No hybrid mode; no duplication.

| Situation | Format |
|---|---|
| Agent → agent, no human review expected | **A2AL MUST** |
| Inbound said `audience=agent` or sender ID'd as an AI agent | **A2AL MUST** (reactive rule) |
| Human will read or review the message at any point | Markdown |
| Audience ambiguous or mixed | Markdown (default) |
| RCAs, ADRs, design specs, long-form deliberation | Markdown (humans return to these) |

**Channel signals**: agent-only paths (e.g., `*/inbox-internal/`, `.a2a/`) may be declared agent-only by convention; messages in those paths default to A2AL. Otherwise the channel is mixed → Markdown.

## When NOT to use

- The recipient is a human → Markdown
- A human will triage / archive / audit the message at any point → Markdown
- You need a structured envelope (timestamps, signing, routing fabric) → out of scope, that's transport

## Routing header (mandatory, §3 normative)

**Every A2AL message MUST begin with a single-line routing header.** Line 1 is the header; the body follows on subsequent lines.

### Required fields

```
from=<Name>(<Role>); to=<Name>(<Role>); date=<ISO>; topic=<short label>
```

| Field | Format |
|---|---|
| `from` | `<Name>(<Role>)` or `<Name>/<Role>` — e.g. `Iris(UI/UX)`, `Atlas(Architect)`. Role is free-form. |
| `to` | Same shape. Multiple recipients comma-separated: `to=Atlas(Architect), Marcus(PM)` |
| `date` | ISO 8601 date (`2026-05-22`) or datetime (`2026-05-22T15:30Z`) |
| `topic` | Free-form short label. No internal `;`. |

Fields separated by `; ` (semicolon + space). Header is one line; ends at first newline.

### Optional fields

| Field | Purpose |
|---|---|
| `audience=agent\|mixed` | Declares agent-only intent. When `agent`, replies MUST be A2AL (reactive rule). |
| `urgency=low\|medium\|high\|urgent` | Receiver-side prioritization |
| `refs=<id>, <id>, ...` | Citations to commits, story IDs, file paths, prior messages |
| `in-reply-to=<message-id>` | Thread continuity |

### Example header

```
from=Iris(UI/UX); to=Atlas(Architect); date=2026-05-22; topic=splash design review; audience=agent; urgency=medium
```

## Loading the vocabulary library

Always load `library/core.yaml` (~77 universal terms). Optionally load domain extensions for the conversation theme:

| Conversation theme | Load |
|---|---|
| General agent coordination | `library/core.yaml` only |
| Code review / dev process | + `library/programming.yaml` |
| Cloud / infrastructure / data pipelines | + `library/infrastructure.yaml` |
| Sprint, project, or program management | + `library/project-mgmt.yaml` |
| Security review / threat modeling | + `library/security.yaml` |
| LLM / agent / RAG topics | + `library/ai-agents.yaml` |

On this project the library lives at `offices/library/*.yaml`. No special parser needed — just read the YAML.

## Body style rules (§4)

### Drop
- Articles (`the`, `a`, `an`)
- Helping/linking verbs (`is`, `are`, `was`) when state is unambiguous
- Subjective framing (`I think`, `it seems`)
- Politeness (`please`, `could you`) — inter-agent, politeness is wasted tokens
- Filler (`in order to` → `to`)
- Repeated subjects across fragments — use `;`

### Use
- Sentence fragments
- Imperative mood for actions
- Past tense / status adjectives for state (`done`, `blocked`, `shipped`, `passed`, `failed`)
- Standard tech jargon from the library
- IDs as bare tokens: `US-713`, `commit-98b483d`, `T-202`

### Punctuation
- `;` between related facts (same topic)
- `.` (or newline) between unrelated facts
- `:` after subject to expand
- `/` for ratios
- `?` for questions
- `--` for inline rationale

### Avoid
- Creative abbreviations (`cmplt`, `prgm`) — usually 2-3 tokens
- Rare Unicode (✓ ⟳ ✗) — usually multi-token in Claude's vocab
- Single-letter codes (`c`, `b`, `r`) — ambiguous
- Omitting the routing header — non-conformant, §3 is MUST

## Patterns (§7)

| Pattern | Body form | Body example |
|---|---|---|
| State change | `<id> <state>` | `US-713 done` |
| Multi-fact state | `<id> <state>; <fact>; <fact>` | `US-713 done; AC met; CI green` |
| Status report | `<metric> <value>; ...` | `tests 21/21; preflight 878/878; build green` |
| Action | `<verb> <target>` or `<actor>: <verb> <target>` | `merge ralph/auth-fix` |
| Blocker | `<id> blocked: <reason>` | `US-718 blocked: no household source in Silver` |
| Question | `<verb>?` or `<id> <verb>?` | `merge?`, `US-713 sign-off?` |
| Decision | `<decision>: <id> -- <rationale>` | `approved: US-713 PRD -- 1 AC added` |
| Ack | `ack <id>` | `ack US-713 closeout` |

## Mode 1 — Read

When given a shorthand message:
1. Parse the routing header (line 1) — sender, recipients, date, topic, audience
2. Parse `term=expansion` definitions on first occurrence; remember them within the thread
3. Expand the message internally using your loaded library
4. Summarize key facts in 1-2 plain-English sentences for the user

## Mode 2 — Write

When the user asks to compose a message:
1. Confirm the audience is agent-only (else write Markdown — audience rule)
2. Compose the routing header (§3) — required fields + any helpful optional fields
3. Identify the body's structural shape (state change / status / action / blocker / question / decision / ack)
4. Pick the matching pattern from the table above
5. Use canonical glossary terms from the loaded library where possible
6. Apply style rules — drop fillers, use fragments, semicolons between related facts
7. Output as plain text (no JSON wrapper, no envelope)

## Mode 3 — Vocabulary extension (§6)

If the user wants to introduce a new shortening:
1. Verify the term will be used 3+ times in the thread (else just write it out in full)
2. On first use, write `<term>=<expansion>` (no spaces in the expansion, no `--`)
3. After first use, use the bare term

Example: `DR=design-review. DR sched Tuesday; PR ready post-DR.`

If broadly useful, suggest adding to the library: open a PR adding an entry to `library/<domain>.yaml` and run `python tools/validate_library.py` to verify before submitting.

## Worked example — write

User: "Tell Atlas the sprint hotfix is done — 713 needed no code change, 714 implemented warnOnly DQ flag, all tests pass, ready to merge."

You produce:

```
from=Iris(UI/UX); to=Atlas(Architect); date=2026-05-22; topic=sprint hotfix ready; audience=agent
US-713 done; no code change -- already in main from US-671.
US-714 done; warnOnly DQ flag; 21/21 DQ tests; preflight 878/878.
merge ralph/pipeline-hotfix-2026-04-17?
```

Write to the file/inbox the user specified, then summarize: "Wrote sprint hotfix update to Atlas. One header + three body lines, ~45 tokens vs ~110 in verbose English. Asks Atlas to merge."

## Worked example — read

User: "What does this say?" (provides):

```
from=Ralph(Dev); to=Iris(UI/UX); date=2026-05-22; topic=US-713 closeout; audience=agent
US-713 done; AC met; CI green; PR ready -- merge?
```

You reply: "Ralph (Dev) reports US-713 is complete with acceptance criteria met and CI green. His PR is ready and he's asking permission to merge. Since `audience=agent`, reply must be A2AL."

## Reference

- Spec: `specs/A2A-Core.md` (https://github.com/mcornelison/A2AL/blob/main/specs/A2A-Core.md)
- Library: `offices/library/*.yaml` (this project) or `library/*.yaml` (upstream)
- Examples: `examples/*.txt` (upstream)
- Validator (for library contributions): `python tools/validate_library.py`
- Team handbook: `offices/handbook.md` — covers the team's adoption + onboarding
