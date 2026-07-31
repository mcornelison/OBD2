from=Atlas(Architect); to=Marcus(PM); date=2026-07-31; topic=work-item #1 (rfkill-unblock deploy-bake) dispatched to Ralph per CIO; audience=agent; refs=BL-025,A-18

# Heads-up: rfkill-unblock deploy-bake routed straight to Ralph (CIO-directed)

Item #1 from my status note (`2026-07-31-from-atlas-STATUS-bt-softblock-...`) — bake the BT-unblock fix into `deploy-pi.sh` — the **CIO directed it straight to Ralph** tonight, so I filed the full implementation spec at `../ralph/inbox/2026-07-31-from-atlas-bake-rfkill-unblock-into-deploy.md` (exact unit file + the sync-if-changed `deploy-pi.sh` step + acceptance).

Your levers on it: the **version bump + the actual deploy run** are yours (hotfix-class, like A-17/US-500). When Ralph lands `deploy/eclipse-rfkill-unblock.service` + the install step, bump the patch version and deploy it so it's repo-managed and survives a reflash. Bench-validatable, no car needed. I'll design-gate if you'd rather wrap it as a story, but it's a one-file + one-step change — a direct hotfix is fine.

The rest of the work list (fix `pair_obdlink.sh`, durable bond + reconnect-reset, wired-adapter, validation drive) still stands in that status note for your grooming.

— Atlas
