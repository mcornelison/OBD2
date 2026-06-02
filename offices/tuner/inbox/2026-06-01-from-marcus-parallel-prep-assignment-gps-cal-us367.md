from=Marcus(PM); to=Spool(Tuner SME); date=2026-06-01; topic=Parallel next-sprint prep — GPS-cal data + drive-27 protocol + US-367 grounding; audience=agent; refs=US-367,speed_pid_calibration

# Your parallel-work assignment: GPS-cal data + drive-27 protocol + US-367 timestamp

While Ralph runs V0.28.2, the team preps the next sprint. Yours (SME research,
non-coding):

1. **Finish the GPS-cal grounded data** you committed to source: 4G63 GST 5-speed
   top-gear + final-drive ratios + wheel/tire rolling circumference (you've got
   the Potenza 205/55R16 card started) → pin into `specs/grounded-knowledge.md`
   per PM Rule 7. These feed the future empirical SPEED factor (replaces the 0.5
   seed post-drive-27).
2. **Define the drive-27 capture protocol** — exactly what to log for the GPS
   cross-correlation (clock-skew handling, scalar-vs-curve gate you flagged), so
   the drive produces a ratifiable `empirical-gps-correlation-Drive-27` factor.
3. **Ground the US-367 prior-ECU install timestamp** — I derived earliest
   `realtime_data` = 2026-04-23 16:36:50 UTC (see `US-367.md`); confirm that vs
   the gsheet, and sign the prior-ECU (`MD346675`) window + the swap instant
   (~2026-05-22 18:30 UTC) so the ECU backfill is grounded when it grooms.

## Lane + protocol
`offices/tuner/` + `specs/` only — **not `src/`/`tests/`** (Ralph's lane).
Commit-immediately to your office (handbook §13 — this is why your edits keep
"floating"); I push + integrate. Output → notes to `offices/pm/inbox/`. SPEED
value stays 0.5 until the drive — no rush, this is prep. Prod is read-only via
`offices/pm/scripts/prod_db_query.sh`.

— Marcus
