from=Atlas(Architect); to=Ralph(Dev); date=2026-07-31; topic=Bake the radio-unblock fix into the deploy (CIO-directed, P0); audience=agent; refs=BL-025,A-17,A-18,deploy-pi.sh

# Task (CIO-directed): make the Bluetooth-unblock fix survive a clean deploy/reflash

## Why
The OBD-capture root cause was found live tonight: `systemd-rfkill` restores a **stale saved Bluetooth soft-block** (`/var/lib/systemd/rfkill/platform-107d50c000.serial:bluetooth = [1]`) on **every boot** → BT comes up soft-blocked → eclipse-obd can't use the dongle → 0 capture (this is the "dead since ~07-03" root). I fixed it **live on the Pi** with a boot-unblock service, verified persistent across 2 reboots. **But it's not in the repo yet** — a full `deploy-pi.sh --init` or reflash would lose it and BT would go dark again. Bake it in.

## 1. Add the unit file — `deploy/eclipse-rfkill-unblock.service` (exact content, this is what's live on the Pi):
```ini
[Unit]
Description=Unblock all rfkill radios at boot (counter stale systemd-rfkill BT soft-block)
After=systemd-rfkill.service bluetooth.service

[Service]
Type=oneshot
ExecStart=/usr/sbin/rfkill unblock all
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```
Add the standard project file header comment block above `[Unit]` per `specs/standards.md` (unit files carry a `#`-comment header in this repo — see the sibling `deploy/*.service`).

## 2. Install it in `deploy-pi.sh` — follow the existing sibling pattern
Add a `step_install_rfkill_unblock` function mirroring the **sync-if-changed** install steps already in the file (e.g. the `drain-forensics` / `orphan-cleanup` / `eclipse-powerwatch` unit-install steps: `cmp -s` guard → install to `/etc/systemd/system/` → `daemon-reload` on change → `systemctl enable --now`). Then call it in the main deploy sequence (near the other unit installs). DRY-RUN branch + real branch, same shape as the siblings. Enable with `--now` so it also takes effect on the deploy itself.

## 3. Clear the stale saved block on deploy (belt-and-suspenders)
In the same step, if a stale block exists, neutralize it so a fresh deploy doesn't inherit a blocked radio:
```bash
sudo rfkill unblock all
# optional: zero any saved bluetooth block so systemd-rfkill restores unblocked
for f in /var/lib/systemd/rfkill/*bluetooth*; do [ -e "$f" ] && echo 0 | sudo tee "$f" >/dev/null; done
```
The service already unblocks at boot, so this is just to avoid a one-boot window on the very first deploy.

## Acceptance (bench-validatable — no car needed)
1. `deploy/eclipse-rfkill-unblock.service` exists in the repo with a proper header.
2. A full `bash deploy/deploy-pi.sh` installs + enables it (idempotent; re-run = no-op / "already up-to-date").
3. After deploy **+ a reboot**: `rfkill list` shows **BOTH** `hci0: Bluetooth` and `phy0: Wireless LAN` → `Soft blocked: no`; `systemctl is-enabled eclipse-rfkill-unblock` = `enabled`; `systemctl is-active` = `active`.
4. `bluetoothctl show` → `Powered: yes`.

## Notes
- The service is ALREADY live + enabled on the Pi (`10.27.27.100`), so a deploy will find it present — the `cmp -s` guard should report no-change once the repo copy matches. Your job is to make it **repo-managed** so a reflash/`--init` re-installs it.
- Requires the `rfkill` binary (`/usr/sbin/rfkill`, package `rfkill` — standard on Raspberry Pi OS Trixie; add to `deploy` package preflight if you have one).
- This is a hotfix-class deploy change (CIO-directed, like the A-17 capture fix / US-500). Marcus owns the version bump + the actual deploy run.

— Atlas
