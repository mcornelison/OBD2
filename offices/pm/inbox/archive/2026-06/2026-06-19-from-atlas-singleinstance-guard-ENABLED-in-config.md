from=Atlas(Architect); to=Marcus(PM); date=2026-06-19; topic=single-instance guard ENABLED in config.json (CIO-directed) -- deploy is yours; audience=mixed; refs=offices/architect/reports/2026-06-19-a9-drivedetector-rca-ruling.md

# Atlas → PM: I enabled the single-instance guard in config.json (CIO-directed). Deploy is yours.

**Heads-up — a config change I made directly, by explicit CIO direction** (CIO: "fix
config.json yourself, that's quickest vs Atlas→Marcus→Ralph; just do it, but inform
Marcus"). Logging it so you're not surprised by a config delta you didn't route.

## What I changed
`config.json` → added `pi.runtime.singleInstanceGuard`:
```json
"runtime": {
  "singleInstanceGuard": {
    "enabled": true,
    "lockPath": "/run/eclipse-obd/orchestrator.lock"
  }
}
```
This turns ON the F-107 Mechanism B pidfile guard that was built but shipped
`default-OFF` — the fix for the A-9 dual-attribution root (two concurrent
orchestrator processes). Full RCA: `reports/2026-06-19-a9-drivedetector-rca-ruling.md`.
Committed; this is the Rule-10 sign-off **actioned** in config, not just signed.

**Validated:** `python validate_config.py` → all pass; JSON valid; the orchestrator's
exact read path (`pi.runtime.singleInstanceGuard.enabled`) resolves `True`.

## What's STILL yours (I did not do these — out of my lane)
1. **The deploy.** The repo config is enabled; the *running Pi* won't pick it up until
   a deploy. **Condition C-1 (load-bearing):** the deploy MUST `systemctl stop` the
   orchestrator before starting the new one. With the guard ON, a deploy that
   double-starts will have the **new** process correctly *refused* until the old exits.
   Pair this with **US-354** (the deploy-didn't-restart-cleanly class). Fail-safe note:
   worst case is "new code waits for old to stop," never "two drives." lockPath is on
   tmpfs `/run` (cleared on reboot); stale locks are reclaimed via a liveness probe.
2. **The A-9 RCA sprint (US-386..389) still stands** for the OTHER root — Root 2, the
   stale-open-drive leak (unreliable close → stale `drive_id` latch). The guard does
   NOT fix that; it needs guaranteed-close + stamp-only-when-RUNNING + gap-fence. See
   the sprint-scope brief I filed alongside this
   (`2026-06-19-from-atlas-a9-rca-ruling-sprint-scope.md`).
3. **IRL re-gate** to re-close A-9: short/back-to-back + key-on-after-missed-close +
   **deploy-double-start** (now testable — prove the guard refuses the 2nd process).

## Lane note
Enabling a config flag is normally Ralph's/your surface, not mine — I'm on it only
because the CIO explicitly directed the shortcut this once. Everything downstream
(deploy, sprint dispatch, the Root-2 fix) is back in your lane. I owe the Rule-13
sign-off when you freeze the refined A-9 sprint.

— Atlas
