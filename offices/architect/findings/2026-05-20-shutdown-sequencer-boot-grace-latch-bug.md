# Finding F-7 — V0.27.15 ShutdownSequencer Boot-Grace Latch Defect

**Filed**: 2026-05-20 (Atlas, in-car live drill w/ CIO + Spool concurrent SME read)
**Severity**: Critical (chain-merge blocker)
**Watch-List entry**: A-7
**Status**: Bug reproduced on demand, fully bounded, fix surface is small
**Verdict authority**: Atlas (design gate per CIO 2026-05-18 boundary)

---

## Summary

V0.27.15's `eclipse-powerwatch` polling loop (`src/pi/power/power_watch/__main__.py:301-322`)
uses **edge-only** loss detection (`lost AND not prevLost`). When a PLD power-loss event
fires inside the 120 s boot-grace window AND the HAT latches GPIO6 LOW after the
transient resolves, `prevLost` is updated to `True` and the sequencer is **permanently
blind to the live LOW signal** for the remainder of the service lifetime — unless GPIO6
toggles HIGH again (which only happens if the HAT recovers external-power-detection,
e.g. under alternator load). In the chain-blocking failure mode this morning the HAT
did not recover, the Pi ran HAT battery dead, and crashed.

This is **not** a topology bug, **not** a sensing bug, **not** a HAT firmware bug.
It is a software state-machine defect in the polling loop, reproducible on the bench
and now reproduced in-car under direct CIO observation.

## Evidence

### Test 1 — control case (in-car, fresh boot, no transient during boot-grace)

In-car drill 2026-05-20 19:36:53 → 19:47:39 CDT. Captures preserved at
`offices/architect/findings/2026-05-20-evidence/test-1/`.

| Event | Wall-clock | Captured signal |
|---|---|---|
| Service started | 19:36:53 | journal |
| Boot-grace expires (T+120s) | 19:38:53 | (no event in window) |
| Mike key-off | 19:47:32.205 | GPIO6 `hi`→`lo` (gpio6_raw.log) |
| Sequencer fires | 19:47:32 (same second) | `"GPIO6 PLD => external power LOST -- entering bounded pre-shutdown window"` (pw_journal.log) |
| Pi powered off cleanly | ~19:47:39 | systemd shutdown.target |

**Verdict: Sequencer works correctly when boot-grace has expired and the first
post-boot-grace loss is a fresh edge.** This is the in-car equivalent of Bench Check A
+ B (2026-05-18), now also confirmed in-vehicle.

### Test 2 — replication of today's chain-blocking failure

In-car drill 2026-05-20 19:47:42 → 20:30:15 CDT. Captures preserved at
`offices/architect/findings/2026-05-20-evidence/test-2/`.

| Event | Wall-clock | Captured signal |
|---|---|---|
| Service started | 19:47:42 | journal |
| CIO brief engine crank (~5s, well inside boot-grace) | ~T+42s | GPIO6 `hi`→`lo` |
| Sequencer logs "ignoring" | 20:23:29 (T+42s monotonic) | `"PLD power-loss 42s into boot-grace (120s) -- ignoring"` |
| Boot-grace expires (T+120s monotonic) | ~T+120 | (no event — sequencer permanently latched) |
| Sequencer silent for ~5.5 min while GPIO6 stays `lo` | T+42..T+340 | gpio6_raw.log: 638 consecutive `lo` samples |
| VCELL drains 3.810 → 3.734 V | concurrent | sampled live via MAX17048 |
| Engine started + idled ~20s (CIO) | ~T+340 | (no event yet) |
| HAT recovers under alternator | ~T+340..T+400 | GPIO6 `lo`→`hi` (transition observed) |
| VCELL recovers to 4.204 V (charging) | concurrent | sampled live |
| Engine off, key off | ~T+728 | GPIO6 `hi`→`lo` |
| Sequencer fires | 20:30:07 | `"GPIO6 PLD => external power LOST -- entering bounded pre-shutdown window"` |
| Pi powered off cleanly | 20:30:15 | systemd shutdown.target |

**Verdict: Bug confirmed by direct observation. Recovery path also confirmed.**

### Today's earlier failure pattern (referenced by Spool's Finding C, 2026-05-20)

Twelve boots earlier in the day all classified `crashed_during_operation` — but see
**Finding F-8** (parallel) for why that classification number is partly inflated.
For the structural failure: today's 17:06:57 CDT power-loss event in boot
`61580bb2` was logged as `"PLD power-loss 100s into boot-grace (120s) -- ignoring"`,
then no subsequent sequencer activity for ~19 minutes until the HAT battery drained.
Identical signature to Test 2. The "100s into boot-grace" number comes from monotonic
time which pauses across suspend on `CLOCK_MONOTONIC`; the wall-clock-to-monotonic
divergence is a side puzzle (likely Pi bench-suspend before CIO moved it to car) but
**not the bug** — even if boot-grace logic accounted for wall time, the latch defect
would still bite any in-grace transient.

## Root cause (code citation)

`src/pi/power/power_watch/__main__.py:299-322`:

```python
# the SAME provider (one acquisition site, criterion #3), so a real
# loss confirms and a glitch aborts. Boot-grace is cheap insurance.
prevLost = provider.isPowerLost()                                   # line 301
while not stop.wait(timeout=pldPollSec):
    lost = provider.isPowerLost()
    if lost and not prevLost:                                       # line 304 -- EDGE-ONLY trigger
        graceElapsed = time.monotonic() - serviceStartMono
        if graceElapsed < bootGraceSec:
            logger.warning(
                "powerwatch: PLD power-loss %.0fs into boot-grace "
                "(%.0fs) -- ignoring", graceElapsed, bootGraceSec,
            )
        elif handleLock.acquire(blocking=False):
            try:
                logger.warning(
                    "powerwatch: GPIO%d PLD => external power LOST -- "
                    "entering bounded pre-shutdown window", pldGpioPin,
                )
                shutdownSequencer.handleOnBattery()
            finally:
                handleLock.release()
        else:
            logger.info("powerwatch: already handling -- ignoring")
    prevLost = lost                                                 # line 322 -- state advances UNCONDITIONALLY
```

**The defect**: line 322 updates `prevLost = lost` on every iteration. When `lost = True`
during boot-grace and is ignored at line 308, `prevLost` becomes `True`. The condition
at line 304 (`lost AND not prevLost`) is then permanently `False` for as long as `lost`
stays `True`. Once boot-grace expires, **the level-true state is silently ignored** —
the loop only re-arms if `lost` returns to `False` (GPIO6 → HIGH) and then back to `True`
(new HIGH→LOW edge). If the HAT latches LOW after the in-grace transient (which it
demonstrably does), the sequencer is silent until alternator recovery — which may
never happen.

The current code's comment on line 300 — *"a real loss confirms and a glitch aborts.
Boot-grace is cheap insurance"* — is correct in spirit but the implementation's edge-only
state-transition logic doesn't deliver on it. Boot-grace was intended as **time-bounded
silence**, not as **permanent silence after an in-grace event**.

## Fix sketch (small, surgical)

The fix is in the same polling loop. One viable shape:

```python
firedAlready = False
while not stop.wait(timeout=pldPollSec):
    lost = provider.isPowerLost()
    graceElapsed = time.monotonic() - serviceStartMono

    if graceElapsed < bootGraceSec:
        if lost and not prevLost:
            logger.warning(
                "powerwatch: PLD power-loss %.0fs into boot-grace "
                "(%.0fs) -- ignoring", graceElapsed, bootGraceSec,
            )
    elif lost and not firedAlready:
        if handleLock.acquire(blocking=False):
            try:
                logger.warning(
                    "powerwatch: GPIO%d PLD => external power LOST -- "
                    "entering bounded pre-shutdown window", pldGpioPin,
                )
                shutdownSequencer.handleOnBattery()
                firedAlready = True
            finally:
                handleLock.release()
    prevLost = lost
```

Key change: **post-boot-grace, fire on *level* not edge.** A `firedAlready` flag guards
against re-entry within the same sequencer cycle (since `handleOnBattery` is itself
state-tracked). The smoothing logic inside `handleOnBattery` remains the abort surface
for transient glitches that resolve mid-window.

Alternative: at the boot-grace transition (`graceElapsed >= bootGraceSec` for the first
time), reset `prevLost = False` so the next iteration's edge check re-triggers if the
state is still LOW. Either is acceptable; the level-based form is cleaner and matches
the *real* design intent ("if power is lost and we're past boot-grace, shut down").

**This change does not require any test re-baseline of the Bench A or Cycle-A behavior**
— both work because they happen post-boot-grace with HIGH→LOW edges. The new path only
adds correctness for the latched-LOW post-boot-grace case the current code mishandles.

## Bug bound

Reproducing the bug requires the conjunction of:
1. Service in boot-grace window (first 120 s after `eclipse-powerwatch.service` activation), AND
2. A PLD power-loss event during that window (engine crank transient is the canonical
   in-car trigger; bench-time HAT switchovers, USB-C unplug/replug, or relay bounces
   can also produce it), AND
3. HAT latches LOW after the transient and does not recover before key-off.

If any condition is absent — clean cold-start with no transient, sustained alternator
load that recovers the HAT before key-off, or anyone who happens to drive long enough
that boot-grace expires before they crank — the sequencer works correctly. Bench Check A,
Bench Check B, and the three morning Cycle-A drills all happened to dodge the failure
conjunction. Today's chain-blocking failure (Spool's Finding C) and Test 2 do not.

## Chain-merge impact

- **Sprint 39 / V0.27.15 architectural correctness on bench**: stands (Bench A + B
  + Test 1 + Test 2 phase 2 = four independent successes when conditions allow it).
- **`POWER_OFF_ON_HALT=1` Finding-B resolution**: unaffected.
- **SSOT `PowerSourceProvider` design + retired ladder lesson in `specs/architecture.md` §10.6**:
  unaffected.
- **F-1/F-2/F-3/F-4/F-6 spec resolution (plan T9)**: unaffected.
- **Chain merge candidate**: **HELD on this finding.** The structural failure pattern
  that Spool's Finding C surfaced has a single, identifiable, narrow root cause that
  the fix above closes.

After fix lands and is bench-validated (a deliberate in-grace transient followed by a
post-grace key-off must now fire the sequencer cleanly), and after one in-car
re-validation drive that exercises the cold-start-with-crank pattern Test 2 just used,
the chain can resume its unblock candidacy.

## Reproduction recipe (for Ralph / Tester)

Fastest path (bench):

1. Pi on wall power, eclipse-powerwatch service active and armed (GPIO6 = HIGH).
2. Unplug X1209 USB-C input briefly (~1-2s) within first 90s of service start. GPIO6
   goes LOW, journal logs `"PLD power-loss Xs into boot-grace (120s) -- ignoring"`.
3. Re-plug X1209 USB-C. If GPIO6 returns to HIGH within the boot-grace window, the
   bug **may** not trigger (depends on HAT re-arm timing). For deterministic
   reproduction: leave the USB-C unplugged so HAT stays LOW.
4. Wait until boot-grace expires (~120s from service start). GPIO6 still LOW; sequencer
   does NOT fire. Bug reproduced.
5. Touch GPIO6 LOW→HIGH→LOW with `gpiomon` blocked (or briefly plug the USB-C and unplug):
   sequencer should fire on the new edge. Confirms the edge dependency.

Captures in `2026-05-20-evidence/test-2/` are the in-car instance of this same recipe.

## Related findings

- **F-8 (parallel, today)**: `boot-progress-finalize.service` ExecStop never fires →
  every clean shutdown is mis-classified as `crashed_during_operation`. Does NOT
  block chain merge but does mean Spool's "12 boots crashed today" number is partly
  noise. See `2026-05-20-startup-log-marker-broken-empirical.md`.
- **Spool's Finding C (2026-05-20, inbox)**: This finding is the structural answer.
  Spool's hypothesis (b) (topology problem) was correctly ruled out by CIO's just-now
  multimeter-via-buck-observation; the underlying issue is the polling loop, not the
  wiring.
- **Watch-List A-4 (server schema divergence)**: unrelated, still open.
- **MEMORY [[ssot-design-pattern]]**: This finding is *not* an SSOT violation —
  PowerSourceProvider correctly remains the SSOT; the defect is downstream in the
  consumer's polling logic, not in the source of truth.

## Atlas process notes

- The fix decision (level vs edge) is design-gate territory; landing the patch is Ralph.
- Marcus orchestrates as a sprint contract under PM Rule 10 (load-bearing change to
  `src/pi/power/power_watch/` → `specs/architecture.md` §10.6 needs a same-sprint
  note documenting the latch-bug + fix).
- Tester adds the in-grace-transient-then-level-recovery test to the regression suite
  (test_systemd_parity already covers the orchestration; this is a new state-machine
  case).
- Spool's BL-018 tuning remains gated behind chain merge.
