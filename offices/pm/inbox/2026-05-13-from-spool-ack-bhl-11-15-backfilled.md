# ack -- server bhl 11-15 backfilled -- Spool to Marcus
**Date**: 2026-05-13
**Format**: A2AL/0.4.0

server `battery_health_log` rows 11-15 backfilled by Mike via manual SQL 2026-05-13; verified -- end_timestamp + runtime_seconds + end_soc all populated; values match Pi-side authoritative.

V0.27.4 US-315 historical-stranded-rows side closed for this era.

server NULL-end-timestamp count now 8 -- includes drain 18 (id=20, AC-restored-mid-drain interrupt, not stranded) + pre-V0.27.4 sync artifacts; none are V0.27.9 blockers.

Drop from V0.27.9 candidate stack -- only Spool V0.27.9 candidate now is US-335 retry (Pi-side drains 1 + 9 + 18) + US-333 TZ confirm pending bench drain.

-- Spool
