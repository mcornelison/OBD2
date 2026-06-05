# Rule 13 Audit Discipline — Patterns from Sprint 43 PRD review

**Date**: 2026-05-28
**Context**: First PM Rule 13 (validation-block sign-off) executed; Sprint 43 / V0.28.0 PRD review.
**Audience**: Future Atlas sessions running Rule 13 reviews or any architecture audit against `sprint.json` / `bigDoDHash`.

---

## 1. Encoding-on-Windows audit gotcha

When auditing `sprint.json` (or any JSON containing the `→` arrow used in `bigDefinitionOfDone` formatting), Python's `open()` without `encoding='utf-8'` defaults to **cp1252 on Windows** and silently mojibakes every clause. This produces a hash mismatch that LOOKS like freeze drift but is actually instrument failure.

**Symptoms**:
- `lintSprintValidation()` returns `[]` (clean)
- Manual `hashlib.sha256(canonicalizeBigDoD(bdod).encode('utf-8')).hexdigest()` returns a DIFFERENT hash than stored
- All 103/103 clauses appear to "differ" between two loads of the same file
- Byte-comparison of the file via both paths reports identical

**Root cause**: `json.load(open('path.json'))` on Windows opens in text mode using `locale.getpreferredencoding()` = `cp1252`. The `→` (U+2192) gets replaced or raises depending on errors mode. Even when it appears to load, the in-memory string has wrong code points.

**Correct form**:
```python
with open(path, encoding='utf-8') as f:
    s = json.load(f)
```
or:
```python
import pathlib
s = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
```

**The script does it right** (`Path.read_text(encoding='utf-8')`) — only my ad-hoc Python audits got bitten. Lesson: when freeze-hash recompute mismatches but `sprint_lint` reports clean, suspect the auditor's encoding before suspecting freeze drift. Always recompute via the project's own `canonicalizeBigDoD` helper, never re-implement the recipe in an audit harness.

**File**: `offices/pm/scripts/_freeze.py` is the canonical recipe.

---

## 2. Fold sprint-level IRL clauses into per-Story validationCriteria (better than spec literal)

The validation-criteria-upfront spec (2026-05-28) + PRD template `## Sprint-level validation.bigDefinitionOfDone` section both imply two tiers:
- Per-Story `validationCriteria` aggregate into bigDoD via `prd_to_sprint.py`.
- Sprint-level IRL clauses are "added at freeze time on top of per-Story aggregation."

In practice, `prd_to_sprint.py` only does per-Story aggregation; it does NOT parse the PRD's sprint-level IRL markdown table. Marcus closed the gap by **folding sprint-level IRL clauses into the per-Story validationCriteria of whichever Story produces the artifact the clause validates**.

**Why this is better than the spec's literal text**:
1. Folded clauses are in the freeze hash (protected from drift). Standalone sprint-level appended at freeze time would also be in the hash, but only if the script supported it.
2. Folded clauses are attributed to specific Stories (Ralph knows which Story owns each gate's artifact production). Standalone sprint-level clauses risk being orphaned ("no Story owns producing the artifact this clause validates").
3. The IRL gate is checked at Story-completion time, not just sprint-end, surfacing failure earlier in the dev loop.

**Example mapping (Sprint 43)**:
| PRD sprint-level IRL clause | Folded into |
|---|---|
| Drive 27+ exactly 1 drive_id | US-359 vc1/vc2 + US-361 vc1 (reproducer fixture asserts) |
| Recompute `attribution_anomaly` on 23+24 only | US-363 vc1/vc2/vc3 + US-364 backfill |
| `show_ecu_lineage` 2 rows | US-366 vc (specific lineage-output criterion) |
| Freeze-frame smoke | US-368 + US-369 sync criteria |
| Drive_summary backfill invariant | US-372 vc1 (explicitly tagged "Atlas Sprint-IRL clause #5") |
| Drive_statistics rename verification | US-371 vc1/vc2/vc3 |

**When fold-into-stories doesn't work**: genuinely cross-Story IRL gates that no single Story produces the artifact for (e.g., "5 consecutive in-car clean shutdowns" across multiple stories, like Sprint 39's acceptance gate). For those, extending `prd_to_sprint.py` to parse a sprint-level IRL markdown table + append at freeze time is the right tool. PM call when the case arises.

**Verification pattern when auditing**: cross-check each named PRD sprint-level IRL clause against `bdod` substring search. If all 6 appear (folded or otherwise), aggregation is faithful.

---

## 3. Structural-pin discovery via sync mechanics

When a Story adds columns to a synced table, audit `src/server/api/sync.py` for the `_PRESERVE_ON_UPDATE` set BEFORE issuing a verdict. Columns NOT in `_PRESERVE_ON_UPDATE` get overwritten on Pi-sync conflict; columns that Pi never sends in the payload are preserved on the server (current behavior: payload columns get upserted, server-only columns stay).

**Sprint 43 finding**: US-365 added 5 new columns to `vehicle_info` (4 ECU identity + 1 notes). If Pi were also migrated and synced those columns, the server's edited values would get clobbered. The architectural fix: **ECU columns + notes must be server-side-only**. Pi's `vehicle_info` schema stays unchanged. Pin lands in US-365 vc10 + vc11.

**Same pattern, prior Sprints**:
- §10.7 (Sprint 41 / V0.27.17): server analytics columns on `drive_summary` are server-side-only (Pi never writes them); sync upsert path uses `_PRESERVE_ON_UPDATE` to keep them safe.
- This is now a recurring pattern: any new column that's "server-derived" or "server-managed" goes through the same sync-clobber-prevention review.

**Audit checklist for any Story that adds columns to a synced table**:
1. Is the column Pi-authored or server-authored?
2. If server-authored: is it in `_PRESERVE_ON_UPDATE`? (No — it doesn't need to be; Pi won't send it in payload.)
3. Does the Pi-side schema get a parallel column? (No — Pi schema stays unchanged; server-only.)
4. Validation criterion: sync round-trip preserves server-edited value.

If any of these are unclear in the Story, CHANGES-REQUEST it.

---

## 4. Story-criteria verification pattern (use this, not narrative trust)

Marcus's Rule 13 reroute note will summarize what's in the package. **Verify against the artifacts, not the summary.** Specifically:

```python
import json
with open('offices/ralph/sprint.json', encoding='utf-8') as f:
    s = json.load(f)
# Per-story count + content
for st in s['stories']:
    print(st['id'], len(st['validationCriteria']), len(st['acceptance']), bool(st.get('goal')))
# Hash recompute via project's own canonicalize
from offices.pm.scripts._freeze import canonicalizeBigDoD
import hashlib
canonical = canonicalizeBigDoD(s['validation']['bigDefinitionOfDone'])
recomputed = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
assert recomputed == s['validation']['bigDoDHash'], "FREEZE DRIFT"
# Story-file existence check
import pathlib
for st in s['stories']:
    p = pathlib.Path(f"offices/pm/backlog/{st['id']}.md")
    assert p.exists(), f"missing Story.md: {st['id']}"
```

Run this BEFORE issuing PASS. Marcus's package was clean; future packages may not be. The cost of verification is small; the cost of a PASS issued on faulty narrative is large.

---

## 5. The discipline-loop holding across V0.28.0 grooming

V0.27 chain closed because the discipline-loop held — independent re-verification, honest empirical gating, flag-don't-improvise, production-fidelity drills. **V0.28.0 PRD grooming is the first test of whether the loop survives outside the closing-saga context** (no immediate empirical gate forcing rigor; just paperwork).

It held:
- Q1: CIO ratified the trade-off rather than rubber-stamping Atlas's recommendation.
- Q2: Spool refined Atlas's PASS-by-default into a stronger design (provenance column).
- Q4: Spool deeper-dived Atlas's FK-only ruling into FK + identity-immutable + mutable-notes carve-out + temporal invariant.
- Structural pin: Atlas discovered the `_PRESERVE_ON_UPDATE` constraint by reading sync code, not by accepting the PRD framing.
- Marcus PM-orchestration call: fold IRL clauses into Stories, BETTER than the spec literal.
- 4-way joint design: no single agent owned the final shape; each contributed a refinement that improved the others' work.

**Lesson worth carrying**: the discipline-loop doesn't need an empirical gate to fire. It fires whenever any agent deeper-dives instead of rubber-stamping. Sprint 43 dispatch is on a load-bearing contract because four agents deeper-dived in parallel.

Keep it holding. Each session, look for one place where deeper-diving instead of accepting the framing produces a better answer. That's the engine.

— Atlas
