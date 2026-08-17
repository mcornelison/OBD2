# EDR Staging-Plan Review — GROOMING INPUT (1 re-scope + 3 grounding inputs)
**Date**: 2026-07-26
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important
**Refs**: prd-edr-next-draft.md (E-006), F-112, F-113, F-114/F-115, A-14

## Review Scope
`offices/pm/prds/prd-edr-next-draft.md` — the two groomable-now features in my lane: **F-112** (ECMLink/knock feasibility spike) and **F-113** (dedicated-reader / bus-contract design, engine-signal inputs). Reviewed against `offices/tuner/knowledge.md` (OBD-II §, ECMLink V3 §, Drive-25 capability probe) + my EDR alert advisory.

## Result: GROOMING INPUT — F-112 needs a re-scope before it freezes; F-113 needs 3 grounded inputs
This is a staging plan, not frozen stories, so no threshold-value pass applies yet. But F-112 as currently framed would burn a spike **re-proving a negative I already established**. Fix the framing before it grooms.

---

## Issue 1 (F-112) — "is knock reachable over the OBD path" is ALREADY ANSWERED: **no**. Re-scope the spike.
**What the PRD says**: F-112 = "Determine whether **knock** ... is reachable from the ECMLink datastream **over the existing ECU/OBD path**."

**What it should say**: The OBD-path half of that question is closed. Grounded in my own **Drive-25 probe** (`scripts/probe_obd_capabilities.sh`, logged in `knowledge.md` OBD-II §):
- **Mode 22 (vendor enhanced) NOT IMPLEMENTED** on MD326328 at 8 probed addresses → *"the OBDLink-via-Pi pipe cannot reach ECMLink-internal data on this ECU."*
- Knock sum / knock retard / per-cylinder timing live in **ECMLink-exposed RAM**, read via **MUT-II RAM-peek commands over the ECMLink USB-to-serial cable + PC software** — NOT the ELM327/OBD path. `TIMING_ADVANCE` (0x0E) on the OBD path is **base timing, not knock**.

So don't scope F-112 as "can the OBDLink reach knock" (proven no). The genuine open questions are:
1. **Is MUT-II / ECMLink-RAM-peek Pi-hostable at all** without ECMLink's Windows app, or does it hard-require the PC software? (This is the real feasibility unknown.)
2. If yes, it needs the **ECMLink cable as a dedicated transport** — which lands on Issue 2 (K-line contention).
3. **ECMLink V3 is owned but NOT installed** (summer 2026). No live knock read is possible now → **F-112-now is a protocol/paper feasibility investigation, not a live probe.** Do NOT write an acceptance criterion that requires reading actual knock data this sprint.

**Why it matters**: A spike scoped to re-test the OBD path wastes the sprint confirming a known negative and produces a false "knock not feasible" when the real (unexplored) path is Pi-hosted MUT-II. This is the #1 engine-killer signal — get the question right.

## Issue 2 (F-112 → F-113 dependency) — every knock path rides the **single K-line**; ECMLink↔OBDLink arbitration is the gating constraint.
The K-line physically tolerates **one reader** (10.4 kbps single bus; the ELM327 "multiple access on port" message I logged Session 27 is the two-reader failure signature). Both the OBDLink OBD pipe **and** MUT-II ride that same K-line. So knock-logging (MUT-II) and OBD monitoring (ELM327) **cannot run concurrently** without an arbitration scheme (time-slice, or suspend OBD while ECMLink-logging). This transport/arbitration answer is an **F-112 output that F-113's "K-line arbitration" design depends on** — F-113 can't be correct without it. Sequence F-112 to deliver it.

## Issue 3 (F-113 input — my owed deliverable, producible now) — ground the rate-handling on the MEASURED budget + a PID-priority allocation.
F-113's rate-handling ("100 Hz-IMU-vs-~6/s-OBD") must sit on the empirical ceiling, not a guess:
- **Drive 27 measured: 16 PIDs @ ~0.39 Hz/PID, ~6.3 samples/sec aggregate**, ISO 9141-2 @ 10,400 bps. It's a **fixed total you ALLOCATE across PIDs, not a rate you set** — higher per-PID rate only by polling fewer PIDs.
- I owe the **PID-priority allocation** (Tier-1 safety-critical PIDs sampled fastest — coolant, RPM, load, O2/trims — vs Tier-2/3 informational). Hardware-independent; **I can produce it during this groom.** Name it as an explicit F-113 input story so it isn't left implicit.

## Issue 4 (F-114/F-115 grounding — verify before grooming) — IMU "installed @0x69" vs later "dead IMU clones."
PRD hardware-status (06-27) lists **ICM-20948 @0x69 installed**. But the V0.29.15 deploy context (07-22) reports **"dead IMU clones graceful-absent."** If the IMU isn't actually enumerating, **F-114/F-115 stay hardware-blocked** and the entire IMU-derived trigger catalog — spool characterization, lateral-g↔fuel-trim, vertical-g↔knock-discrimination (half the EDR value; the plan itself calls the IMU "the real prize") — **can't proceed.** The **TSL2591 light @0x29 IS confirmed live** (V0.29.15 wired it), so F-115's auto-dim can proceed independent of the IMU. **Reconcile the IMU ground truth (CIO / Atlas) before grooming F-114/F-115.** Not my lane to fix, but it changes what's groomable.

---

## Confirmed correct-as-is (noting so it isn't lost)
- **Engine-trigger thresholds correctly deferred to F-115** (post-hardware). They're already seeded in my SSOT `offices/tuner/edr-alert-live-instrument-thresholds-advisory.md`: coolant 🟢≤99 / 🟡100–103 / 🔴≥104 °C graduated; knock ECMLink-gated (≥~15–18° non-recovering retard = 🔴); voltage + lean-under-load bands; live>stored arbitration; 🔴 full-brightness floor. F-115 triggers build against that file.
- **F-110 bus slice** shipped-dark, correctly awaiting flag-flip validation.

## On the PRD's open question for CIO (design+spike sprint vs defer)
**Concur with (a)** — the design+spike sprint. It's the critical-path foundation and hardware-independent. Just scope F-112 honestly per Issue 1: the live knock read is install-gated; the now-doable work is (i) the Pi-hostable-MUT-II paper investigation, (ii) the K-line arbitration finding (Issue 2), (iii) my PID-priority allocation (Issue 3). All real, all hardware-free.

## Routing
Issues 1–3 are also **Atlas's** inputs (he rules the F-112 outcome + owns the F-113 contract). I'll send him a short A2AL pointer to this note. Issue 4 is a CIO/Atlas hardware-ground-truth reconcile. Ping me when F-112/F-113 groom and I'll produce the PID-priority allocation.

— Spool
