# Power Management — Phase 2: Bounded Pre-Shutdown Pipeline — Design Spec

- **Date:** 2026-05-17
- **Status:** Approved architecture (all decisions ratified by CIO in design session) — pending spec review → implementation plan. **Build is gated on Phase-1 = GREEN (now satisfied, see §5).**
- **Supersedes / deletes:** the legacy in-app `PowerDownOrchestrator` VCELL ladder (WARNING/IMMINENT/TRIGGER + at-floor trigger). Demotes the V0.27.12 boot-progress instrument (`docs/superpowers/specs/2026-05-15-honest-boot-progress-instrument-design.md`) to last-priority housekeeping.
- **Prime directive (unchanged):** collect OBD2 data for Spool's tuning analytics on the 1998 Eclipse. Power management is a small enabler that must *work* but must stop consuming the project.

---

## 1. Why this exists (the pivot, in one paragraph)

The project spent a week+ on graceful-shutdown-on-power-loss. Root cause: it was solved at the wrong layer — an in-app ladder that *rode the battery down* and tried to trigger a clean shutdown near the battery floor (~3.45V), under exactly the I/O-storm conditions a near-dead Pi is worst at, plus a journal-scraping canary sharing the data app's failure domain (the I-036/I-037 class). External-solution research confirmed the universal pattern: **shutdown and wake belong to the OS/firmware layer, never the data application**, and "come back on power" is a hardware/firmware concern. The pivot has two phases: **Phase 1** — unattended power-cycle (HW+firmware+systemd), now proven; **Phase 2** (this spec) — a minimal, isolated, *bounded* pre-shutdown pipeline that replaces the ladder entirely.

## 2. Objectives & priority (CIO, verbatim intent)

1. **Collect data** for analytics — everything else is a thin enabler.
2. **Power up / down gracefully**, unattended (Phase 1 — done).
3. On power loss: **best-effort, bounded** attempt to sync to the home server *if reachable*, then graceful shutdown regardless.
4. Edge-triggered logging only (WiFi/BT state *changes*, not polled status).
5. Battery health: passive observability for replacement planning — *separate* from the shutdown mechanism.

## 3. CIO phased plan

| Phase | Scope | State |
|---|---|---|
| 1 | Unattended graceful shutdown ↔ auto-boot on power return, zero human touch | **GREEN — 3/3, see §5** |
| **2** | **This spec — bounded pre-shutdown pipeline (on-battery → tasks → graceful poweroff)** | **architecture locked; build-gated on Phase 1** |
| 3 | Bluetooth/OBD reconnect when on car/wall power | later |
| Housekeeping | Fix instrument `CLEAN_COMPLETE` (Finding A) — instrument **kept, not deleted** | last priority |

## 4. The architectural through-line

Every mature solution decouples **detect / decide+execute / return-on-power**, and keeps decide+execute *out of the data application*. Phase 1 put *return-on-power* and *shutdown execution* in the OS/firmware. Phase 2 puts *the decision and the bounded pre-shutdown work* in a **minimal isolated unit** that the data app's I/O storm cannot wedge — because it is tens of lines doing nothing else, and the actual poweroff is the OS's job.

## 5. Phase-1 result (the gate — now GREEN; Phase-2's foundation)

- **Hardware:** Raspberry Pi 5 Model B Rev 1.1 + **Geekworm X1209** 5.1V 6A UPS HAT, car-power topology (the real rig).
- **Fix:** the **EEPROM-first** step — latest bootloader installed + `POWER_OFF_ON_HALT=1`, `WAKE_ON_GPIO=1`, config captured before/after. No wake circuit, no HAT jumper, no code.
- **Validated:** 3/3 acceptance cycles — clean `sudo systemctl poweroff` → Pi fully dark → car power removed (key off) → dwell → car power restored (key on / ACC) → **Pi auto-boots unattended, `eclipse-obd` active**, zero human touch. Spool re-verified read-only.
- **Consequence:** the legacy `PowerDownOrchestrator` VCELL ladder is **deleted**. There is no longer any "ride the battery to the floor and trigger at the last safe moment" path — so **Bug-1 (the I/O-storm at-floor shutdown failure) is eliminated by design, not deferred: the scenario ceases to exist.**

## 6. Phase-2 architecture

### 6.1 Component & boundary
A **minimal, isolated power-watch unit** implemented as a **dedicated long-running systemd service** (a *separate process* from the OBD data application, consistent with the rest of the deploy architecture and the NUT `upsmon` pattern), reusing the **already-proven** power-state detector (the same `UpsMonitor`/`PowerSource` logic the display uses — **not** a new detector, **not** a VCELL ladder). It must not share the data app's failure domain, must be tiny enough that nothing else in its address space can wedge it, and the actual shutdown is the OS's (`systemctl poweroff`). It is NOT a thread/path inside the OBD app — that re-creates the original failure-domain entanglement.

### 6.2 Trigger
**Sustained on-battery, debounced** (reuse the existing `pi.hardware.upsMonitor.*` sustained-below-threshold detection). The *power-loss event* is the trigger, acted on **promptly**. The battery is a *bridge* sized for (the window + a clean shutdown) — **not** a runtime to maximize. No waiting for near-empty.

### 6.3 The bounded pre-shutdown pipeline
An **ordered list of best-effort, individually time-boxed, interruption-safe tasks**, executed within the on-battery window, the whole window hard-bounded, then **unconditional graceful `poweroff`**.

**Task contract (every task, no exceptions):**
- Best-effort; own hard per-task timeout.
- **Interruption-safe**: killable at the bound with no bad side-effect (idempotent, non-half-stateful). *A task that cannot be safely killed mid-run does NOT belong in this window — it belongs at a boot/maintenance boundary.*
- Failure isolated: one task's failure/timeout never blocks the next task or the shutdown.
- On a *real* fault (not a benign expected condition), emit a **typed durable outcome record** (producer only).
- Uniform: **no per-task criticality.** The only guarantee is the graceful poweroff at the bound; true durability (DB flush/fsync) is the **OS's normal graceful shutdown**, not a task.

**Today's pipeline = `[sync_with_server]`.** Extensible by appending tasks; this must be trivial and must **never** weaken the hard bound. Recorded future candidate: a **check-for-updates** task (system/OBD2-software) — *check/fetch/stage/mark only*; the **apply** is a separate, not-yet-written headless process that runs at a **boot/maintenance boundary, never in this window** (applying a heavy stateful update on a draining battery with a guaranteed poweroff = corrupted/bricked collector — the same trap class as I-036). Scaffolding already exists: the `pi.update.*` config family + the B-047 US-C(check→marker)/US-D(apply, rollback) split.

### 6.4 `sync_with_server` task (CIO-specified state machine)
1. Is **chi-srv-01** reachable? (reuse the existing `pi.homeNetwork`/`pi.companionService` reachability/ping, hard timeout.)
   - **No** → task done (benign skip). Pipeline continues.
   - **Yes** → sync the database (existing sync client, hard timeout):
     - success → **log success**;
     - failure → **log error, retry once** (hard timeout);
     - still failing → **log error, continue** (no further retries).
2. Unsynced data is **not lost** — it remains in the Pi's local SQLite and syncs the next time home. "Confirmed sync" means *the bounded attempt resolved* (done / skipped / failed-after-retry), never "every byte uploaded."

### 6.5 Outcome records (producer-only scope)
On a real fault, the task writes a **typed durable record**: `server_unavailable` (benign), `sync_failed_after_retry`, or `real_error` + detail. **We deliver only the producer.** A *separate* process consumes these on next boot and routes real errors through the OBD app's error pipeline — **out of scope for this spec.**

### 6.6 Hard bound (the un-hangable guarantee)
Per-task timeout **+** overall wall-clock total cap on the whole window **+** a **VCELL-floor safety short-circuit** (if already critically low, skip the window entirely and power off now). Whichever fires first → **unconditional `systemctl poweroff`**, *independent of the pipeline* — a hung/slow task can never prevent or delay the poweroff past the bound. The VCELL floor is a *defensive backstop only* (we no longer ride the battery down, so it should rarely matter).

### 6.7 Power-return abort
If external power returns at **any** point during the window (engine restarted / brief stop): **cancel the pipeline and the pending poweroff, resume normal operation.** (This is the legacy "AC-restore cancels" behavior — correct, kept.)

### 6.8 Shutdown & wake
Plain `sudo systemctl poweroff` — the OS owns the shutdown sequence and the flush. Phase-1's proven EEPROM/X1209 path auto-boots the Pi when power returns. (Phase-2 shutdowns are ordinary clean OS shutdowns — exactly what Phase-1's wake was validated against in §5.)

## 7. Scope

**IN:** the isolated power-watch unit; the bounded pipeline + task contract; the `sync_with_server` task; the typed-durable-record *producer*; configuration of all bounds; the **clean deletion** of the legacy `PowerDownOrchestrator` ladder.

**OUT:** the durable-record *consumer* (separate process, next-boot); the headless update *apply* process (separate, boot/maintenance boundary); Phase-3 Bluetooth/OBD; the instrument `CLEAN_COMPLETE` fix (housekeeping, last); Bug-1 (eliminated by design — the ladder it lived in is deleted).

## 8. What this deletes / supersedes
- **Deleted:** the `PowerDownOrchestrator` VCELL ladder (WARNING/IMMINENT/TRIGGER thresholds + at-floor trigger) and its in-app shutdown decision/execution. The journal-scan canary was already deleted (T10 cutover).
- **Demoted:** the boot-progress breadcrumb instrument — *kept* for possible future use but reduced to last-priority housekeeping (fix `CLEAN_COMPLETE`); it is no longer load-bearing because the OS now owns/loggs the shutdown and the watcher logs its own state transitions.
- **Net:** Phase-2 is mostly *deletion* plus a small, isolated, bounded unit. This is the point.

## 9. Configuration (no hardcoded values — project rule)
Operational knobs under the tier-aware `pi.*` config (validator dot-notation defaults; `python validate_config.py` gate). Reuse existing families where present:
- on-battery sustained/debounce → reuse `pi.hardware.upsMonitor.*`.
- server reachability → reuse `pi.homeNetwork.*` / `pi.companionService.*`.
- new `pi.powerWatch.*`: per-task timeout(s), total window cap, VCELL-floor safety threshold, pipeline task list.
**Numeric bounds (per-task timeout, total cap, VCELL floor, debounce) must be derived with Spool from real battery-runtime data — not hardcoded optimistically.** The contract (task vocabulary, record types) is code + a contract test, **not** mutable config (mutable contract = the US-308/US-342 silent-drift class).

## 10. Verification strategy (the institutionalized lesson)
The recurring failure of this project was tests/reviews that passed because they were **not representative of the real invocation** (synthetic-green ≠ runtime). Phase-2 verification therefore requires:
1. Unit tests: the pipeline state machine, the task contract, the hard-bound + power-return-abort guarantees, the `sync_with_server` state machine, the typed-record producer.
2. **A test that exercises the power-watch unit exactly as it is actually invoked** (the real process/entrypoint/env — not a pytest-masked path). This is mandatory and is the lesson from the V0.27.12 DOA.
3. An **IRL Phase-2 acceptance** (the CIO "when" end-to-end): sustained-on-battery → chi-srv-01 reachable? → sync/skip per §6.4 → bounded → graceful poweroff → Phase-1 auto-boot. Spool re-verifies read-only. Acceptance count to be ratified by CIO (mirror the Phase-1 discipline).

## 11. Sequencing & open items
- **Build is gated on this spec being reviewed/approved**, then `writing-plans`. Phase-1 is GREEN (§5), so Phase-2 is unblocked to *plan* once this spec is accepted.
- The legacy-ladder deletion must be a **clean cutover** with the same discipline as the T10 boot_reason cutover: no dual deciders, no orphaned consumers, full-suite green, the real-invocation test in place.
- Numeric bounds (§9) need Spool's battery-runtime input before the plan's config task is finalized.
- Housekeeping (instrument `CLEAN_COMPLETE` / Case-1 induction) stays last; Bug-1 needs no work (eliminated by design).
