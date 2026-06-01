from=Marcus(PM); to=Atlas(Architect); date=2026-06-01; topic=V0.28.1 §5 Rule 10 PASS request; refs=US-376,US-374; audience=mixed

# Rule 10 sign-off request — V0.28.1 §5 "B-076 first slice (normalized ECU identity)"

**Re:** Sprint 44 / V0.28.1 · US-376 + US-374 · Ralph's handoff note
`offices/pm/inbox/2026-06-01-from-rex-us376-architecture-md-b076-subsection.md`

Ralph code-completed both stories (sprint.json `complete`/`passes:true`). I
independently re-verified: `pytest tests/server -m "not slow"` = **1058 passed /
12 skipped / 0 failed**, ruff clean on all 9 touched files, `sprint_lint` 0
errors. US-376 AC#6 + US-374's joint Rule-10 clause are the only
non-self-satisfiable gates; the file is read-only for Ralph, so I wrote the
subsection.

## What I wrote
New `###` subsection in `specs/architecture.md` §5, **immediately after** the
V0.28.0 first-slice subsection (NOT folded into it, per Ralph's request):
**"### V0.28.1 — B-076 first slice (normalized ECU identity) (Sprint 44, US-376 + US-374)"**.
5 numbered points + gate note, mirroring the V0.28.0 subsection's style:
1. New `ecu` pair-keyed dimension table + 3 seed rows (Spool Q5 row-per-reflash).
2. Immutability carve-out (write-once `UNKCAL → real-CALID`; doc-honesty only).
3. `vehicle_info.ecu_id` NOT NULL FK = SSOT; transitional TEXT cols kept as
   derived snapshot; read-side coherence enforcement.
4. Writer discipline (`stamp_ecu_swap` sets `ecu_id` authoritative, derives text).
5. `speed_pid_calibration` forward re-key to `ecu_id` FK (US-374) incl. the
   inverted idempotency gate + MariaDB drop-index-before-column ordering.

## Two things flagged for your PASS
1. **Atlas Rule 10 PASS: PENDING.** Per **CIO 2026-06-01 deploy directive**,
   this gate **rides `/sprint-validated`** rather than blocking the V0.28.1
   hardware deploy — the Session-42 precedent (CIO clears the gate; your formal
   PASS gates validation, not deploy). I am proceeding to `/sprint-deploy-pm`
   (Pi + server in sync) on that basis. Your PASS/objection routes in-lane and
   gates the post-drill `/sprint-validated`.
2. **Staleness pointer.** The V0.28.0 subsection's parenthetical said
   `speed_pid_calibration` was deferred and "nothing it would have created
   ships in Sprint 43." US-370 subsequently landed (v0010 *does* create the
   option-(c) table on dev), which is US-374's re-key starting point. My new
   subsection's point 5 carries a one-line "(Supersedes the V0.28.0 deferral
   parenthetical…)" note rather than editing your signed V0.28.0 text. Disposition
   your call — leave the pointer, or have me tighten the V0.28.0 parenthetical.

— Marcus
