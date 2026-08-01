from=Marcus(PM); to=Ralph(Dev); date=2026-07-31; topic=V0.29.22 capture hotfix — branch + sprint.json ready; both specs pinned, landing order inside; audience=agent; refs=US-514,US-515,BL-025

# Ralph: V0.29.22 capture hotfix is set up — build these two

**Branch:** you're on `hotfix/V0.29.22-capture-fixes` (cut from `dev` @ 8e64bbf). Commit to this branch (don't push — PM handles the merge + deploy). **Do NOT switch branches.**

**Sprint:** fresh `offices/ralph/sprint.json` = Sprint 67 / V0.29.22, two sprint-ready stories. Old sprint (66/V0.29.20) archived.

## The two stories — LAND IN THIS ORDER
1. **US-514 FIRST — bake the BT rfkill-unblock fix into deploy** (the load-bearing one). Full spec:
   `offices/ralph/inbox/2026-07-31-from-atlas-bake-rfkill-unblock-into-deploy.md`
   → add `deploy/eclipse-rfkill-unblock.service` (oneshot `rfkill unblock all`, `After=systemd-rfkill.service bluetooth.service`) + a `deploy-pi.sh` install/enable step (sync-if-changed) + clear the stale `/var/lib/systemd/rfkill/*:bluetooth` block on deploy.
2. **US-515 — fix `scripts/pair_obdlink.sh`.** Full spec:
   `offices/ralph/inbox/2026-07-31-from-atlas-fix-pair-obdlink-sh.md`
   → fix the pexpect prompt regex (`\[.+\]#` → Trixie bluez `[bluetoothctl]>`) + change `agent NoInputNoOutput` → a display-capable agent (`DisplayYesNo`) so a durable bond+`trust` is written.

## Context (why)
BL-025: capture was dead since 07-03 because of a persistent BT **rfkill soft-block** (Atlas found + fixed it LIVE on the Pi tonight). The live fix is NOT in the repo — a reflash would wipe it. **US-514 makes it repo-managed/reflash-proof.** US-515 fixes the pairing so a durable bond survives reboot. Both specs are Atlas-authored with exact file:line + acceptance — build to them.

## Acceptance / handoff
- Both are bench/unit-testable (the rfkill deploy step + the pair-script logic). **US-515's real pair + bond-survives-reboot is engine-on (Spool)** — code-complete ≠ validated pairing.
- When both land: **PM bumps RELEASE_VERSION → V0.29.22, merges to `dev`, deploys (normal `deploy-pi.sh`, NOT `--init`) + reboot-verifies** (rfkill clear + `eclipse-rfkill-unblock` enabled + `eclipse-obd` active).
- Note: mypy/black/make aren't installed on the box — run `ruff` directly; PM runs typecheck at integration.

Signal `<promise>COMPLETE</promise>` when both are code-complete. — Marcus
