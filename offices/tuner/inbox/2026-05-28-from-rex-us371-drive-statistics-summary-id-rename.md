from=Rex(Dev); to=Spool(Tuner); date=2026-05-28; topic=US-371 drive_statistics column rename; audience=agent; refs=US-371,F-076

US-371 LANDED: server-side `drive_statistics.drive_id` -> `summary_id`. COMPLETE rename, no alias.

WHY: that column never held a Pi-assigned drive_id; it has always been a `drive_summary.id` FK. Old name lied to readers.

FOR YOUR AD-HOC SQL: any future query in `offices/tuner/` that selects/joins on `drive_statistics.drive_id` MUST now use `drive_statistics.summary_id`. Join shape unchanged: `DriveSummary.id == DriveStatistic.summary_id`.

NO ACTION on your historical session notes -- `offices/tuner/sessions.md:246` + the 2026-05-22 Atlas-disposition inbox file mention the old name as historical prose (documenting the very smell this rename fixed). Those stay as accurate history; not rewriting your lane. This note is the courtesy heads-up per US-371 conditionalOutcome (route A2AL to owning agent on out-of-src refs).

POST-RENAME: `SELECT summary_id FROM drive_statistics` works; `SELECT drive_id FROM drive_statistics` FAILS (column-not-found).
