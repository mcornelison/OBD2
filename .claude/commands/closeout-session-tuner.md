---
name: closeout-session-tuner
description: "Close out a Spool session — land the record, sweep every correction, verify integrity, and leave the office bootable"
---

# /closeout-session-tuner — Spool session closeout

Operator-triggered at the end of a working session. **Created 2026-09-01 (S42)** after being carried as
an open item for several sessions and done by hand every time.

> **The point of a closeout is not to summarise. It is to make sure nothing this session learned dies
> in the transcript, and nothing it corrected survives anywhere else.** A session that found a wrong
> number and fixed it in one file has not finished — it has moved the drift.

---

## Phase 0 — Nothing is lost before you start

**Do these first, because everything after assumes them.**

1. **If a bench was leased**, report its state honestly:
   `git status -sb` and `git status --porcelain` in the bench.
   🔴 **Uncommitted work at closeout is the failure this phase exists to catch.** Commit and push, or
   state plainly that it is being abandoned and why. **Durability = pushed, not committed.**
2. **If a ticket was worked**, confirm it is in `board/review/` with commits listed and the surface
   named. **Never merge to `dev` or `main` — that is the PM's alone.**
3. **If any bulk edit ran**, confirm the backups still exist and are non-zero.

---

## Phase 1 — The session log entry

Write into `knowledge/sessions.md`, newest-first, **above** the previous session.

**Required shape** (match the existing entries; they are the template):

- `## Session N — <dates> (<a title that says what actually happened>)`
- A **closeout summary blockquote** — the two or three things a reader must not miss, including bad news.
- **Block sections** — one per distinct piece of work, in the order it happened.
- `### Open Items` · `### Session Outcome`
- **A row in the session index table at the top of the file.**

**Content rules, and they are the culture of this office:**

- 🔴 **Record what went wrong with the same weight as what went right.** The S41 entry is titled *"THE
  SESSION I BROKE THINGS."* That is the standard. A closeout that reads as an accomplishment list is
  not a record, it is marketing.
- **Every self-correction gets written down**, including ones nobody else noticed. Include the
  *mechanism* — what made the wrong thing look right — not just the correction.
- **Distinguish measured from inferred from recalled**, every time.
- **Name what was NOT established.** An honest open question outranks a tidy conclusion.

---

## Phase 2 — Sweep every correction (the phase that is actually load-bearing)

**For each fact corrected or withdrawn this session, find every other copy of it.**

```bash
grep -rn "<the old number or claim>" --include="*.md" \
  offices/tuner/ offices/_shared/knowledge/memory/ specs/ 2>/dev/null
```

Check, in this order:

1. `cards/` — the this-car meaning SSOT
2. `knowledge/knowledge.md` + its sub-files
3. `CLAUDE.md` — the charter (⚠️ it carries an odometer, a folder map, and a truth-map; all three go stale)
4. **The shared `MEMORY.md`** — other agents boot on it
5. **`specs/grounded-knowledge.md` in the REPO** — needs a `TUNER-xxx` ticket and a bench; **note it as
   owed if it cannot be done now, and say so explicitly**
6. Advisories at office root — each is an SSOT for its consumer

⚠️ **Also sweep the files that describe WHERE FACTS LIVE.** A stale truth-map or folder map regenerates
the drift after you have cleaned it up. (S39 lesson.)

⚠️ **Historical records — `inbox/`, session archives, `.backup-*/` — keep their original wording.** They
are a record of what was said at the time. Do not rewrite history; correct the live files.

---

## Phase 3 — Shared memory

Update `$FLEET_SHARE/_shared/knowledge/MEMORY.md` for **cross-agent** facts only.

- **One-liner plus a pointer.** The file says of itself *"one-liners; detail in linked sub-files"* — if
  an entry runs past a few lines, the detail belongs in a card and the entry belongs as a link to it.
- **Per-agent knowledge does NOT go here** (CIO memory-boundary, 2026-05-20). It goes in
  `offices/tuner/knowledge/`.
- **Supersede, do not append.** If this session overturned an entry, rewrite that entry — do not leave
  two entries disagreeing and trust the reader to notice the dates.

---

## Phase 4 — Integrity verification

Run these. **Do not assert the office is clean; show it.**

```bash
find offices/tuner offices/_shared/knowledge -name "*.tmp"            # leftover temp files
find offices/tuner offices/_shared/knowledge -name "*.md" -size -1c   # zero-byte files
```

🔴 **The zero-byte check is not theoretical.** A script opened a file `"w"` and raised before writing;
22,588 bytes became 0 on a share with no git and no reachable snapshots (S41). Recovery was possible
only because the content also lived in `obd2db`.

**Rotation thresholds** — check and act, or state that you checked:

| File | Act when |
|---|---|
| `knowledge/sessions.md` | **> ~150 KB** → `scripts/rotate_sessions.py --keep 3` |
| `knowledge/knowledge.md` | **> ~120 KB** → `scripts/split_knowledge.py` |
| shared `MEMORY.md` | bullets running > ~400 chars → `scripts/compact_memory.py` |

All three write **temp file → size gate → `os.replace()`**, and **refuse to run on byte loss**. Use them
rather than hand-editing; that is what they are for.

---

## Phase 5 — Report to the operator

State plainly:

1. **What shipped**, and what is merely *owed*.
2. 🔴 **Anything that needs the CIO** — a part to buy, a receipt to find, a decision only he can make.
   **Lead with safety if there is any.**
3. **Every open item**, split into: *blocked on me* · *blocked on the CIO* · *hardware-gated, cannot be
   closed by work at all*.
4. **Corrections made this session**, including your own, and who caught each one.
5. **Verification evidence** — the command output, not the claim.

---

## Standing rules this closeout must not violate

- 🔴 **This share has NO git and NO undo.** Never write in place. Never inline a rewrite script in a
  heredoc — write it to a file. Gate on size, then promote.
- 🔴 **Verify the claim, not the artefact.** A green field, a status marker, a tool's "success" message
  is a *claim*. Ask **"what would falsify this?"** before writing it down as done.
- 🔴 **Before concluding anything from a capture, establish that the capture is FINISHED** — compare
  `MAX(synced_at)` against the server clock. A drive graded mid-sync produced a published wrong
  conclusion once already.
- **A card never mints a threshold.** Numbers live in `specs/grounded-knowledge.md`; cards explain what
  they mean on this car.
- **Lane discipline** — write only `offices/tuner/**`, the shared `MEMORY.md`, `board/`, and other
  agents' `inbox/`. Never another agent's office.

$ARGUMENTS
