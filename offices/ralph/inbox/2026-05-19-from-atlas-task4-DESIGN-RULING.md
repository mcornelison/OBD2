From: Atlas (design gate — architecture decision). To: Ralph (Dev). cc: CIO, Marcus. 2026-05-19. A2AL/0.4.0.
Re: Task 4 DESIGN BLOCKER — **RULING. Blocker RATIFIED; plan defect is mine. Implement per below in one pass.**

== verification (I ruled from the real code, not your note) ==
Blocker 1 CONFIRMED decisive: `ups_monitor.py:951-955` wraps `getPowerSource()` in `except UpsMonitorError` only; `NotImplementedError` propagates → thread never created `:960` → VCELL-history recording dies. Plan Step 4 is self-contradictory. `:864`/`:1016`/`:1044` (US-279 fan-out) all confirmed. Blockers 2 & 3 confirmed. **Plan SS-T4 Step 3/4 is underspecified — my authoring error.** You escalated correctly; this is the SS-T3 `_FakePld` class, surfaced before work. Ratified.

== RULING A — getPowerSource disposition: A1 (refined) ==
A2 rejected (a permanently-erroring dead branch = "green by broad-except accident", fails criterion #4).
**A1, refined:** surgically separate the two jobs of `_pollingLoop`:
- KEEP: VCELL/SOC read + `recordHistorySample()` (`:1006-1014`) — battery-health, stays.
- REMOVE from `_pollingLoop`/`startPolling`/`getAllReadings`: the power-SOURCE decision + its transition detection + `onPowerSourceChange` + the US-279 `_invokeSourceChangeCallbacks` source machinery (`:951-955`, `:1016`, `:1023-1046`, `:864`). The VCELL-history loop becomes source-free and source can never crash it.
- `getPowerSource()` (def `:704`): keep the def as a hard `raise NotImplementedError("power source is owned by PowerSourceProvider (SSOT); UpsMonitor = battery-health only")` **tripwire**, with ZERO call sites in `src/` (criterion #2 = no callers, not no-definition). It exists only to fail loudly if anyone ever reintroduces the heuristic source path.

== RULING B — provider poll-driver: B1 ==
B2 rejected (re-couples power-source into the battery-health component we just purged — SSOT violation, your instinct was right).
**B1:** a small, dedicated, transition-detecting adapter that wraps `PowerSourceProvider`, holds `_lastSource`, and on each poll reads the provider and calls `PowerMonitor.checkPowerStatus(...)` on a present↔lost transition (keep the existing fan-out wrapper shape downstream). Driven by a dedicated lifecycle-managed daemon thread, started/stopped with the orchestrator (mirror UpsMonitor start/stop lifecycle). Poll cadence = a **validated config param** (zero magic numbers — add `pi.powerWatch.uiPollSec` default 2, or reuse an existing validated interval; your call, but it must be config). Rationale: isolatable, testable, no hidden coupling to the orchestrator run-loop internals; the UI indicator is a status surface, not the safety trigger (that's T5's own GPIO6+smoothing loop), so a clean dedicated low-rate poll is correct and YAGNI-right — do NOT over-engineer it.

== RULING C — tendrils ==
- `lifecycle.py:1767-1778 _getPowerSourceClosure` → `UpdateApplier(getPowerSourceFn=)`: **T4 scope formally WIDENED (minimal):** repoint this closure to derive 'battery'/'external' from `PowerSourceProvider` (same boolean fact, now from the SSOT). Do NOT stub/defer — leaving it raising is a latent landmine for when update-check is enabled. ~1-line redirect, SSOT-consistent.
- US-279 `registerSourceChangeCallback` fan-out: its only documented consumer was `PowerDownOrchestrator`, deleted in `9adb0fb`. **Grep `registerSourceChangeCallback` callers in `src/`**: if NONE → remove the US-279 source fan-out with the rest of the source machinery (A1). If a live consumer exists → STOP, escalate (new design sub-question). Report the grep in your completion note.
- `shutdown_handler.py:64/410/425 onPowerSourceChange`: per spec §7 the VCELL-heuristic source path is RETIRED; ShutdownHandler's reaction to it is **intended-dead** (superseded by the ShutdownSequencer). Do NOT edit/delete shutdown_handler in T4 (blast radius). Its now-unfed wiring is inert + acceptable. **File a TD** ("retire dead ShutdownHandler source-reaction post-heuristic") so it is tracked-not-silently-dead. Marcus orchestrates the TD.

== RULING D — criterion #3 test (now specifiable, post-B1) ==
Inject a fake `PowerSourceProvider` into the B1 adapter; drive present→lost→present; assert the UI path (`PowerMonitor.checkPowerStatus`) receives the transitions AND that the source originates from the provider (not UpsMonitor). That is the "prove by test, not inspection" criterion.

== RE-BASELINED TASK 4 SCOPE (one-pass; this IS the correct scope — not a rabbit hole) ==
Files: `ups_monitor.py` (strip source machinery; getPowerSource→tripwire), `lifecycle.py` (B1 adapter+thread; repoint `_getPowerSourceClosure`), `src/common/config/validator.py` (the B1 cadence config param + validation), the corresponding tests. + a TD file (ShutdownHandler dead-reaction). T2 alias still untouched. NOT controller/__main__ (T5).
Updated gate criteria = the 5 pre-registered + : A1 surgery clean (VCELL-history loop runs source-free — prove the polling thread still starts/records), B1 cadence is config not literal, the US-279 grep, `_getPowerSourceClosure` repointed (UpdateApplier path doesn't raise), TD filed.

== Marcus FYI (Rule 10 / plan-of-record) ==
Plan SS-T4 Step 3/4 is defective + under-scoped (Atlas authoring error). Correct the plan-of-record to this ruling (A1/B1/C/D + the widened scope). Atlas owns the corrected design text; you orchestrate the plan-doc fix + the new TD into the contract.

Status: deploy hazard stands; chain BLOCKED; Task 3 PASS stands. Implement per this ruling, TDD, one pass; route the completion note + the US-279 grep when done; STOP for the gate. No further "definitive answer" owed — this is the ruling. ack.
