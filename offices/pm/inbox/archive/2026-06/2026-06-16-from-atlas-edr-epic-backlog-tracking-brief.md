# Brief — EDR (Pi-5 black-box) epic: track in upcoming backlog (V0.3x+)

**Date**: 2026-06-16
**From**: Atlas (Architect)
**To**: Marcus (PM)
**Purpose**: Backlog tracking + sizing input for an upcoming epic. Not a blocker, not a sprint
yet — a heads-up so it's on your radar with the right shape, dependencies, and timeline before
it grooms.

## What it is

CIO + Spool are shaping a **Pi-5 automotive "black box" / Event Data Recorder (EDR)** — an
FDR-style recorder: high-rate local buffer → rolling disk segments → protected event vault, with
on-Pi triggers that seal event segments, plus new sensors (9-DoF IMU, light sensor) feeding both
the recorder and the display. It **complements** the tuning mission (event reconstruction +
datalog context); it does not replace it.

Spool ran the external concept through an engine/OBD reality check and routed the architectural
calls to me (`offices/architect/inbox/2026-06-16-from-spool-blackbox-edr-engine-side-assessment.md`).

## Architecture decisions already made (so you can groom against settled ground)

- **EDR vs B-104 — RULED.** The EDR's on-Pi trigger/event layer does **not** reverse B-104.
  Reconciled as a **dual-role Pi**: Role 1 = canonical raw emitter (B-104 unchanged, server keeps
  analytics authority); Role 2 = real-time edge safety + event recorder (exists because the server
  is structurally offline mid-drive). Full ruling: `offices/architect/reports/2026-06-16-edr-vs-b104-architecture-ruling.md`.
- **Single-reader / SSOT-bus direction (CIO).** Target architecture: ONE threaded reader owns all
  sources → publishes to an internal pub/sub bus → consumers (vault, display, triggers, **and
  server-sync**) subscribe; shared transforms compute once in a transform tier *before* publish.
  Server-sync is just another subscriber (no special path). Incremental — "keep pushing toward
  SSOT," not a rewrite.

## Timeline (hardware gate — drives sequencing)

CIO has **ordered the two sensors** (9-DoF IMU + TSL2591-class light sensor):
- **Arrive:** ~2026-06-30 to 2026-07-07 (2–3 weeks).
- **Wire + bench-test:** +1–2 weeks → hardware integration-ready **~mid-to-late July 2026**.

Implication for grooming: **IRL/hardware-dependent EDR work can't start before ~mid-July.** But
two pieces are **hardware-independent and can be groomed/started earlier** if you want to fill the
gap: (a) the ECMLink datastream **feasibility spike** (uses the existing ECU/OBD path), and (b) the
**dedicated-reader/bus-contract** design artifact (Atlas-owned, design-only).

## Sizing + sequencing recommendation

- **Size as a V0.3x+ epic, multi-sprint** — not a single sprint. Spool concurs.
- **Suggested phase order:**
  1. ECMLink feasibility spike (gates whether knock — the #1 engine-killer signal — is even
     reachable; do this early, it's hardware-independent and it shapes everything downstream).
  2. Dedicated-reader / bus-contract design artifact (Atlas) — the load-bearing piece everything
     subscribes to; design-only, can run in parallel with the spike.
  3. Single-reader consolidation + IMU/light raw channels (needs hardware, ~mid-July).
  4. Event vault + triggers (Spool's threshold spec) → display surfaces (Iris).

## Open architectural gates Atlas owns when it grooms

1. Dedicated-reader/bus contract (per-subscriber QoS [lossless sync/safety vs lossy display],
   bounded queues, producer-never-blocks, 100 Hz-IMU-vs-~6/s-OBD rate handling, ECMLink/OBDLink
   K-line arbitration).
2. IMU raw table + event-vault schema under versioned `src/common/` contract discipline — flagged
   as a **new instance of Watch List A-4** (don't repeat Pi↔server schema divergence).
3. ECMLink feasibility-spike ruling (knock coverage) before its architecture commits.
4. Graduate the SSOT-bus direction into `specs/ssot-design-pattern.md` once CIO firms it.

## Recommended action for you

- Add an **Epic** to the backlog (E-00x, "EDR / black-box recorder") with the 4 phases above as
  Feature-level placeholders; mark it **hardware-gated, earliest IRL ~mid-July 2026**.
- No sprint dispatch needed now. When you're ready to groom, loop in Atlas (architecture), Spool
  (engine triggers + PID budget), and Iris (display surfaces).
- Cross-ref: Atlas Watch List **A-14** tracks this from the architecture side.

— Atlas
