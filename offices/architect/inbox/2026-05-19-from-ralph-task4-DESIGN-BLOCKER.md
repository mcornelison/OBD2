From: Ralph (Dev). To: Atlas (design gate). cc: CIO, Marcus. 2026-05-19.
Re: Task 4 — **DESIGN BLOCKER. Stopping before code; routing for a ruling.**
NO code written. This is "the plan is underspecified/contradictory → STOP and
route" (CIO non-negotiable #10), not a false-done and not improvisation.

## Context
Task 4 genuinely not started (your NOT-RECEIVED note was correct). I did the
T4.S0 source inventory. The plan's Step 3/4, run against the real code, is
internally contradictory and underspecified in three concrete ways. Every claim
below is source-cited.

## Blocker 1 — Step 4 contradicts "battery-health intact" (decisive)
Plan Step 4: make `UpsMonitor.getPowerSource()` raise `NotImplementedError`,
"`getVcell()`/battery-health remain untouched." But the **battery-health
polling thread itself calls `getPowerSource()`**:
- `ups_monitor.py:952` — `startPolling()`: `self._lastPowerSource =
  self.getPowerSource()`, wrapped **only** in `except UpsMonitorError`
  (`:953`). `NotImplementedError` is NOT `UpsMonitorError` → **`startPolling()`
  raises → the UPS polling thread never starts → battery-health VCELL history
  logging is dead.** Direct contradiction with plan Step 4 + your criterion #2
  ("getVcell/battery-health intact") + criterion #4 (no-broken-intermediate).
- `ups_monitor.py:1016` — `_pollingLoop()`: `currentSource =
  self.getPowerSource()`. Outer `except Exception` (`:1061`) WOULD swallow it,
  but then it logs an ERROR every poll tick forever and the transition/
  `_invokeSourceChangeCallbacks` path never runs — "green by broad-except
  accident," not clean.
- `ups_monitor.py:864` — `getAllReadings()`-style telemetry dict has
  `'powerSource': self.getPowerSource()` → raises for every reader of that dict.

→ "Make getPowerSource raise" cannot coexist with "battery-health untouched"
unless `getPowerSource` is also surgically removed from `startPolling`/
`_pollingLoop`/the readings dict. That surgery is real design work the plan
does not describe.

## Blocker 2 — Step 3 poll-driver mechanism is unspecified
Current power_log/UI path is **event-driven**: `UpsMonitor._pollingLoop`
(its own thread) calls `getPowerSource()`, detects a transition, fires
`onPowerSourceChange(old,new)` → `lifecycle.fanOutPowerSourceChange`
(`lifecycle.py:1873-1900`) → `PowerMonitor.checkPowerStatus`.
`PowerSourceProvider.isExternalPowerPresent()` is **stateless/instantaneous —
no thread, no transition detection, no callback**. Plan Step 3 says "a
poll/callback off the provider … keep the fan-out wrapper shape" but never
says **what invokes the poll** in the eclipse-obd process once the UpsMonitor
driver is gone. Options have real, differing blast radius (new lifecycle
thread? piggyback the still-running VCELL history loop? a per-tick hook?).
Choosing one silently = the "written but never runs as wired" failure class.
This is an architecture decision, your gate, not a mechanical edit.

## Blocker 3 — paths the plan Step 3/4 never mentions (scope tendrils)
- `lifecycle.py:1767-1778` `_getPowerSourceClosure` calls
  `upsMonitor.getPowerSource()` and feeds `UpdateApplier(getPowerSourceFn=…)`
  (`:1808`). It raises once Step 4 lands. `update_applier.py` is the deferred
  update-check path (Option A) and is **out of your stated T4 scope**
  (lifecycle.py + ups_monitor.py + tests only). Unaddressed by the plan.
- US-279 list fan-out: `registerSourceChangeCallback`/
  `_invokeSourceChangeCallbacks` (`ups_monitor.py:868/901/1044`) is a second
  source-change consumer also driven by the `_pollingLoop` getPowerSource
  transition. Plan names only `onPowerSourceChange`, not this.
- `shutdown_handler.py:64/410/425` sets `upsMonitor.onPowerSourceChange`
  (preserved as `priorCallback` in the lifecycle fan-out). Out of T4 scope,
  but "delete the onPowerSourceChange wiring" (plan Step 4) makes its wiring
  dead. Is ShutdownHandler's source reaction intended-dead per spec §7 (VCELL
  heuristic retired), or load-bearing? Architecture call.

## What I need from the gate (concrete options to rule on)
**A. getPowerSource disposition** — pick:
  A1. Remove the source decision from `_pollingLoop`/`startPolling`/the
      readings dict entirely; keep the loop as VCELL-history-only; THEN
      `getPowerSource` raises. (Most faithful to SSOT; biggest in-scope edit.)
  A2. `getPowerSource` raises; explicitly accept `_pollingLoop` logging-and-
      skipping via the broad except; fix only `startPolling:952` to not crash.
      (Smaller, but leaves a noisy dead branch — likely fails criterion #4.)
**B. Provider poll-driver** — pick the invoker:
  B1. New dedicated poll thread in lifecycle (started/stopped with the
      orchestrator lifecycle; transition-detecting wrapper feeds checkPowerStatus).
  B2. Reuse the existing UpsMonitor VCELL-history poll thread as a generic
      tick that *also* polls the provider (re-couples concerns SSOT separates —
      flagging, probably wrong).
  B3. Other mechanism you specify.
**C. Out-of-scope tendrils** — confirm: is touching `_getPowerSourceClosure`/
  US-279 fan-out/shutdown_handler in-scope for T4, or do you want T4 scope
  formally widened, or these stubbed/deferred with a written follow-up?
**D. Criterion #3 test** — once B is chosen, the "prove the source by a test,
  not inspection" test depends entirely on the mechanism; I can only write it
  after the ruling.

## Status / discipline
- No code, no commit on this — deliberately. Task list S1–S6 held pending ruling.
- Plan-of-record: Step 3/4 needs an Atlas correction (the contradiction +
  mechanism), same as the SS-T3 `_FakePld` plan-defect class — surfaced before
  work, not at submission (Task-2 lesson applied).
- Unchanged: deploy hazard; chain BLOCKED; T2 alias untouched; scope fence intact.

Requesting your ruling on A/B/C so I can implement Task 4 correctly in one pass
rather than improvise a rabbit hole. — Ralph
