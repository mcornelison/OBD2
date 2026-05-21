---
name: feedback-verify-service-restart-after-deploy-before-drill
description: Before any IRL drill, verify the affected service's process start time is AFTER the deploy time. Code on disk ≠ code in memory. Learned 2026-05-21 (V0.27.16 drill).
metadata:
  type: feedback
---

Before running any IRL drill on a fresh deploy, **verify the relevant service's running process started AFTER the deploy time** — code on disk does not mean code in memory.

**Why:**
2026-05-21 V0.27.16 drill setup. `.deploy-version` reported V0.27.16 / `5837239` deployed 11:17 CDT. F-7 fix file on disk verified at lines 32-261. F-8 systemd `Conflicts=shutdown.target` directive verified on disk. But `eclipse-powerwatch.service` PID 734 had started at 2026-05-20 20:35:41 CDT — **15h before the deploy**. `deploy-pi.sh` writes files and bumps `.deploy-version` but does NOT restart `eclipse-powerwatch` or run `systemctl daemon-reload`. The Pi was running V0.27.15 in memory. If I had drilled cold without checking, Test 2 would have re-reproduced the F-7 bug (because the buggy code was still running), and we'd have falsely concluded the fix was bad. Filed `pm/issues/2026-05-21-from-tester-v0.27.16-deploy-did-not-restart-powerwatch-or-daemon-reload.md`. Worked around with bench `daemon-reload && reboot` before the drill.

**How to apply:**
- Pre-drill check (add to runsheet §1 preconditions): for every service whose fix is being validated, compare `ps -o pid,lstart -p $(systemctl show -p MainPID <svc> --value)` against `.deploy-version` mtime. The process start time MUST be later than the deploy. If it isn't, the running code is stale and the drill will produce a false-negative.
- For systemd UNIT FILE changes (like F-8's `Conflicts=`), `daemon-reload` is needed for the new directive to enter systemd's in-memory transaction logic before the next shutdown.
- The runsheet §1 #34 INFO log check ("powerwatch service up (GPIO%d PLD SSOT trigger): ...") is a poor canary because production logs at WARNING+ filter the banner — easy to mistake "no banner" for "service didn't start" when it just means INFO is filtered. Use PID start time instead.
- This also catches the broader "deploy hygiene" class: anything that ships a file but doesn't restart the consumer is a latent false-negative source.

Related: [[feedback-tester-validate-deploy-fixes-irl-not-just-code]]
