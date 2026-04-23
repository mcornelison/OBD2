# I-017: specs/standards.md ↔ offices/ralph/agent.md duplication (cross-document drift risk)

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Low-Medium (no active bug today; drift risk over time as one doc updates without the other) |
| Status       | **Closed 2026-04-21 via US-218** — canonicalization done. See "Closure (2026-04-21, US-218)" below for what-canonicalized-where. |
| Affected     | `specs/standards.md` (PM-owned, 827 lines — NOT touched by closure) and `offices/ralph/agent.md` (Ralph-owned, 352 → 333 lines after closure dedup) |
| Discovered   | 2026-04-20, Session 71 Tier 1/2 knowledge read per CIO direction |
| Filed by     | Ralph (Rex), Session 71, 2026-04-20, at CIO direction during file-size optimization |
| Closed by    | Ralph (Rex), Session 87, 2026-04-21, via US-218 (Sprint 16 "Wiring") |

## Closure (2026-04-21, US-218)

**Approach.** Option B from "Suggested paths forward" — picked per-topic canonical source-of-truth, reduced agent.md to a pointer table + Ralph-operational additions; specs/standards.md unchanged (PM territory).

**What canonicalized where (canonical → agent.md after):**

| Topic | Was in agent.md (duplicated) | After closure (agent.md) |
|-------|------------------------------|--------------------------|
| File headers | 1-line pointer to §1 | ✅ Pointer table row |
| Naming conventions | 6-line summary table + exemption-count hint | ✅ Pointer table row + 1-line exemptions note |
| SQL conventions | 1 line in summary | ✅ Pointer table row (§2 + §5) |
| Code commenting | Not in agent.md | ✅ Pointer table row (§3) |
| Python imports / type hints / Google docstrings | 3 bullets | ✅ Pointer table rows (§4) |
| Error handling (5-tier list) | 5 bulleted tiers + methodology pointer | ✅ Collapsed to "defined in methodology.md + architecture.md §7" + kept operational constants (retry schedule, exit codes) |
| Testing (coverage, AAA, fixtures, markers) | 5 bullets | ✅ Pointer table row (§7) + Ralph-specific pi_only marker + knowledge/patterns-testing.md pointer |
| Logging format | None duplicated in agent.md header | ✅ Pointer table row (§8) — see divergence note below |
| Git commits | Sprint-branching flow only (distinct) | ✅ Unchanged — no overlap |
| ConfigValidator / SecretsLoader / error classification | Already moved to knowledge/patterns-python-systems.md Session 71 | ✅ Pointer table row (§11) |
| File size rules (~300 / ~500) | "Small files:" bullet in Code Quality Rules | ✅ Pointer table row (§12) |
| Database patterns | Already moved to knowledge/patterns-obd-data-flow.md Session 71 | ✅ Pointer table row (§13) |

**Files touched by closure:**
- `offices/ralph/agent.md` (dedup + pointer table + mod-history entry) — 352 → 333 lines
- `offices/pm/issues/I-017-standards-md-agent-md-duplication.md` (this annotation)
- `offices/pm/inbox/2026-04-21-from-ralph-us218-dedup-complete.md` (audit results + divergence flag)

**NOT touched** (per invariants in US-218 scope):
- `specs/standards.md` — PM-owned canonical source; no edits.
- `offices/ralph/knowledge/patterns-*.md` — operational, not duplicating standards.md; audited clean.
- `offices/ralph/prompt.md` — linked, not duplicated.

**Divergence discovered during dedup** (flagged to Marcus, not resolved here):

`specs/standards.md` §8 Log Message Format shows f-string examples:
```python
logger.info(f"Processing batch | batchId={batchId} | recordCount={len(records)}")
```
while `offices/ralph/agent.md` Golden Code Patterns (derived from `specs/golden_code_sample.py`) says:
```python
logger.info("Loaded %d record(s)", count)   # % formatting (not f-strings) for lazy evaluation
```

These are authoritatively-different, not just duplicated — Golden Code prefers `%` for lazy evaluation, while standards.md §8's example uses f-string. This is a latent drift that predates US-218 and falls outside US-218's scope fence (agent.md dedup, not standards.md edits). Marcus is the arbitrator — inbox note 2026-04-21-from-ralph-us218-dedup-complete.md carries the specific file:line references.

**Verification evidence:**
- TOC comparison before/after: agent.md lost 4 H3 headings under Coding Standards (Naming Conventions / File Headers / Code Quality Rules / Documentation) + renamed "Error Handling" → "Error Handling — operational constants". No other H1/H2/H3 removed.
- Line count: `wc -l offices/ralph/agent.md` 352 → 333 (−19 lines).
- `pytest tests/ -m "not slow" -q`: [verified in US-218 progress.txt entry].
- `python offices/pm/scripts/sprint_lint.py`: 0 errors.

— Rex, 2026-04-21 (Session 87)


## Observation

During the Session 71 file-size optimization (CIO-directed refactor of agent.md into a slim core + 5 load-on-demand subsidiary knowledge files), I noticed that several topics had partial or near-complete duplication between `specs/standards.md` (PM-owned, canonical for the project) and `offices/ralph/agent.md` (Ralph-owned agent manual).

Because specs is PM-owned and agent.md is Ralph-owned, I was explicitly instructed NOT to cross-edit during this session. I kept Ralph's version intentionally brief with pointers to specs/standards.md for the authoritative form, but the duplication remains and is a drift source.

## Specific overlap sites

| Topic | In specs/standards.md | In offices/ralph/agent.md (pre-refactor) | Drift risk if one updates |
|-------|----------------------|------------------------------------------|--------------------------|
| File headers | §1 (full boxed format + SQL variant) | Prior §"File Headers" pointer, now a one-line pointer post-refactor | Low — Ralph's is now a pointer. |
| Naming conventions | §2 (full table + 9 camelCase exemptions) | §"Naming Conventions" (original had 4-item table, same core rules but NO exemptions) | **Medium** — agent.md's brief table is a subset of standards.md's. Post-refactor, agent.md has a summary table + "(9 exemptions listed in standards.md §2)" pointer. Still two surfaces. |
| SQL conventions | §2 (tables/columns snake_case, PK table_id, FK_child_parent, IX_table_column) + §5 (full CREATE TABLE template) | Original §"Naming Conventions" table had 1 line on SQL | Low — agent.md defers on SQL; standards.md is single source. |
| Code commenting | §3 (DO / DON'T Comment lists + Good/Bad examples) | None — agent.md never had this | N/A |
| Python imports ordering | §4 (stdlib / third-party / local) | None | N/A — only in standards.md |
| Type hints + docstrings | §4 | None in agent.md, but Golden Code Patterns has Module-level `logger = logging.getLogger(__name__)` pattern | Low |
| Error handling | §4 (specific exception + classify + NEVER catch broad Exception) | §"Error Handling" (5-tier retryable/auth/config/data/system list) | **Medium** — agent.md summary now has 5-tier list + pointer to methodology.md/architecture.md §7, but standards.md §4 also has error examples |
| Testing standards | §7 (test file naming, function naming, AAA pattern, fixtures, markers) | §"Testing Requirements" (coverage + AAA + fixtures + markers) | **High** — both docs cover the same topic with overlapping-but-not-identical content. Post-refactor, agent.md brief summary pointing to standards.md §7. |
| Logging | §8 (log message format + structured logging + sensitive data) | §"Logging Patterns" subsection of Operational Tips (unique logger per instance, RotatingFileHandler encoding) | Low — distinct content (standards.md covers principles; the pattern subsection now in `knowledge/patterns-python-systems.md` covers specific implementation tricks) |
| Git standards | §9 (commit messages + branch names) | §"Git Branching Strategy" (sprint-based flow) | Low — distinct content, standards.md covers message format, agent.md covers workflow |
| ConfigValidator dot-notation | §11 Project-Specific Patterns | Original "Configuration" subsection now in `knowledge/patterns-python-systems.md` | **Medium** — same pattern explained twice in slightly different forms |
| Error Classification decorator | §11 Project-Specific Patterns (retry decorator, classifyError, ErrorCategory enum) | §"Error Handling" 5-tier list (agent.md) | **Medium** — both describe the same system from different angles |
| File size rules | §12 Rule 2 (~300 source / ~500 test, subpackage pattern) | §"Code Quality Rules" (mirrors — ~300 source / ~500 test) + Housekeeping file-size flag | **High** — same numbers in 3 places |
| Database patterns | §13 (full — ObdDatabase.connect(), idempotent initialize, ALL_INDEXES list, FK awareness, Canonical Timestamp Format with full code) | Original "Database Patterns" subsection (temp dbs, INSERT OR REPLACE, FK handling) now in `knowledge/patterns-obd-data-flow.md` | Low — the knowledge file covers testing-adjacent DB patterns; standards.md §13 covers production-code DB patterns. Distinct scopes. |

## Why this matters

The drift risk is cumulative: every time Marcus updates specs/standards.md (or the project standards evolve), the matching agent.md summary can fall out of sync. Today the Session 71 refactor sharpened this by making agent.md's summaries explicitly reference specs/standards.md sections — but a pointer is only correct the day it's written, and specs/ renumbering would silently break the references.

**Example of drift that already happened this session** (caught and fixed): agent.md line 45 `Set passed: true` had drifted from sprint.json's `"passes": true` key. The typo survived unknown sessions because nothing forced cross-doc consistency. Same class of silent drift applies to every overlap site above.

## Suggested paths forward

**(a) Status quo** — agent.md uses pointers to specs/standards.md; accept the drift risk; rely on periodic review.
- Cost: low (no work).
- Risk: drift continues to accumulate; next reviewer has to cross-check both docs manually.

**(b) Canonicalization story** (recommended — S/M size story for Sprint 16+)
- Pick canonical source-of-truth for each overlap (per the table above).
- For topics where standards.md is canonical (§7 testing, §11 patterns, §12 file sizes, §13 DB): agent.md retains ONLY a pointer + 1-line summary.
- For topics where agent.md is canonical (workflow, CIO dev rules, Golden Code Patterns): standards.md references it, doesn't duplicate.
- Update both docs in a single PR so drift is eliminated at refactor time.
- Estimated size: S (≤3 files, ≤3 criteria, ≤200 lines diff net).

**(c) Auto-lint** — extend `scripts/audit_config_literals.py` pattern (the B-044 lint from Sprint 14) with a doc-drift checker: define canonical topics and their source-of-truth file; assert the non-canonical files contain only a pointer, not duplicated content.
- Cost: M-size story; real tooling work.
- Value: prevents future drift permanently.
- Bundle candidate: could pair with TD-028 (ralph.sh promise-tag contract drift) since both are "doc drift" flavor.

## My recommendation

**Option B for Sprint 16 or Sprint 17.** Low urgency (no active bug), but Session 71's refactor left the two docs in a state where canonicalization would be cheap to do now — the subsidiary knowledge files are already clean. Extracting the remaining specs/standards.md ↔ agent.md overlap into single-source-of-truth references would close the drift window.

Option C (auto-lint) is worth considering if you like the B-044 audit-script precedent, but it's incremental polish after Option B.

## Tracking

- Related filings this session:
  - `offices/pm/tech_debt/TD-028-ralph-sh-promise-tag-contract-drift.md` — sibling doc-drift TD (different files)
  - `offices/ralph/agent.md` post-refactor — references this issue in its mod history
  - `offices/ralph/knowledge/README.md` — index of where the extracted content now lives
- Grounded in the Session 71 CIO directive: *"Optimize to reduce duplication but without forgetting anything."* The intra-file (agent.md → knowledge/) portion is done; this issue tracks the cross-file (agent.md ↔ specs/standards.md) portion that needs PM/CIO involvement.

— Rex
