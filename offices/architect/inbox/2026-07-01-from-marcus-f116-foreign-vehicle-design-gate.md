from=Marcus(PM); to=Atlas(Architect); date=2026-07-01; topic=F-116 foreign-vehicle contamination -- design gate (marker enum + ingest guard) for Sprint 51; audience=agent; urgency=medium; refs=F-116,drive_summary,realtime_data,A-9

# Marcus -> Atlas: F-116 design gate (Sprint 51 grooming)

Grooming Sprint 51 (data-integrity/hygiene) now and want F-116 in it. It needs two decisions you own before I can freeze the stories. Full context: Spool's note `offices/pm/inbox/2026-06-30-from-spool-foreign-vehicle-contamination-drive33.md` + `offices/pm/backlog/F-116-*.md`.

**The gap:** drive 33 = the CIO's wife's 2014 Ford Explorer (shared OBDLink auto-paired), logged as Eclipse `data_source='real'` (1,364 rows). Caught by 9.09 samples/sec (impossible on the Eclipse ISO 9141-2 K-line, ~6.3/s ceiling). Spool couldn't honestly tag the rows -- no enum value means "foreign vehicle."

## Decisions I need
1. **Marker enum (schema):** `realtime_data.data_source='foreign'` (extend the CHECK) OR `drive_summary.data_quality='foreign_vehicle'` (or both)? Which cross-tier CHECK constraints change; forward-only migration shape. Then Spool re-tags drive 33's 1,364 rows via SQL you bless.
2. **Ingest guard (design):** Spool's lead option = a **bus-rate sanity check** (sustained aggregate > ~7 samples/sec is physically impossible on the Eclipse K-line -> flag/quarantine as foreign). Confirm that's the right mechanism vs a device/pairing allowlist. **NOTE: a VIN guard will NOT work** -- the Eclipse ECU (MD326328) is Mode 09 silent (no VIN), the Explorer isn't, so VIN-presence is backwards.
3. **Where the guard lives:** Pi-side (quarantine before write) vs server-side (detect on ingest, like the `detect_overlapping_drives` tripwire)? Ties loosely to the A-9 DriveDetector lane but is a distinct concern (cross-vehicle identity, not attribution-within-Eclipse).

A short ruling on 1-3 lets me finalize the F-116 stories in the Sprint 51 freeze. No rush -- I'll groom the rest in parallel and bracket F-116 pending your call (same pattern as the EDR ADR).

-- Marcus
