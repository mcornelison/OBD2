---
name: feedback-on-disk-journal-is-authority-not-live-tail
description: Live `journalctl -f` over SSH is unreliable across Pi power-cycle events — connection drops cleanly OR mid-event. Always read the on-disk journal after the Pi comes back. Learned 2026-05-21 (V0.27.16 drill).
metadata:
  type: feedback
---

When capturing sequencer / shutdown events on a Pi that's about to power off, **do not rely on `journalctl -f` over SSH as the authoritative evidence source**. Treat the live tail as a courtesy live-view. The on-disk journal is the source of truth.

**Why:**
2026-05-21 V0.27.16 drill. Across THREE Cycle-A power-down events (Test 1 key-off, Test 2 key-off, bench-unplug), I started `journalctl -u eclipse-powerwatch.service -f` over SSH in background to capture the sequencer's full trace live. **Every single one died with only 0-1 lines of useful capture before SSH dropped.** Sometimes the SSH connection dropped from a transient WiFi blip BEFORE the event started; sometimes it dropped DURING the event with only the LOST line captured before the rest of the smoothing/window/poweroff sequence flushed. The on-disk journal (`journalctl -u <svc> -b -1 --no-pager` after Pi rebooted) had the COMPLETE trail every time. Even with `-o ServerAliveInterval=5 -o ServerAliveCountMax=2` keepalive, the live tail failed.

Net effect: I spent time setting up live tails and reading their empty output files; I should have skipped the live capture entirely and just read the on-disk journal after-the-fact.

**How to apply:**
- Skip `journalctl -f` over SSH for capturing power-down sequences. Just wait for Pi to come back and run `journalctl -u <svc> -b -1 --no-pager`. The full event trail is preserved by systemd's persistent journal regardless of whether SSH was connected.
- Live tail is still useful for steady-state observation (no Pi power transitions involved). It's the cross-power-transition case where it fails.
- If you need real-time evidence (e.g., to confirm an event happened "right now"), use boot_id changes + uptime + recent journal entries as proxies after Pi reboots, not the live stream.
- The Pi's `journald` is configured persistent and preserves entries across reboots (`/var/log/journal/`). `journalctl -b -1` gives you the prior boot's full journal regardless of whether you had SSH open during it.

Related: [[feedback-verify-service-restart-after-deploy-before-drill]]
