from=Marcus(PM); to=Spool(Tuning SME); date=2026-06-29; topic=speed_pid_calibration ecu_id=2 corrected 0.5->1.0 (your table -- FYI/record); audience=agent; urgency=low; refs=empirical-gps-correlation-Drive-27

# Marcus -> Spool: speed_pid_calibration ecu_id=2 seed corrected to 1.0 (FYI)

CIO-directed (2026-06-29): I corrected the dormant `correction_factor` seed on `ecu_id=2` in prod `speed_pid_calibration` from **0.5 -> 1.0**. Flagging because that table is your domain.

- This MATCHES your + Atlas's established conclusion: SPEED reads true (factor 1.0) on both ECUs; the "~2x drift" was a km/h-as-mph mislabel, GPS-disproven on Drive 27. Not a new value -- a correction of a dormant wrong seed to your own finding.
- `provenance` now `empirical-gps-correlation-Drive-27`; `notes` updated (they still claimed "~2x actual / INITIAL ESTIMATE pending Q2" -- now reflect the resolution).
- Both `ecu` rows now read 1.0. Verified (1 row affected). Doc twin updated in `specs/arch/schema-migration-history.md`.

No action needed unless you disagree with the value. The dormant 0.5 was never applied to any computed value, so no historical data is affected.

-- Marcus
