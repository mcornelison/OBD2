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

## When to build a new script

Add one here if you find yourself running the same `python -c "..."` inline
pattern twice. Keep them stdlib-only, CLI-first, idempotent, and add a one-line
example to this README.

Don't build tooling for operations that happen once per project (e.g. a single
schema migration).
