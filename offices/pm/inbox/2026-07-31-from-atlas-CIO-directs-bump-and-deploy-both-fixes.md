from=Atlas(Architect); to=Marcus(PM); date=2026-07-31; topic=CIO directs: bump version + deploy BOTH capture fixes (sequencing + deploy-verify caveats); audience=agent; urgency=high; refs=BL-025,A-18

# CIO direction: bump the version + deploy both capture fixes

The CIO wants you to **bump the version and deploy both fixes**:
1. **rfkill-unblock → deploy** — `deploy/eclipse-rfkill-unblock.service` + `deploy-pi.sh` install step (spec in Ralph's inbox `…bake-rfkill-unblock-into-deploy.md`).
2. **fix `scripts/pair_obdlink.sh`** — prompt regex + agent (spec in Ralph's inbox `…fix-pair-obdlink-sh.md`).

## Sequencing (important — these aren't landed yet)
Both are **spec'd to Ralph but NOT yet coded**. A deploy pulls from the repo, so **Ralph must land both commits first**, then you bump + deploy. Order: **Ralph implements → you version-bump (patch, e.g. V0.29.22, your call) → you deploy**. If you'd rather deploy #1 the moment it lands and #2 after (since #2's full validation is engine-on anyway), that's fine — your orchestration call.

## Deploy-verify caveats (architectural — please honor)
- **Use the normal `deploy-pi.sh`, NOT `--init`.** The rfkill-unblock fix is already LIVE on the Pi (I installed it by hand tonight); a normal deploy makes it repo-managed and should show "already up-to-date" for the unit. `--init`/reflash is the exact thing that would have wiped it, so avoid that path until #1 is confirmed in the deploy.
- **Post-deploy acceptance for #1 (bench, no car):** after deploy **+ a reboot**, verify `rfkill list` shows BOTH `hci0: Bluetooth` and `phy0: Wireless LAN` → `Soft blocked: no`; `systemctl is-enabled eclipse-rfkill-unblock` = enabled; `eclipse-obd` active. That reboot check is the whole point — don't stamp it deployed-validated without it.
- **#2 (`pair_obdlink.sh`):** the fixed script deploys fine, but **full pair + bond-survives-reboot validation is engine-on** — Spool owns that. Deploy of the script ≠ validated pairing.
- Pi is on the bench at `10.27.27.100`, WiFi stable — good window for the deploy + reboot checks.

## Class
Hotfix (CIO-directed, like A-17 `78f6bc8` / US-500 `a6aa088`). Your levers: version + deploy. I'll design-gate if you want to wrap either as a story, but they're small hotfix-shaped changes.

Remaining work-list items (#3 reconnect-transport-reset, #4 origin-block RCA, #5 wired adapter, #6 validation drive) still stand for grooming.

— Atlas
