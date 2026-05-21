# V0.27.16 Deploy Did Not Restart eclipse-powerwatch or daemon-reload — Dead Code In Memory

**Date**: 2026-05-21
**From**: Argus (Tester/QA)
**To**: Marcus (PM)
**Severity**: HIGH (deploy-hygiene gap — every Pi-side deploy ships dead code until a manual reboot; chain-blocking precondition was caught at IRL drill setup, would have produced a false-negative validation if drilled cold)
**Component**: `deploy/deploy-pi.sh`

## Summary

When I started V0.27.16 IRL validation preconditions today (~11:30 CDT), I discovered the Pi was running **V0.27.15 code in memory** despite `.deploy-version` reporting V0.27.16 / `5837239`. The deploy wrote new files to disk and bumped `.deploy-version` but did **not** restart `eclipse-powerwatch.service` and did **not** run `systemctl daemon-reload`. The F-7 fix (Python module change) and F-8 fix (systemd unit file change) were both inert.

If I had proceeded to the in-car drill without catching this, **Test 2 (F-7 reproducer) would have failed** — and we'd have concluded the F-7 fix was bad when in fact the V0.27.15 buggy code was running. Same for US-345's CLEAN_COMPLETE evidence: the next clean shutdown's `boot-progress-finalize.service` would have been the old unit (no `Conflicts=shutdown.target`), ExecStop wouldn't fire, `startup_log.prior_boot_clean` would have stayed `0`, and US-345 would have looked unfixed.

I worked around it for this drill (`daemon-reload && reboot` on the bench before CIO moves the Pi to the car). The underlying deploy script needs fixing so future deploys don't booby-trap themselves.

## Evidence

State captured 2026-05-21 11:30-11:44 CDT on `chi-eclipse-01` (running V0.27.15 process):

```
.deploy-version mtime:                 2026-05-21 11:17:54 CDT
.deploy-version contents:              V0.27.16 / gitHash 5837239 / "F-7 + F-8 + V0.27.7 false-pass cluster redo"
__main__.py mtime (F-7 fix file):      2026-05-20 22:33:00 CDT  (V0.27.16 code on disk — level-based post-grace check at lines 32-261 verified present)
boot-progress-finalize.service:        Conflicts=shutdown.target present on disk at line 63 (F-8 fix verified)

eclipse-powerwatch.service status:
  Active: active (running) since Wed 2026-05-20 20:30:18 CDT; 15h ago
  Main PID: 734 (python)
  Invocation: e614246a8d4e4514bc5f111e4decd0d5
  CPU: 6min 29.842s

ps -o pid,lstart,cmd -p 734:
  PID 734  STARTED Wed May 20 20:35:41 2026
  CMD /home/mcornelison/obd2-venv/bin/python -m src.pi.power.power_watch

journalctl -u eclipse-powerwatch.service -b --no-pager | wc -l:
  1
journalctl -u eclipse-powerwatch.service -b --no-pager:
  May 20 20:30:18 Chi-Eclips-01 systemd[1]: Started eclipse-powerwatch.service - Eclipse OBD Phase-2 power-watch (bounded pre-shutdown pipeline).
```

Timeline:
- 2026-05-20 20:30:18 CDT — Pi rebooted; `eclipse-powerwatch.service` started with V0.27.15 code (last build before today's deploy).
- 2026-05-20 22:33 CDT — V0.27.16 `__main__.py` written to disk (first deploy of the day per Atlas's "second-of-two-deploys" memory hint).
- 2026-05-21 11:17:54 CDT — V0.27.16 `.deploy-version` written (second deploy of the day).
- 2026-05-21 11:44 CDT — I queried; `eclipse-powerwatch.service` still on PID 734 with the May 20 20:35 process start time. **Zero restarts since either deploy.**

Within this entire boot session (15h), `journalctl -u eclipse-powerwatch.service -b` shows exactly one event: the original systemd "Started" line. No restart cycles. The Python process loaded the V0.27.15 source files into memory at 20:35:41 CDT and has held them ever since.

The systemd unit files on disk also did not propagate into systemd's in-memory transaction logic — there was no `daemon-reload`, so the new `boot-progress-finalize.service` (with the F-8 `Conflicts=shutdown.target` directive) would only have been honored after manual reload or fresh boot.

## Impact

1. **Every Pi-side `deploy-pi.sh` run ships dead code until the next manual reboot.** Documented in the runsheet as a "deploy hazard" footnote in a different context (§6 recovery procedure) but not surfaced as a deploy-time gap.
2. **The IRL drill would have produced a false-negative validation if I hadn't caught this.** Test 2 would have re-reproduced the F-7 silent-5.5-min behavior — not because the fix is bad but because the fix wasn't loaded. We'd have concluded the chain-blocker isn't fixed and queued a Sprint 41 redo that didn't need to exist.
3. **US-345's CLEAN_COMPLETE evidence depends on the F-8 systemd unit being in systemd's *in-memory* transaction graph at shutdown time** — `daemon-reload` is mandatory for that, and deploy didn't run it. Same false-negative risk.
4. Two prior deploys touched the powerwatch unit and module in the V0.27 chain (V0.27.14 bricking-recovery deploy + V0.27.15 sequencer landing). They may have worked because the user / deploy script rebooted the Pi as part of those events for other reasons. This deploy didn't, and the gap surfaced.

## Recommended Action

Fix `deploy/deploy-pi.sh` to do, in this order, after files are copied + before bumping `.deploy-version`:

```bash
sudo systemctl daemon-reload
sudo systemctl restart eclipse-powerwatch.service eclipse-obd.service
# verify both come back active + emit their respective startup banners within N seconds; fail the deploy if either doesn't
```

Plus a post-restart verification step that asserts the new `eclipse-powerwatch` PID's process-start time is later than the deploy start, and the `boot-progress-finalize.service` unit file mtime in systemd's in-memory view matches the disk mtime. That gives deploy-time evidence the new code is actually live, not just on disk.

Optional belt-and-braces: have `deploy-pi.sh` also offer a `--reboot` flag for cases where a full power-cycle is wanted (cleanest, exercises F-8 + brings up Pi process tree fresh).

## What I Did to Unblock

- Ran `sudo systemctl daemon-reload && sudo reboot` on `chi-eclipse-01` before the IRL drill. This serves double-duty as US-345 evidence — first clean shutdown post-deploy with F-8 in-memory → next boot's `startup_log.prior_boot_clean` should flip to `1` + `last_stage=CLEAN_COMPLETE`. I'll verify after the Pi comes back up.
- Filing this issue so future deploys aren't booby-trapped.

## Notes

- This is **NOT** chain-blocking by itself once worked around per above. The V0.27.16 fixes are correct on disk (I verified the F-7 level-based post-grace check at `__main__.py:32-261` and the F-8 `Conflicts=shutdown.target` at `boot-progress-finalize.service:63`). The gap is in deploy hygiene, not in Ralph's or Atlas's fix work.
- Suggest folding into V0.27.17 if there is one, or V0.28 deploy-hygiene cluster otherwise. Mike's call.
- The runsheet's §1 precondition #34 ("expect the startup line `powerwatch service up (GPIO%d PLD SSOT trigger): ...`") is the canary for this class of bug — the line is absent when the service hasn't restarted post-deploy. If we make that precondition assertion-strict (fail-the-drill rather than informational), this class of false-negative is caught at preflight, not after-the-drive.

— Argus
