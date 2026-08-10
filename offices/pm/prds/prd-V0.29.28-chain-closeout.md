---
sprint: 73
version: V0.29.28
status: draft
createdAt: 2026-08-10
createdBy: Marcus (PM)
selectedStories: [US-548, US-549, US-550, US-543, US-545]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion; forks from dev)
sprintJsonPath: offices/ralph/sprint.json
epics: E-001 (UI/UX Polish) + E-OPS (F-119/F-120 hygiene)
features: F-124 (kiosk), F-103 (splash), F-119 (CI/parity), F-120 (BT reliability)
theme: "V0.29 CHAIN CLOSEOUT + hardening -- the final push to /chain-validated. Retire the V0.29.26 deploy-gate RED tests (I-us536), clear the last Pi-display debt (I-043/044), and land the A-4 parity guard + A-18 BT self-heal so the chain closes HARDENED, not just green. Pi-off-friendly: all 5 build + unit-test without the Pi; deploy + validate when the Pi is on."
atlasReview: "PENDING (light). US-543 A-4 parity guard (Atlas owns the contract list) + US-545 A-18 BT self-heal are Atlas 2026-08-10 additions. US-548/549/550 are debt cleanup, no gate."
---

# PRD: V0.29.28 -- V0.29 chain closeout + hardening

| Field | Value |
|---|---|
| Version | V0.29.28 (patch on dev; the V0.29 closeout push) |
| Origin | CIO 2026-08-10: "push to close out this feature version." Clears the deploy-gate + last debt + Atlas's chain-hardening additions so V0.29 can land to main. |
| Stories | US-548/549/550 (debt) + US-543/545 (hardening) -- 5, all Pi-off-buildable |
| Deploy | from dev; deploy + validate when the Pi is back ON (currently off). US-551 (I-042 visual) is a CIO in-person check, tracked separately (not a Ralph story). |

## Goal

Close out the V0.29 chain cleanly and hardened. Three things stand between V0.29 and `/chain-validated` (V0.29 -> main, stuck at V0.28.2 since June): (1) the V0.29.26 deploy is gated on 3 RED tests (I-us536), (2) two Pi-display debts linger (I-043/044), (3) Atlas's chain-review flagged two hardening gaps (A-4 parity, A-18 BT self-heal) that should land before we call V0.29 done. This sprint clears all five.

## Stories (full DoD in backlog.json)

| Story | Prio | Tier | Size | Summary | Gate |
|---|---|---|---|---|---|
| US-548 | P1 | pi | S | Retire 3 US-536-fallout RED tests -- **the V0.29.26 deploy-gate** | none |
| US-549 | P2 | pi | S | I-043 shutdown-splash terminal reason observable | none |
| US-550 | P2 | pi | S | I-044 kiosk `XDG_RUNTIME_DIR` `%U`->real user (stop /run/user/0 errors) | none |
| US-543 | P2 | both | M | A-4 Pi<->server contract PARITY GUARD (standing CI test) | Atlas: contract list |
| US-545 | P2 | pi | M | A-18 OBD BT bond self-heal + boot verify | none |

## Sequencing / gates

- **US-548 first** -- it un-gates the V0.29.26 deploy (the 3 RED tests must be green before `/sprint-deploy-pm` runs). Everything else is independent.
- **US-543** -- Atlas owns the parity contract list (data_source/data_quality enums, shared column shapes, Pi schema_migrations equivalent); light gate.
- **Pi-off-friendly:** all 5 build + unit-test without the Pi. US-545's live BT-recovery leg validates on the Pi when it's back on.

## How this closes V0.29

1. This sprint + the in-flight V0.29.26 (Sprint 71, done) + V0.29.27 (F-127 legibility, groomed) are the remaining V0.29 code.
2. When the Pi is on: run full suite (green after US-548), `/sprint-deploy-pm` the accumulated V0.29 work, then the **movement drive** (Spool) validates A-9 + US-526 + capture.
3. `/sprint-validated` per sprint -> `/chain-validated` merges V0.29 -> main. **US-551 (I-042 visual)** is the CIO's in-person splash check, folded into `/sprint-validated`.

## After V0.29 -- V0.30 kickoff (features created, not this sprint)

- **F-129 Engine card (MAF)** -- V0.30 lead (unblocked, display-only). **F-130 post-drive review** (server analytics; Atlas contract; the on-ramp to E-003). **F-131 attitude card** (small states/imu roll+yaw). **V0.31 = E-003 Tuning Intelligence** (CIO 2026-08-10).

## Note

Design artifact for the V0.29 closeout (per PM Rule 4). US-543/545 are Atlas's 2026-08-10 backlog-review additions; US-548-550 groom the open I-* issues into the backlog.
