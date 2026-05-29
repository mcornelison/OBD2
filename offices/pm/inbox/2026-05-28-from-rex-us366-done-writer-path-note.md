# US-366 done — F-108 ECU-lineage CLIs (+ a heads-up for US-368)

**From:** Rex (Ralph Agent, Agent 1)
**To:** Marcus (PM)
**Date:** 2026-05-28
**Sprint:** 43 / V0.28.0 (`sprint/sprint43-V0.28.0`)
**Re:** US-366 `stamp_ecu_swap` + `show_ecu_lineage` + `add_ecu_note` CLIs

## Status

US-366 is **DONE** (`passes: true` in sprint.json). Additive, server-only, over
the US-365 `vehicle_info` ECU-lineage schema. All runnable validation GREEN:

- 16 new tests (RED→GREEN); `pytest tests/server/ -m "not slow"` = **911 passed
  / 12 skipped / 0 failed** (+16 over US-365's 895; no regressions).
- ruff clean on all 8 touched files.
- Changes **UNSTAGED** per PM protocol.

No cross-agent gate to chase for US-366: unlike US-361/363/365 it has **no
schema or `architecture.md` change**, and its ACs do **not** list an Atlas Rule
10 sign-off. The §5.X / §10.7 doc work is US-373's deliverable.

## One heads-up for when US-368 is groomed/validated (not blocking)

US-368 AC#3 / its validation plan a "no UPDATE on `vehicle_info` in
`src/server/`" grep (or runtime assertion) to prove the append-only invariant.

That guard must target **raw SQL `UPDATE ... SET ecu_signature`** (the *identity*
columns), **not ORM attribute assignment**. US-366's sanctioned writer path
legitimately mutates `vehicle_info` via the ORM:

- `stamp_ecu_swap` sets `ecu_removal_timestamp_utc` on the active row (the
  write-once *close* half of close+open), and
- `add_ecu_note` sets `notes` (a MUTABLE column).

Both are exactly the close+open / annotate mechanisms the invariant *sanctions*.
A naive grep for the literal token `UPDATE` against `src/server/` won't match ORM
attribute sets anyway, but if US-368 reaches for a runtime/listener assertion it
should scope to the **identity columns** (`ecu_signature`,
`ecu_install_timestamp_utc`) only — otherwise it would trip the legitimate close
and note-append paths.

## Sprint state after US-366

- `passes: true` (7/15): US-359, US-360, US-361, US-362, US-363, US-365, US-366.
- Blocked: US-364 (BL-022, IRL-only), US-367 (needs Spool naming sign-off first
  per its conditionalOutcome).
- Dev-doable remaining: US-370, US-371 (note: per my US-365 close, US-371's ORM
  rename + v0010 substep + test file already appear in-tree but sprint.json still
  says `passes: false` — please reconcile/verify before a fresh dispatch),
  US-372, US-368, US-369. US-373 (architecture.md + Atlas Rule 10) is best last
  so it documents the *final landed* state of all schema stories.
