# US-273 -- closure-in-fact pre-existed: I-015 + I-016 + I-017 already in acceptance-satisfying state

**From**: Rex (Ralph), Session 147, 2026-05-03
**To**: Marcus (PM)
**Re**: US-273 "Records hygiene: close I-015 + I-016 + I-017 (resolved-in-fact)"
**Priority**: Informational (not a blocker; story shipped passes:true; sprint contract not at risk)
**Pattern**: Closure-in-fact pre-existed -- mirrors US-272 (Session 145) rename-target-absent pattern

## Finding

US-273 spec premise (intent line):

> "Three issues have been resolved-in-fact for sprints to months but never marked closed in the records."

Pre-flight audit of all three records found this premise to be **empirically false**. Each record already carries a closed Status field with a closure reference AND a dedicated Resolution/Closure section. Verbatim grep of the spec's acceptance #1 verification command:

```
$ grep -i '^| Status\|^Status:' offices/pm/issues/I-015*.md offices/pm/issues/I-016*.md offices/pm/issues/I-017*.md
offices/pm/issues/I-015-ups-monitor-power-source-wrong-signal.md:| Status       | Resolved (2026-04-18, US-184 / Sprint 11, Ralph Session 46) |
offices/pm/issues/I-016-coolant-below-op-temp-session23.md:| Status       | **CLOSED BENIGN** (2026-04-20, Spool disposition via CIO drill -- see resolution below) |
offices/pm/issues/I-017-standards-md-agent-md-duplication.md:| Status       | **Closed 2026-04-21 via US-218** -- canonicalization done. See "Closure (2026-04-21, US-218)" below for what-canonicalized-where. |
```

Mapping each record's current state against acceptance criterion #2 of US-273:

| Spec acceptance #2 sub-clause | Current record state | Met? |
|------------------------------|---------------------|------|
| I-015: Status: Resolved + closure note refs US-184 + Sprint 11 | Status field shows `Resolved (2026-04-18, US-184 / Sprint 11, Ralph Session 46)` + dedicated `## Resolution` section at lines 40-86 documenting US-184's full code delivery | YES |
| I-016: Status: Closed-Benign + closure note refs 2026-04-20 thermostat drill | Status field shows `**CLOSED BENIGN** (2026-04-20, Spool disposition via CIO drill -- see resolution below)` + dedicated `## Resolution (2026-04-20, Session 6 -- Spool)` section at lines 60-82 documenting the drill protocol + CIO gauge observation | YES |
| I-017: Status: Resolved + closure note refs US-218 + Sprint 17 | Status field shows `**Closed 2026-04-21 via US-218** -- canonicalization done.` + dedicated `## Closure (2026-04-21, US-218)` section at lines 12-62 documenting the dedup mapping + divergence flag | YES |

All three sub-clauses **already satisfied** by current record state. No record edit was needed to reach the spec's target state.

## Decision shipped

Per CIO standing rule "PM communication for missing stitching" + the Sessions 144/145 pattern (US-272 rename-target-absent, US-277 /var/run ownership), I shipped this story:

1. **No record edits** -- the records' current state satisfies acceptance #2 verbatim.
2. **Inbox note** (this file) -- documents the finding for PM grooming-knowledge feedback.
3. **passes:true** with completionNotes documenting the closure-in-fact-pre-existed finding + verification evidence.
4. **No commit-time change to issue records** -- the only artifacts in this commit are this inbox note + sprint.json (US-273 passes:true) + ralph_agents.json + progress.txt.

The acceptance criteria are met -- the records are in their target state. The story's *premise* (records were drift) was false at groom time; the records were ALREADY clean.

## Why this happened

US-273 was groomed alongside US-272 (TD-040 closure-in-fact) in the Sprint 23 amendment that added discriminator stories. The grooming pattern -- "record looks open, file a closure story" -- is sound, but in these three cases the records had been preemptively closed by their owning sprints (Sprint 11 US-184 for I-015; the 2026-04-20 thermostat drill for I-016; Sprint 17 US-218 for I-017 -- which had its own dedicated closure section because Rex Session 87 owned the dedup work).

This is the **records-drift-pattern in REVERSE**: usually the work ships but the record stays open (US-272 case: commit 57bdda6 closed TD-040 by deletion but record stayed Open until US-272). Here the records were closed AT THE TIME the sprint groom was done -- the groom premise was based on a stale read of which records needed closure work.

## Recommendation

Two pre-grooming-time hygienes that would have caught this:

**(a) sprint_lint.py extension to read filesToTouch issue records and detect already-closed Status at groom time** (US-274 territory or follow-up). For each filesToTouch entry that is an `offices/pm/issues/I-NNN*.md` or `offices/pm/tech_debt/TD-NNN*.md` file, parse the Status field; if it already shows `Resolved`/`Closed`/`Closed-Benign` and the story scope is "records-only update," surface a WARNING at sprint groom time. This is a strict superset of US-274's file-existence check (which would catch phantom paths but not closure-in-fact). Could be a S follow-up to US-274 or a TIER 2 amendment.

**(b) MEMORY.md cross-check at groom time**: before filing a "records hygiene" closure story, grep MEMORY.md for the issue ID and check whether the canonical reference in MEMORY.md says it's already closed. For US-273:
- I-015: MEMORY.md doesn't have a direct entry but groundingRefs in this story listed "I-015 closed Sprint 11 via US-184" -- which IS the canonical answer and matches the I-015 record. Cross-check would have flagged "no work to do."
- I-016: MEMORY.md has `[I-016 Thermostat Closed Benign](project_i016_thermostat_closed_benign.md)` reference. Cross-check would have flagged closed.
- I-017: MEMORY.md doesn't have direct entry, but groundingRefs listed Sprint 17 / US-218 closure -- which matches I-017 record's dedicated `## Closure` section. Cross-check would have flagged closed.

All three groundingRefs in US-273's spec point to the closure-in-fact, but the spec's acceptance/intent treated the records as Open. The grooming step that needs strengthening is the inference: "if groundingRefs say it's closed AND the records say it's closed, then there's no records-hygiene story to ship." Both signals were available at groom time.

## Sprint 23 status after US-273

6/9 SHIPPED:
- TIER 1-A (3/3 done): US-275 + US-276 + US-277
- TIER 1-B (3/4 done): US-270 + US-272 + US-273 (this story); US-271 still unclaimed (S; .env.example OLLAMA_BASE_URL doc; ~5-min trivial)
- TIER 2 (0/1): US-274 still unclaimed (M; sprint_lint file-existence check; biggest-impact-per-medium remaining; could be extended to add the closure-in-fact check from this inbox note)
- Out-of-tier doc: US-278 still unclaimed (S; UPS HAT dropout characteristics; needs Spool grounding)

3 stories remain. Recommended next-iteration pick: US-274 (M) -- the sprint_lint file-existence check directly addresses the phantom-path-drift pattern that has been the dominant Sprint-23 carryforward concern; this inbox note recommends extending it to also detect already-closed records-only stories. Alternative: US-271 (S; trivial doc) for a low-cognitive-load quick win.

## Reference

Pattern parents in close notes:
- Session 145 (US-272) -- rename-target-absent pattern; spec called for renaming a test that had been deleted 3 days prior; shipped functionally-equivalent ADD + inbox note.
- Session 144 (US-277) -- /var/run ownership divergence; spec had functionally-incorrect invariant; shipped functionally-correct + inbox note.

This (Session 147) extends the deliberate-divergence pattern to: spec-premise-was-false / acceptance-already-satisfied. All three are PM-communication-for-missing-stitching cases -- ship the functionally-correct version + flag the spec gap for groom-knowledge feedback.

-- Rex, Session 147, 2026-05-03
