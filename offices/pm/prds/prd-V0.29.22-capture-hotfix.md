---
sprint: 67
version: V0.29.22
status: draft
createdAt: 2026-07-31
createdBy: Marcus (PM)
selectedStories: [US-514, US-515]
forksFrom: hotfix/V0.29.22-capture-fixes (cut from dev @ 8e64bbf)
sprintJsonPath: offices/ralph/sprint.json
epic: E-OPS
feature: F-120 (OBDLink LX / Bluetooth connectivity reliability)
theme: BL-025 capture P0 durability — make the live rfkill-unblock fix repo-managed + fix pair_obdlink.sh. CIO-directed hotfix.
designSpecs: offices/architect/inbox/2026-07-31-from-atlas-STATUS-bt-softblock-rootcause-fixed-plus-open-work.md; implementation specs in offices/ralph/inbox/2026-07-31-from-atlas-{bake-rfkill-unblock-into-deploy,fix-pair-obdlink-sh}.md
atlasReview: "Both are Atlas-authored implementation specs (design already Atlas's); direct hotfix class per CIO. Atlas offered to design-gate if wrapped as stories — these ARE now stories. No new design decision beyond his specs."
---

# PRD: V0.29.22 — capture hotfix (rfkill-unblock deploy-bake + pair_obdlink fix)

| Field | Value |
|---|---|
| Version | V0.29.22 (hotfix branch `hotfix/V0.29.22-capture-fixes` off `dev`) |
| Origin | BL-025 breakthrough 2026-07-31: the capture P0 was a persistent BT rfkill soft-block. Fixed LIVE on the Pi; these two stories make it durable + repo-managed. CIO-directed. |
| Stories | US-514, US-515 (both **F-120**, both P0) |
| Deploy | PM bumps RELEASE_VERSION → V0.29.22, merges hotfix → dev, deploys normal `deploy-pi.sh` (**NOT** `--init`) + reboot-verify |

## Why this hotfix now
The rfkill-unblock fix is live on the Pi (Atlas installed by hand) but **not in the repo** — a reflash/`--init` would wipe it and capture would go dark again. And `pair_obdlink.sh` is broken on Trixie bluez (can't write a durable bond). These two close the durability gap so the capture fix survives deploys.

## Stories (full DoD/validationCriteria in `backlog.json`; implementation specs in Ralph's inbox)
| Story | Size | Summary |
|---|---|---|
| **US-514** | S | Bake `eclipse-rfkill-unblock.service` + a `deploy-pi.sh` install/enable step + clear stale rfkill block on deploy. Spec: `…bake-rfkill-unblock-into-deploy.md`. |
| **US-515** | S | Fix `pair_obdlink.sh` — Trixie bluez prompt regex (`[bluetoothctl]>`) + display-capable agent (`DisplayYesNo`) for a durable bond+trust. Spec: `…fix-pair-obdlink-sh.md`. |

## Landing order (for Ralph)
1. **US-514 first** (rfkill deploy-bake — the load-bearing reflash-proofing of the live capture fix).
2. **US-515** (pair_obdlink) second.

## Acceptance / deploy gate (PM)
- After Ralph lands both on the hotfix branch: PM bumps → V0.29.22 → merge → deploy → **reboot-verify** (`rfkill list` both `Soft blocked: no`; `eclipse-rfkill-unblock` enabled; `eclipse-obd` active).
- US-515 full pair + bond-survives-reboot validation is **engine-on (Spool)** — deploy of the script ≠ validated pairing.

## Not in this hotfix
- BL-025 #3 reconnect-transport-reset + #4 origin RCA → **V0.29.23** combined sprint (US-512/513).
- The full UI round-2 line → V0.29.23 (US-501..511).
