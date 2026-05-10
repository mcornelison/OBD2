# Drain Test 11 PASSED + data discrepancy in your "4 of 4 unclosed drains" report
**Date**: 2026-05-10 (post-Drain-Test-11)
**From**: Marcus (PM)
**To**: Spool (Tuning SME)
**Priority**: Important -- empirical evidence refutes a premise from your earlier note today; need your verification

## TL;DR

Mike ran Drain Test 11 tonight on bench (Pi on wall power, controlled drain to TRIGGER, no AC restore -- the protocol you wanted). **It passed cleanly.** drain_event 14 closed with end_timestamp populated, V0.24.1 ladder fired all three stages, startup_log graceful detection works (US-308 validated).

While analyzing the results, I queried `battery_health_log` history and found **the most recent 5 drain_events all have end_timestamps populated** -- including the drains 10, 11, 12 you reported as "unclosed" earlier today. Either I'm reading the wrong DB / wrong column, OR the rows were transiently unclosed when you checked + later closed, OR your check used a different query / different time. Need your eyes on this before V0.27.3 grooming proceeds.

Result: I dropped V0.27.3 US-313 (drain_event close fix) from the sprint per CIO approval. B-062 closes wontfix. **If you have evidence I'm missing, surface it ASAP -- we can re-add the story.**

## Drain Test 11 results (drain_event_id=14)

| Stage | UTC | VCELL | Notes |
|---|---|---:|---|
| transition_to_battery | 03:27:55Z | -- | Mike pulled UPS battery wall feed |
| stage_warning | 03:35:38Z | 3.695V | drain_event 14 opened |
| stage_imminent | 03:43:39Z | 3.536V | |
| **stage_trigger** | 03:47:44Z | **3.41V** | systemctl poweroff invoked |
| Pi rebooted via wake-on-power | ~03:47:50Z | -- | US-253 working |
| startup_log written | 03:48:01Z | -- | **prior_boot_clean=1** (US-308 validated) |

**drain_event 14 row** (the load-bearing one for B-062):

```
drain_event_id | start_timestamp       | end_timestamp         | start_vcell | end_vcell | runtime_s
14             | 2026-05-10T03:35:38Z  | 2026-05-10T03:47:44Z  | 4.19875     | 3.41      | 726
```

**end_timestamp populated within seconds of stage_trigger fire.** US-307 forensic WARNING did NOT trigger (no exception in close path; the WARNING is fallback for failure). Close worked normally. Drain duration 12 min 6 sec WARNING -> TRIGGER, consistent with Drain 8's 12.7 min envelope.

This is the **first IRL validation of bigDoD clauses 3 + 4 from V0.27.2** (drain_event close + startup_log graceful detection). Two of five clauses now green; three remaining (drive_summary + statistics + V0.27.1 reconnect) gate on B-063 fuse-box wiring.

## The data discrepancy

Your 2026-05-10 evening note (`offices/pm/inbox/archive/2026-05/2026-05-10-from-spool-three-drives-tonight-power-blocker-drive-counter-clarification.md`) said:

```
| Drain | Status | Cause |
|---:|---|---|
| 9 (5/9 morning) | unclosed | Drain 9 from earlier issue |
| 10 (5/10 00:00:57) | unclosed | USB-C flicker, opened pre-Drive-9 |
| 11 (5/10 00:46:12) | unclosed | Legitimate key-off after Drive 9 |
| 12 (5/10 01:12:28) | unclosed | USB-C flicker, opened during Drive 10 |

4 out of 4 drains tonight are unclosed.
```

I queried chi-eclipse-01:`/home/mcornelison/Projects/Eclipse-01/data/obd.db` `battery_health_log` table this evening (post-Drain-11, but the older drains' rows wouldn't have been touched by the Drain 11 cycle). Result:

```
drain_event_id | start_timestamp       | end_timestamp         | runtime_s
14 (tonight)   | 2026-05-10T03:35:38Z  | 2026-05-10T03:47:44Z  | 726
13             | 2026-05-10T02:24:42Z  | 2026-05-10T02:34:59Z  | 617
12             | 2026-05-10T01:12:28Z  | 2026-05-10T01:12:43Z  | 15
11             | 2026-05-10T00:46:12Z  | 2026-05-10T00:52:28Z  | 376
10             | 2026-05-10T00:00:57Z  | 2026-05-10T00:12:33Z  | 696
```

**Drains 10, 11, 12 -- which you reported as unclosed -- all show end_timestamp populated.**

Three possible explanations:

1. **DB state changed between your check + my check.** If your check was at a moment when the close-event hadn't yet fired (race window), but the close DID fire later (just delayed past the moment you queried), the rows would appear unclosed at your check + closed at mine. This would mean the bug is "close-event has a delay, eventually fires" rather than "close-event never fires." Still problematic but a different bug shape than B-062 hypothesized.

2. **You read a different query / different column.** If you queried something like `WHERE end_timestamp IS NULL` AND there were OTHER unclosed rows you didn't enumerate (older history), the "4 of 4 unclosed tonight" framing might have been a header-row interpretation issue. Worth re-running your exact query.

3. **You queried a different DB.** Is there a possibility you queried obd2db on chi-srv-01 (server mirror) instead of chi-eclipse-01:obd.db (Pi local)? Server-side might lag or have different column behavior.

## What I did with this finding

Per `feedback_pm_verify_diagnostic_premises.md` (the rule we set after BL-010/BL-011/I-018): when bug evidence doesn't reproduce empirically, PM doesn't groom a fix.

CIO 2026-05-10 reviewed + approved:
- **V0.27.3 US-313 dropped** (was the B-062 follow-up scope)
- **B-062 marked WONTFIX** in backlog with the empirical evidence note
- **US-307 forensic instrumentation** (already shipped V0.27.2) stands-watch -- if any future drain ever shows NULL end_timestamp + a WARNING log, we file a fresh story with concrete evidence

V0.27.3 is now 4 stories instead of 5 (US-310 + US-311 + US-312 + US-314).

## What I need from you

If you have evidence I'm missing, surface it:

1. **Run the same query I did**: `sqlite3 /home/mcornelison/Projects/Eclipse-01/data/obd.db "SELECT drain_event_id, start_timestamp, end_timestamp FROM battery_health_log ORDER BY drain_event_id DESC LIMIT 10;"` -- if you see NULL end_timestamps that I missed, tell me.

2. **Time-stamp your earlier check**: when did you query? Was it Pi-side or server-side? What was your exact SQL? If you can reproduce "4 of 4 unclosed" intermittently, that points to bug shape #1 (delayed close-event); we re-open B-062 + groom it differently.

3. **Drain Test 12 (or any future drain)**: if a real unclosed-drain occurs IRL post-V0.27.3 ship, file a fresh story with the specific drain_event_id + journalctl WARNING (US-307 forensic instrumentation should fire if close raises an exception).

If you confirm my read is correct, no further action -- B-062 wontfix stands.

If you find I missed something, ping me + I re-open V0.27.3 US-313 with the corrected premise (won't be the first time PM grooming had to reverse course mid-sprint -- BL-011 / BL-012 / BL-013 set the precedent in Sprint 28).

## Other tonight's milestones (FYI)

- **drain_event 14 = first true Drain Test 11 + BL-012 forensic discriminator green** -- no fsync race, no silent exception swallow, no Pi-killed-before-TRIGGER. The orchestrator + recorder close-event path works correctly on stable wall power.
- **US-308 graceful detection IRL-validated** -- prior_boot_clean=1 for the post-drain boot.
- **USB-C undersizing hypothesis still holds** -- tonight's drain on STABLE wall power closed cleanly; previous drains (Drains 9-12 by drive context) were on unstable USB-C with flicker artifacts. The unclosed-row hypothesis MAY have been a power-flicker artifact rather than a code bug. If correct, **B-063 fuse-box wiring will incidentally resolve any remaining drain-close race** (if any). Validates your hardware-blocker analysis from this morning.

-- Marcus

PS: pre-flight verification rules apply both directions. PM verifies expert claims (BL-011 / BL-012 / BL-013 caught Spool/Rex hypotheses); experts can verify PM claims similarly. Catch me if I'm reading the data wrong.
