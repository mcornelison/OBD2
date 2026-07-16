# I-rule13-audit-spec-still-requires-story-md-mirror: Rule-13 audit spec still asserts Story.md mirror existence (retired convention)

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Low |
| Status       | Open |
| Category     | infrastructure |
| Found In     | `specs/rule-13-audit-discipline.md` (lines ~111-115) |
| Found By     | Rex (Ralph, US-468, Sprint 58) |
| Related B-   | F-118 (US-468 Story.md-mirror retirement) |
| Created      | 2026-07-13                |

## Description

`specs/rule-13-audit-discipline.md` contains an active pre-flight audit snippet that
**requires** every sprint story to have an `offices/pm/backlog/US-*.md` Story.md mirror:

```python
# Story-file existence check
import pathlib
for st in s['stories']:
    p = pathlib.Path(f"offices/pm/backlog/{st['id']}.md")
    assert p.exists(), f"missing Story.md: {st['id']}"
```

This contradicts US-468's Story.md-mirror retirement (`backlog.json` is the single
story SSOT; per-story `US-*.md` mirrors retired/optional; newest mirror ~US-398).
The same file also encodes the **retired Rule-13 / `bigDoDHash` FREEZE-DRIFT audit**
mechanic (lines ~106-110) — per CIO 2026-07-13 the freeze mechanic is fully retired
(`prd_to_sprint.py` no longer stamps `frozenAt`/`bigDoDHash`; `sprint_lint` no longer
drift-checks). So the whole spec is stale, not just the mirror assert.

## Why this is filed as an issue (not fixed in US-468)

`specs/` is **read-only for Ralph** (per `offices/ralph/prompt.md`: "specs/ is
read-only for Ralph — request changes via offices/pm/issues/"). US-468 scrubbed the
mirror requirement everywhere within Ralph's lane (PM folder-structure table +
`_template-prd.md`); this spec is the one remaining active "step still requires
mirrors" site and needs a PM edit.

## Expected Behavior

The spec's Story-file existence assert is removed/annotated (mirrors are retired), and
— ideally — the whole `rule-13-audit-discipline.md` is retired or marked SUPERSEDED,
since the Rule-13 freeze audit it documents is itself retired.

## Actual Behavior

The spec still presents "assert every story has a `US-*.md`" as a required pre-PASS
audit step, and still documents the retired `bigDoDHash` freeze-drift check.

## Impact

Documentation-only. No runtime code runs this snippet automatically today (Rule-13 is
retired), so no live gate breaks. Risk is confusion: an agent following the spec
literally would re-introduce the retired mirror + freeze conventions. No workaround
needed; low urgency.

## Resolution

[Fill in when resolved] Suggested: retire/supersede `specs/rule-13-audit-discipline.md`
(freeze + mirror both retired), or at minimum delete the Story-file existence assert
and annotate the mirror-retirement + freeze-retirement at the top of the file.
