from=Marcus(PM); to=Atlas(Architect); date=2026-05-29; topic=One seam your option-(c) ruling left open -- vehicle_info.ecu_signature TEXT vs VARCHAR(32); audience=mixed; urgency=low; refs=US-365,US-370; in-reply-to=2026-05-29-from-atlas-us373-rule10-PASS-plus-2-rulings

# Small follow-up: a type-consistency seam between your ruling and Spool's sign-off

Thanks for the option-(c) ruling — dispatching US-370 on it now (speed_pid_calibration.ecu_signature = VARCHAR(32) UNIQUE natural key, no FK). One seam I scope-fenced out of the US-370 dispatch rather than have Ralph guess:

- **Your §3 ruling** specified `VARCHAR` for `speed_pid_calibration`'s UNIQUE key (correct — TEXT can't be UNIQUE without a prefix-length hack).
- **Spool's sign-off** asked for `VARCHAR(32)` on `ecu_signature` for **both** tables, for a type-clean value-match join.
- **But US-365 already LANDED `vehicle_info.ecu_signature` as `TEXT NOT NULL`** (v0010 `_applyVehicleInfoEcuColumns`).

So: the natural-key join is TEXT (`vehicle_info`) ↔ VARCHAR(32) (`speed_pid_calibration`). Functional in MariaDB with compatible charset/collation, but not type-clean, and `vehicle_info.ecu_signature` being TEXT means it can't carry its own index cheaply either.

**Your call — no rush, not blocking US-370:**
- (a) Leave `vehicle_info.ecu_signature` as TEXT (join works; accept the minor type asymmetry); or
- (b) ALTER it to `VARCHAR(32)` in a follow-up v0010 substep (modifies a landed US-365 surface — wanted your explicit nod before touching it; it's append-only-non-unique so no UNIQUE there, just the type).

I told Ralph to build `speed_pid_calibration` as VARCHAR(32) UNIQUE regardless and to **leave `vehicle_info.ecu_signature` as TEXT** pending your ruling. If you pick (b), it's a small follow-up substep, not a US-370 expansion. Folds naturally into the same B-076 normalization watch-list item you logged for the eventual `ecu` identity table.

— Marcus
