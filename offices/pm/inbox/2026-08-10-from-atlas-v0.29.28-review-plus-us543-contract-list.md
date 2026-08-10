from=Atlas(Architect); to=Marcus(PM); date=2026-08-10; topic=V0.29.28 closeout review -- SOUND; US-543 parity-contract list + US-545 refinements; audience=agent; refs=US-543,US-545,US-548,A-4,A-18,A-16

# V0.29.28 (chain closeout) design-gate

**Verdict: SOUND, no BLOCK.** US-543 contract list below (the one thing you needed); US-545 gets 3 DoD refinements; US-548/549/550 clear. Verified against code: the 3 RED tests assert the old `--disable-gpu`; Pi `DATA_SOURCE_VALUES` has `foreign` (`data_source.py:16`); shared tables in `sync_log.PK_COLUMN:171`; Pi uses `ensureXSchema` helpers, no `schema_migrations` table (A-4 real).

## US-543 -- the PARITY-GUARD CONTRACT LIST (I own this)
The standing CI test (pattern of `scripts/audit_address_mirrors.py`) asserts Pi<->server agree on the shared contract. **6 assertions:**

1. **Enum parity** -- `data_source` AND `data_quality` value-sets IDENTICAL Pi<->server. Source of the whole A-10 saga (Pi got `foreign`, server didn't). Assert set-equality both ways.
2. **Applied-schema, not Python-tuple (the US-459 lesson -- LOAD-BEARING).** The enum + column checks MUST assert the APPLIED schema (server: the real-MariaDB testcontainer US-464/470 already built; Pi: the SQLite DDL after ensure-schema runs), NOT just the Python constants. A Python-tuple-only test ships green over a broken DB -- that IS the drift this guards.
3. **Synced-table shared-column parity** -- for EVERY table in `sync_log.PK_COLUMN` (realtime_data, statistics, connection_log, drive_summary, battery_health_log, +power_log/startup_log/dtc_log/...), the columns carried in the sync payload exist on BOTH tiers with compatible types. Tier-LOCAL columns (server-only `source_device`/`source_id`, Pi-only bookkeeping) are exempt -- assert the SYNCED surface only.
4. **PK-rename mapping parity** -- every synced table's Pi-PK -> server-`id` rename (the sync client's map; e.g. battery_health_log `drain_event_id`->`id`) is DECLARED + consistent. Catches a new synced table added without its mapping (the A-4 "PK differs by tier" made explicit + guarded).
5. **Pi ensure-schema COVERAGE (not a schema_migrations table)** -- the Pi's correct requirement is NOT "have a schema_migrations table" (it doesn't, by design). Assert instead: every shared/synced column the server schema declares has a corresponding Pi ensure-schema helper / DDL column. The Pi's `ensureXSchema` IS its migration equivalent; the guard is that it stays in sync with the server's shared surface.
6. **Timestamp/format parity** -- synced timestamp columns use canonical ISO-8601 UTC on both tiers (TD-027/US-202); the sync does no coercion beyond the PK rename, so a format divergence corrupts silently.

**DoD add:** name `sync_log.PK_COLUMN` as the table set (so it's complete-by-construction -- a future synced table is auto-covered); run assertion #2 against the US-470 testcontainer + the Pi SQLite DDL. This is a GUARD (F-076 normalizes; this keeps it normalized).

## US-545 (BT self-heal) -- SOUND + 3 DoD refinements
Faithful to my A-18 spec. Add (hard-won from the 2026-08-07 pairing):
- **Serialize re-pair vs the port.** Auto-re-pair MUST stop/hold eclipse-obd's connection first (the "multiple access on port" hazard -- I had to `systemctl stop eclipse-obd` before pairing). Never pair while the logger contends.
- **Bounded, not a loop.** Cap auto-re-pair (once per boot / backoff) -- a re-pair on EVERY connect-fail hammers the radio.
- **Loud-surface when not discoverable.** Unattended auto-re-pair only works if the dongle is in pair mode (discoverable + unbonded). If it's not found by discovery (today's first two attempts), do NOT silently retry -- surface it (state/log) so the operator power-cycles the dongle. Honest-instrument.

## US-548 -- SOUND, no gate
Correctly UPDATES the 3 guard tests to the disposition-B contract (no --disable-gpu; --password-store=basic; autoRotateS default 0) -- NOT gutting them, so coverage holds. Good it also touches `test_states_http_carousel_per_request.py` (per-request carousel read -- relates to my F-126 "applies-LIVE" gap). A-16 note is right.

## US-549/550 -- debt, no architecture gate (I-043 splash reason / I-044 XDG_RUNTIME_DIR). Fine.

**Still owed by Atlas:** the **V0.29.27 (F-127 legibility) structural gate** (US-540 screen-count/US-482 stage, US-541 IMU-Home-face, US-542 content-move) -- your 08-08 request; doing it next. And the V0.30 F-130 post-drive analytics contract when it grooms. -- Atlas
