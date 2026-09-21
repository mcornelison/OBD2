# Shutdown Orchestration — design

**Status:** approved in design, not yet built · **Owner:** Atlas (Architect) ·
**Ratified by:** the CIO, 2026-09-20 · **Ticket:** ARCH-035
**Relationship to `specs/architecture.md`:** this design changes shutdown behaviour, so the
power-watch section of `architecture.md` must be updated **in the same sprint that builds it**
(PM Rule 10 design-gate DoD). This file is the design; `architecture.md` remains the
system-of-record description. Neither is superseded until the build lands.

---

## 1. Why this exists

The Pi has never had an orchestrator. It has a **sequencer** — a fixed pipeline that runs
whether or not the work it is protecting has finished, and which no subsystem can answer.
Three consequences, all observed:

- **Nothing can say "not yet".** Sync is interrupted mid-transfer with no way to object.
- **Nothing records why.** After a failed shutdown the next boot reads `RUNNING` and
  nothing else — not who was busy, not how long, not what was lost.
- **Subsystems work against each other.** The shutdown drain pushes "until the backlog is
  empty" while capture is *still writing*, so it chases a moving target.

🔴 **The single fact that frames this whole design:**

    pack, all project software stopped   762 s   (battery_health_log row 42, run to cutoff)
    pack, our software running          0.49 s   (2026-09-20 wall-power cut, VCELL 3.6787)

**Same pack, same voltage band.** 3.6787 V is a voltage this pack demonstrably runs at for
*minutes* on its way down to its 3.4712 V cutoff. **0.49 s is therefore not a power budget.
It is a symptom of a software defect**, and this design must not be built around it.

🔴 **RULE — derive every budget from a MEASURED CAPABILITY, never from an observed failure.**
An earlier draft of this design sized the shutdown budget from the 0.49 s. That would have
written the bug into the architecture as a requirement: a system designed to shut down in
under a second because that is "all we have". The capability is 762 s.

## 2. Two modes, one protocol

| | **NEGOTIATE** (power available) | **NEGOTIATE** (on battery) |
|---|---|---|
| Veto | waits | waits |
| Ends on | subsystems done | **reserve reached** (§5) |
| Splash | plays | plays *if* reserve not reached |

There is **one protocol and one code path**. The modes differ only in whether a voltage
reserve is applying pressure. A user-initiated shutdown on wall power takes the identical
path — deliberately, so the path is exercised constantly and cannot rot unused.

## 3. The subsystem contract

Every participant implements exactly three methods:

```python
readyToShutdown() -> tuple[bool, str]
    # Asked repeatedly. The reason string is logged VERBATIM on every NO.

prepareForShutdown() -> None
    # Called once, when the orchestrator commits. Do your finishing work.

abandon() -> None
    # Called when the reserve is reached. Stop NOW. Leave durable state.
```

### The gates — these are enforceable rules, not guidance

1. 🔴 **`abandon()` MUST leave a consistent on-disk state.** A subsystem that cannot be
   interrupted safely **does not get a vote** — it is shed. This rule is what makes granting
   a veto risk-free: worst case the reserve is reached, everyone abandons, and the machine is
   still consistent.
2. 🔴 **A NO MUST carry a reason, and the reason is written to the durable shutdown log**
   (§6), not only to the journal.
3. **No subsystem may veto on state it does not own.** Sync may veto on *"transfer in
   flight"*. It may not veto on *"I might have work later"*.
4. **The orchestrator never re-asks a subsystem it has already shed.** One direction, no
   re-entry.
5. **Every vote, every re-ask and every override lands in the stage machine**, so the next
   boot can say who held the shutdown up and for how long.
6. **A subsystem that raises from any of the three methods is treated as YES and logged.**
   Bookkeeping is never worth leaving the Pi up.

**Re-ask interval: 2 s** in negotiate mode. Responsive enough to be useful, slow enough that
the log stays readable.

## 4. The tiers — a DEPENDENCY order, not a priority list

    TIER 1  CAPTURE      stop producing.  OBD, IMU, light, EDR writers.
       |                 close current write, flush, done.
       v
    TIER 2  SYNC         drain what exists.
       |                 CANNOT converge until Tier 1 has stopped.
       v
    TIER 3  UPS/POWER    close the drain event, land battery-health.
       |                 records the shutdown, so it runs after the work.
       v
    TIER 4  SPLASH       the animation. Plays only when 1-3 report done.
       |                 Its completion IS the all-clear.
       v
            log CLEAN_COMPLETE, power off.

🔴 **A tier is asked only once every tier above it has finished.** That is the whole rule.

⚠️ **Tier 1 before Tier 2 is a bug fix, not tidiness.** Today's drain pushes until the
backlog reads empty *while capture is still running* — a target that keeps moving. It has
exactly two outcomes and both are observed: it never converges and burns the window, or it
converges falsely. It converges falsely because **the backlog reader excludes the EDR
tables** (US-766), so the largest producer is invisible to the count that decides
"synchronised". Stopping capture first makes the set finite and the count honest.

### The animation is the terminal signal

It is not a competitor for time. It is the **proof the sequence completed**, in the one place
visible without SSH — which matters because in production the Pi is a data-collection device
nobody logs into.

- **Completed normally** → animation plays, reports done, `CLEAN_COMPLETE` logged. The
  visible state and the log agree by construction.
- **Reserve reached** → animation is **CANCELLED, not skipped**, and the log says
  `splash=cancelled reason=reserve_reached`. A shutdown with no animation is then *diagnostic
  information*, not an anomaly.

⚠️ This also retires a live defect: today `splash-grace.path` cold-starts a second browser
the instant the shutdown-state SSOT is written, at T=0, *while* the shed is trying to reduce
load. Under this design the splash cannot start until Tiers 1–3 are done, so it can never
compete with the work.

## 5. The reserve, and the override

    RESERVE = measured_graceful_shutdown_duration + 15 s

**The +15 s is not slack for the shutdown to run long.** It is the margin that lets the
orchestrator stop negotiating *while a graceful shutdown is still possible*. Without it the
system negotiates until it can only crash — which describes the current behaviour exactly.

When the reserve is reached, the orchestrator **overrides**:

    sync    -> "stop now, finish the current write"
    splash  -> cancelled, not asked
    all     -> notified: MANDATORY shutdown
    then    -> the ordinary clean sequence

The override is an **authority, not a kill**. Every subsystem is still told, and still
finishes its current write. The difference from today is that today nothing is told anything.

### Detecting the reserve — threshold PLUS dwell

🔴 **The floor is voltage-driven** (CIO ruling, 2026-09-20). 🔴 **A bare `VCELL <= floor`
comparison is NOT acceptable.**

Measured 2026-09-20: VCELL read **4.1063 → 3.6787 V in 114 ms** at the moment the pack took
the load. That is the documented *loaded-terminal transition*, not discharge. A bare
threshold inside a signal's normal operating range is this project's most-repeated defect
(five instances catalogued in `specs/grounded-knowledge.md`).

**Required:** VCELL must read at or below the floor on **N consecutive reads** before the
reserve is considered reached. Still one mechanism, still voltage-driven, no timer racing it
— it simply cannot be tripped by a transient.

⚠️ **The floor value is PROVISIONAL and must be labelled so in config.** The reserve is
expressed in seconds; the floor is in volts; converting needs the discharge curve, and that
curve currently rests on **n = 1** (`battery_health_log` row 42 is the only drain in the
entire ledger carrying VCELL telemetry). Set the first floor conservatively. **US-790 ships
the curve and replaces it.** Shutdown takes seconds against a 762 s pack, so even a generous
floor leaves minutes of negotiation.

## 6. Logging — minimal, durable, timestamped

🔴 **The journal CANNOT hold this.** Measured: the journal loses its tail by ~8 s at a hard
cut (2026-09-20: last line 10:08:46 for a death at 10:08:58). **Every record this design
exists to produce falls inside the window the journal drops.**

**The shutdown log writes fsync-per-line to local disk.** That is the only reason any of the
2026-09-20 evidence survived.

Four lines for a normal shutdown. One line per event, greppable prefix, no prose:

    2026-09-20T15:08:58.101Z SHUTDOWN negotiate vcell=4.106 sync=NO:transfer_in_flight edr=YES ups=NO:drain_open
    2026-09-20T15:09:12.340Z SHUTDOWN mandatory vcell=3.712 reason=reserve_reached dwell=3
    2026-09-20T15:09:14.002Z SHUTDOWN override  sync=stop_after_current_write splash=cancelled
    2026-09-20T15:09:18.551Z SHUTDOWN complete  stage=CLEAN_COMPLETE elapsed=20.4s

**Not verbose.** Enough to answer *"who held it up, for how long, and did it finish"* on the
next boot — the question that has been unanswerable for three months.

## 7. What already exists — build on it, do not rebuild it

The bounded pipeline is roughly 80% of this orchestrator. **Extend it.**

| Existing | Role in this design |
|---|---|
| bounded pipeline, `perTaskTimeoutSec` 20 / `totalWindowCapSec` 45 | becomes the tier runner |
| `boot_progress.py` stage machine, `CLEAN_COMPLETE` | unchanged; gains vote/override rungs |
| `PHASE_FLUSHING` / `PHASE_POWERING_OFF` emitter | the notification channel |
| `sync_custody.py` — `DELIVERED / OUTSTANDING / UNKNOWN` | Tier 2's honest verdict |
| `PowerSourceProvider` SSOT | the only power-source authority; unchanged |
| `writeAtomicJson` (`outcome.py`) | the durable-write pattern §6 needs |

**What is genuinely new:** the `readyToShutdown()` question, the tier ordering, the reserve
with dwell, and the durable log. Nothing else.

## 8. Out of scope — deliberately

- **The 0.49 s death itself.** Root cause is still unknown as of this writing; ruled out by
  measurement or timing: draw spike, depletion, the VCELL floor fast-path, the drain, the
  systemd watchdog (60 s), and our own `ShutdownHandler` (it never ran — stage was `RUNNING`).
  🔴 **This design must not be treated as that fix.** It makes shutdowns orderly and
  observable; it does not explain why the machine stops.
- Sync protocol, retry policy, server-side custody.
- The discharge curve (US-790).
- Any change to `PowerSourceProvider`.

## 9. Open items

| Item | Owner | Blocks |
|---|---|---|
| **Measured graceful-shutdown duration** → sets `RESERVE = t + 15 s`. Time from *shutdown committed* (not power loss — that includes the debounce) to *Pi dark*, on wall power, **3 runs**; size the buffer off the worst, not the mean. | **CIO** | the reserve constant only |
| Discharge curve → replaces the provisional floor | US-790 | refinement, not the build |
| Dwell count `N` for the floor | Atlas, with the curve | the constant only |

⚠️ Reference point, n=1: the one reconstructable clean sequence ran **~4 s** from
confirmation to `poweroff.target`. If the CIO's measurement lands near that, the reserve is
~19 s — about **2.5% of a 762 s pack**.

## 10. Definition of done

1. All four participants implement the three-method contract; each has a test proving
   `abandon()` leaves consistent state.
2. Tier order enforced **structurally** — a test that asserts only "all tiers ran" passes
   with the order wrong, so the test must pin the sequence.
3. A subsystem returning NO forever is forced through at the reserve, and the log names it.
4. The durable shutdown log survives a real hard cut — verified by a cut, not a unit test.
5. `CLEAN_COMPLETE` is reached with the animation completed on wall power, and with
   `splash=cancelled` on a reserve-reached shutdown.
6. 🔴 **Acceptance measured over n ≥ 5 real cuts.** A single clean shutdown proves nothing:
   6 of 17 historical events completed by chance.
