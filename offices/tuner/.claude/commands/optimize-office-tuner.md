# /optimize-office-tuner — Spool workspace re-trim

On-demand command. Re-trims Spool's office when context bloat surfaces. **Operator-triggered, NOT auto-run at session close.**

## Structural notes (adapted from template)

Spool deviates from the assumed 3-file boot pattern:
- **Boot file**: `offices/tuner/CLAUDE.md` (identity, role, principles, communication model, workflow). Loaded by the `/init-tuner` **skill** (not a command file), so there is no `init-tuner.md` command to refactor here. The skill itself is `.claude/skills/init-tuner` — shared, out of scope.
- **No discrete dashboard.** The "recent sessions + priorities + Knowledge Index" pattern is split across `sessions.md` (running log w/ Open Items in latest entry) + `knowledge.md` (the tuning bible) + `knowledge/` folder (persona/feedback/followups migrated 2026-05-18 per CIO memory-boundary directive).
- **Existing archive pattern**: `sessions-archive-2026-04.md` already holds Sessions 1–7. Sliding window applies; honor the precedent.

## Scope fence (verbatim — do not widen)

- **ALLOWED**: `offices/tuner/**` (entire Spool office, including `inbox/`, `knowledge/`, `drills/`, `scripts/`, `sessions-archive-*.md`).
- **FORBIDDEN**: every other agent's office (`offices/pm/**`, `offices/ralph/**`, `offices/tester/**`, `offices/architect/**`), the shared `~/.claude/projects/.../memory/MEMORY.md`, the project root `CLAUDE.md`, `.claude/skills/` (incl. `init-tuner`, `a2al`), `.claude/commands/<other-role>*.md`, `specs/`, `docs/`, `src/`, deploy scripts, `obd2db` server data. If a refactor needs to touch any of those, STOP and surface to operator.

## Phase 0 — Ask the operator: dry run or live?

Before any writes, ask verbatim:

> Run a **dry-run first** (survey + duplication report only, no writes) or go **live** (refactor + archive + write)?

- **Dry-run**: execute Phases 1–2 and Phase 5 read-only; produce the Phase 6 report with proposed changes; STOP. Operator decides whether to re-invoke live.
- **Live**: execute all phases.

## Phase 1 — Survey

`wc -l` every Spool-owned file in scope. Capture current line counts. Compare against the last-optimize baseline at `offices/tuner/.optimize-baseline.json` (create-on-first-run; see Phase 6). Flag any file exceeding its target OR growing >50% from baseline.

Targets (Spool-specific; revise via Phase 6 when reality shifts):

| File | Target | Purpose |
|---|---|---|
| `CLAUDE.md` | ~150 lines | Identity + role + principles + communication model + workflow. Larger than the template's ~45 because it's the only boot file. |
| `sessions.md` | ~700 lines inline (after sliding-window archive) | Running session log. Older sessions append to `sessions-archive-YYYY-MM.md`. |
| `knowledge.md` | ~1600 lines | The tuning bible. Larger by design — this is the lazy-loaded body, not a boot file. Target only enforced if growth is structural (drift / duplication), not content. |
| `drive-annotations.md` | ~300 lines | Per-drive metadata sidecar. Grows linearly with drives; archive entries for drives that have been retired from the pre-mod shelf. |
| `drain-test-procedure.md` | ~280 lines | Procedural anchor. Should be ~stable; flag growth >20%. |
| `drive-review-checklist.md` | ~80 lines | Stable checklist. Flag growth >20%. |
| `knowledge/<name>.md` (each) | varies | Individual persona/feedback/followup files. Flag any single file growing past ~150 lines (split if so). |
| `inbox/` count | ~30 unread + ~60 archived | If unread > 30, surface to operator (triage triggers, not optimize). |

Also list `inbox/` files older than 4 weeks for possible archive (operator decides; not auto).

## Phase 2 — Identify duplication

Walk this table; report any hit:

| Class | Canonical home (only home) | Common drift |
|---|---|---|
| Identity / role / principles | `CLAUDE.md` | Re-stated in `knowledge.md` headers |
| Communication model + inbox templates | `CLAUDE.md` | Re-stated in session entries |
| Boot/init phases | `init-tuner` skill (out of scope to edit) | Mirrored in `CLAUDE.md` (drop if duplicated) |
| Tuning thresholds + ranges + DSM facts | `knowledge.md` (the bible) | Snapshotted in old session entries (sessions snapshot context; keep but flag if a session restates >5 thresholds — likely should reference instead) |
| Drive metadata | `drive-annotations.md` + `obd2db.drive_annotations` | Sometimes in session entries (link, don't duplicate) |
| Drain procedure | `drain-test-procedure.md` | Don't restate steps in sessions; link |
| Spool persona / feedback rules | `knowledge/role-boundaries.md` etc. | Older sessions may inline these — leave (historical), but don't add new inline copies |
| Vehicle followups + long-term vision | `knowledge/fuel-pump-replacement-followup.md`, `knowledge/summer-2026-upgrade.md`, `knowledge/mrspool-vision.md` | Linked from MEMORY.md index pointers — do not re-home into shared memory |
| Pi power state + Finding B | `docs/pi-power-state.md` (cross-agent; out of scope to edit) | If a session restates the wake-edge mechanism, link to `docs/pi-power-state.md` instead |

Report findings as a duplication table (offender file + class + suggested fix).

## Phase 3 — Refactor in order (LIVE only)

`CLAUDE.md` → `knowledge/` folder index → `sessions.md`. Order matters because session entries reference both, so sessions get re-tightened last.

- **CLAUDE.md**: enforce single-source for identity / role / principles / communication-model templates. Drop anything that's pure restatement of the `init-tuner` skill content or the bible.
- **`knowledge/` folder**: confirm each file matches its frontmatter description; split any file >150 lines into sibling files; ensure cross-links between files use relative paths.
- **`sessions.md`**: trim **stale narrative**, never trim session-specific findings (engine grades, drain data, advisories filed, decisions, diagnostic-record entries). Stale = sentences that restate canonical knowledge already in `knowledge.md` or `docs/pi-power-state.md`. Replace with a one-line link.

## Phase 4 — Auto-archive (LIVE only)

Date-anchored sliding window, **NOT count-anchored**. Spool is multi-day-per-session (sessions 8/10/14/15/16 each span 2–6 calendar days).

- **Window**: keep ~3 weeks of session detail inline. Older sessions APPEND to `sessions-archive-YYYY-MM.md` (current archive: `sessions-archive-2026-04.md` holds Sessions 1–7). Create `sessions-archive-YYYY-MM.md` for any new month boundary crossed.
- **Append-only**. Older sessions are forensics — engine-grade history, drain calibration history, diagnostic-record honesty. Never truncate.
- **Inbox archive**: optional. Surface any `inbox/*.md` older than 4 weeks; ask operator whether to move to `inbox/archive/` (do not auto-move).

## Phase 5 — Verify canonical state + Knowledge Index

Walk every file that Spool's `CLAUDE.md` and `knowledge.md` reference. For each:
- Confirm path exists.
- Confirm referenced specs / DB tables / cross-files still authoritative (a renamed table or moved file breaks downstream).
- Spot-check that `obd2db.drive_annotations` still has rows for every drive the pre-mod shelf claims (one quick mysql query — see `~/.claude/projects/Z--o-OBD2v2/memory/reference_chi_srv_01_obd2db_access.md` for access pattern).
- Verify the `knowledge/` folder contents match what `MEMORY.md` says was migrated (12 files at last count: role-boundaries, spec-discipline, spec-discipline-protocol-timing, spec-invariant-validated-against-real-signal, pi-power-mode-check, us339-test-signal, pending-research, i016-thermostat-closed-benign, mrspool-vision, agent, fuel-pump-replacement-followup, summer-2026-upgrade).
- Drop stale rows from any in-file Knowledge Index; add new sub-files created since last optimize.

## Phase 6 — Report + persist baseline

Produce:
- **Sizes before / after** (or before / proposed for dry-run) for every file surveyed.
- **Duplications removed** (offender + class + action taken).
- **Archived**: filenames + line counts moved to `sessions-archive-*.md`, `inbox/archive/`.
- **Knowledge Index verification**: count verified-active vs dropped-stale vs newly-added.
- **Safety advisories or tuning data touched**: should be **zero** (Spool optimize is structural only; engine knowledge is sacred — never trim a threshold or DSM fact during an optimize).

On LIVE run, persist the new baseline to `offices/tuner/.optimize-baseline.json`:

```json
{
  "last_run": "YYYY-MM-DD",
  "files": {
    "CLAUDE.md": <lines>,
    "sessions.md": <lines>,
    "knowledge.md": <lines>,
    "drive-annotations.md": <lines>,
    "drain-test-procedure.md": <lines>,
    "drive-review-checklist.md": <lines>
  },
  "knowledge_folder_count": <int>,
  "inbox_unread_count": <int>,
  "inbox_archived_count": <int>
}
```

If a new duplication class surfaces (not in Phase 2's table), add it to this command file under a new section so the next optimize catches it.

## Rules (verbatim)

- **Read before write.** Read each current file before refactoring. Don't generate from memory; preserve session-specific content the operator inserted between optimizes.
- **Preserve session-specific content.** Engine grades, drain data, diagnostic-record honesty, advisories filed, decisions, fuel-grade corrections — all stay. Only structural duplication + stale narrative get trimmed.
- **Append, never truncate the archive.** `sessions-archive-*.md` is append-only.
- **Tuning values are sacred.** Never edit a threshold, DSM fact, ECMLink parameter, or `[EXACT: value — DO NOT CHANGE]` marker during an optimize. If a threshold appears duplicated, link to the canonical home in `knowledge.md` — do not delete the duplicate without operator approval.
- **Scope fence enforcement.** Touch only `offices/tuner/**`. STOP and surface if anything would require editing another office, `MEMORY.md`, `specs/`, `docs/`, or `src/`.
- **On-demand only.** Operator triggers when bloat surfaces. NOT auto-run at session close. `/closeout-session-tuner` is unchanged.
- **Run order matters.** CLAUDE.md → `knowledge/` → `sessions.md`. Out-of-order re-introduces drift.
- **Idempotent.** Safe to run multiple times; no-op when already at target sizes.
- **A2AL is for peer-agent messages only.** This command produces Markdown reports for the operator (human).

## When to invoke

Trigger if ANY of:
- Combined `CLAUDE.md` + `sessions.md` exceeds ~900 lines (boot context approaching expensive ground-time).
- Any single tracked file > 50% growth from last-optimize baseline.
- `sessions.md` inline window exceeds 3 weeks.
- `inbox/` unread count > 30 (separate from optimize — surface as triage trigger).
- After 2+ multi-day session clusters merge without a closeout-archive pass.
- Operator says "feels bloated" or "slow to ground at /init-tuner."
