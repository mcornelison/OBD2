---
name: knowledge-update
description: "Update the Agent Handbook and canonical specs with lessons learned. Use after completing work sessions to capture new knowledge. Triggers on: update agent handbook, sync progress, capture learnings, update knowledge base, what did we learn."
---

# Knowledge Update Skill

Curate and maintain the project's knowledge base by routing lessons learned to the correct canonical files.

---

## The Job

1. Read `ralph/progress.txt` for new learnings
2. Classify each item by its canonical destination
3. Update the appropriate spec file(s)
4. Keep `ralph/agent.md` focused on operational tips only
5. Cross-link between files when helpful

**Goal:** Single source of truth across all documentation. No duplication.

---

## Canonical File Routing Table

Use this table to decide where information belongs:

| Content Type | Destination File |
|--------------|------------------|
| Agent tips, tricks, unblockers, operational lessons | `ralph/agent.md` |
| System design, boundaries, components, data flow | `specs/architecture.md` |
| New or refined terms, acronyms, domain language | `specs/glossary.md` |
| Process, workflows, SDLC, ticket flow, reviews | `specs/methodology.md` |
| Bad practices, failure modes, what NOT to do | `specs/anti-patterns.md` |
| Coding conventions, naming rules, formatting | `specs/standards.md` |

**Rule:** If an item fits one of these categories, update the correct file directly.

---

## What Goes in agent.md

### INCLUDE in agent.md:
- Non-obvious implementation tips and local dev quirks
- Practical troubleshooting steps and unblockers
- Build/run/test/debug/deploy lessons learned
- Tooling, scripts, CI/CD, and environment gotchas
- External system quirks (timeouts, sandboxes, rate limits)
- Performance tricks and operational insights
- Release/rollback caveats and incident learnings
- Cross-repo conventions unique to this project

### EXCLUDE from agent.md (route elsewhere):
- Architecture explanations → `architecture.md`
- Definitions or glossary-style entries → `glossary.md`
- Methodology or process descriptions → `methodology.md`
- Coding anti-patterns or bad practices → `anti-patterns.md`
- Coding standards or naming conventions → `standards.md`

---

## Process

### Step 1: Load and Scan

Read all relevant files:
- `ralph/agent.md` (required)
- `ralph/progress.txt` (required - source of new knowledge)
- `specs/architecture.md` (if architecture insights found)
- `specs/glossary.md` (if new terms found)
- `specs/methodology.md` (if process insights found)
- `specs/anti-patterns.md` (if failure modes found)
- `specs/standards.md` (if coding standards found)

Treat `ralph/progress.txt` as authoritative for new knowledge.

### Step 2: Classify Each New Item

For every meaningful entry in `progress.txt`:
1. Determine its canonical destination using the routing table
2. Reject duplicates of existing, accurate knowledge
3. Flag items that need verification with `(Verify)`

### Step 3: Update the Correct File(s)

- Merge changes into the appropriate markdown file
- Preserve existing structure and tone
- Deprecate outdated guidance with clear notes and dates
- Add to existing sections rather than creating new ones when possible

### Step 4: Cross-Link When Helpful

- Ensure `agent.md` references (links to) any newly updated specs
- Add tips or caveats related to the new info
- **Never duplicate content** - link instead

### Step 5: Normalize and Clean

- Use active voice and concise, actionable phrasing
- Prefer bullets and code blocks
- Avoid speculative or unverified guidance
- Remove redundant or outdated information

### Step 6: Safety and Hygiene

- **Never include:** secrets, credentials, tokens, or private data
- Redact sensitive values as `REDACTED` if found
- Scrub stack traces while preserving diagnostic signatures
- Remove any PII or environment-specific paths

### Step 7: Stamp and Changelog

- Update "Last Updated" dates in every modified file
- Add concise changelog entries describing what changed

---

## Output Format

For each modified file, output the full updated contents with a clear header:

```markdown
## Updated: ralph/agent.md

[Full file contents here]

---

## Updated: specs/architecture.md

[Full file contents here if modified]
```

---

## Conflict Resolution

- Prefer the newest, most concrete info from `progress.txt`
- If ambiguity exists, annotate with `(Verify)` and log it
- Never silently delete existing guidance without explanation
- When in doubt, ask for clarification

---

## Example: Classifying Progress Entries

**Progress entry:**
> "Discovered that the 3E API returns dates in UTC but without timezone indicator. Must parse as UTC explicitly."

**Classification:** This is an external system quirk → goes in `ralph/agent.md`

---

**Progress entry:**
> "The Bronze layer stores raw JSON payloads without transformation. Silver layer applies cleaning rules."

**Classification:** This is architecture/data flow → goes in `specs/architecture.md`

---

**Progress entry:**
> "SCD Type 2 means we track historical changes by creating new rows with effective dates."

**Classification:** This is a glossary term → goes in `specs/glossary.md`

---

**Progress entry:**
> "Don't use SELECT * in production queries - always specify columns explicitly."

**Classification:** This is an anti-pattern → goes in `specs/anti-patterns.md`

---

## Readiness Checklist

Before completing the update:

- [ ] All progress items routed to correct canonical file
- [ ] No architecture/glossary/methodology/anti-pattern content left in agent.md
- [ ] Cross-linked specs updated when required
- [ ] No secrets or sensitive data exposed
- [ ] Changelog and timestamps refreshed in all modified files
- [ ] Content remains skimmable and action-oriented
- [ ] No duplicate content across files

---

## When to Use This Skill

Run this skill:
- After completing a significant work session
- When `ralph/progress.txt` has accumulated new learnings
- Before starting a new major feature (to capture previous learnings)
- During code review when new patterns are discovered
- After debugging sessions that revealed non-obvious issues

Regular knowledge updates help future AI agents (and humans) avoid repeating mistakes and leverage proven solutions.
