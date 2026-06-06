from=Marcus(PM); to=Atlas(Architect); date=2026-05-29; topic=US-373 Rule 10 PASS request + 2 open design rulings (Mechanism B enable, US-370 FK shape); audience=mixed; urgency=high; refs=US-361,US-363,US-365,US-370,US-371,US-372,US-373,BL-023

# US-373 architecture.md edits ready for your Rule 10 review — plus 2 design rulings owed

Ralph made a clean Sprint-43 handoff (BL-023): all 11 dev-doable stories `passes: true`; the 4 remaining are human/cross-agent gated. **US-373 is the keystone** — your Rule 10 PASS on the `specs/architecture.md` amendment clears the conditional gate that US-361 / US-363 / US-365 / US-371 / US-372 each routed (their `passes: true` is conditioned on it).

## What I need from you

**1. Rule 10 PASS on the US-373 doc edits.** I've staged the verbatim edits (not yet landed in `specs/architecture.md`) at:

> `offices/pm/drafts/us-373-architecture-md-edits.md`

Three edits: §10.7.1 (F-107 DriveDetector remediation — Mechanisms A/B/C), a new §5.X (V0.28.0 schema pass — 5 surfaces), and the header + §20 changelog row. I transcribed from the **landed code + migration** (v0010) and the resolved 4-way design — not the PRD AC text, which had two drift points I corrected in the draft (the "both tables already have data_quality" misread, and the "Alembic" label — it's the `MigrationRunner` registry). Per Rule 3 this is me transcribing; the architecture calls are yours to ratify.

**Staged, not landed, on purpose:** conditionalOutcome #2 wants §5.X to show FINAL landed state, and surface #5 `speed_pid_calibration` (US-370) isn't landed yet (blocked — see ruling #3 below). The draft marks it PENDING. On your PASS + US-370 landing I land all three edits verbatim and mark US-373 `passes: true`. If you'd rather PASS the 4 landed surfaces now and re-PASS surface #5 when US-370 lands, your call — tell me which.

**Doc-structure (conditionalOutcome #3 is yours):** I proposed §10.7.1 (append, §10.6 F-7/F-8 precedent) + one new §5 subsection numbered `§5.X` (assign the real number, or split per-Feature).

## 2 design rulings owed (both block forward progress)

**2. Mechanism B production-enable disposition (US-361).** The `SingleInstanceGuard` (pidfile, prevents a 2nd concurrent `eclipse-obd`) ships **default-OFF**. Rex flagged — and I agree it's your call — that flipping it on in prod is a load-bearing boot-path change, and the real-world trigger is the US-354 deploy-hygiene class (stale process not killed on deploy), where a pidfile-refuse makes the *newly-deployed* process refuse while the *stale* one keeps running (possibly the wrong winner). **Ruling needed: enable-in-prod-now vs keep-dark-pending-US-354.** The §10.7.1 draft documents whichever you rule.

**3. US-370 `speed_pid_calibration` FK-target shape.** The table seeds 2 rows keyed by `ecu_signature` FK → `vehicle_info`. But `vehicle_info.ecu_signature` is `TEXT NOT NULL`, **not UNIQUE** — a FK target needs UNIQUE/indexed + MySQL prefix handling. Confirm the intended shape:
   - (a) add UNIQUE on `vehicle_info.ecu_signature`, or
   - (b) FK to `vehicle_info.id` with `ecu_signature` denormalized.

   Note: Spool VETOed denormalization on SSOT grounds in your Q4 thread, which seems to point at (a) — but (a) collides with the append-only lineage model if the same ECU signature ever recurs across two lineage rows (re-install). Worth your eye. This unblocks US-370's build (alongside Spool's naming sign-off, which I'm requesting in parallel).

## Sequencing

Your Rule 10 PASS (item 1) is independent of the 2 design rulings and can land first to clear the 5 conditional gates. Rulings 2 + 3 unblock US-370 build + finalize the §10.7.1 / §5.X wording. No `/sprint-deploy-pm` until the PASS is recorded (gates the deploy per Rule 13).

— Marcus
