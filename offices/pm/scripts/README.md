# PM Scripts

Marcus's (PM) operational tooling. Stdlib-only Python; runs on Windows git-bash
or Linux. Invoked from repo root.

## pm_status.py

Session-start snapshot. Run this first in every PM session.

```bash
python offices/pm/scripts/pm_status.py              # full snapshot
python offices/pm/scripts/pm_status.py --sprint     # current sprint only
python offices/pm/scripts/pm_status.py --backlog    # backlog grouped by status
python offices/pm/scripts/pm_status.py --counter    # story counter state
```

Shows:
- Current `offices/ralph/sprint.json` — name, size mix, status counts, per-story
  (id / size / priority / status / deps / title)
- `offices/pm/backlog.json` — B- features grouped by status
- `offices/pm/story_counter.json` — nextId + last reservation notes

## backlog_set.py

CLI for common `backlog.json` mutations at sprint boundaries. Every operation is
idempotent (re-run-safe). Use `--dry-run` to preview.

### Bump `lastUpdated` + `updatedBy`

```bash
python offices/pm/scripts/backlog_set.py --updated-by "Marcus (PM, Session 24)"
```

### Flip feature status

```bash
python offices/pm/scripts/backlog_set.py --feature B-044 --status in_sprint \
    --field inSprint="Sprint 14 (US-201)"
```

Valid statuses: `pending | groomed | in_sprint | in_progress | blocked | complete | declined`

### Record feature completion

```bash
python offices/pm/scripts/backlog_set.py --feature B-042 --status complete \
    --completed-date 2026-04-18 \
    --completed-by "Ralph (US-187, Sprint 12 — obd → obdii rename)"
```

### Add a phase record (used for B-037 crawl/walk/run/harden)

```bash
python offices/pm/scripts/backlog_set.py --feature B-037 --add-phase harden \
    --phase-status in_progress \
    --phase-sprint "Sprint 14" \
    --phase-branch sprint/pi-harden \
    --phase-date 2026-04-19 \
    --phase-stories US-192,US-193,US-194,US-195,US-196,US-197,US-198,US-199,US-200,US-201 \
    --phase-note "Sprint 14 Pi Harden loaded — TD fixes + data-collection v2 + carryforward"
```

## bump_passed_statuses.py

Sprint-close Phase 1 hygiene. Bumps `status` field to `passed` for stories with `passes:true` but a non-passed terminal status (`pending`/`complete`/`completed` -- Ralph's standing hygiene gap, observed every sprint close since Sprint 14).

```bash
python offices/pm/scripts/bump_passed_statuses.py             # bump in-place
python offices/pm/scripts/bump_passed_statuses.py --dry-run   # preview
python offices/pm/scripts/bump_passed_statuses.py --path <override>
```

Idempotent. No-op when all `passes:true` stories already at `passed`.

## archive_sprint_artifacts.py

Sprint-close Phase 2. Snapshots `offices/ralph/sprint.json` + `progress.txt` to `offices/ralph/archive/` with UTC-timestamped filenames (`sprint.archive.YYYY-MM-DD_HHMMSSZ.json` + same for progress).

```bash
python offices/pm/scripts/archive_sprint_artifacts.py
python offices/pm/scripts/archive_sprint_artifacts.py --dry-run
```

Copy semantics (NOT move) -- sprint.json + progress.txt stay in place for the close commit. Exits 2 on timestamp collision (re-run within 1 sec; abort + investigate).

## verify_release_version.py

Sprint-close Phase 6 validator. Validates `deploy/RELEASE_VERSION` against the deploy-pipeline cap constraints. Prevents mid-deploy halts from oversize fields (TD-040 description-cap + TD-048 theme-cap; both have caused mid-deploy halts in prior sprint closes).

```bash
python offices/pm/scripts/verify_release_version.py     # default deploy/RELEASE_VERSION
python offices/pm/scripts/verify_release_version.py --path <override>
```

Caps:
- `version` matches `r'^V\d+\.\d+\.\d+$'`
- `theme` <= 50 chars
- `description` <= 400 chars

Exit 0 on all checks pass; 1 on cap violation (caller fixes file before deploy); 2 on file/parse error.

## repair_ralph_agents.py

Repair `offices/ralph/ralph_agents.json` corruption from Rex's bloated-note bug pattern (unescaped quote in long note breaks `json.load`). Observed Sprint 21 close, Sprint 24 close.

```bash
python offices/pm/scripts/repair_ralph_agents.py             # repair if corrupt
python offices/pm/scripts/repair_ralph_agents.py --dry-run   # detect + describe
python offices/pm/scripts/repair_ralph_agents.py --check     # exit 0/1 on validity
```

Strategy: truncate Rex's bloated note to a short pointer; preserve agents 2/3/4 verbatim. Detail log canonical in `progress.txt`.

## sprint_lint.py

Audits `offices/ralph/sprint.json` against the Sprint Contract v1.0 spec at
`docs/superpowers/specs/2026-04-14-sprint-contract-design.md`. Run before
committing a new sprint or after grooming changes to catch:

- Missing required fields (`feedback` scaffold, `passes: false-not-null`, etc.)
- Sizing cap violations (S ≤2 / M ≤5 / L ≤10 filesToTouch; acceptance counts)
- Title length > 70 chars
- Banned phrases (`etc.`, `handle edge cases`, `tests pass` without command, etc.)
- Missing pre-flight audit as first acceptance criterion
- L stories missing `pmSignOff` field

```bash
python offices/pm/scripts/sprint_lint.py             # full audit
python offices/pm/scripts/sprint_lint.py --story US-195   # one story
python offices/pm/scripts/sprint_lint.py --strict    # exit non-zero on warnings too
```

Exit code: 0 = clean, 1 = errors found (or warnings with --strict), 2 = file/arg error.

Run this BEFORE every PM commit that touches sprint.json.

## Composition pattern: slash commands call Python scripts

Per `feedback_pm_python_for_deterministic_work.md` (CIO 2026-05-05): repeatable mechanical work belongs in a Python script in this folder; orchestration belongs in a slash command at `.claude/commands/`. They compose -- a slash command's phases each invoke `python offices/pm/scripts/<verb>.py [args]`. This saves CIO tokens (script body doesn't reappear in messages) + gets correct deterministic results.

### Current slash command -> script call graph

| Slash command | Phase | Script invocation |
|---|---|---|
| `/sprint-close-pm` | 0 pre-flight | `pm_status.py` + `sprint_lint.py` (incl. `--check-feedback`) |
| `/sprint-close-pm` | 1 status hygiene | `bump_passed_statuses.py` |
| `/sprint-close-pm` | 2 archive | `archive_sprint_artifacts.py` |
| `/sprint-close-pm` | 3 PM artifacts | `backlog_set.py` (phase status flip) + manual MEMORY.md / projectManager.md edits |
| `/sprint-close-pm` | 6 RELEASE check | `verify_release_version.py` |
| `/sprint-close-pm` | 8 deploy verify | shell `ssh` + grep (candidate for extraction at next organic touch) |
| (any session) | Ralph harness repair | `repair_ralph_agents.py` -- detect + repair ralph_agents.json corruption from Rex's bloated-note bug pattern |

## When to build a new script

Add one here if you find yourself running the same `python -c "..."` inline pattern twice (or once if it's >10 lines). Keep them stdlib-only, CLI-first, idempotent, and add a one-line example to this README.

**Scope**: PM-office work ONLY. Do NOT add scripts that operate on `offices/ralph/`, `offices/tuner/`, or other agent folders -- those agents own their own automations.

Don't build tooling for operations that happen once per project (e.g. a single schema migration).
