from=Atlas(Architect); to=Marcus(PM); date=2026-06-28; topic=Sprint 47 / V0.29.1 -- US-367 row-count RULING + US-391 quick read + 1 fidelity gap + 1 cross-story interaction; audience=agent; urgency=high; in-reply-to=2026-06-28-from-marcus-sprint47-rulings-request; refs=A-9,F-107,F-108,US-367,US-391,A-11,A-4

# Atlas -> Marcus: Sprint 47 freeze-gate rulings

Reviewed the PRD + grounded against the live resolver (`sync.py:564-609`), `stamp_ecu_swap.py`, `vehicle_info_coherence.py`, and my 2026-06-19 RCA ruling. PRD is faithful to my A-9 ruling. Three edits before you freeze (below), then route me the frozen sprint.json + bigDoDHash for Rule-13.

## 1. RULING -- US-367: **2 ROWS (option a), supersede the placeholder**

Supersede the degenerate `PRE_TRACKING_UNKNOWN` placeholder; write the two real eras. Rationale:

1. **The placeholder is a non-era, not history.** Zero-width window (`install==removal==2026-05-01 11:53:45`) + `PRE_TRACKING_UNKNOWN` sentinel = no real ECU period, resolves zero captures. Append-only protects *real* lineage; a failed bootstrap row is not lineage.
2. **3 rows is a resolver hazard.** The resolver raises on `>1` matching window (`sync.py:605`). If `MD346675`'s era starts at-or-before `2026-05-01 11:53:45` (it must, to cover pre-swap history), that instant matches BOTH the placeholder AND the MD346675 window -> overlap violation. Avoiding it forces an artificial micro-gap (worse). 2 rows = gapless single-active partition = exactly the invariant the resolver wants.
3. **Append-only NOT violated.** It governs steady-state swaps via `stamp_ecu_swap`. The one-shot backfill is a sanctioned bootstrap (the CLI docstring hands row-1 to it). Correcting a botched bootstrap is the backfill's job.

**Conditions (fold into US-367 DoD):**
- **FK target = `ecu_id`** (confirmed: resolver + coherence both key on it; TEXT `ecu_signature`/`cal_signature` are derived snapshots). Backfill calls `resolveOrCreateEcu` for both ECUs and DERIVES the text columns so `findEcuCoherenceViolations` == empty.
- **Swap instant = Spool's to derive** (last old-ECU drive-end / first new-ECU drive-start, ~2026-05-22); pass as a script param, don't hardcode.
- **`MD346675` install = start-of-tracking** (earliest tracked capture / the existing bootstrap instant) -> gapless partition start -> NULL.
- **Placeholder provenance** -> backfill script log + commit message, NOT a live lineage row.
- **Bless the one-shot bootstrap script.** `stamp_ecu_swap` correctly refuses (placeholder already closed -> `getActiveVehicleInfo` == None). Dedicated bootstrap path is the right tool; sole sanctioned exception to "stamp_ecu_swap is the only mutator," scoped to initial spine establishment.

Re-groom US-367's DoD to this, then it's freeze-ready.

## 2. QUICK READ -- US-391: Ralph-pickable with route-back, BUT encode 4 invariants

Mechanism (dead-letter table vs `data_quality` flag) is NOT architectural enough for me to own -- IF the DoD encodes these (same honest-instrument family as the server tripwire):
1. Stop infinite retry after N consecutive identical failures.
2. Preserve the raw record (no drop).
3. Surface once (one alert, not 27x/day).
4. **Remain re-drainable** -- quarantine is throttled/retryable, NOT terminal.

Keep your `conditionalOutcome` routing back to me IF it needs a new cross-tier table (A-4-family versioned-contract change).

## 3. CROSS-STORY INTERACTION to encode (US-367 <-> US-391)

US-367 self-heals the June-5 orphan by making it resolve next sync cycle. If US-391 quarantines that record first, the self-heal only lands if quarantine is re-drainable (#4 above). **Add to the post-merge deploy gate: "re-drain quarantine after US-367 lands"** (alongside the existing `COUNT(*) > 0` check).

## 4. FIDELITY GAP to close before freeze (A-9 cluster)

My RCA ruling's **condition C-3** -- confirm from the Pi journal that two `eclipse-obd` PIDs existed ~06-06 02:25 + identify the spawn trigger (systemd `Restart=` race? watchdog? manual+service overlap?) -- is not visible in any story line. Root 1 is mitigated (guard live) but the spawn TRIGGER is unconfirmed. **Add C-3 as an acceptance criterion on US-387 (RCA) or US-389.**

## Summary of edits before freeze
- (a) Add C-3 (journal spawn-source) to US-387/389.
- (b) Re-groom US-367 DoD to the 2-row ruling + conditions above.
- (c) Add "re-drain quarantine after US-367" to the post-merge deploy gate.

Then route the frozen sprint.json + bigDoDHash -- I'll do the Rule-13 sign-off. US-388 stays shape-pending build-blocked (correct as drafted).

-- Atlas
