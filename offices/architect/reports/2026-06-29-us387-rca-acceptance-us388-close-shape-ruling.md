# Atlas — US-387 RCA acceptance + US-388 close-mechanism shape ruling

**By:** Atlas (Architect) · **Date:** 2026-06-29 · **Tasked by:** CIO (Sprint-47 active block)
**Verdict: RCA ACCEPTED. Root-2 close mechanism IS architectural — shape ruled inline below so US-388 unblocks without a second round-trip.**
**RCA under review:** `docs/rca/2026-06-28-us387-drivedetector-close-signal-rca.md` (Rex)
**Refines:** my 2026-06-19 RCA ruling §3.2 (`reports/2026-06-19-a9-drivedetector-rca-ruling.md`)

---

## 1. RCA acceptance — root cause accepted (US-387 validationCriteria #2 gate)

I re-verified the load-bearing claims against the real code (verify-before-asserting), not Rex's word:

| RCA claim | Verified |
|---|---|
| Close is tick-driven ONLY — `processValue` is the sole evaluator | ✅ `detector.py:521`; under `self._lock` (`:535`); only caller = `event_router.py:407` (reading callback) |
| Connection-lost does NOT close a drive | ✅ `_handleConnectionLost` (`event_router.py:522-556`) = display + `_startReconnection` only; never touches the detector |
| No independent watchdog/timer thread | ✅ no `Thread`/`Timer` in detector; close depends entirely on a future tick |
| RPM-debounce needs a post-60s tick | ✅ `detector.py:665-672` (STOPPING branch) |
| ECU-silence backstop also tick-bound | ✅ `_checkEcuSilenceDriveEnd` (`:932-986`) runs only inside `processValue` (`:569`) |
| Single detector can't overlap (Root-1 needs 2 processes) | ✅ one `_currentSession` (`:218`); only `_endDrive` (`:790`) exits RUNNING |

**One-root hypothesis REFUTED → two independent roots** — confirmed and consistent with (sharper than) my 2026-06-19 split:
- **Root 2** = single-process state-machine; close path unreachable when ticks stop → **absorption** (fewer ids than drives). US-388's target.
- **Root 1** = two concurrent processes racing `drive_counter` → **overlap** (more, out-of-order ids). Mitigated out-of-band; closed by US-389/US-390.

The RCA's distinction (absorption *reduces* id count; overlap *increases* it; the live 29/18 is Root-2-dominated) is correct and well-argued. US-386's `conditionalOutcome` correctly did NOT fire — the substantive half reproduces in-process; overlap is provably out of unit scope by construction. **RCA accepted; the US-388 build-block lifts.**

## 2. Is the Root-2 fix architectural? YES (for the close mechanism) — so I rule the shape

Per US-388's `conditionalOutcome` ("route back to Atlas if architectural — detector re-entrancy / id-minting concurrency"). The "guaranteed close" behavior **must run off the tick path** (the whole defect is that ticks stop). That introduces a second writer to drive state → **detector re-entrancy** — exactly the named trigger. Rather than a separate ruling round, I rule the shape here (it refines my §3.2). Four binding constraints:

- **C-α (off-tick).** The close decision must NOT depend on a future `processValue` call. A close fires when the deadline elapses even if no further reading ever arrives. (Connection-lost / data-loop-dry is the natural *signal that ticks have stopped* — but see C-γ: it triggers an evaluation, it does not itself close.)
- **C-β (lock discipline — the re-entrancy guard).** Any off-tick close path MUST acquire the **existing** `self._lock` (`detector.py:285`) before reading/mutating `_currentSession`/`_driveState`. No new lock, no lock-free mutation. This is what makes the off-tick writer safe against an in-flight tick.
- **C-γ (deadline-anchored, NOT dropout-anchored — do not regress US-361).** The close fires only after `driveEndDurationSeconds` of genuine RPM-below / ECU-silence has elapsed — NOT on the connection-lost event itself. A transient mid-drive dropout that resumes within `MIN_INTER_DRIVE_SECONDS` must still re-attach via the US-361 `_isEcuSilenceContinuation` path, unchanged. (Verify by keeping the existing detector/lifecycle suite green — already in US-388 DoD.)
- **C-δ (fail-safe direction).** If forced to choose, prefer closing a still-open drive over leaving it open: an over-eager close is an honest extra boundary the server can reconcile; a missed close is silent absorption/corruption — the strictly worse failure. C-γ bounds this so normal resumes are not chopped.

**Mechanism is Ralph's engineering within these constraints** — reuse an existing periodic loop (orchestrator health-check / heartbeat) in preference to adding a new thread; only add a dedicated timer if no existing loop is suitable. **Document the chosen mechanism in the in-sprint `specs/architecture.md` DriveDetector update (C-4 design-gate DoD).**

## 3. The other two behaviors — accept as already-ruled (Ralph builds directly)

- **Mint `drive_id` only on entering `RUNNING`** — a resume after a missed close must reach `_startDrive`/`_openDriveId` and mint a fresh id, never silently continue a stale session. (Mechanical; already ruled §3.2(b).)
- **Gap-fence the latch** — idle/KOEO rows carry `NULL drive_id` so a stale-open cannot absorb a later key-on. (Mechanical; already ruled §3.2(c).)

(b)+(c) make the corruption impossible-by-construction; the C-α…δ guaranteed close makes the *boundary* reliable. Defense-in-depth, as in my original ruling.

## 4. Acceptance oracle + validation
- **Code oracle:** US-388 turns `test_backToBackMissedClose_*` + `test_keyOnAfterMissedClose_*` GREEN and removes their `xfail`; existing suites stay green (C-γ proof). US-390 then locks the file into the regression manifest.
- **True acceptance is the live IRL re-gate** (deploy-time, CIO-gated): short/back-to-back + key-on-after-missed-close + deploy-double-start. An off-tick close (esp. if it reuses the heartbeat loop) can only be fully validated live. A single clean drive remains insufficient.

## 5. Disposition
- **RCA ACCEPTED**; US-388 build-block lifts.
- **US-388 shape ruled inline** (§2 C-α…δ + §3) — no separate ruling round; Ralph may code.
- **A-9 stays OPEN (HIGH)** until the live IRL re-gate passes.
- Routed: acceptance → `offices/ralph/inbox/`; confirmation → Marcus. The remaining US-367 gate is **Spool's** (signature-naming + swap-instant), not my lane.

— Atlas
