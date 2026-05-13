# US-330 shipped (I-030 startup_log prior_boot_clean regression) -- one residual: live journalctl confirmation

from: Rex (Ralph agent, Sprint 33 / US-330 session)
to: Marcus (PM)
re: US-330 closed `passes:true`; the live-Pi pre-flight in acceptance #1 was done as code archaeology (same pattern as US-326/327/328 this sprint) -- one CIO follow-up + one TD filed.

## What shipped

`src/pi/diagnostics/boot_reason.py` -- `detectBootReason` now retries the
`journalctl --list-boots` lookup (`LIST_BOOTS_RETRY_ATTEMPTS=3`,
`LIST_BOOTS_RETRY_SLEEP_SECONDS=2.0`, sleep DI'd via a `sleeper` kwarg) so a
transient subprocess failure doesn't permanently strand the `startup_log`
row at NULL `prior_boot_clean` / `prior_last_entry_ts`. Happy path is
unchanged (one call, zero backoff -- the retry cost is only ever paid on the
anomalous path). When every attempt fails it now logs a WARNING (the I-030
row was written *silently* -- no silent failures, per the V0.24.1 anti-pattern
lesson). The US-308 graceful-detection logic (tail-marker scan + V0.24.1
ladder `-g` probe) is untouched. New regression gate:
`tests/pi/diagnostics/test_boot_reason_v0276_graceful.py` (7 tests) -- feeds a
V0.27.6-flavour journalctl sequence (`--list-boots` `None` on the first call,
then the real listing) and asserts the writer recovers `prior_boot_clean=1`;
FAILS pre-fix. Plus a 1-line no-op-`sleeper` injection into the existing
`test_detectBootReason_journalctlUnavailable_*` test so the new retry backoff
doesn't make it block on real `time.sleep`.

Verification all green: `pytest tests/pi/diagnostics/ -m 'not slow'` (98
tests), `pytest tests/ -m 'not slow'` (exit 0, full fast suite), `ruff check`
on all 3 touched files, `sprint_lint.py` (0 errors -- the US-330 warn is just
the pre-feedback-population one and clears with this close).

## The pre-flight finding (code archaeology -- live `ssh chi-eclipse-01` is the CIO follow-up)

The PM forensic showed the V0.27.6 post-Drain-17 boot's `startup_log` row had
**both** `prior_boot_clean` AND `prior_last_entry_ts` empty. In
`writeStartupLog` that pair is NULL only when `report.priorBootClean is None`
AND `report.priorLastEntryTs is None`, which in `detectBootReason` is the
`priorEntry is None` branch -- reached when `journalctl --list-boots` returns
`None` (the `runJournalctl` failure sentinel: subprocess `TimeoutExpired` /
`FileNotFoundError` / `OSError`), or when the parsed listing has no
negative-idx boot. `journalctl` is on the service's PATH (`/usr/bin`), so it's
not `FileNotFoundError`; the most likely sentinel is `TimeoutExpired` -- the
10 s subprocess cap blown under boot-time I/O contention.

**Mapping to the I-030 hypotheses:**
- **Hypothesis C (ladder shutdown sequence breaks the graceful regex) -- RULED OUT.**
  C would surface as `prior_boot_clean=0` (the tail scan + ladder probe both
  miss) with `prior_last_entry_ts` *populated* (it comes from `--list-boots`,
  not the tail). The observed symptom is both NULL -- so the failure is
  upstream of graceful detection, in the `--list-boots` lookup itself.
- **Hypothesis A (V0.27.6 US-322 orphan-cleanup.timer) -- LEADING.** The
  V0.27.5 -> V0.27.6 delta that fits the regression cliff is precisely the new
  `orphan-cleanup.timer` (`Persistent=true` -> fires at boot to catch up the
  missed nightly 03:00 run) running `cleanup_orphan_realtime_data.py --execute`
  -- a DELETE against `data/obd.db` on the SD card -- concurrently with the
  launching orchestrator. SD-card I/O starvation -> `journalctl --list-boots`
  times out -> `None` -> (pre-fix) immediate NULL row. The V0.27.6 deploy
  also `enable --now`'d the timer, so it likely fired at the deploy AND at the
  next boot.
- **Hypothesis B (V0.27.6 deploy changed boot order) -- not supported by code;
  partially overlaps A.** The V0.27.6 deploy-pi.sh changes
  (`step_install_orphan_cleanup_unit`, `step_install_nm_wifi_powersave`) add no
  `Before=`/`After=` ordering that would move `eclipse-obd.service` earlier.
  (The wifi-powersave drop-in *could* let `network.target` be reached slightly
  sooner, which would start `eclipse-obd.service` sooner -- a weak B-flavoured
  contributor at most.)

The chosen fix (race-guard retry in `boot_reason.py`) is robust to A **and**
to any B-flavoured contributor, and it's the in-scope option
(`scope.filesToTouch` is `boot_reason.py`; the alternative -- throttle/reorder
the orphan-cleanup unit -- touches a deploy file). I considered the
unit-ordering approach (`IOSchedulingClass=idle` and/or
`After=eclipse-obd.service` on `orphan-cleanup.service`) and filed it as
**TD-051** (`offices/pm/tech_debt/TD-051-orphan-cleanup-io-priority.md`) --
complementary, non-urgent now that the race-guard absorbs the symptom.

## The one residual (CIO follow-up)

To **confirm** the trigger (and rule out the two less-likely alternatives the
symptom doesn't cleanly contradict -- journald in volatile mode, or a
`--list-boots` output-format change from a Pi rebuild), capture from
chi-eclipse-01 the next time it's reachable:

```
ls -la /var/log/journal/                          # persistent storage present?
journalctl --no-pager --list-boots | head -20     # does it now show prior boots? what format?
cat /etc/systemd/journald.conf.d/* 2>/dev/null    # the deploy/journald-persistent.conf drop-in
journalctl -u orphan-cleanup.service -n 30        # did it run at the post-Drain-17 boot, and how long?
journalctl --boot=-1 -n 100 --reverse | head -40  # the V0.24.1 ladder tail (US-308 sanity check)
```

If `/var/log/journal/` is missing or `journald.conf` is `Storage=volatile`,
the real fix is restoring persistent journald (a separate issue -- the
`step_install_journald_persistent` deploy step exists but something defeated
it); the US-330 retry doesn't help that case (but also does no harm -- a few
seconds of bounded boot latency once, plus the new loud WARNING surfaces it).
If `--list-boots` shows a format `parseListBoots` can't handle (Pi rebuilt
with newer systemd), that's a follow-up `parseListBoots` story -- happy to
take it once we have the actual output.

**Real-world validation gate** (per the story's invariant + groundingRefs):
Drain 18+ followed by a graceful boot on V0.27.7 -> the `startup_log` row has
`prior_boot_clean=1` + `prior_last_entry_ts` populated. That's the CIO drill
check; the synthetic gate (the 7-test file) is in place now.

## Backfill question (acceptance #4, optional)

Acceptance #4 ("backfill the empty row from the Drain 17 boot using
`journalctl --boot=-1` evidence") is your call -- it needs a SQL `UPDATE` on
the Pi's `startup_log` for that one row, which I can't run from here. If you
want it, it's a one-row `UPDATE` keyed on the `boot_id` from that boot, using
the `journalctl --boot=-1` tail/listing as the source for `prior_boot_clean`
(it was a clean V0.24.1 ladder shutdown -> 1) and `prior_last_entry_ts`. Low
value (one historical row) -- I'd skip it.

## Sprint state after US-330

US-326 / US-327 / US-328 / US-330 all `passes:true`. US-329 (S, P3 --
drive_counter, I-029) remains `passes:false`, deps met, no blocker -- it's the
last story in Sprint 33 / V0.27.7. Per the tester's 2026-05-12 DB-review note
there's an open question on US-329's framing ("compute-from-drive_summary"
vs CIO's "drop the server-side table") + the V0.28 server-schema-normalization
epic -- those are your calls before the next iteration picks up US-329.
Still open from earlier: BL-014 (the harness `.claude/commands` write gate
from US-318).
