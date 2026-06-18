---
title: EDR Dedicated-Reader + Internal Bus — Contract & First-Slice Design
date: 2026-06-18
author: Atlas (Architect)
status: design (approved in brainstorm; pending written-spec review)
scope: Pi tier — the single-reader → internal pub/sub bus → subscribers data pipeline
refs:
  - offices/architect/reports/2026-06-16-edr-vs-b104-architecture-ruling.md   # EDR vs B-104 dual-role ruling
  - offices/architect/CLAUDE.md §8 A-14                                       # SSOT-bus direction + open gates
  - offices/architect/findings/2026-06-18-server-address-ssot-mirror-drift.md  # SSOT cautionary tale
  - specs/architecture.md §10.7                                              # B-104 (Pi=emitter / server=authority)
  - specs/ssot-design-pattern.md                                             # SSOT pattern (graduation target)
  - offices/tuner/inbox/2026-06-16-from-spool-blackbox-edr-engine-side-assessment.md  # SME source (§6 single-reader, §8 catalog)
---

# EDR Dedicated-Reader + Internal Bus — Contract & First-Slice Design

## 1. Purpose & context

The Pi tier has **no message bus today.** The OBD reader writes raw readings straight to SQLite;
the display polls that table every 500 ms on its own connection; the sync transport polls a cursor
every 60 s; the drive detector reads RPM back out of the DB. **SQLite + polling is the de-facto
coupling** — which means a stuck K-line query starves the display and detector, the display is
500 ms-stale by construction, and every consumer is one schema change away from breaking.

This design introduces a **dedicated reader → internal publish/subscribe bus → subscribers**
pipeline (CIO architectural direction, 2026-06-18; Watch List A-14). It is the load-bearing
foundation for the EDR (black-box recorder) epic and, more broadly, moves the Pi toward
single-source-of-truth for **derived** data, not just raw — eliminating the "two surfaces show
the same value computed two different ways" defect class.

It is the concrete realization of two prior rulings: the **dual-role Pi** (EDR vs B-104,
2026-06-16) and the **single-reader-per-bus** precondition (Spool §6).

This is gate #1 of the EDR epic: **the contract everything else subscribes to.** It is a V0.3x+
epic, multi-slice; this spec covers the contract plus the first migration slice.

## 2. Goals / Non-goals

**Goals**
- One **dedicated reader (producer) per hardware source**; the source is read exactly once.
- An in-process pub/sub bus where every other component (persistence/sync, display, triggers,
  transform tier, EDR vault) is a **subscriber** — no component re-reads hardware.
- **SSOT for derived data:** a shared transform tier computes each derived value **once** and
  publishes it; consumers subscribe rather than recompute.
- **Decoupling / resilience:** a slow or stuck consumer can never stall the producer.
- **Extensibility:** new sources/transforms are added as new producers/topics; existing consumers
  opt in or ignore with zero code change.
- **Honest instrument:** any dropped/lost sample is explicitly counted and marked, never silent.
- B-104 preserved: the server remains the sole authority for persisted analytics.

**Non-goals (YAGNI)**
- **No external broker** (ZeroMQ / Redis / MQTT). In-process, single-app distribution is served by
  `queue.Queue`; a broker daemon adds a process + dependency to a constrained Pi for no benefit.
- **No full cutover now.** Strangler-fig (§7): slice 1 migrates only the OBD producer + a
  persistence subscriber; display/detector/sensors follow in later slices.
- **Not the EDR triggers/vault themselves**, the IMU/light producers, or the transform-tier
  catalog — those are later slices that build *on* this contract.
- **Not ECMLink** — gated behind a separate feasibility spike (knock coverage).

## 3. Architecture — dual-role Pi, producer → bus → subscribers

Two roles, one direction of flow:

- **Role 1 — canonical raw emitter (B-104, unchanged).** Raw samples are captured and made
  available to the server, which stays the sole authority for persisted analytics.
- **Role 2 — real-time edge layer (new).** Live safety triggers + event recording happen on the
  Pi *because the server is structurally offline mid-drive.*

```
  ┌──────────┐  raw.obd.*  ┌─────────┐ raw.*        ┌──────────────────────────────┐
  │ ObdReader│────────────▶│         │─────────────▶│ PersistenceSub (raw + state +  │ → realtime_data
  └──────────┘             │         │              │   event-log) → server transport│   (+ event/state recs)
  ┌──────────┐  raw.imu.*  │ Sample  │ raw.*        └──────────────────────────────┘
  │ ImuReader│────────────▶│  Bus    │─────────────▶┌──────────────────────────────┐
  └──────────┘  (later)    │         │◀─────────────│ TransformTier                  │
  ┌──────────┐  raw.light  │         │ subscribes   │  (sub raw.* → pub derived.*)   │
  │LightReader│───────────▶│         │ raw.*; pubs  └──────────────────────────────┘
  └──────────┘  (later)    │         │ derived.gear, derived.speedMph, ...
                           │         │ raw.*+derived.*  ┌───────────────────────────┐
                           │         │─────────────────▶│ Display/UI · Safety triggers│ (later slices)
                           │         │                  │ · EDR vault                 │
                           └─────────┘                  └───────────────────────────┘
```

**The transform tier is a bus node** (subscriber of raw, publisher of derived). A cross-source
derived value (gear = f(RPM, speed, acceleration)) needs inputs from multiple producers arriving
at different rates, so it cannot live inside one producer's pre-publish step; it subscribes,
time-aligns, computes once, and publishes. From every consumer's view the derived value is already
on the bus, computed once — the SSOT-for-derived property.

**Gating rule (what computes live on the Pi at all):** the Pi computes a transform/calc/derived
value **only if a current-drive consumer needs it live** (gear on the display, km/h→mph for a
gauge, a safety-relevant value). Everything else is **not** computed on the Pi — the raw data is
recorded flight-data-recorder style and shipped to the server, where the heavy analysis (Spool's
catalog: grade-corrected load, spool maps, dyno trend, corner-lean, …) runs after the drive.

This composes with B-104, it does not reverse it (full reasoning: the 2026-06-16 ruling). The
transform tier serves **local** consumers; raw still emits to the server; the server keeps
persisted-analytics authority — the same compute-once discipline applied on both tiers.

## 4. The contract

### 4.1 The `Sample` envelope

One normalized, **immutable** record (frozen — fan-out hands the same object to N subscriber
threads with zero copy and no mutation races). Grounded in today's `LoggedReading` /
`realtime_data` shape, extended for multi-source:

```python
@dataclass(frozen=True)
class Sample:
    topic:      str            # routing key: "raw.obd.RPM", "raw.imu.accel", "derived.gear"
    source:     str            # producer id: "obd" | "imu" | "light" | "transform"
    value:      float | tuple  # scalar (OBD) or a small fixed vector (IMU accel = (ax, ay, az))
    unit:       str | None      # "rpm", "km/h", "g", "lux", ...
    tsUtc:      str            # ISO-8601 UTC wall-clock (utcIsoNow) — the value that PERSISTS
    tsCapture:  float          # high-res monotonic seconds — for in-drive time-alignment & latency
    driveId:    int | None     # current drive context
    dataSource: str            # "real" | "simulator" — existing hygiene, carried not re-tagged
    seq:        int            # per-producer monotonic counter — gap/drop detection + ordering
```

- **`tsCapture` (monotonic)** is required for aligning a ~6 Hz OBD stream against a ~100 Hz IMU
  stream; wall-clock can be NTP-stepped. `tsUtc` is what persists.
- **`seq` is per-producer** (a global counter would force cross-thread sync on every publish — a
  100 Hz contention point). Per-producer keeps publish lock-free per source and still detects gaps.
- **`value` may be a small fixed tuple** (an IMU vector as one sample). The persistence subscriber
  owns mapping that to storage (explode to rows, or a structured table); the bus is
  storage-agnostic.

### 4.2 Topic model

Hierarchical, dotted, four roots:

```
raw.<source>.<channel>     raw.obd.RPM   raw.obd.SPEED   raw.imu.accel   raw.light.lux
derived.<name>             derived.gear  derived.speedMph  derived.grade
event.<name>               event.drive.start   event.trigger.coolant   event.integrity.gap
state.<name>               state.vin   state.supportedPids   state.calibration.speedFactor
                           state.config.*
```

Subscribers match by **segment-prefix with a trailing `*` wildcard** — `raw.*`, `raw.obd.*`,
`raw.obd.RPM`, `derived.*`. **Not** regex (YAGNI — regex invites slow/ambiguous patterns we never
need in-box).

### 4.3 Topic kinds — STREAM vs STATE (and lookup tables are off-bus)

Every topic is one of two kinds; static/slowly-changing data is the reason this distinction exists.

- **STREAM (default):** time-series, FIFO, **not retained**. A subscriber receives samples
  published *after* it subscribes. (`raw.obd.RPM`, all telemetry.)
- **STATE (retained / last-value-cache):** the bus keeps the **latest** `Sample` per topic; on
  subscribe, the subscriber is immediately handed the current retained value (if any), then
  updates on change. Declared via `retain=True` on publish (MQTT-style "retained message"). This
  is how slowly-changing / write-once data sits on the bus: **VIN, supported-PIDs, calibration
  factor, and `state.config.*`** — a late-joining consumer always gets the current value.

**Lookup / reference tables are NOT bus data.** A DTC-code→description table, PID decoders, gear-
ratio tables are immutable *libraries*, loaded as shared read-only resources by whoever needs them.
The bus carries the *event* (`event.dtc` → code `P0301`); the consumer joins it against the
reference data it already holds. If more than one *live* consumer needs the **enriched** value
(human-readable DTC text on screen), the transform tier does the lookup once and publishes
`derived.dtc.enriched` — compute-once, gated by the §3 rule.

### 4.4 Interface

```python
class SampleBus:
    def publish(self, sample: Sample, retain: bool = False) -> None   # producer thread; NEVER blocks
    def subscribe(self, topics: list[str], qos: QoS, name: str) -> Subscription

class Subscription:
    def get(self, timeoutS: float | None = None) -> Sample | None     # blocking drain (own thread)
    def poll(self) -> Sample | None                                    # non-blocking drain
    def close(self) -> None
    def stats(self) -> SubStats        # depth, highWater, droppedCount, lastSeqBySource

class QoS(Enum):
    LOSSLESS   # delivered OR spilled OR marked as integrity-gap; never silent loss, never blocks producer
    LOSSY      # drop-oldest when full; never affects the producer
```

A producer calls `bus.publish(sample)`. A subscriber runs **its own daemon thread** looping on
`sub.get()` — the same pattern `RealtimeDataLogger`, `UpsMonitor`, and the drive detector already
use, so this grafts onto the existing concurrency model rather than replacing it.

**Synchronous test mode:** the bus supports an injectable delivery mode where `publish()` delivers
inline (no threads) so tests are deterministic without sleeps (see §6).

### 4.5 Subscription map — Bound B as a subscription filter

This is the **target end-state** subscription set, realized incrementally across the slices in §7
(slice 1 stands up only the persistence subscriber; display/triggers/transform/vault are added in
later slices). It is shown whole here because the *contract* must define each subscriber's topic
set and QoS up front.

| Subscriber | Subscribes to | QoS | Rationale |
|---|---|---|---|
| **Persistence / server feed** | `raw.*` + `event.*` + `state.*` | LOSSLESS | FDR records raw; server recomputes analytics from raw (B-104). Never needs `derived.*`. |
| **Display / UI** | `raw.*` + `derived.*` | LOSSY | live raw gauges + derived (gear, mph); a stale frame is worthless. |
| **Safety triggers** | `raw.*` + `derived.*` | LOSSLESS | thresholds on raw + derived; cannot miss an alarm. |
| **Transform tier** | `raw.*` (+ inputs) → publishes `derived.*` | LOSSLESS in | computes the live-needed set once. |
| **EDR vault** | `raw.*` + `event.*` | LOSSLESS | seals event segments + survivability cache. |

"Don't ship the server what it can recompute" and "only compute live what the drive needs" are both
enforced by **what each subscriber listens to** — not by remembered rules. The persistence/server
feed ignores `derived.*` entirely, so derived values never pollute the authoritative raw record.

### 4.6 Config as `state.config.*`

Config is slowly-changing data → a retained STATE topic, published once at startup from the **one
canonical config loader** (the `config.json` + validator path) and re-published if it changes at
runtime. Consumers subscribe; none hold their own copy of an address/port/flag. The 2026-06-18
chi-srv-01 IP incident (one server address duplicated across config.json + validator DEFAULTS +
`addresses.sh`, drifted on a host move, broke sync) is the cautionary tale this enforces.

## 5. QoS, backpressure & error handling

**Absolute invariant: the producer NEVER blocks.** The single hardware reader must keep reading;
if any consumer could stall it, every consumer starves. `publish()` is provably bounded
(enqueue → spill → mark, never waiting on a consumer).

Each subscriber owns a **bounded queue**; the overflow policy is keyed on QoS:

| QoS | Subscriber(s) | Queue full → | Why safe |
|---|---|---|---|
| **LOSSY** | display | **drop-oldest**, bump `droppedCount` | stale frame worthless; newest-wins; producer never waits. |
| **LOSSLESS** | persistence/sync, safety, transform, EDR | **try durable spill; if unspillable, emit a counted+alarmed `event.integrity.gap` and continue** — never block, never silently drop | OBD ~6/s + sub-ms SQLite ⇒ realistically never fills; 100 Hz IMU handled by **batched** persistence writes. |

**The lossless guarantee:** *delivered, OR spilled to durable store, OR recorded as an explicit
`event.integrity.gap`* (source + lost `seq`-range + count + reason). Never a silent loss; never a
producer stall. The gap marker is a first-class bus event that the server's authoritative record
ingests, so a hole is visible as "N samples lost here," not a silent absence. (CIO decision
2026-06-18: never block the producer even for lossless — accept the marked gap immediately.)

**Error isolation:**
- Each subscriber runs its own thread; an exception is caught at its loop boundary, logged,
  counted — producer and other subscribers untouched. Repeated failures → the bus detaches the
  subscriber (loudly) and drops its queue; everyone else continues. A stuck *consumer* can no
  longer starve the *producer* (today's failure mode, inverted).
- Producer-side hardware errors stay the producer's concern (existing ECU-silent / reconnect logic
  unchanged); it publishes fewer samples and subscribers detect the gap via `seq`. **The bus never
  fabricates a sample to fill a gap.**

**Observability:** `Subscription.stats()` exposes `depth / highWater / droppedCount /
lastSeqBySource`; the bus exposes per-subscriber health into the existing telemetry surface. Drops,
spills, and integrity gaps are visible, never hidden.

## 6. Testing strategy

The hard part is determinism — threads + timing cause flaky tests. The fix is the **synchronous
test mode** (§4.4): production fans out to subscriber threads; tests deliver inline, so outcomes
are asserted without `sleep()`.

| Layer | Proves |
|---|---|
| **Unit (sync mode)** | `Sample` immutability; topic prefix-matching; STATE replay-on-subscribe; each QoS overflow policy (lossy drop-oldest, lossless spill, lossless-unspillable → gap-marker); `seq` gap detection. |
| **Concurrency** | The load-bearing invariant — a wedged/slow consumer does **not** reduce producer throughput, and other subscribers keep receiving; publish fan-out thread-safety. |
| **Integration (slice 1)** | Golden-master: `ObdReader → bus → PersistenceSubscriber` writes **byte-identical `realtime_data` rows** vs today's inline path. Runs the real SQLite write path (no mocks). |
| **Honesty** | An unspillable lossless overflow emits exactly one `event.integrity.gap` with the correct lost-`seq` range + count. |

Rides existing pytest discipline (AAA, markers, 80% floor, no-mocks-for-real-systems).

## 7. Migration sequencing (strangler-fig)

Wrap the new structure around the old; route one consumer at a time through it; delete an old path
only when nothing reads it. Each slice is independently shippable and verifiable — critical on a
shared checkout that must keep working between every commit.

- **Slice 1 — the spine (this design's build target).** Introduce `SampleBus`, extract the K-line
  ownership + poll loop into `ObdReader` (the single reader), add `PersistenceSubscriber` that
  writes `realtime_data` (your "one subscriber that saves data for the server"). The existing HTTP
  sync transport is **unchanged** — it still reads `realtime_data` and ships it. Display + detector
  **unchanged** — still read the DB. **Observable output is byte-identical** (same rows land);
  regression test is the golden-master. Net: producer → bus → persistence proven with zero change
  to the well-tested downstream.
- **Slice 2 — display → subscriber.** Display subscribes to `raw.*` (+ `derived.*` once they
  exist), becomes event-driven, retires the 500 ms DB poll.
- **Slice 3 — detector → subscriber.** Drive detector subscribes to `raw.obd.RPM` instead of
  reading it back out of the DB.
- **Slice 4 — new sensors.** `ImuReader` + `LightReader` producers; `PersistenceSubscriber` writes
  the IMU raw channel (new structured table under versioned `src/common/` contract discipline).
- **Slice 5 — the EDR proper.** Transform tier lights up its first derived topic (gear);
  safety-trigger subscriber + EDR event-vault subscriber; `event.integrity.gap` in force.

## 8. Open items / dependencies (routed, not owned here)

- **IMU raw table + event-vault schema** must follow versioned `src/common/` contract discipline —
  a new instance of the Pi↔server schema-divergence risk (Watch List A-4). Slice 4.
- **ECMLink feasibility spike** gates whether knock (the top engine trigger) is reachable; if it
  fails, the safety layer has no knock trigger and we say so explicitly.
- **Display live-alert latency** is a non-functional requirement on Role 2's live path (Iris owns
  rendering).
- **Graduate the SSOT-bus direction** into `specs/ssot-design-pattern.md` once ratified (currently
  CIO direction, A-14).

## 9. References

See frontmatter `refs`. Primary: the 2026-06-16 EDR-vs-B-104 ruling (dual-role Pi),
`specs/architecture.md` §10.7 (B-104), Spool's 2026-06-16 SME assessment (§6 single-reader, §8
derived-signal catalog), and the 2026-06-18 server-address SSOT finding (cautionary tale).
