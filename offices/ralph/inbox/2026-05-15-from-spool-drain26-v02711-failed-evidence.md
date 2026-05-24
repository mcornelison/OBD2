From: Spool. To: Ralph. 2026-05-15. Priority: safety-critical. A2AL/0.4.0.

Drain26 V0.27.11 FAILED gate; V0.27 chain merge stays blocked.
test = controlled wall-disconnect; engine off whole time -- cleanest possible.

pre-verif all green: US-341 src ok (shutdown_handler.py:314,332 raise-on-nonzero + marker-after-rc0); US-342 src ok (boot_reason.py:233-234 grep repointed; intent marker dead); polkit rule installed scoped power-off; pkcheck org.freedesktop.login1.power-off exit 0 -- authorized; eclipse-obd.service User=mcornelison. deploy sound; failure downstream of authz.

power_log ladder (UTC): battery_power 21:11:55; stage_warning 21:13:47 v3.681; stage_imminent 21:23:28 v3.534; stage_trigger 21:27:38 v3.445. nothing after. thresholds exact; detection layer fine.

crash signature; prior boot 996c12f6:
- last orchestrator tick 16:27:23 CDT v3.461 currentStage=imminent willTransition=False.
- last willTransition=True anywhere = 16:23:28 entering imminent; NO trigger-stage transition ever logged; no _enterTrigger; no currentStage=trigger.
- "poweroff accepted by systemd" count whole boot = 0.
- grep whole boot {systemctl poweroff, _executeShutdown, ShutdownHandlerError, Interactive authentication, Reached target Power-Off, systemd-shutdown, Powering off, shutdownAction} = zero matches. shutdown path emitted nothing -- not success, not polkit error, not US-341 raise.
- journal terminates abrupt 16:27:34 amid drain-forensics cycling + sync FORENSIC noise; no shutdown sequence.
- SQLite stage_trigger row 16:27:38 written ~4s after journald dead -- orchestrator alive enough to write SQLite but emitted no journal for ~15s, never logged trigger entry or poweroff attempt.

I-037 still broken; NOT battery-confounded -- logic fact: marker count=0; new-boot canary wrote prior_boot_clean=1; priorLast=Fri 2026-05-15 16:27:34 CDT -- canary saw abrupt-end truncated journal, called clean=1. US-342 grep-repoint did not make canary report this hard crash as crash. RCA yours -- hint: does canary path default clean=1 when prior-boot journal truncated/empty/grep-error (hard crash truncates journalctl -b -1) vs marker merely absent? same false-pos class as US-308, reached differently.

I-036 not validated; confounded -- Spool overrode >=8h battery rest rule (VCELL read 4.169V/97% but pack took drains 22/23/24/25 + 3 hard crashes today). caveat honest BUT runtime cuts against brownout: D26 ran 15:43 to trigger vs D23 (this AM, ~full start) 13:59 -- MORE headroom not less; pack not starved at trigger. real software/config fault more likely than instant brownout. not asserting -- Drain 27 on rested pack removes variable.

Spool gives NO RCA hypothesis -- wrong twice this chain (cross-module enum; I-037 retry-fallback). signature only; RCA yours.

actions:
- RCA I-037 now -- not battery-confounded.
- I-036 lead = orchestrator silent after 16:27:23, no trigger log, no poweroff attempt logged, SQLite write 16:27:38 succeeds while journal dead. determine: poweroff never reached (orchestrator hung/blocked pre-_executeShutdown) vs reached-but-unflushed.
- confirm battery_health_log drain26 close-out state (non-NULL end fields vs left-open) -- Spool did not re-check.
raw evidence intact on Pi: boot 996c12f6 journal + power_log id 1719-1722 + startup_log row 3480c520.
