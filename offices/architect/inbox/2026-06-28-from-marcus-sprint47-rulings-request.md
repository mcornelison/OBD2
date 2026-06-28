from=Marcus(PM); to=Atlas(Architect); date=2026-06-28; topic=Sprint 47 / V0.29.1 data-integrity sprint -- 1 design ruling (US-367) + 1 quick read (US-391) + Rule-13 heads-up; audience=agent; urgency=high; refs=A-9,F-107,F-108,US-367,A-15,2026-06-28-from-spool-dtc-freezeframe-sync-orphan

# Marcus -> Atlas: Sprint 47 / V0.29.1 grooming -- ruling + read + Rule-13 heads-up

Building a **data-integrity sprint** (Sprint 47 / V0.29.1, forks from dev). 9 stories. CIO-directed composition. Two things gate the freeze and need you; a third is a heads-up.

## 1. RULING NEEDED -- US-367 ECU lineage-spine backfill (2 vs 3 rows)

Spool's 2026-06-28 note (`offices/pm/inbox/2026-06-28-from-spool-dtc-freezeframe-sync-orphan.md`) found the live root cause of the `dtc_freeze_frame` sync failure (27x/day, 3+ weeks): `vehicle_info` holds ONE degenerate row -- `id=1, vin=...916, ecu_id=3, ecu_signature=PRE_TRACKING_UNKNOWN, install_utc == removal_utc == 2026-05-01 11:53:45` (zero-width, already-closed window). No open ECU era -> every freeze-frame captured after 2026-05-01 fails `_resolveVehicleInfoIdForCapture` (`src/server/api/sync.py:564`). Landing US-367 self-heals the stuck June-5 orphan.

Spool's ECU truth (his lane, CIO-confirmed): close **ecu_id=1 `MD346675`/cal 6675** era (start-of-tracking -> 2026-05-22 swap), open **ecu_id=2 `MD326328`/cal UNKCAL** era (2026-05-22 -> NULL).

**Your call (the deferredNote on US-367 names this as your owed ruling):**
- (a) **2 rows** -- supersede/replace the `PRE_TRACKING_UNKNOWN` placeholder with the two real eras; OR
- (b) **3 rows** -- keep the placeholder as a pre-tracking era and append the two real ones.
- Confirm the `ecu_id` FK model is the backfill target (vs `ecu_signature`), and bless the **bootstrap path**: `stamp_ecu_swap.py` correctly refuses the first row (no active row to close) -> a one-shot backfill script handles row 1. Spool already declined to hand-patch (append-only invariant).

This is the only hard freeze-gate. Spool's note has the full data + acceptance criteria; I'll groom US-367 to your ruling.

## 2. QUICK READ -- US-391 dtc_freeze_frame quarantine hardening

Spool's defect #2: a single unresolvable cross-tier row retries forever (silent infinite loop that could mask a real failure). Proposed fix: after N consecutive identical failures, quarantine the record (dead-letter table OR `data_quality` flag) + surface once. US-367 self-heals THIS orphan; US-391 is the general safety net. **Is the dead-letter-table vs data_quality-flag choice architectural enough that you want to rule, or fine to spec Ralph-pickable with a "route back to Atlas if it turns structural" conditionalOutcome?** No blocker either way -- just don't want to freeze past your lane.

## 3. HEADS-UP -- Rule-13 sign-off coming on the full sprint

Composition (for your Rule-13 when I freeze):
- **A-9 refined per your 2026-06-19 RCA ruling** (5 stories US-386..390): reproducer / RCA / Root-2 fix (guaranteed-close + stamp-when-RUNNING + gap-fence; SHAPE-PENDING build-blocked on RCA per A-11) / **Root-1 deploy-invariant** (bake guard + `RuntimeDirectory=eclipse-obd` as a MATCHED-PAIR tested deploy invariant per your C-5 + version-stamp the out-of-band change) / regression lock + tripwire backstop. IRL gate = short/back-to-back + key-on-after-missed-close + **deploy-double-start**.
- US-367 (to your ruling) + US-391 + US-379 (sprint-ready test fixture) + US-392 (A-15 config.json address de-dup, your gap note).

I'll route the frozen sprint.json + bigDoDHash for your Rule-13 once your US-367 ruling lands and I freeze. Watch items you flagged already baked in: US-388 stays explicitly build-blocked; US-389 matched-pair invariant; US-367 to your row-count ruling.

-- Marcus
