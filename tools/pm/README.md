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

> The `python offices/pm/scripts/backlog_set.py ...` invocations below are stale
> — the tools moved to `tools/pm/` in the 2026-08-24 decouple and their data
> moved to `$FLEET_SHARE`. Invoke as `python -m tools.pm.backlog_set ...`.

### Create a Story (`--add-story`, US-669)

Files a Story with every schema-required field already stamped, so
`validateBacklog` accepts it unmodified. This is the only story-creation path;
before it existed, filing a story meant hand-editing a ~900 KB JSON file and
remembering twelve required fields — which drifted twice (47 records repaired by
US-465, then 41 more).

```bash
python -m tools.pm.backlog_set --add-story \
    --story-parent F-118 \
    --story-title "The backlog lint reports every violation" \
    --story-goal "As the PM, I want ... because ..." \
    --story-dod "SSOT: tools/pm/sprint_lint.py" \
    --story-dod "END STATE: every violation is listed" \
    --story-vc "run the lint over a backlog with 3 violations" "all 3 are reported" \
    --story-type tech-debt --story-size S --story-status sprint-ready
```

What it stamps, and what it refuses:

- **Stamped** — `id` (allocated above `story_counter.json`, `counters.story` and
  every id present), `createdAt`/`updatedAt` (run date), `conditionalOutcomes`
  and `tasks` (empty lists), and `type`/`size`/`status` defaults
  (`normal`/`M`/`pending`).
- **Refused, with nothing written** — missing or blank `goal`,
  `definitionOfDone`, `validationCriteria`, `title` or `parent` (it will never
  invent a placeholder to satisfy the schema); a `parent` that is not an
  existing **Feature** id (Rule 11); an `id` that already exists.
- Every reason is reported at once, not one per run.
- Writes via temp + `os.replace`, never truncating in place. The counter lands
  first on purpose: a failed backlog write leaves a harmless *gap* in the id
  sequence rather than handing the next caller a *duplicate*.

The required-field list is read from `backlog_schema.REQUIRED_STORY_FIELDS` and
never restated — add a field there and this tool starts requiring it with no
edit. A test bans a second copy of that constant anywhere in `tools/pm/`.

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

## chain_validate_aggregate.py

`/chain-validated` Phase 1+2 support (B-067 / Sprint 31 US-318). Enumerates
sprint.json files belonging to a V0.X minor-version chain (e.g. V0.27 =
V0.27.2 + V0.27.3 + V0.27.4 + V0.27.5 stacked sprint branches awaiting
chain-end merge to main), aggregates each sprint's validation block, and
reports whether the chain is READY (the CHAIN-TIP sprint carries a
`validatedAt` stamp) or INCOMPLETE (the tip does not, or no sprint matched the
`--chain` prefix -- `chainTipVersion` tells those two apart).

**The gate is the chain TIP alone** (`chain_validate_aggregate.py:238`). Earlier
patches in the chain keep `validatedAt: null` under the CIO 2026-05-23
chain-end-merge rule -- superseded by the next patch, never individually
re-validated -- so null is the EXPECTED state, not a debt. `unvalidatedSprints`
lists them as context only (`:188`). Corrected under US-618, which was groomed
after this claim's stale form cost a sprint.

Per CIO 2026-05-10 chain-end-merge rule: main = "fully functional working
system"; sprint branches stay deployed-but-pre-merge until the WHOLE chain
validates IRL. This script powers the chain-wide pre-flight gate
`/chain-validated` runs before touching git history.

```bash
# Auto-discover (globs archive + current sprint.json):
python offices/pm/scripts/chain_validate_aggregate.py --chain V0.27

# Machine-readable for downstream piping:
python offices/pm/scripts/chain_validate_aggregate.py --chain V0.27 --json

# CI gate -- exit 1 if the CHAIN TIP lacks validatedAt (or the chain is empty):
python offices/pm/scripts/chain_validate_aggregate.py --chain V0.27 --strict

# Explicit paths (test harness + ad-hoc inspection):
python offices/pm/scripts/chain_validate_aggregate.py \
    --chain V0.27 --paths sprint.json archive/sprint.archive.X.json
```

Output fields (`--json`): `chainPrefix`, `sprintsInChain` (per-sprint
records ordered by `currentVersion`), `aggregateValidatesFeatures` (sorted
unique union), `aggregateBigDoD` (chain-wide clauses, each carrying a
`retired` boolean), `unvalidatedSprints`, `chainTipVersion`, `chainStatus`
('READY' / 'INCOMPLETE'), `retiredBigDoD`, `staleRetirements`.

Exit codes: 0 if chain READY (or report mode), 1 if `--strict` +
INCOMPLETE **or `--strict` + a stale retirement**, 2 on file/parse error
(including a `--retirements` path that does not exist).

### Retiring a bigDoD clause (US-619)

Sometimes a chain bigDefinitionOfDone clause is invalidated by a finding that
lands *after* the sprint that wrote it. The founding case: V0.29.29 carries
`(output is the panel-native 480x320 ...) [from US-552]`, and BL-034 later
measured the panel's EDID -- the OSOYOO HDMI35 is a **scaler** panel that
advertises no 480x320 mode at all. 720p IS the shipping configuration, so the
clause can never be discharged truthfully.

**Why this needs a route rather than a judgement call.** Anyone sweeping that
clause has exactly two outs: fail the chain, or write evidence for something
that did not happen. The second is the fabricated-fixture defect at chain
scale, and this project has shipped that defect before. The retire route exists
so the sweep operator is never forced to choose.

**The route is ADDITIVE. Archive snapshots are testimony and are never
edited.** A clause is retired by adding a record to
`tools/pm/bigdod_retirements.json`, which the aggregator overlays at read time.
The sprint that made the claim keeps its original text, so a reader sees both
the claim and the authority that withdrew it.

```jsonc
{
  "schemaVersion": "1.0.0",
  "retirements": [
    {
      "currentVersion": "V0.29.29",       // required
      "clause": "<VERBATIM clause text>", // required -- copy from the aggregate
      "retiredAt": "2026-08-28",
      "retiredBy": "Atlas(Architect) BL-034 ruling R1, CIO-ratified 2026-08-27",
      "authority": "offices/pm/.../BL-034-....md",  // required -- a document
      "reason": "why it can never be discharged",
      "supersededStory": "US-560"
    }
  ]
}
```

Rules the tool enforces, and the reason each one is there:

- **`authority` is required.** A retirement withdraws a project commitment. One
  with no cited source is the same defect class as a fixture asserting an
  unmeasured fact.
- **Matching is EXACT on the `(currentVersion, clause)` pair -- never
  substring.** This is load-bearing, not fastidious. The V0.29.15 clause
  `(480x320 UI scales up centered ...) [from US-482]` *also* contains
  "480x320", and it describes the shipping arrangement **exactly** -- it must
  survive. A substring rule retires a correct clause by association. Clause text
  also repeats across sprints, which is why the sprint version is half the key.
- **Copy the clause verbatim from the aggregate output, do not retype it.** The
  real text carries `→` (U+2192), not `->`. A mistyped clause produces an
  *inert* retirement that reports success and retires nothing.
- **A record whose version is in the chain but matches no clause is STALE** and
  is reported in `staleRetirements`; `--strict` then exits 1 with a message
  distinguishing it from a gate failure. A record for a sprint outside the
  aggregated chain is simply not applicable and stays silent.
- **Retirement never touches `chainStatus`.** The gate stays chain-tip-only
  (`:238`, CIO 2026-05-23). Retirement annotates the clause list.

```bash
# See the retirements applied to a chain:
python -m tools.pm.chain_validate_aggregate --chain V0.29

# Alternate ledger (test harness):
python -m tools.pm.chain_validate_aggregate --chain V0.29 --retirements path/to/ledger.json
```

## chain_validate_manifest_bump.py

`/chain-validated` Phase 3 support (B-067 / Sprint 31 US-318). For each
supplied feature ID (typically the `aggregateValidatesFeatures` union from
chain_validate_aggregate.py), bumps `lastValidated` to the chain merge date
and stamps `validatedBy` with the chain-merge label.

```bash
# Bump 2 features for V0.27 chain merge:
python offices/pm/scripts/chain_validate_manifest_bump.py \
    --features F-005 F-007 \
    --label "by chain merge V0.27.5" \
    --date 2026-05-15

# Preview without writing:
python offices/pm/scripts/chain_validate_manifest_bump.py \
    --features F-005 F-007 --label "..." --date 2026-05-15 --dry-run

# Manifest path override (test harness):
python offices/pm/scripts/chain_validate_manifest_bump.py \
    --path /tmp/manifest.json --features F-001 --label "..." --date 2026-06-01
```

Unknown feature IDs are skipped (not added to the bumped list); reported on
stderr. Exit codes: 0 on success (>= 1 feature bumped), 1 if no IDs
matched, 2 on file/parse error.

## pm_regression_status.py

Reports user-facing-feature validation status against the regression manifest. Per Mike 2026-05-08 directive: main = "fully validated stable"; sprint branches stay deployed-but-pre-merge until real-hardware drill validates affected features.

```bash
python offices/pm/scripts/pm_regression_status.py             # full status report
python offices/pm/scripts/pm_regression_status.py --stale     # only STALE + NEVER
python offices/pm/scripts/pm_regression_status.py --by-sprint 27   # which features sprint 27 touched
python offices/pm/scripts/pm_regression_status.py --next      # next validation triggers
python offices/pm/scripts/pm_regression_status.py --json      # machine-readable
```

Output categories per feature:
- **OK**: validated within `staleThresholdDays`
- **STALE**: validated but overdue
- **NEVER**: synthetic-only; never validated in real life

Exit 0 if all OK; 1 if any STALE or NEVER (use as CI gate); 2 on file error.

Reads `offices/pm/regression_manifest.json` (stdlib JSON; no PyYAML dep).

## repair_ralph_agents.py

Repair `offices/ralph/ralph_agents.json` corruption from Rex's bloated-note bug pattern (unescaped quote in long note breaks `json.load`). Observed Sprint 21 close, Sprint 24 close and 2026-08-31 -- three occurrences to date.

```bash
python -m tools.pm.repair_ralph_agents             # repair if corrupt
python -m tools.pm.repair_ralph_agents --dry-run   # detect + describe
python -m tools.pm.repair_ralph_agents --check     # exit 0/1 on validity
```

Strategy: truncate Rex's bloated note to a short pointer; preserve every other agent verbatim. Detail log canonical in `progress.txt`.

The roster size is **read from the file under repair**, never assumed (US-664). `max_agent` is recovered from the document being repaired, and the post-repair agent count is compared against the pre-repair count -- so a repair that would lose (or invent) an agent still refuses, at any roster size. Writes go through a temp file + `os.replace`: the share has no undo, and this tool writes over the only copy of the file it exists to recover.

## sprint_lint.py

Audits `offices/ralph/sprint.json` against the Sprint Contract v1.0 spec at
`$FLEET_SHARE/knowledge/superpowers/specs/2026-04-14-sprint-contract-design.md`. Run before
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

### `--backlog` mode

Lints `$FLEET_SHARE/pm/backlog.json` against schema v2.0.0 instead of the
sprint. Schema violations are errors; rollup-cache staleness is a warning.

```bash
python -m tools.pm.sprint_lint --backlog
```

**It reports EVERY violation in one run** (US-670), then a count per violation
class:

```text
ERROR: Story US-628: missing required fields ['createdAt', 'updatedAt']
ERROR: Story US-629: missing required fields ['createdAt', 'updatedAt']
...
VIOLATIONS: 41 total in 2 class(es)
  storyMissingFields 40
  storyOrphan         1
```

The count line is the point. Until US-670 the lint stopped at the first
failing story, so a 41-story drift printed one line and was indistinguishable
from a single typo -- it was believed, and it under-reported by 40x. Firing is
not the same as informing.

Nothing is printed on a clean backlog; exit stays 0. A single violation still
exits 1 -- the mode is more informative, never more permissive.

## Composition pattern: slash commands call Python scripts

Per `feedback_pm_python_for_deterministic_work.md` (CIO 2026-05-05): repeatable mechanical work belongs in a Python script in this folder; orchestration belongs in a slash command at `.claude/commands/`. They compose -- a slash command's phases each invoke `python offices/pm/scripts/<verb>.py [args]`. This saves CIO tokens (script body doesn't reappear in messages) + gets correct deterministic results.

### Current slash command -> script call graph

| Slash command | Phase | Script invocation |
|---|---|---|
| `/sprint-deploy-pm` | 0 pre-flight | `pm_status.py` + `sprint_lint.py` (incl. `--check-feedback`) + `repair_ralph_agents.py --check` |
| `/sprint-deploy-pm` | 1 status hygiene | `bump_passed_statuses.py` |
| `/sprint-deploy-pm` | 2 archive | `archive_sprint_artifacts.py` |
| `/sprint-deploy-pm` | 3 PM artifacts | `backlog_set.py` (phase -> "awaiting-validation") + manual MEMORY.md / projectManager.md edits |
| `/sprint-deploy-pm` | 5 RELEASE check | `verify_release_version.py` |
| `/sprint-deploy-pm` | 7 deploy verify | shell `ssh` + grep (candidate for next-pass extraction) |
| `/sprint-validated` | 1 evidence | manual confirmation OR journalctl/DB queries |
| `/sprint-validated` | 3 manifest update | inline python (extract candidate -- bumps `lastValidated` for sprint's `validatesFeatures`) |
| `/sprint-validated` | 6 merge to main | `git checkout main && git merge --no-ff <sprint> && git push` |
| `/chain-validated` | 1+2 chain aggregate + status gate | `chain_validate_aggregate.py --chain V0.X [--strict]` |
| `/chain-validated` | 3 manifest bump chain-wide | `chain_validate_manifest_bump.py --features ... --label "by chain merge V0.X.N" --date YYYY-MM-DD` |
| `/chain-validated` | 4 merge chain to main | `git checkout main && git merge --no-ff <chain-tip> && git push` |
| `/chain-validated` | 5 tag stable | `git tag -a V0.X.N && git push origin V0.X.N` |
| (any session) | Ralph harness repair | `repair_ralph_agents.py` -- detect + repair ralph_agents.json corruption from Rex's bloated-note bug pattern |
| (any session) | Regression status | `pm_regression_status.py` -- which features are STALE/NEVER-validated |

## When to build a new script

Add one here if you find yourself running the same `python -c "..."` inline pattern twice (or once if it's >10 lines). Keep them stdlib-only, CLI-first, idempotent, and add a one-line example to this README.

**Scope**: PM-office work ONLY. Do NOT add scripts that operate on `offices/ralph/`, `offices/tuner/`, or other agent folders -- those agents own their own automations.

Don't build tooling for operations that happen once per project (e.g. a single schema migration).
