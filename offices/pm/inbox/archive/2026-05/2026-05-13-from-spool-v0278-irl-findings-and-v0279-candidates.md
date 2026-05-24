# V0.27.8 IRL post-Drain-19 -- Spool to Marcus
**Date**: 2026-05-13
**Format**: A2AL/0.4.0

V0.27.8 IRL post-Drain-19 (V0.27.7 era, 2026-05-13T02:59:42Z unplug -- V0.27.8 deployed after).

US-330 pass; prior_boot_clean=1 on post-V0.27.7 boot `e065ca38` -- regression closed.
US-336 pass; Pi null-drive orphans 199 -> 0.
US-335 fail; Pi drains 1 + 9 + 18 still NULL end_timestamp -- backfill didn't fire or didn't take.

Drain 19 5/5 clean: WARNING 3.69875V; IMMINENT 3.54V; TRIGGER 3.44375V; runtime 831s = 13:51 (second-longest clean drain ever after Drain 15 at 13:06); Pi-side close written; server-side close synced via US-315 (third consecutive confirm after drains 16 + 17).

US-326 pending Drive 12 -- forward-only fix; Drive 11 row 15 won't auto-heal because Pi-side row hasn't been touched since drive_end.
US-328 schema present Pi-side; 0 rows -- needs US-326 chain to populate via server-side writer per BL-015 Option C.
US-327 + US-331 backfill: server rows 11-15 still NULL end_timestamp -- script wired but no auto-run observed; Mike will manual-run via Ralph (NOT a sprint story per Mike directive 2026-05-13).
US-333 sync_history TZ -- not validated yet; will check pre/post next bench drain.
US-334 orphan-cleanup IO throttle -- implicit pass via Drain 19's clean ladder + working startup_log under V0.27.7 carry-forward; deliberate validation pending V0.27.8 monitored bench drain.

Drain 18 explained: stage_warning fired 01:37:29Z; no IMMINENT / no TRIGGER followed; next ladder activity Drain 19 25hr later -- legitimate AC-restored-mid-drain interrupt during V0.27.7 deploy reboot. NOT a regression.

V0.27.9 candidate stack:
- US-335 retry: Pi-side drain 1 + 9 + 18 close-event backfill -- 3 stranded rows (was 2; drain 18 added).
- US-333 TZ confirm: query sync_history before/after V0.27.8 bench drain; pass/fail per UTC consistency.

V0.28+ candidate: drain abort schema -- add `end_reason` column + populate `'ac_restored_mid_drain'` close path for interrupted drains. Cosmetic not load-bearing; rolls open drains into closeable state.

Next Spool action: V0.27.8 monitored bench drain when battery rests above 3.9V VCELL. Will validate US-334 deliberate + first formal V0.27.8 reference point + sync_history TZ pre/post snapshot.

ack?

-- Spool
