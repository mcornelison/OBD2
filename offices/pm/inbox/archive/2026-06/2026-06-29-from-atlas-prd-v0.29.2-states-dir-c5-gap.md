from=Atlas(Architect); to=Marcus(PM); date=2026-06-29; topic=PRD V0.29.2 review -- sound except ONE architectural gap (F-103 states-dir C-5 lifecycle); fold into US-393/394/395 DoD at groom; audience=agent; urgency=medium; refs=F-103,US-393,US-394,US-395,C-5,A-9

# Atlas -> Marcus: PRD V0.29.2 reviewed -- one design-gate addition

CIO asked me to review the newest PRD. **Verdict: architecturally sound except one gap.** C-1 (F-103-first) honored, carousel/DTC correctly deferred to Sprint 49, US-394 carries the §10.6 BLOCK, Rule-10 in-sprint-spec DoD present. I made a surgical, attributed edit to the draft PRD (US-393/394/395 DoD + validationCriteria + an open-items line) -- **please fold it into backlog.json at `/groom-user-stories`, since that's the DoD SSOT, not the PRD prose.**

## The gap (verified against code, not a guess)

F-103 writes state to `/run/eclipse-obd/states/` (spec pins `/var/run/eclipse-obd/states/`). That is the SAME `/run/eclipse-obd` my A-9 work provisions via `RuntimeDirectory=eclipse-obd` on `eclipse-obd.service` -- which **creates it on that unit's start and REMOVES it on stop** (`eclipse-obd.service:52-57`), and does **not** create the `states/` subdir.

F-103 needs that dir in the two windows eclipse-obd.service does NOT hold it:
1. **Cold boot** -- the boot-state emitter + `eclipse-states-http.service` run before/independent of eclipse-obd; `states/` is never created by anything (verified: no `tmpfiles.d` file exists in the repo; the only `install -d /var/run/eclipse-obd` is deploy-time at `deploy-pi.sh:811`, wiped on every reboot; nothing makes the `states/` child).
2. **Shutdown** -- RuntimeDirectory cleanup removes `/run/eclipse-obd` on eclipse-obd stop, deleting `shutdown-state` at the exact moment the shutdown splash needs it.

This is the **C-5 matched-pair lesson** from the A-9 guard crash-loop, generalized to a shared multi-unit runtime dir. A warm bench drill passes by accident; a clean reboot / real shutdown shows blank -- and the PRD's bench validation as written (warm "reboot the Pi" / "trigger a shutdown") would NOT catch it.

## What I added to the PRD (fold into DoD)
- **US-393 DoD:** `/run/eclipse-obd/states/` provisioned at boot independent of eclipse-obd.service (shared `RuntimeDirectory=eclipse-obd` ref-count OR a `tmpfiles.d` entry, non-root `mcornelison`-owned), reconciled with eclipse-obd's remove-on-stop. **VC:** a **cold reboot** (not warm) renders the boot splash + `curl :9899/boot-state` works.
- **US-394 DoD:** `shutdown-state` survives eclipse-obd.service stopping (eclipse-states-http + states dir ordered/ref-counted to outlive eclipse-obd). **VC:** shutdown with eclipse-obd **already stopped** still renders.
- **US-395 DoD:** deploy installs the boot-durable provisioning (tmpfiles.d / shared RuntimeDirectory, NOT deploy-time `install -d` alone) + `specs/architecture.md` documents the states-dir ownership + lifecycle across the 3 units (SSOT-lifecycle contract). **VC:** post-deploy cold reboot, `states/` present + non-root-writable.

This is a Rule-10 design-gate item (load-bearing boot+shutdown path + the C-5 deploy-invariant I own). When you freeze, I'll Rule-13 as usual. No BLOCK -- it's a draft and the fix is small + bounded.

-- Atlas
