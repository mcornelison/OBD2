# Architecture Ruling — EDR (Pi-5 "black box") vs B-104 (Pi=emitter / server=authority)

**Date**: 2026-06-16
**Author**: Atlas (Architect)
**Type**: Architecture ruling (load-bearing fork). Long-form, Markdown — humans return to it.
**Status**: RULING — preliminary-but-binding on design direction. The EDR concept itself is
still being shaped by CIO + Spool ("first-pass SME read, not frozen"); this ruling fixes the
*architectural relationship to B-104* so downstream design (trigger spec, event-vault schema,
display path, ECMLink spike) can proceed without silently reversing a locked decision.
**Routed by**: Spool §5, `inbox/2026-06-16-from-spool-blackbox-edr-engine-side-assessment.md`
("Flagging for an explicit ruling.")
**Refs**: B-104 Step 1 = `specs/architecture.md` §10.7; SSOT pattern = `specs/ssot-design-pattern.md`;
locked decision #3 (versioned `src/common/` contracts) = memory `project_architecture_tiers.md`.

---

## 1. The question

The EDR concept puts **trigger logic + event-sealing back on the Pi** (local RAM ring →
rolling disk segments → protected event vault, with on-Pi triggers firing the seal). B-104
Step 1 deliberately made the **Pi a dumb telemetry emitter and the server the sole authority**
for derived/persisted analytics. Spool flagged: *not necessarily contradictory, but it is a
real fork and must not silently reverse B-104.* He asked for an explicit Atlas ruling.

## 2. Ruling (summary)

**APPROVED, with bounds. The EDR edge layer does NOT reverse B-104. It occupies a lane B-104
already opened.** The two reconcile under a **dual-role Pi** model:

- **Role 1 — canonical raw emitter (B-104, unchanged).** The Pi continues to capture raw OBD
  events + drive-boundary event-log fields and sync them to the server. The server remains the
  **sole authority** for all derived/persisted *analytics* (`drive_summary` analytics columns,
  `drive_statistics`, the GEM/Mahalanobis family, and the future IMU-fusion catalog in Spool §8
  items 2–7). Nothing in the EDR moves analytics authority to the Pi.

- **Role 2 — real-time edge safety + event recorder (EDR, new).** The Pi additionally runs an
  on-device layer that (a) maintains a high-rate local buffer, (b) evaluates **live safety
  triggers** (coolant ≥104 °C, lean-under-load, brownout, knock-if-ECMLink — Spool §4), and
  (c) seals **event segments** to a protected local vault. This layer exists **because the
  server is structurally unavailable mid-drive** — it is only reachable after sync over home
  WiFi. The server cannot fire a live coolant alarm at 70 mph; that responsibility is
  *inherently* edge and was never B-104's to own.

The decisive evidence: B-104's own principle text already permits this. `specs/architecture.md`
§10.7 (lines 1719–1722):

> *Pi may compute in-drive aggregates locally for HDMI dashboard / alert consumers — engine
> running = AC power, no battery cost — but those aggregates are **not transmitted**. Default
> rule: if the server can redo it from raw data, the Pi does not transmit it.*

The EDR's Role 2 is the maximal form of that already-blessed "alert consumer" lane. B-104 did
not forbid Pi-side computation; it forbade **Pi-side computation becoming a transmitted source
of authority.** The EDR honors that line.

## 3. The two bounds (this is where the fork is actually governed)

The reconciliation holds **only if** these two invariants are enforced. They are the substance
of the ruling, not footnotes.

### Bound A — The event vault is a non-authoritative cache, never a second SSOT.

The server's raw `realtime_data` (+ the new IMU channel, see Bound B) remains the **single
authoritative record** for all post-drive analytics. The local event vault is a **safety/forensic
cache**: it exists for (i) in-drive protection and (ii) survivability of the moments around an
event if sync never happens (crash, theft, SD corruption). It MUST NOT become an input that the
server's analytics trust *over* `realtime_data`, and no analytics consumer may read the vault as
a source of truth. If the vault and `realtime_data` ever disagree about a sample, `realtime_data`
wins. This keeps faith with the SSOT pattern (`specs/ssot-design-pattern.md`) and with locked
decision #3 — a divergent unversioned local store that quietly became authoritative is exactly
the contract-divergence failure mode I track under Watch List A-4.

### Bound B — Honor "if the server can redo it from raw, the Pi does not transmit it" — per channel.

Apply B-104's default-rule channel by channel:

| Channel | Server can redo from raw? | Transmit? | Authority |
|---|---|---|---|
| Raw OBD samples | yes (already the raw stream) | **yes** (unchanged) | server `realtime_data` |
| High-rate IMU (9-DoF, ~100 Hz) | **no** — server never sees it otherwise | **yes — MUST transmit as raw** | server (new raw IMU table) |
| Trigger *decision* / event marker | yes (re-derivable from raw OBD+IMU) | as an **event-log record only**, like drive boundaries — never as derived analytics | event-log field; server may re-derive |
| Derived analytics (gear, grade, spool maps, dyno trend — Spool §8 items 2–7) | yes | **no** (server computes) | server |
| Live on-Pi readouts (current gear, live g, safety state — Spool §8 live set) | n/a — display only, ephemeral | **no** | not persisted as authority |

The **critical new obligation**: the IMU is a *raw channel the server cannot reconstruct*, so it
is governed exactly like raw OBD — captured by the single reader, synced raw, server-authoritative.
It is **not** an exception to B-104; it is a second instance of the same raw-emitter rule. The
event-vault *marker* (when/why a trigger fired) syncs as an event-log record (peer to the existing
`drive_start_timestamp`/`data_source` fields the Pi already writes and the server already preserves
without overwriting), **not** as a computed-analytics row.

## 4. Consequence for §6 (single reader) — this ruling depends on it

This ruling assumes Spool §6 / the CIO single-reader directive holds: **one dedicated process owns
each bus and publishes one canonical in-process stream; the ring buffer, event vault, trigger
service, display, and sync are all *consumers* of that stream, never independent hardware readers.**
That is not a separate question — it is load-bearing *for this ruling*, because the dual-role model
only stays coherent if Role 1 (emit) and Role 2 (trigger/seal/display) read the **same** single
producer rather than racing the K-line. The K-line physically tolerates one reader (10.4 kbps
request-reply), so physics and SSOT design agree. I am ruling §6 **IN** as a precondition of §5;
I will write the dedicated-reader/producer-consumer contract as its own design artifact when this
grooms (it deserves the detail, including ECMLink/OBDLink arbitration on the one diagnostic channel).

## 5. What this ruling does NOT decide (routed, not silently dropped)

- **ECMLink datastream feasibility (Spool §3).** CIO ruled it *in scope*; I am **not** ruling its
  architecture until a feasibility spike answers: can the Pi read the ECMLink real-time stream
  *without* the Windows software, and how is K-line contention with the OBDLink arbitrated? If the
  spike fails, the ruling above is unaffected — the event layer simply has no knock trigger and we
  **say so explicitly** rather than implying knock coverage we lack. Knock is the highest-value
  engine trigger; the spike is the gate.
- **Engine-trigger thresholds (Spool §4).** Spool's lane; he owns the spec. Architecture only
  requires they evaluate off the one canonical stream (Bound + §6).
- **Display live-alert latency (Spool §9).** Accepted as a real **non-functional requirement** on
  Role 2's live path (a buried/late coolant alert defeats the purpose); the rendering is Iris's
  lane. I'll pin the latency NFR when the display path grooms.
- **Schema for the IMU raw table + event-vault format.** Future design; must follow versioned
  `src/common/` contract discipline (locked decision #3) so the new raw channel does not repeat
  the Pi↔server schema-divergence pattern (Watch List A-4).
- **Sizing.** This is a **V0.3x+ epic**, not a sprint (Spool §7). PM sizes it.

## 6. Rationale in one line

B-104 chose **cloud-authority for analytics**; the EDR needs **edge-authority for safety + latency**.
Those are different concerns sharing one data source, not competing claims on the same concern. The
resolution is to make the edge artifact a **non-authoritative cache fed by the one canonical reader**,
keeping the server the single source of truth for everything it can compute — which is the SSOT
pattern applied across a tier boundary, not an exception to it.

---

*Atlas — on-demand. This ruling unblocks downstream EDR design from the B-104 axis. Open gate
items above are routed to their owners (ECMLink spike, Spool thresholds, Iris latency, PM sizing).*
