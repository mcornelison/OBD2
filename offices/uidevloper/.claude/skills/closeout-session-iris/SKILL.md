---
name: closeout-session-iris
description: End-of-session ritual for Iris (UI/UX Designer). Sweeps inbox, updates charter §8 watch list + §9 session log, captures new feedback/patterns/references to knowledge/, files pending A2ALs to peers, commits only offices/uidevloper/**. Use at the end of every Iris session. Triggers on phrases like "close out the session", "wrap up", "end session", "session closeout", "/closeout-session-iris", "ready to stop".
---

# Iris — Session Closeout

End-of-session ritual for the UI/UX Designer office. Structured, sequential — execute phases in order. Track them with whatever todo mechanism the session has; if none is available, just work the phases in order. Be honest — if a phase finds nothing, say so. Do not fabricate work.

---

## Phase 1: Inbox sweep

Read every file in `offices/uidevloper/inbox/` that you haven't already processed this session.

For each:
- **Ack/reply to one of my pending A2ALs** → note disposition for the session log (Phase 2b)
- **New request or question** → queue for response (this session or call out as pending in Phase 6)
- **FYI / informational** → note in §9 log if material
- **Resolved** → if `offices/uidevloper/inbox/archive/YYYY-MM/` exists, move the file there; else leave in place (CIO has not yet directed the archive pattern)

If the inbox is empty or unchanged since last session, say so and move on.

---

## Phase 2: Charter updates

### 2a. Watch list (§8)

Re-read §8 of `offices/uidevloper/claude.md`. For this session:
- **Add** any new design items discovered (W-N+1, W-N+2, …)
- **Update status** on existing items if they progressed (Open → Tracked-by-<peer> → In-progress → Resolved-YYYY-MM-DD)
- Never delete a row — status carries the history. If an item becomes irrelevant, mark `Withdrawn-<date>` with a one-line reason.

If no watch-list changes, skip.

### 2b. Session log (§9)

Append a dated entry to §9. Capture:
- **Key decisions** made or ratified this session (CIO directives, lane-boundary calls)
- **Proposals filed** (peer + slug + date)
- **Peer hand-offs** — incoming (notes received + acted on) + outgoing (A2ALs filed)
- **Open questions** for the CIO
- **Anything future-me will need** to pick up where past-me left off

Use H3 (`### YYYY-MM-DD — <short title>`) for new entries. Don't pad. A short session is a short entry. A session with no real work needs no entry beyond a one-liner ("housekeeping only — no design output").

---

## Phase 3: Knowledge capture

Scan the session for material that belongs in `offices/uidevloper/knowledge/`. Per the memory boundary rule (handbook §11), personal lessons live HERE, not in shared `MEMORY.md`.

| Source signal | File pattern |
|---|---|
| CIO corrected or confirmed an approach | `knowledge/feedback-<slug>.md` |
| A design or process pattern worked | `knowledge/pattern-<slug>.md` |
| CIO pointed at an external reference / asset / dimension | `knowledge/reference-<slug>.md` |

**Before writing, ask: is this MINE or the PROJECT's?** Facts any agent might need — hardware
specs, printer/toolchain behaviour, vendor dimensions — are **project-shared** and belong in a
shared location with one version of the truth (`docs/`, `specs/`), not in my office. Knowledge
here is *how I work*: the CIO's preferences toward me, my design-process lessons, my traps.
Consolidated 2026-08-20 on CIO direction — see `docs/3d-printing/README.md` for the pattern.

For each candidate:
1. Check existing knowledge files first — no duplicates. Update an existing file if the lesson is a refinement.
2. Write the file with frontmatter (`name:`, `description:` one-line summary).
3. Lead with the rule/fact. For feedback: include **Why:** (the reason the CIO gave) and **How to apply:** (when/where it kicks in).
4. Cross-link related entries with `[[other-slug]]`.

If no new knowledge surfaced, say so. Padding the knowledge folder dilutes it — be ruthless.

---

## Phase 4: Pending A2ALs

Review the session for A2ALs that should have been filed but weren't:

| Trigger | File to |
|---|---|
| Spec or asset bundle ready for implementation | `../ralph/inbox/` |
| UI proposal touches load-bearing surface | `../architect/inbox/` (design-gate review BEFORE forwarding) |
| Value-semantic question on tuning UI | `../tuner/inbox/` |
| UI feature ready for acceptance criteria review | `../tester/inbox/` |
| Proposal ready for sprint orchestration | `../pm/inbox/` |

File using A2AL/0.4.1 (mandatory routing header, audience rule). One file per peer. Filename: `YYYY-MM-DD-from-iris-<slug>.md`.

If nothing pending, say so.

---

## Phase 5: Commit my own work, then hand off to the PM

**CIO 2026-08-20 — supersedes the 2026-08-17 "PM handles ALL git" phase.**

**I MAY:** `git add`, `git commit`, and read-only git (`status`, `log`, `diff`, `show`).
**I MUST NEVER:** `push`, `pull`, `fetch`, `merge`, `rebase`, `branch`, `checkout`, `git mv`.
Those stay Marcus's, and so do dev/main and every deploy.

### 5a. Commit

Scope is strict — **`offices/uidevloper/**` plus peer `inbox/` notes I wrote myself.**
Never a peer's own files, never `.deploy-version`, never a peer's `settings.local.json`
(the CIO auto-normalises those; sweeping them into my commit misattributes his work).

Check what's actually in scope first, and read the list before staging:

```bash
git status -s -- offices/uidevloper/ offices/pm/inbox/ offices/architect/inbox/ \
                 offices/tuner/inbox/ offices/tester/inbox/ offices/ralph/inbox/
```

Stage **by explicit path**, never `git add -A` / `git add .` — a broad add is how a peer's
in-flight work gets swept into my commit under my message (it happened to my A2ALs in
`dd2e123`, in the other direction).

Archive sweeps surface as delete+add pairs. Say so in the commit message so the diff
doesn't read as data loss.

### 5b. Hand off — still mandatory

**Committing is NOT delivery.** Only Marcus pushes, and **origin is the source of truth**,
so my commits are invisible to the team and unsafe against a re-provisioned clone until he
does. File the note in `../pm/inbox/`:

```
YYYY-MM-DD-from-iris-git-handoff-<slug>.md
```

List the **commit SHAs** and what each carries, plus anything needing his merge or deploy.

- If work is **urgent** (a correction to something already groomed, a spec a story points
  at), mark it `urgency=high` and name the story it affects.
- **Report honestly in Phase 6:** "committed locally, pending Marcus's push" — never
  "pushed", and never "delivered". Do not verify delivery by checking a local branch;
  that reads my own machine, not origin.
- Stale-work risk is unchanged in kind, only reduced: see
  `knowledge/pattern-the-artifact-is-not-the-fact.md` — that near-miss would
  have shipped a dead boost gauge. A committed-but-unpushed file still rots.

Hard NOs:
- `push` / `pull` / `fetch` / `merge` / `rebase` / `branch` / `checkout` / `git mv` — ever
- `git add -A` / `git add .` — stage by explicit path only
- Staging a peer's own file, `.deploy-version`, or a peer's `settings.local.json`
- Editing peer office files (inbox-only, unchanged)
- Assuming a file is delivered because it is committed — origin is the source of truth

## Phase 6: Session summary

Present this report to the CIO. Be specific — counts and pointers, not vague claims.

```
## Iris — Session Closeout Complete (YYYY-MM-DD)

**Inbox**: [N total / N processed this session / N archived / N still pending]
**Charter §8 watch list**: [N items added / N items updated / no changes]
**Charter §9 session log**: appended ("<short title>")
**Knowledge captured**: [N feedback / N pattern / N reference / none new]
**A2ALs filed**: [peer/slug, peer/slug, … / none pending]
**Committed**: [SHAs + one line each / nothing to commit]
**Handed to PM**: [`pm/inbox/<handoff-note>` — SHAs listed, branch named]
**Pending Marcus's push** — say this plainly; committed is NOT delivered

**Open for next session**:
- [item]
- [item]
- [or "nothing pending"]
```

---

## Edge cases

### Empty session (no real work done)
Phases 1-5 still run; most will return "no change." Phase 6 summary is honest about it. Do NOT fabricate accomplishments to justify the closeout.

### Nothing changed this session
Phase 5 still commits + files the hand-off note if ANY path changed. If `git status -- offices/uidevloper/` shows nothing at all, say "no changes — nothing to commit or hand off" and skip both. Never push either way.

### Urgent inbox item I cannot resolve
If Phase 1 finds an urgent item I cannot address now (e.g., needs CIO input), surface it explicitly in Phase 6 under "Open for next session" so the CIO knows it's pending.

### No `inbox/archive/` folder yet
Skip the archive step in Phase 1. Mention in Phase 6 if the CIO might want to establish the pattern.

### Charter file is locked/changed by linter mid-session
Re-read before editing (Phase 2). The harness will warn if state has drifted; just re-read and apply the edit fresh.

### Pending A2AL routing through Atlas blocked on review
If Phase 4 has a proposal that should go to Ralph BUT requires Atlas's design-gate review first per PM Rule 10, file it to Atlas's inbox instead and note in Phase 6 that the Ralph hand-off is gated.
