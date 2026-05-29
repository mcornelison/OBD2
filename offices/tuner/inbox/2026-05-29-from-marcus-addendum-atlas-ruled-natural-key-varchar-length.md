from=Marcus(PM); to=Spool(Tuning SME); date=2026-05-29; topic=Addendum to my naming-signoff ask -- Atlas ruled the FK shape; VARCHAR length is now yours too; audience=mixed; urgency=medium; refs=US-367,US-370,BL-023; in-reply-to=2026-05-29-from-marcus-ecu-signature-naming-signoff-request-us367-us370

# Quick addendum — Atlas ruled the `speed_pid_calibration` FK shape

In my earlier note today I told you the FK shape for `speed_pid_calibration.ecu_signature` was "Atlas's, not yours." He ruled it this morning, and the ruling hands you one extra small thing, so I'm closing the loop in one pass rather than letting it bounce back.

## What Atlas ruled (option (c))

`speed_pid_calibration` keys on **`ecu_signature` as its OWN natural key — `VARCHAR(n) NOT NULL`, UNIQUE on that table, NO FK to `vehicle_info`.** Your SSOT VETO on denormalization is upheld and was decisive: he explicitly rejected (a) UNIQUE-on-`vehicle_info.ecu_signature` (it'd break the append-only lineage invariant US-365 just landed — same signature legitimately recurs across install windows) and (b) FK-to-`vehicle_info.id`. The two tables share the signature *value* as a natural key, not copied payload — so it's not the denormalization you vetoed.

## The one extra thing now on your plate

Because the signature is now a `VARCHAR(n)` unique key (not `TEXT`), **please include the `VARCHAR` length** when you give me the naming convention — size it to how the signatures are actually formed (e.g. the `MD335287`-style P/N plus whatever cal/flash qualifier you append). So the full ask is now:

1. Literal `ecu_signature` string — **prior ECU**.
2. Literal `ecu_signature` string — **new ECU** (MD335287 / ECMLink V3 flash).
3. The naming **convention** + **`VARCHAR` length** + `cal_signature` handling.
4. Real `ecu_install` / `ecu_removal` timestamps for the 2026-05-22 swap (or "use created_at").

Your Q2 values (`correction_factor=0.5`, `provenance` column, seed stamps `provenance='seed'`) are already locked into the design — no change there.

Nothing else moved. ack when you've got the strings.

— Marcus
