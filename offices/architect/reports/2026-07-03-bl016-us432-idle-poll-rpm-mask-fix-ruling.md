# Atlas Ruling — BL-016 / US-432 idle-poll RPM-mask: fix-shape (A-9 start-side)

**Date:** 2026-07-03
**Requested by:** Marcus (PM) — `inbox/2026-07-02-from-marcus-bl016-idle-poll-rpm-mask-a9.md`
**Refs:** BL-016, US-432, US-242/B-049, US-221, US-388, US-367, A-9, A-17
**Lane:** A-9 start-side architectural ruling. Marcus completed the code-level RCA and correctly BLOCKED rather than guess; I own the fix-shape call.

---

## Verdict (one line)

**Option B — un-mask RPM past python-obd's dark-ECU support cache — scoped to known-mandatory PIDs, applied to BOTH the escalation probe AND the ongoing poll. REJECT Option C (it regresses US-388's close-guarantee by construction). Option A is acceptable-but-inferior.** One genuine live-Pi confirm remains, and prior A-17 live evidence already de-risks it.

---

## 1. RCA verification (grounded in the real code, not the note)

Every load-bearing claim in BL-016 verified against the tree at `dev` (`ac7e76c`):

| Claim | Verified | Evidence |
|---|---|---|
| `supported_commands` probed once, never refreshed | ✓ | `obd_connection.py:408` `_runSupportedPidProbe()` in the connect-success path only; US-199 comment says "one-shot". |
| The *real* gate is python-obd's OWN cache, not our mirror | ✓ | python-obd's `supported_commands` is populated inside `obdlib.OBD(...)` at `_createObdConnection` (`obd_connection.py:566`), i.e. at connect while the ECU is dark. Our `SupportedPidSet` (`_runSupportedPidProbe`, line 479-501) is a **separate** mirror → clearing it is a no-op for RPM. |
| RPM is the legacy branch, queried `force=False` | ✓ | `logger.py:210-220`: RPM ∉ `PARAMETER_DECODERS` → falls through to `self.connection.obd.query(cmd)` (no force) → null → `ParameterReadError` (223-228). |
| `_assertPidSupported` is a red herring for RPM | ✓ | Only invoked for decoder entries (`logger.py:211-212`); RPM never reaches it. |
| Escalation swallows the null + latches single-shot | ✓ | `core.py:1244-1251`: `queryAndLogParameter('RPM')` in try/except → WARN; `_engineOnEscalated` stays `True` (set at 1205, single-shot). |
| US-221 recovery can't help | ✓ | `_ecuSilentMode` clears **only on a successful read** (`realtime.py:590`, `_clearEcuSilentMode` 711); a null-without-wire read never succeeds → never clears. |
| Production backend is real python-obd (not a facade) | ✓ *(newly resolved from code)* | `_createObdConnection` returns `obdlib.OBD(...)`; `_obdFactory` is the **test-only** seam. Answers one of BL-016's three "needs-live" questions statically. |

**The RCA is sound. I concur with the root cause.**

## 2. The decisive structural fact (why "fix the probe" is not enough)

`drive_start` is emitted only at `_startDrive(now)` (`detector.py:667`), reached from `STARTING` **only when RPM stays `> driveStartRpmThreshold` for `driveStartDurationSeconds` across repeated ticks** (660-667). A single injected probe moves `STOPPED → STARTING` (655) and then **stalls/resets** on the next tick if no further RPM arrives (668-671).

**Therefore any fix confined to the one escalation probe is architecturally insufficient. The fix MUST un-mask the *ongoing* RPM poll for the life of the connection once engine-on is confirmed.** This is the single most important constraint on the fix and it applies to whichever option is chosen.

## 3. The ruling and its architectural basis

### The reframing (my lane — honest-availability / SSOT)

The python-obd support set built while the ECU was dark is **not a truthful "unsupported" verdict — it is UNKNOWN** (probed against a silent ECU). The defect is that the system collapses *"absent because probed-dark"* into *"ECU says no."* That is precisely the honest-availability anti-pattern I own (`specs/ssot-design-pattern.md` — an unavailable source must resolve to typed-unknown, **never a confident wrong verdict**). RPM on the 4G63 is a **mandatory Mode-01 PID → known-supported.** Forcing it past a cache populated against a dark ECU is not "forcing an unsupported PID" — it is correcting a false-negative in a cache that had no authority to say "no."

This dissolves Marcus's stated risk for B ("forced 2G reads produce garbage for genuinely-unsupported PIDs"): **it does not apply to RPM, because RPM is not genuinely unsupported.** Scope the un-mask to the **known-mandatory legacy set** (RPM at minimum; the argument extends to the other Mode-01 mandatory PIDs like COOLANT_TEMP), **NOT** a blanket force-all — a blanket force would re-expose the genuine-garbage risk for the 2G-unsupported candidates (0x42/0x0B/0x15) US-199 exists to skip.

### B over A

- **A (re-probe `supported_commands`)** depends on a python-obd API that *truly* re-interrogates. python-obd has no clean public re-probe — you reconstruct the `OBD` object or call internal `__load_commands`. That is (i) coupling to python-obd internals (fragile across versions), (ii) a full Mode-01 support-bitmap re-interrogation over the slow 2G K-line at the exact moment you want responsiveness, (iii) still contingent on the ECU answering the support bitmap promptly at wake. Purist, but higher-cost and internals-coupled.
- **B (un-mask the known-mandatory PIDs)** re-interrogates nothing. It stops trusting a known-stale "unsupported" for a PID we *know* is supported. Minimal blast radius, deterministic, no python-obd-internals coupling.

### REJECT C, with a US-388 non-regression proof

**Option C (alternator-active as a first-class `drive_start`) regresses US-388's close-guarantee by construction.** C mints `drive_start` on the BATTERY_V signature independent of RPM, and by design *tolerates RPM staying masked*. But US-388's **primary guaranteed-close path**, `_maybeCloseOnDeadline` (`detector.py:694,710`, constraint C-γ), arms only after an **observed RPM=0 reading drives RUNNING → STOPPING** (674-679). A drive with no RPM stream never arms STOPPING → the deadline-anchored close cannot fire → close narrows to the *tentative* ECU-silence path only → **re-opens the A-9 Root-2 stale-open-drive surface US-388 just closed.** C also collides with the "stamp drive_id only-when-RUNNING" invariant (US-388) and the drive_summary defer-INSERT (no-RPM start) + foreign-guard. It trades a start-side miss for a close-side regression, and it is exactly the re-design the AC's "do NOT re-solve" clause discourages. **Rejected for this fix.**

> Future note: if a later epic wants a battery-signature `drive_start`, it must FIRST guarantee an equally-reliable battery-signature `drive_END`; otherwise it is a net A-9 regression. That belongs to the server-side re-segmentation fork (B-104 / EDR epic), not this patch.

## 4. Fix shape Ralph builds

1. **Latch, don't one-shot.** On the engine-on escalation edge (`_maybeEscalateOnAlternatorActiveSignature` firing, `core.py:1205`), set a connection-scoped **"engine-confirmed → un-mask mandatory PIDs"** flag. Clear it on `drive_end` (alongside `_resetEngineOnEscalation`, `core.py:1264`) and on disconnect.
2. **Un-mask at the read path for the known-mandatory set only.** While the flag is set, the legacy read (`logger.py:220`) issues `self.connection.obd.query(cmd, force=True)` for RPM (and the Mode-01 mandatory set), bypassing the stale python-obd cache. Everything else keeps `force=False` (US-199 silent-skip preserved for the genuine-unsupported 2G candidates).
3. **Covers the ongoing poll, not just the probe** — this is the §2 requirement. Because the flag lives on the connection/logger, the *regular* realtime poll un-masks too, so the detector reaches `RUNNING` through the **identical existing** RPM-sustained state machine.

## 5. US-388 / A-9 non-regression (explicit)

B touches **only the read path** (the `force` flag / support-set trust). It does **NOT** touch `evaluateTimeouts`, `_maybeCloseOnDeadline`, `_openDriveId`, the drive_id NULL-latch, or `_startDrive`. `drive_start` still fires through the *unchanged* RPM-sustained state machine — the sole change is that RPM becomes actually readable. **The close-guarantee and NULL-latch are untouched.** This is B's decisive advantage over C: it makes the *existing correct* start/close machine work, rather than bolting on a parallel start signal that bypasses the close machine.

## 6. Live-Pi bench gate (the one real runtime unknown — already de-risked)

B's only genuine runtime dependency: **does `obd.query(RPM, force=True)` return a valid `010C` on this ELM327 + 2G ISO 9141-2 K-line once the ECU is powered** (not garbage/timeout)?

**I already have strong live evidence it does.** In the 2026-07-03 A-17 session, a raw single-threaded python-obd read on the same port returned RPM flawlessly (780/756/728/744/752, ISO 9141-2, 5/5) — the ELM327 + K-line + ECU answer `010C` cleanly; eclipse-obd's miss was the wrapper, not the wire. So the forced-read risk for B is **low**. Bench confirm to fully close it: after engine-on in the cold-boot-key-OFF sequence, issue one forced `010C` and confirm a real RPM value on the wire (folds into Marcus's already-planned BL-016 bench trace).

## 7. Fold into the A-9 IRL re-gate (guardrail b)

Confirmed: BL-016's missed-start-in-idle-poll is another drive-lifecycle failure the A-9 IRL re-gate must exercise. **Add the sequence: cold-boot with car key OFF → collector connects (dark ECU) → start engine → assert `DRIVE STARTED` + `drive_start` connection_log row + non-NULL RPM in realtime_data.** Sits alongside the existing re-gate matrix (short/back-to-back, key-on-after-missed-close, deploy-double-start).

## 8. A-17 sequencing note (do not conflate)

BL-016 and A-17 are **independent** and both gate OBD capture, so the re-gate must clear both:
- **A-17** = thread race — orphaned timeout/heartbeat daemons corrupt the shared non-thread-safe connection mid-read.
- **BL-016** = stale dark-ECU support cache masks RPM at the cold-boot-key-OFF → engine-on ordering.

The A-17 isolation test ran with the ECU already awake (RPM in cache), so it did **not** exercise BL-016's entry condition; and fixing BL-016 does nothing for A-17's race. Sequence them as two fixes; the single IRL drive re-gate exercises both.

---

**Disposition:** Fix-shape **B** approved for US-432 re-groom into Sprint 54, scoped as §4, gated by the §6 bench confirm and the §7 IRL re-gate. A-9 stays OPEN (HIGH) until the hardened re-gate passes on the car. No BLOCK — this refines the routed work, it does not stop it.

— Atlas
