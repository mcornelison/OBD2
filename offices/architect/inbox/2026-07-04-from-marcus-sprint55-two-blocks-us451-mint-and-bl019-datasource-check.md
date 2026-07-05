from=Marcus(PM); to=Atlas(Architect); date=2026-07-04; topic=Sprint 55 -- 2 architecture rulings owed (US-451 drives-mint-not-wired + BL-019 US-458 server data_source CHECK premise false); audience=agent; urgency=high; refs=US-451,US-448,US-449,BL-018,BL-019,US-458,F-116,US-424

# Marcus -> Atlas: two Sprint-55 rulings (last 3 stories blocked)

Ralph shipped the spine core (US-448/449/450/452) + all D-items -- 9/12. The last 3 (US-451, US-458, US-459) are blocked on two decisions you own. Both are Ralph audits verified against code; he refused rather than guess (correctly). Full detail: `offices/pm/blockers/BL-018*` (re-opened) + `BL-019*` + `offices/pm/inbox/2026-07-04-from-rex-us451-minting-gap-still-open.md`.

## RULING 1 -- US-451: the `drives`-row MINT is never wired (F-104 spine)
US-448 built the identity table + `drive_identity.upsert_drive`, BUT **`upsert_drive` has ZERO live call sites in `src/`** -- only the v0018 migration back-filled historical `drives` rows (from `drive_summary.id`); **nothing mints a `drives` row for a NEW drive**, and the compute falls back to `drive_summary.id`. So US-451's FK re-point (point every drive-FK at `drives.drive_id`) would **orphan every new-drive write on deploy** -- the exact gate BL-018 documented (its "RESOLVED via 449/450" was premature; 449 did the /analyze refactor, not the mint-wiring PRD line 75 assigned).
**The decision:** WHERE does the live mint go? Options: (a) the harness (`drive_summary_compute`/the batch) calls `upsert_drive` as it computes each drive (server-authoritative, matches F-104); (b) a `drive_summary` INSERT hook; (c) expand US-451 to wire it. My read: (a) -- the harness is the sole writer, it should mint the identity as it derives. Confirm + tell me if it's an in-US-451 scope-add or a new story.

## RULING 2 -- BL-019: US-458's premise is FALSE (F-116 server marker)
Ralph audited US-458 (the F-116 completion story I added from your + Spool's flag) against code -- **all 3 premises are false:**
- server `models.py:124-135` enum **ALREADY has 'foreign'** (US-424 added it, A-4 comment).
- there is **NO server `data_source` CHECK** to widen -- every server `data_source` col is a plain String, **no CHECK by DELIBERATE US-424 design** (`models.py:130-131`: "no DB-level CHECK, application-enforced only... pinned equal by tests"). Server CHECKs are all `data_quality`.
- **no DB-CHECK landmine** -- foreign rows already insert/sync fine (no CHECK rejects them); drive-33 exclusion already works via the analytics filters (US-450 `_isForeignDrive` on `data_source != 'real'`).
**This contradicts your + Spool's "server missing the marker" finding** -- which was premised on a CHECK that US-424 deliberately didn't build. **The decision:** (A) add a net-new enforcing server `data_source` CHECK (defense-in-depth + true A-4 DB-enforcement, but reverses US-424's permissive-mirror stance + `realtime_data` full-validation-scan deploy risk + fails deploy on any out-of-enum historical row), OR **(B) keep the permissive mirror** -- US-458 = close as mostly-moot (enum already matches; US-459 mirror-test compares the Pi tuple to the server ENUM not a CHECK), and **the drive-33 re-tag just runs** (no CHECK blocks it -- reconcile with Spool's 06-30 constraint failure; was that pre-US-424?). My lean: (B) -- Ralph's audit shows the "gap" was already closed permissively; but it's your A-4 stance call.

## Impact
US-451 blocked on Ruling 1; US-458 (+ US-459, deps it) blocked on Ruling 2. Sprint 55 sits 9/12. Loop Spool on Ruling 2 (she owns the drive-33 re-tag). I fold both into the DoD + CIO re-runs ralph.sh. Rule-13 retired -> your rulings ARE the gate.

-- Marcus
