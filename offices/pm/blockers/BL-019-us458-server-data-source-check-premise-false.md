# BL-019 — US-458 premise is false: there is NO server data_source CHECK, and the server enum already has 'foreign'

- **Filed:** 2026-07-04 by Rex (Ralph, Agent 1)
- **Story:** US-458 "Complete F-116 server marker -- add data_source='foreign' CHECK" (Sprint 55 / V0.29.9, parent F-116)
- **Blocks:** US-458 (this story) + US-459 (mirror-consistency test, deps US-458 — same false premise)
- **Routes to:** Atlas (architectural decision) via Marcus (PM)
- **Class:** stale-premise + architectural-stance decision (not a code defect)

---

## TL;DR

US-458 asks for a "forward-only server migration [that] adds 'foreign' to the data_source **CHECK**" and asserts "server models.py:125 enum currently lacks 'foreign'" + a validation "INSERT foreign → **was CHECK-rejected pre-migration**." **All three premises are false against the actual code.** There is no server-side `data_source` CHECK to widen, the server enum already contains `'foreign'`, and foreign rows already insert/sync fine. The requested fix (add a net-new CHECK) would **reverse a deliberate, documented US-424 decision** and carries real deploy risk. That is an architecture call, not a Ralph scope call → filed rather than guessed (Refusal Rule 1 + CLAUDE.md role boundary; same discipline as BL-017).

---

## The audit (grounded against code)

**Premise 1 — "server models.py:125 enum currently lacks 'foreign'" → FALSE.**
`src/server/db/models.py:124-135` `DATA_SOURCE_VALUES = ('real','replay','physics_sim','fixture','foreign')`. `'foreign'` was added by **US-424** (line 134) with an A-4 mirror comment. The server enum tuple already matches the Pi SSOT.

**Premise 2 — "add 'foreign' to the data_source CHECK" → there IS no server data_source CHECK.**
- Every server `data_source` column is a plain `String(DATA_SOURCE_LENGTH)` with `server_default` and **no CHECK** (RealtimeData:176, Statistic:217, ConnectionLog:251, SyncLog:535, DtcLog:610, CalibrationSession:699, Profile:759, DriveSummary:1135/1236).
- Every migration that creates a `data_source` column declares it `VARCHAR(16) DEFAULT 'real'` with **no CHECK** (v0001 catch-up, v0002:70, v0004:166, v0005:133, v0018:99).
- The only server `CheckConstraint`s (models.py:1115/1198/1205/1306/1470) are all `data_quality`, NOT `data_source`.
- **models.py:130-131 documents this as intentional (US-424):** *"The server data_source column carries no DB-level CHECK (application-enforced only), so no server migration is needed to accept the value; the Pi and server tuples are pinned equal by tests/pi/data/test_data_source_foreign_marker.py (A-4, no-drift)."*

**Premise 3 — "the latent sync landmine" / "INSERT foreign → was CHECK-rejected pre-migration" → FALSE.**
Because there is no server CHECK, a `data_source='foreign'` row **already inserts and syncs fine** on the server today. There is no CHECK that rejects it → no landmine at the DB-CHECK level. The validation clause "was CHECK-rejected pre-migration" cannot be satisfied because it was never rejected.

**Tier reality:** the Pi *does* CHECK-enforce data_source (`data_source.py::DATA_SOURCE_COLUMN_DDL` includes `CHECK (...)`); the server does *not*. So the tiers are inconsistent in **enforcement**, but consistent in **enum membership** (both tuples have 'foreign'). Drive-33 exclusion already works via the analytics filters (US-450 `_isForeignDrive` on `data_source != 'real'`; `compare_drives.driveExclusionReason`) — it does not depend on a server CHECK.

---

## Why this needs an Atlas ruling (not a Ralph guess)

Building the requested CHECK is not a mechanical scope-fence call:

1. **It reverses a documented architectural decision.** US-424 deliberately made the server a *permissive mirror* ("no DB-level CHECK... no server migration is needed"). Adding a CHECK flips the server to *enforcing*. Reversing a documented design stance is architecture (CLAUDE.md: architecture → Atlas).
2. **Real deploy risk.** A net-new `CHECK` on populated production columns forces MariaDB to full-scan/validate every existing row — on `realtime_data` (the largest table) that is a slow, locking validation, and it **fails the deploy** if any historical row carries a data_source value outside the enum. The story author did not account for this (they believed a CHECK already existed).
3. **Legitimate design tension both ways.** A permissive mirror lets the Pi lead the enum without the server rejecting already-synced rows; an enforcing server gives defense-in-depth + A-4 both-tier consistency. Either is defensible → a decision, not a default.

---

## Options (for Atlas / PM)

- **Option A — Add the net-new server data_source CHECK (US-458 as an ADD, not a widen).**
  Build from `DATA_SOURCE_VALUES` (A-4 define-once), idempotent, INFORMATION_SCHEMA-probed, on realtime_data + statistics + connection_log (+ the data_source-carrying tables). US-459 mirror-test compares the Pi tuple to the server CHECK enum.
  *Pro:* true both-tier DB enforcement.
  *Con:* reverses US-424's permissive-mirror design; realtime_data full-validation scan + deploy-failure risk if any out-of-enum value exists; a server CHECK can reject a legitimately Pi-synced future value if the Pi enum ever leads the server.

- **Option B — No server CHECK; keep the permissive mirror (recommended).**
  Recognize the landmine premise is false: 'foreign' is already in the server enum tuple (US-424) and already accepted; drive-33 exclusion already works via analytics filters. Re-scope US-458 to "verified no server CHECK needed + documented" and re-scope US-459's mirror guard to assert the two **Python tuples** match (Pi `DATA_SOURCE_VALUES` == server `DATA_SOURCE_VALUES`) — the real A-4 anti-drift guard, which models.py:132 says is **already covered** by `tests/pi/data/test_data_source_foreign_marker.py`.
  *Pro:* honest, zero deploy risk, faithful to US-424.
  *Con:* US-458 delivers ~nothing net-new (the marker already landed on the server in US-424).

- **Option C — Application-level enforcement in the sync API.**
  Validate `data_source` against the enum in `src/server/api/sync.py` before insert (coerce/reject unknowns) instead of a DB CHECK. Enforcement without the DB-CHECK deploy risk / mirror brittleness.

**Rex's recommendation: Option B.** The stated landmine does not exist — US-424 already landed the 'foreign' value on the server enum, foreign rows already sync, and the A-4 tuple-mirror guard appears to already exist. If Atlas wants true DB enforcement, Option A/C should be a separately-scoped story with the `realtime_data` validation-scan deploy risk called out up front.

---

## What Ralph did / did NOT do

- **DID:** exhaustive source audit (models.py + all migrations + sync.py + analytics); confirmed no server data_source CHECK; confirmed the enum already has 'foreign'; wrote this blocker with options + recommendation.
- **Did NOT:** author any migration/CHECK (shipping a net-new CHECK that reverses a documented decision + risks a realtime_data deploy failure is not a scope-fence judgment call), and did NOT touch US-459's scope.

---

## Resolution path

Atlas rules A/B/C (routed via Marcus). On the ruling: if B → close US-458 as verified-no-op + point US-459 at the tuple-mirror guard (or confirm the existing test covers it). If A/C → re-groom US-458/US-459 with the deploy-risk + enforcement-point specified, and I execute the clean forward-only migration (or sync.py guard) + mirror test.
