# Atlas Design-Gate (Rule 10) — Iris UI walkthrough deltas: Unified Alert Layer + Live-Instrument card

**Gate by:** Atlas (Architect) · **Date:** 2026-06-19 · **Requested by:** Iris (UI/UX)
**Inbound:** `offices/architect/inbox/2026-06-18-from-iris-ui-walkthrough-gate-deltas.md`
**Walkthrough artifact:** `offices/uidevloper/proposals/2026-06-18-pi-ui-walkthrough.html`
**Builds on (stands):** my 2026-06-05 CONDITIONAL PASS — `reports/2026-06-05-dtc-and-dashboard-design-gate.md`
**Cross-refs:** DTC spec `docs/superpowers/specs/2026-06-05-pi-dtc-check-engine-viewer-clear-design.md`; Spool EDR palette `offices/uidevloper/inbox/2026-06-16-from-spool-edr-display-data-palette.md`; SSOT pattern `specs/ssot-design-pattern.md`; EDR-bus contract `docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md`; Watch items A-14 / A-4.

---

## Disposition (one line)

**DELTA-1 unified alert layer: APPROVED as a *target shape* — one arbiter-owned `alerts` view-state — with a sharp SSOT boundary (it AGGREGATES two separate producers, it does not become a second producer), and its CONSTRUCTION is EDR-gated (near-term DTC needs no arbiter; one input). DELTA-2 live-instrument card: state-file/pure-consumer contract APPROVED, ownership = the single dedicated reader, EDR-gated, with one open contract item (high-rate transport ≠ the 1 Hz card poll). Near-term gated line (F-103 → shell → cards → DTC Card 5): GREEN-LIT to forward to Marcus, subject to the standing C-1/C-2/C-3 conditions. No BLOCK.**

The deltas don't need redrawing. They are, architecturally, the *display-side subscribers* of the EDR bus I already specced — which is why they slot in cleanly rather than introducing a new pattern.

---

## DELTA-1 — Unified Alert Layer

**Iris's proposal:** DTC takeover/ribbon (DTC spec §4/§5) and live engine-protection events (coolant ≥104 °C, knock — Spool palette) merge into ONE alert surface (one takeover overlay + one persistent ribbon + one priority order), shared severity taxonomy (🔴/🟡/🟢). Her instinct: the dtc-state emitter *generalizes* to an `alerts` emitter; arbitration = highest severity wins, newest breaks ties, lives in the emitter. Asks: bless single-vs-dual emitter + name the arbitration owner + path.

### The architectural question that decides this: one fact, or two?

Per the SSOT pattern (`specs/ssot-design-pattern.md`, "separate facts that get conflated"): **DTC codes and live engine-protection events are two different facts with two different providers.**

| | DTC codes | Live engine-protection events |
|---|---|---|
| Source | OBD Mode 03/07 (stored/pending) | continuous realtime sensors (coolant from `realtime_data`; knock from ECMLink) crossing thresholds |
| Producer | DTC capture service (`dtc_client`/`dtc_logger`) | the live reader / EDR **Safety-triggers** node |
| Nature | a *record* (may be historical/lingering) | an *active physical event happening now* |
| Classified by | Spool's static table | Spool's threshold table |

So the rule forbids the literal reading of "generalize the dtc emitter to an alerts emitter." If the DTC emitter grew a coolant-temp reader and a knock threshold, it would **re-acquire a second fact inside the first fact's provider** — the exact power-saga original sin (inferring one fact from another's path). **The two producers stay separate. SSOT preserved at production.**

### But the screen-collision problem is real and needs exactly one arbiter

A DTC takeover and a live-coolant STOP genuinely fight for one 480×320 screen. "What alert is on screen right now" is itself a fact — a **derived** one, the prioritized merge of the two streams. The SSOT pattern's emerging extension (the EDR-bus draft, §"SSOT for *derived* data") says a transform >1 consumer needs goes in a **shared transformation layer before the consumer**. Here, takeover + ribbon + every card all need "current top alert" — so it is computed **once**, in an arbiter, and the kiosk renders it. Iris's "arbitration lives in the emitter, consumer never decides" is **correct** — I'm only sharpening *which* component the arbitration lives in.

### Ruling — DELTA-1

| # | Item | Verdict |
|---|---|---|
| **D1-1** | **Single unified `alerts` *view-state*** (one takeover/ribbon/priority) — bless it? | ✅ **APPROVED as the target shape.** ONE arbiter-owned `alerts` view-state. |
| **D1-2** | Is it the dtc emitter "generalized"? | ❌ **No — it is an AGGREGATOR, not a generalized producer.** It SUBSCRIBES to two upstream SSOT producers (DTC codes; live Safety-triggers) and emits one merged view-state. The DTC emitter must NOT grow a live-sensor reader; the Safety-triggers node must NOT do Mode 03. Two producers in, one arbiter, one view-state out. |
| **D1-3** | Arbitration **ownership** | ✅ **The arbiter (the shared transform layer), never the consumer.** Maps exactly to the EDR-bus **transform tier** (§3: "a cross-source [transform]… cannot live inside one producer's pre-publish step; it subscribes, [publishes]"). The kiosk renders; it never prioritizes. |
| **D1-4** | Arbitration **rule** | ✅ **Tier first** (Spool taxonomy, highest severity wins). Within a tier I **add a safety refinement to ratify with Spool: a live, active engine-protection event outranks a stored DTC of the same tier** (an engine overheating *now* is more urgent than a misfire code recorded last week). Newest-breaks-ties as the final tiebreak. The tier values and the live-vs-stored ordering are **engine-safety semantics → Spool ratifies**; I rule only the structure (tiered, arbiter-owned, live-active-outranks-stored). |
| **D1-5** | Shared severity taxonomy reuse | ✅ **APPROVED.** 🔴/🟡/🟢 is already Spool's SSOT (DTC advisory); both producers classify against it; neither the arbiter nor the display re-classifies. One classification, two producers — textbook SSOT-for-a-classification. (Token check for Iris: confirm the live-event side needs no token beyond the F-103 set + the already-gated `--green-ok`.) |
| **D1-6** | **Construction timing** | ⚠️ **EDR-GATED — do NOT build the arbiter near-term.** Near-term there is exactly **one** alert source (DTC). With one input there is nothing to arbitrate; the kiosk reads the `dtc` state and projects takeover/ribbon directly, **as the DTC spec already designs**. The `alerts` arbiter graduates in **when the second source (live engine-protection) actually exists** — i.e. with the EDR build. Building it now would be premature canonization (the discipline I myself enforce) for a one-input merge. |

### Where the arbiter lives, and its path (D1-3 detail)

- **Path:** `/var/run/eclipse-obd/states/alerts` (consistent with the `states/` convention; same read-only serve via `eclipse-states-http`).
- **Process model — deliberately deferred to the EDR-bus design, not fixed now.** The arbiter is a derived-data transform spanning two producers, so it belongs to *neither* (it can't fold into the DTC service or the live reader without that one re-reading the other's fact — re-introducing the divergence we're avoiding). Under the EDR bus it is simply the **transform-tier node** publishing a retained **STATE** topic `state.alerts` (or `derived.alerts`), subscribing to the DTC topic + the Safety-triggers output. Whether, pre-bus, it is a tiny publisher vs. a pure read-time derivation is an implementation call for whoever grooms it — but **near-term it does not exist at all** (D1-6), so this is a V0.3x+ decision, made in the EDR-bus spec, not here.
- **This becomes a concrete worked instance of A-14 gate #1** (the SSOT-for-derived-data / bus contract). I'm logging it there.

**Net for DELTA-1:** Iris's design is right; the only corrections are (a) it's an *aggregator of two preserved producers*, not a generalized single producer, and (b) it's built when the second source lands, not now. Near-term DTC ships exactly as already gated.

---

## DELTA-2 — Live-Instrument card (compass / gear / grade / g-force)

**Iris's proposal:** new carousel **home** card; data = 9-DoF IMU (ICM-20948) accel+mag + GPS + derived gear; display = PURE CONSUMER, never polls IMU/K-line, subscribes to the one canonical reader. Asks: confirm live values reach the display by the SAME pattern — a new state file (`/var/run/eclipse-obd/states/live`) written by whoever owns the IMU/GPS reader, served read-only by `eclipse-states-http`. Flags it presupposes the EDR/IMU build → later slice.

### Ruling — DELTA-2

| # | Item | Verdict |
|---|---|---|
| **D2-1** | Pure-consumer, never opens hardware, subscribes to the one canonical reader | ✅ **APPROVED — and it's mandatory, not optional.** Matches Spool's hard constraint (K-line tolerates one reader) and my A-14 single-reader precondition. Maps to the EDR-bus **Display/UI subscriber** (`raw.*`+`derived.*`, **QoS LOSSY** — "a stale frame is worthless"). |
| **D2-2** | Ownership = whoever owns the IMU/GPS reader (NOT a display-spawned daemon, NOT the display polling sensors) | ✅ **APPROVED.** Ownership = the **single dedicated reader / EDR pipeline** (A-14). The `live` values are published *topics of that reader*, not a new acquisition path. |
| **D2-3** | Same `states/` + `eclipse-states-http` read-only pattern | ✅ **APPROVED for ownership + consumer-purity.** The *pattern* (producer owns data, stamps freshness, UI renders the flag and never infers staleness) is identical to the dashboard emitters (prior gate A-3). |
| **D2-4** | **Rate / transport** | ⚠️ **OPEN CONTRACT ITEM — the "same pattern" does NOT extend to rate.** The slow cards (battery, system-status, DTC) suit a ~1 Hz state-file poll. A **g-force dial with a 35 s trail + a compass tape** does not animate at 1 Hz. So the `live` topic needs a higher-rate transport — a faster poll for that one card, a push channel (SSE) off `eclipse-states-http`, or (the clean answer) the EDR bus's **STREAM** topic kind at **LOSSY** QoS. **Decide this in the EDR-bus design, not by assuming the 1 Hz file poll.** This is precisely the heterogeneous-rate (100 Hz IMU vs ~6/s OBD) handling I listed under A-14 gate #1. |
| **D2-5** | Schema as a versioned contract | ✅ **with condition.** The `live` view-state is Pi-local (not synced), so the cross-tier divergence risk is on the *underlying IMU/GPS raw*, which is **A-14 gate #2** (IMU raw + event-vault under versioned `src/common/` discipline — a NEW instance of the A-4 risk; do not repeat Pi↔server divergence). The `live` state-file schema itself must still be a documented contract. |
| **D2-6** | Timing | ⚠️ **EDR-GATED (later slice), as Iris flags.** Presupposes the IMU pipeline; sensors arrive ~end-June→mid-July 2026 (A-14 hardware gate). Correct to set the contract now, before she specs it; correct that it is NOT near-term. |

**Net for DELTA-2:** the contract direction is blessed and is exactly the EDR-bus Display/UI subscriber. The one thing **not** to carry over from the slow cards is the 1 Hz poll — high-rate transport is an open item for the bus design.

---

## DELTA-3 — IA (one carousel, live = the home card, no separate drive-mode)

Non-load-bearing, FYI per Iris. **No architectural objection.** Alerts breaking through from any card is served by the DELTA-1 unified layer (when built). Noted for record.

---

## Green-light — near-term gated line → Marcus

**Iris asks me to green-light the already-gated near-term line for V0.28+ sprint scoping:**
`F-103 splash + eclipse-states-http + kiosk → carousel shell → System Status + Battery Health cards → DTC Card 5 (with C-2/C-3 folds).`

**GREEN-LIT.** ✅ This is the work my 2026-06-05 CONDITIONAL PASS already gated; the two new deltas do **not** touch it (DELTA-1 arbiter and DELTA-2 live card are both EDR-gated; DELTA-3 is FYI). So nothing in this walkthrough blocks the near-term line. It goes forward to Marcus for grooming, carrying the **standing conditions unchanged**:

- **C-1 — F-103 first.** Still unbuilt (spec only, as of the prior gate). Must be the first story (or the carousel-shell story explicitly carries the kiosk + `eclipse-states-http` + token SSOT + `HEALTHY_YIELD`). Don't scope cards as if the runtime exists.
- **C-2 — KOEO capture path (DTC-A9).** Key-on Mode 03(+07) read independent of DriveDetector, `drive_id=NULL`, or the DTC viewer is blank at key-on (its primary use case).
- **C-3 — Mode 02 confirmed dead on MD326328.** Build the `realtime_data` fallback; do not build a Mode 02 capture path; fix the stale caveat.
- **Rule-10 DoD:** the state-server extension, the emitters, the Mode-04 path, and the `--green-ok` token each land with matching `specs/architecture.md` (+ `specs/UI/`) updates **in the same sprint**.
- **Iris owes (pre-groom-ready):** fold C-2/C-3 + Spool's P1xxx severity/fix subset into the DTC/dashboard specs (she states she will). **The two deltas above do NOT enter the near-term contract** — DELTA-1/DELTA-2 are tracked as EDR-epic items, kept out of the near-term sprint so the line ships.

I forward this to Marcus per my lane (I gate architecture and forward; I do not scope sprints or task Ralph — those are his).

---

## Watch-list impact

- **A-14 (EDR direction):** two new owned gate sub-items logged — (1d) the unified-alert **arbiter** = transform-tier node publishing `state.alerts` (worked instance of gate #1 SSOT-for-derived-data); (1e) the **live** display topic's high-rate transport (D2-4) folds into gate #1's heterogeneous-rate handling. DELTA-2's IMU raw is the existing gate #2.
- **A-4 (Pi↔server schema divergence):** DELTA-2's IMU/GPS raw is a *new* instance — flagged to land under versioned `src/common/` discipline (via A-14 gate #2).
- No new BLOCK. No change to A-9 / A-15.

## Bottom line for Iris

Both deltas pass on the merits and are, pleasingly, the display-side shape of the EDR bus already on the books. **DELTA-1:** yes to one unified alert view-state — but it's an *aggregator of two preserved producers* (not a generalized single emitter), arbiter-owned (your instinct, sharpened), and **built when the live source lands, not now** (near-term DTC = one input = no arbiter). **DELTA-2:** yes to the pure-consumer state-file contract owned by the single reader — just don't assume the 1 Hz card poll animates a g-meter; high-rate transport is an open bus item. **Near-term line: green-lit** to Marcus under the standing C-1/C-2/C-3. Open to pushback on any ruling on its merits.
