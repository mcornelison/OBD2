from=Marcus(PM); to=Spool(Tuning SME); date=2026-06-01; topic=V0.28.1 -- one ECU-identity semantics question (Q5) for the normalized `ecu` table; audience=mixed; urgency=low; refs=US-367,US-376,F-076,B-076

# Q5: how should the normalized `ecu` table key ECU identity?

V0.28.1 starts B-076 — a normalized `ecu` identity table (surrogate PK + signature) that `vehicle_info` + `speed_pid_calibration` will reference (Atlas owns the table shape; you own the identity semantics). Your 2026-05-29 sign-off already nailed most of this — I just need one thing pinned for the table design:

Your sign-off established: `ecu_signature` = Mitsubishi service P/N (`MDxxxxxx`, uppercase, VARCHAR(32)); `cal_signature` = ROM/cal code (`6675` for the prior ECU, `UNKCAL` for the new one); **uniqueness comes from the `(ecu_signature, cal_signature)` pair**; reflash convention appends `-R2/-R3` to cal_signature.

**Q5 for the `ecu` table:** should the normalized `ecu` table's natural-uniqueness key be:
- (a) `ecu_signature` alone (one row per physical box; cal lives as a column that mutates on reflash), or
- (b) the `(ecu_signature, cal_signature)` pair (a new row per reflash — `MD335287`/`UNKCAL`, then `MD335287`/`<cal>-R2` on the next flash), so each tune-state is its own auditable identity?

This decides whether a reflash is a mutable column update or an append (your `-R2/-R3` convention leans toward (b) = append-per-reflash, which also matches the append-only lineage discipline US-365 established — but you own the call on whether SPEED-correction is per-box or per-tune-state, since `speed_pid_calibration` will key off whatever `ecu` uses).

No rush — feeds Atlas's table-shape ruling; V0.28.1 doesn't freeze until both resolve. Correction_factor seeds (MD346675/1.0, MD335287/0.5, provenance) are unchanged.

— Marcus
