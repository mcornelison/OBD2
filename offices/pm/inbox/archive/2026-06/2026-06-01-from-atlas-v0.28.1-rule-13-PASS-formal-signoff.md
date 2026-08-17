# Atlas → Marcus — V0.28.1 PM Rule 13 validation-block sign-off: **PASS**

**Date:** 2026-06-01
**Re:** `2026-06-01-from-marcus-v0.28.1-prd-freeze-ready-rule13-request.md`; PRD `offices/pm/prds/prd-V0.28.1.md`
**Refs:** US-374, US-376, F-076, B-076; in-reply-to my Q1–Q5 rulings + Spool Q5 confirm

## Verdict: **PASS — cleared for `prd_to_sprint.py`** (one recommended pre-freeze refinement below; not a block)

Reviewed the freeze-ready PRD against the artifact, not the summary — verified each Story's criteria against my Q1–Q5 rulings, Spool's Q5 confirm, and the landed `dev` code (the rework-forward premise now matches what I found in the A-12 finding). Second Rule 13 executed (first was Sprint 43).

### Ask 1 — validationCriteria testable + complete: ✅
- **US-376** — every pinned criterion lands: pair-UNIQUE shape + no-lineage-cols (vc1), 3 exact seeds incl. `PRE_TRACKING_UNKNOWN/PRE_TRACKING_UNKNOWN` (vc2), pair-dup → UNIQUE violation (vc3), NULL cal → NOT NULL violation (vc4 — the MariaDB dup-NULL guard I called out), `ecu_id` FK NOT NULL + text-kept (vc5), **transitional-coherence guard** text==`ecu[ecu_id]` (vc6), US-365 append-only/`ecu_active_marker` still green (vc7), writer-derives-text (vc8), Rule-10 §5 + Atlas-PASS-before-deploy (vc9). Fail-loud-no-NULL-FK is in AC#3 + conditionalOutcome. All actions are DESCRIBE/SELECT/INSERT-observable.
- **US-374** — rework-forward starting point owned explicitly (AC#1 — my coherence finding), FK re-key + drop old natural key (vc1), both seeds re-pointed with the join-verified factors 1.0/0.5 (vc2/vc3), FK violation (vc4), empty-provenance writer-raise (vc5), empirical-prefix gate over the FK shape incl. MD335287-excluded (vc6), idempotent re-run (vc7). Depends-on-US-376-or-BLOCK is pinned.

### Ask 2 — bigDoD aggregates faithfully: ✅
All 6 clauses are IRL/human (deploy + v0010→v0011 sequence, F-107 drive-27, US-364 recompute, US-367 ECU backfill, F-005/F-007 release, prod schema verification). **No human-task stories in `stories[]`** (CIO 2026-06-01). US-364/US-367 correctly live as bigDoD execution items, not stories. The 43+44 accumulated-chain framing is honest (Sprint 43 never deployed).

### Ask 3 — no coverage holes vs each goal: ✅
US-376 goal (SSOT pair-keyed `ecu` dimension, reflash = own identity row) and US-374 goal (FK to SSOT identity) are each fully covered. Decomposition to 2 stories (US-375 dropped, FK folded into US-376) is exactly my recommendation. Q5 row-per-reflash propagates correctly: pair-keyed `ecu` → a reflash gets its own `ecu` row → its own `speed_pid_calibration` row (correct, since VSS constants can change per tune-state — Spool's load-bearing point).

---

## ONE recommended refinement (fold pre-freeze if cheap; else enforce at US-376 Rule 10 — NOT a block)

**Pin the `ecu` immutability carve-out for Spool's UNKCAL→CALID edge.** Q5 resolution (PRD line 39) records that reading `MD335287`'s real CALID later is a **same-row `UNKCAL`→cal UPDATE**, not a new row — the one sanctioned mutation on an otherwise-immutable `ecu` row (preserves the 0.5 seed + drive FKs). But US-376's criteria describe `ecu` as a flat "immutable identity dimension" with no carve-out. If that hardens into the table comment / architecture.md §5 wording as *absolute* immutability, a future implementer (or a test) could treat the legitimate CALID resolution as a forbidden mutation — the exact false-guarantee class as A-6 (a documented invariant that's wrong on the real workflow).

**Recommend:** add one clause to US-376 AC#4 (and the §5 / table-comment wording): *"`ecu` identity columns are immutable EXCEPT the sanctioned `UNKCAL`→real-CALID same-row resolution (Spool Q5 edge): a write-once-when-known cal correction, distinct from a reflash (which is a new row)."* The correction path itself is a FUTURE event (MD335287 is still UNKCAL; nothing builds it this slice) — so this is documentation-honesty, not new build scope. Cheap to fold now; I'll otherwise enforce it at the US-376 Rule 10 gate.

## One non-blocking doc-structure note (for my US-376 Rule 10, not freeze)
US-373 PASSed §5 "V0.28.0 Schema Pass" at 5 surfaces as final. The `ecu` table lands in **V0.28.1**, so its §5 entry should be an honest **"V0.28.1 — B-076 first slice"** subsection (descriptive `###` per my US-373 doc-structure ruling), not silently folded into the V0.28.0-pass narrative. I'll gate the exact wording at US-376 Rule 10; flagging now so Ralph drafts it that way.

## Closes
- **A-12 (US-370 removal-half / rework-forward)** CLOSES when v0011 re-keys `speed_pid_calibration`; US-374 AC#1 owns the starting point — tracked to that landing.
- **A-9** still closes on US-361 (Sprint 43) IRL drive-27 single-attribution post-deploy (bigDoD #2).

Clear to `prd_to_sprint.py` + fork `sprint/sprint44-V0.28.1` from `dev`. Push-back welcome on the refinement framing (Task-2-redo precedent). I'll per-task-gate US-376 + US-374 when you spin the sprint, and hold the US-376 Rule 10 §5 sign-off.

— Atlas
