# EDR Bus — Slice 1 (Dedicated Reader → Bus → Persistence) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert an in-process publish/subscribe bus between the OBD reader and the `realtime_data` write, proving it produces byte-identical rows, behind a default-off feature flag.

**Architecture:** New `src/pi/bus/` package (`Sample`, `QoS`, `SampleBus`, `Subscription`, `PersistenceSubscriber`). The existing `RealtimeDataLogger` poll loop gains a publish seam at `_logReadingSafe`: when a bus is injected, it publishes a `Sample` instead of writing; a `PersistenceSubscriber` consumes those samples and writes `realtime_data` by **reusing the existing `ObdDataLogger.logReading()`** (identical SQL ⇒ identical rows). Strangler-fig: display, detector, and the sync transport are untouched and keep reading `realtime_data`.

**Tech Stack:** Python 3.11+, stdlib only (`dataclasses`, `enum`, `queue`, `threading`, `time`), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-18-edr-dedicated-reader-bus-contract-design.md`

## Global Constraints

- **Naming:** Python functions/variables `camelCase`; classes `PascalCase`; constants `UPPER_SNAKE_CASE`; SQL columns `snake_case`. (specs/standards.md)
- **File headers:** every new `.py` file requires the standard header block (specs/standards.md lines 16-33).
- **Type hints** on all public functions; Google-style docstrings with Args/Returns/Raises.
- **No new third-party dependencies** — stdlib only.
- **No magic numbers** — queue sizes / timeouts are named constants or config.
- **Coverage:** ≥80% (pyproject enforced); the bus core is critical-path → aim 100%.
- **Byte-identical invariant:** slice 1 MUST NOT change the columns written to `realtime_data` (`parameter_name, value, unit, profile_id, drive_id, data_source`, plus the write-time `timestamp`). The golden-master test in Task 6 is the gate.
- **Feature flag `pi.bus.enabled` defaults `False`.** Slice 1 ships dark; flipping it on is a separate deploy decision (PM/CIO), not part of this plan.

---

### Task 1: `Sample` envelope + `QoS`

**Files:**
- Create: `src/pi/bus/__init__.py`
- Create: `src/pi/bus/sample.py`
- Test: `tests/pi/bus/test_sample.py`

**Interfaces:**
- Produces: `Sample` (frozen dataclass, fields below); `QoS` enum (`QoS.LOSSLESS`, `QoS.LOSSY`).

- [ ] **Step 1: Create the test directory marker and the failing test**

Create `tests/pi/bus/__init__.py` (empty). Create `tests/pi/bus/test_sample.py`:

```python
import dataclasses
import pytest
from pi.bus.sample import Sample, QoS


def test_sample_isImmutable():
    s = Sample(topic="raw.obd.RPM", source="obd", value=3500.0, unit="rpm",
               tsUtc="2026-06-18T13:00:00Z", tsCapture=123.5, driveId=27,
               dataSource="real", seq=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.value = 4000.0  # type: ignore[misc]


def test_sample_carriesAllFields():
    s = Sample(topic="raw.imu.accel", source="imu", value=(0.1, 0.2, 9.8),
               unit="g", tsUtc="2026-06-18T13:00:00Z", tsCapture=1.0,
               driveId=None, dataSource="real", seq=42)
    assert s.topic == "raw.imu.accel"
    assert s.value == (0.1, 0.2, 9.8)
    assert s.driveId is None
    assert s.seq == 42


def test_qos_hasLosslessAndLossy():
    assert QoS.LOSSLESS != QoS.LOSSY
    assert {QoS.LOSSLESS, QoS.LOSSY} == set(QoS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/bus/test_sample.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pi.bus'`.

- [ ] **Step 3: Create the package and `sample.py`**

Create `src/pi/bus/__init__.py`:

```python
################################################################################
# File Name: __init__.py
# Purpose/Description: Pi in-process publish/subscribe bus package (EDR slice 1).
# Author: (assign)
# Creation Date: 2026-06-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
```

Create `src/pi/bus/sample.py`:

```python
################################################################################
# File Name: sample.py
# Purpose/Description: Immutable Sample envelope + QoS enum -- the unit of data
#     published on the SampleBus. See docs/superpowers/specs/
#     2026-06-18-edr-dedicated-reader-bus-contract-design.md §4.1.
# Author: (assign)
# Creation Date: 2026-06-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class QoS(Enum):
    """Delivery guarantee declared per subscription.

    LOSSLESS: delivered, or (future) spilled, or recorded as an explicit
        integrity-gap marker -- never silently dropped, never blocks the producer.
    LOSSY: drop-oldest when the subscriber queue is full; never affects the producer.
    """

    LOSSLESS = "lossless"
    LOSSY = "lossy"


@dataclass(frozen=True)
class Sample:
    """One immutable reading published on the bus.

    Args:
        topic: Routing key, e.g. ``"raw.obd.RPM"``, ``"raw.imu.accel"``.
        source: Producer id, e.g. ``"obd"``, ``"imu"``, ``"transform"``.
        value: Scalar reading, or a small fixed tuple (e.g. IMU vector).
        unit: Unit of measurement, or None.
        tsUtc: ISO-8601 UTC wall-clock string -- the value that persists.
        tsCapture: High-resolution monotonic seconds, for time-alignment.
        driveId: Active drive id, or None.
        dataSource: Origin tag, e.g. ``"real"`` / ``"physics_sim"``.
        seq: Per-producer monotonic counter, for gap/drop detection.
    """

    topic: str
    source: str
    value: float | tuple[float, ...]
    unit: str | None
    tsUtc: str
    tsCapture: float
    driveId: int | None
    dataSource: str
    seq: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/bus/test_sample.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/pi/bus/__init__.py src/pi/bus/sample.py tests/pi/bus/__init__.py tests/pi/bus/test_sample.py
git commit -m "feat(bus): Sample envelope + QoS enum (EDR slice 1)"
```

---

### Task 2: `topicMatches` + `Subscription` (bounded queue + QoS overflow + stats)

**Files:**
- Create: `src/pi/bus/bus.py`
- Test: `tests/pi/bus/test_subscription.py`

**Interfaces:**
- Consumes: `Sample`, `QoS` (Task 1).
- Produces:
  - `topicMatches(pattern: str, topic: str) -> bool` — prefix/exact matcher.
  - `SubStats` (frozen dataclass): `depth: int, highWater: int, droppedCount: int, lastSeqBySource: dict[str, int]`.
  - `Subscription` with: `name: str`, `topics: list[str]`, `qos: QoS`; methods `get(timeoutS: float | None = None) -> Sample | None`, `poll() -> Sample | None`, `close() -> None`, `stats() -> SubStats`; and internal `_offer(sample: Sample) -> bool` (returns False on a lossless overflow so the bus can emit a gap marker).

- [ ] **Step 1: Write the failing test**

Create `tests/pi/bus/test_subscription.py`:

```python
from pi.bus.sample import Sample, QoS
from pi.bus.bus import topicMatches, Subscription


def _sample(seq=1, topic="raw.obd.RPM", source="obd", value=1.0):
    return Sample(topic=topic, source=source, value=value, unit=None,
                  tsUtc="2026-06-18T00:00:00Z", tsCapture=float(seq),
                  driveId=None, dataSource="real", seq=seq)


def test_topicMatches_wildcardAndExact():
    assert topicMatches("raw.*", "raw.obd.RPM") is True
    assert topicMatches("raw.obd.*", "raw.obd.RPM") is True
    assert topicMatches("raw.obd.RPM", "raw.obd.RPM") is True
    assert topicMatches("raw.*", "derived.gear") is False
    assert topicMatches("derived.*", "derived.gear") is True
    assert topicMatches("raw.obd.RPM", "raw.obd.SPEED") is False


def test_subscription_pollReturnsInOrder():
    sub = Subscription("s", ["raw.*"], QoS.LOSSLESS, maxQueue=10)
    sub._offer(_sample(1))
    sub._offer(_sample(2))
    assert sub.poll().seq == 1
    assert sub.poll().seq == 2
    assert sub.poll() is None  # empty


def test_subscription_lossyDropsOldestWhenFull():
    sub = Subscription("s", ["raw.*"], QoS.LOSSY, maxQueue=2)
    assert sub._offer(_sample(1)) is True
    assert sub._offer(_sample(2)) is True
    assert sub._offer(_sample(3)) is True   # full -> drop oldest (seq=1)
    assert sub.poll().seq == 2
    assert sub.poll().seq == 3
    assert sub.stats().droppedCount == 1


def test_subscription_losslessSignalsOverflow():
    sub = Subscription("s", ["raw.*"], QoS.LOSSLESS, maxQueue=1)
    assert sub._offer(_sample(1)) is True
    assert sub._offer(_sample(2)) is False  # overflow -> bus must mark a gap
    assert sub.stats().droppedCount == 1
    assert sub.poll().seq == 1               # the queued one is preserved


def test_subscription_statsTrackHighWaterAndLastSeq():
    sub = Subscription("s", ["raw.*"], QoS.LOSSLESS, maxQueue=10)
    sub._offer(_sample(5, source="obd"))
    sub._offer(_sample(6, source="obd"))
    st = sub.stats()
    assert st.depth == 2
    assert st.highWater == 2
    assert st.lastSeqBySource["obd"] == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/bus/test_subscription.py -v`
Expected: FAIL — `ImportError: cannot import name 'topicMatches' from 'pi.bus.bus'` (module absent).

- [ ] **Step 3: Create `bus.py` with `topicMatches`, `SubStats`, `Subscription`**

Create `src/pi/bus/bus.py`:

```python
################################################################################
# File Name: bus.py
# Purpose/Description: In-process publish/subscribe SampleBus + Subscription for
#     the Pi data pipeline (EDR slice 1). See docs/superpowers/specs/
#     2026-06-18-edr-dedicated-reader-bus-contract-design.md §4-§5.
# Author: (assign)
# Creation Date: 2026-06-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

from __future__ import annotations

import queue
from dataclasses import dataclass, field

from .sample import Sample, QoS

DEFAULT_MAX_QUEUE = 10000


def topicMatches(pattern: str, topic: str) -> bool:
    """Return True if a subscription ``pattern`` matches a sample ``topic``.

    Patterns are dotted segment-prefix with an optional trailing ``*``:
    ``"raw.*"`` matches ``"raw"`` and any ``"raw.<...>"``; an exact pattern
    matches only itself. Not a regex (by design).
    """
    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        return topic == prefix or topic.startswith(prefix + ".")
    return topic == pattern


@dataclass(frozen=True)
class SubStats:
    """Point-in-time observability snapshot for a Subscription."""

    depth: int
    highWater: int
    droppedCount: int
    lastSeqBySource: dict[str, int]


class Subscription:
    """A consumer's view of the bus: a bounded queue + QoS overflow policy.

    The owning consumer drains via :meth:`get` (blocking) or :meth:`poll`
    (non-blocking) on its own thread. Producers never call these.
    """

    def __init__(self, name: str, topics: list[str], qos: QoS,
                 maxQueue: int = DEFAULT_MAX_QUEUE):
        self.name = name
        self.topics = list(topics)
        self.qos = qos
        self._queue: queue.Queue[Sample] = queue.Queue(maxsize=maxQueue)
        self._droppedCount = 0
        self._highWater = 0
        self._lastSeqBySource: dict[str, int] = {}
        self._closed = False

    def matches(self, topic: str) -> bool:
        """True if any of this subscription's patterns matches ``topic``."""
        return any(topicMatches(p, topic) for p in self.topics)

    def _offer(self, sample: Sample) -> bool:
        """Enqueue per QoS. NEVER blocks.

        Returns:
            True if delivered (or the loss was absorbed by drop-oldest);
            False on a LOSSLESS overflow -- the caller (bus) must record an
            integrity-gap marker. The producer is never blocked either way.
        """
        self._lastSeqBySource[sample.source] = sample.seq
        try:
            self._queue.put_nowait(sample)
        except queue.Full:
            if self.qos is QoS.LOSSY:
                # Drop the oldest, keep the freshest.
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(sample)
                except queue.Full:
                    pass
                self._droppedCount += 1
                return True
            # LOSSLESS: do not block, do not silently drop -- signal the bus.
            self._droppedCount += 1
            return False
        self._highWater = max(self._highWater, self._queue.qsize())
        return True

    def get(self, timeoutS: float | None = None) -> Sample | None:
        """Blocking drain. Returns None on timeout."""
        try:
            return self._queue.get(timeout=timeoutS)
        except queue.Empty:
            return None

    def poll(self) -> Sample | None:
        """Non-blocking drain. Returns None when empty."""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def close(self) -> None:
        self._closed = True

    def stats(self) -> SubStats:
        return SubStats(
            depth=self._queue.qsize(),
            highWater=self._highWater,
            droppedCount=self._droppedCount,
            lastSeqBySource=dict(self._lastSeqBySource),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/bus/test_subscription.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/pi/bus/bus.py tests/pi/bus/test_subscription.py
git commit -m "feat(bus): topicMatches + Subscription with QoS overflow + stats"
```

---

### Task 3: `SampleBus` core — subscribe / publish / fan-out (STREAM)

**Files:**
- Modify: `src/pi/bus/bus.py`
- Test: `tests/pi/bus/test_bus_stream.py`

**Interfaces:**
- Consumes: `Subscription`, `Sample`, `QoS`, `topicMatches` (Task 2).
- Produces: `SampleBus` with `subscribe(topics: list[str], qos: QoS, name: str, maxQueue: int = DEFAULT_MAX_QUEUE) -> Subscription` and `publish(sample: Sample, retain: bool = False) -> None`. Fan-out is synchronous within `publish()` (enqueue into each matching subscription); the queue buffer is the only async boundary, so the bus is fully unit-testable inline (publish then `poll()`), with no special "sync mode" needed.

- [ ] **Step 1: Write the failing test**

Create `tests/pi/bus/test_bus_stream.py`:

```python
from pi.bus.sample import Sample, QoS
from pi.bus.bus import SampleBus


def _sample(topic="raw.obd.RPM", seq=1, value=1.0, source="obd"):
    return Sample(topic=topic, source=source, value=value, unit=None,
                  tsUtc="2026-06-18T00:00:00Z", tsCapture=float(seq),
                  driveId=None, dataSource="real", seq=seq)


def test_publish_fansOutToMatchingSubscribersOnly():
    bus = SampleBus()
    raw = bus.subscribe(["raw.*"], QoS.LOSSLESS, "raw")
    obd = bus.subscribe(["raw.obd.RPM"], QoS.LOSSLESS, "rpm")
    derived = bus.subscribe(["derived.*"], QoS.LOSSY, "derived")

    bus.publish(_sample(topic="raw.obd.RPM", seq=1))

    assert raw.poll().seq == 1
    assert obd.poll().seq == 1
    assert derived.poll() is None  # no match


def test_publish_deliversAfterSubscribeOnly_streamHasNoHistory():
    bus = SampleBus()
    bus.publish(_sample(seq=1))                 # before any subscriber
    sub = bus.subscribe(["raw.*"], QoS.LOSSLESS, "late")
    bus.publish(_sample(seq=2))
    assert sub.poll().seq == 2                  # only the post-subscribe sample
    assert sub.poll() is None


def test_subscribe_returnsUsableSubscription():
    bus = SampleBus()
    sub = bus.subscribe(["raw.obd.*"], QoS.LOSSY, "x")
    assert sub.qos == QoS.LOSSY
    assert sub.topics == ["raw.obd.*"]


def test_publish_doesNotBlockWhenSubscriberNeverDrains():
    # The load-bearing invariant: a consumer that never drains cannot stall the
    # producer. publish() uses only non-blocking enqueue, so this must return.
    bus = SampleBus()
    bus.subscribe(["raw.*"], QoS.LOSSY, "wedged", maxQueue=2)
    bus.subscribe(["raw.*"], QoS.LOSSLESS, "wedgedLossless", maxQueue=2)
    for i in range(1000):
        bus.publish(_sample(seq=i))   # far exceeds both queues; must not hang
    # Reaching here proves publish never blocked on a full/undrained queue.
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/bus/test_bus_stream.py -v`
Expected: FAIL — `ImportError: cannot import name 'SampleBus'`.

- [ ] **Step 3: Add `SampleBus` to `bus.py`**

Append to `src/pi/bus/bus.py`:

```python
import threading


class SampleBus:
    """In-process publish/subscribe broker. One producer per source publishes;
    every consumer subscribes. ``publish`` never blocks (see Subscription._offer).
    """

    def __init__(self) -> None:
        self._subs: list[Subscription] = []
        self._lock = threading.Lock()
        self._retained: dict[str, Sample] = {}

    def subscribe(self, topics: list[str], qos: QoS, name: str,
                  maxQueue: int = DEFAULT_MAX_QUEUE) -> Subscription:
        sub = Subscription(name, topics, qos, maxQueue=maxQueue)
        with self._lock:
            self._subs.append(sub)
        return sub

    def publish(self, sample: Sample, retain: bool = False) -> None:
        """Fan ``sample`` out to every matching subscription. Never blocks."""
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            if sub.matches(sample.topic):
                sub._offer(sample)
```

(The `retain` parameter is wired in Task 4; `threading` import may already be added here — keep a single import at the top of the file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/bus/test_bus_stream.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/pi/bus/bus.py tests/pi/bus/test_bus_stream.py
git commit -m "feat(bus): SampleBus subscribe + publish fan-out (STREAM)"
```

---

### Task 4: STATE / retained topics (last-value-cache)

**Files:**
- Modify: `src/pi/bus/bus.py` (`SampleBus.publish` retain path + `subscribe` replay)
- Test: `tests/pi/bus/test_bus_state.py`

**Interfaces:**
- Produces: `publish(sample, retain=True)` stores latest-by-topic; `subscribe(...)` immediately delivers the current retained value for any matching retained topic to the new subscriber.

- [ ] **Step 1: Write the failing test**

Create `tests/pi/bus/test_bus_state.py`:

```python
from pi.bus.sample import Sample, QoS
from pi.bus.bus import SampleBus


def _state(topic, value, seq=1):
    return Sample(topic=topic, source="config", value=value, unit=None,
                  tsUtc="2026-06-18T00:00:00Z", tsCapture=float(seq),
                  driveId=None, dataSource="real", seq=seq)


def test_state_lateSubscriberGetsRetainedValue():
    bus = SampleBus()
    bus.publish(_state("state.config.serverHost", 1.0), retain=True)
    sub = bus.subscribe(["state.config.*"], QoS.LOSSLESS, "late")
    got = sub.poll()
    assert got is not None and got.topic == "state.config.serverHost"


def test_state_retainsLatestOnly():
    bus = SampleBus()
    bus.publish(_state("state.x", 1.0, seq=1), retain=True)
    bus.publish(_state("state.x", 2.0, seq=2), retain=True)
    sub = bus.subscribe(["state.*"], QoS.LOSSLESS, "s")
    got = sub.poll()
    assert got.seq == 2          # only the latest is replayed
    assert sub.poll() is None


def test_stream_isNotRetained():
    bus = SampleBus()
    bus.publish(_state("raw.obd.RPM", 1.0), retain=False)
    sub = bus.subscribe(["raw.*"], QoS.LOSSLESS, "s")
    assert sub.poll() is None    # streams have no replay
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/bus/test_bus_state.py -v`
Expected: FAIL — `test_state_lateSubscriberGetsRetainedValue` returns None.

- [ ] **Step 3: Implement retention**

In `src/pi/bus/bus.py`, replace `SampleBus.publish` and `SampleBus.subscribe` with:

```python
    def subscribe(self, topics: list[str], qos: QoS, name: str,
                  maxQueue: int = DEFAULT_MAX_QUEUE) -> Subscription:
        sub = Subscription(name, topics, qos, maxQueue=maxQueue)
        with self._lock:
            self._subs.append(sub)
            # Replay current retained values for any matching STATE topic.
            retained = [s for t, s in self._retained.items() if sub.matches(t)]
        for s in retained:
            sub._offer(s)
        return sub

    def publish(self, sample: Sample, retain: bool = False) -> None:
        """Fan ``sample`` out to every matching subscription. Never blocks.

        When ``retain`` is True the sample becomes the last-value-cache for its
        topic (STATE), delivered immediately to future subscribers.
        """
        with self._lock:
            if retain:
                self._retained[sample.topic] = sample
            subs = list(self._subs)
        for sub in subs:
            if sub.matches(sample.topic):
                sub._offer(sample)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/bus/test_bus_state.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/pi/bus/bus.py tests/pi/bus/test_bus_state.py
git commit -m "feat(bus): STATE retained topics (last-value-cache + replay-on-subscribe)"
```

---

### Task 5: Integrity-gap marker on LOSSLESS overflow

**Files:**
- Modify: `src/pi/bus/bus.py` (`SampleBus.publish` emits `event.integrity.gap` when a lossless `_offer` returns False)
- Test: `tests/pi/bus/test_bus_integrity_gap.py`

**Interfaces:**
- Produces: when a LOSSLESS subscription overflows, the bus publishes a `Sample` on topic `event.integrity.gap`, `source="bus"`, `value` = number of samples lost (float), `unit` = the overflowed subscription name, carrying the dropped sample's `seq`. Emitted to *other* subscribers (not re-offered to the overflowing one, to avoid recursion).

- [ ] **Step 1: Write the failing test**

Create `tests/pi/bus/test_bus_integrity_gap.py`:

```python
from pi.bus.sample import Sample, QoS
from pi.bus.bus import SampleBus


def _s(seq, topic="raw.obd.RPM"):
    return Sample(topic=topic, source="obd", value=float(seq), unit=None,
                  tsUtc="2026-06-18T00:00:00Z", tsCapture=float(seq),
                  driveId=None, dataSource="real", seq=seq)


def test_losslessOverflow_emitsIntegrityGapMarker():
    bus = SampleBus()
    # A tiny lossless consumer that will overflow, plus a watcher for markers.
    victim = bus.subscribe(["raw.obd.RPM"], QoS.LOSSLESS, "victim", maxQueue=1)
    watcher = bus.subscribe(["event.integrity.gap"], QoS.LOSSLESS, "watch")

    bus.publish(_s(1))   # fills victim
    bus.publish(_s(2))   # overflow -> gap marker

    marker = watcher.poll()
    assert marker is not None
    assert marker.topic == "event.integrity.gap"
    assert marker.source == "bus"
    assert marker.unit == "victim"     # which subscription lost data
    assert marker.seq == 2             # the lost sample's seq


def test_noOverflow_noMarker():
    bus = SampleBus()
    bus.subscribe(["raw.obd.RPM"], QoS.LOSSLESS, "ok", maxQueue=10)
    watcher = bus.subscribe(["event.integrity.gap"], QoS.LOSSLESS, "watch")
    bus.publish(_s(1))
    assert watcher.poll() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/bus/test_bus_integrity_gap.py -v`
Expected: FAIL — `marker` is None (no gap emission yet).

- [ ] **Step 3: Emit the marker in `publish`**

In `src/pi/bus/bus.py`, replace the fan-out loop in `publish` with:

```python
        gaps: list[tuple[str, int]] = []  # (subscriptionName, lostSeq)
        for sub in subs:
            if sub.matches(sample.topic):
                delivered = sub._offer(sample)
                if not delivered:
                    gaps.append((sub.name, sample.seq))
        # Honest instrument: a lossless loss is recorded explicitly, never silent.
        for subName, lostSeq in gaps:
            self._emitIntegrityGap(subName, lostSeq, sample.topic)
```

And add the helper (and ensure it does not recurse into the overflowing sub — it simply publishes a new marker sample; markers go to `event.integrity.gap` subscribers, which are distinct):

```python
    def _emitIntegrityGap(self, subName: str, lostSeq: int, lostTopic: str) -> None:
        marker = Sample(
            topic="event.integrity.gap", source="bus", value=1.0,
            unit=subName, tsUtc="", tsCapture=0.0, driveId=None,
            dataSource="real", seq=lostSeq,
        )
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            if sub.name != subName and sub.matches(marker.topic):
                sub._offer(marker)
```

(Note: `tsUtc`/`tsCapture` are stamped by the producer for real samples; the bus-internal marker leaves them empty/zero because the bus has no clock access — consistent with the no-`Date.now` discipline. A consumer that needs wall-clock reads its own.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/bus/test_bus_integrity_gap.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/pi/bus/bus.py tests/pi/bus/test_bus_integrity_gap.py
git commit -m "feat(bus): emit event.integrity.gap on lossless overflow (honest instrument)"
```

---

### Task 6: `PersistenceSubscriber` — writes `realtime_data` (byte-identical golden master)

**Files:**
- Create: `src/pi/bus/persistence_subscriber.py`
- Test: `tests/pi/bus/test_persistence_subscriber.py`

**Interfaces:**
- Consumes: `Subscription` (Task 2), and an `ObdDataLogger` (existing, `src/pi/obdii/data/logger.py`) with method `logReading(reading: LoggedReading) -> bool`; `LoggedReading` (`src/pi/obdii/data/types.py`: `parameterName, value, timestamp, unit=None, profileId=None`).
- Produces: `PersistenceSubscriber(subscription, dataLogger)` with `start() -> None`, `stop(timeoutS: float = 5.0) -> None`, and `handleSample(sample: Sample) -> bool` (the unit-testable per-sample handler the loop calls; reconstructs a `LoggedReading` from a `raw.obd.*` sample and calls `dataLogger.logReading`).

- [ ] **Step 1: Write the failing test (golden master + handler)**

Create `tests/pi/bus/test_persistence_subscriber.py`:

```python
from datetime import datetime
from unittest.mock import MagicMock

from pi.bus.sample import Sample, QoS
from pi.bus.bus import SampleBus
from pi.bus.persistence_subscriber import PersistenceSubscriber
from pi.obdii.data.types import LoggedReading


def _s(topic="raw.obd.RPM", value=3500.0, unit="rpm", seq=1):
    return Sample(topic=topic, source="obd", value=value, unit=unit,
                  tsUtc="2026-06-18T00:00:00Z", tsCapture=float(seq),
                  driveId=27, dataSource="real", seq=seq)


def test_handleSample_reconstructsLoggedReadingAndDelegatesToLogReading():
    logger = MagicMock()
    sub = SampleBus().subscribe(["raw.obd.*"], QoS.LOSSLESS, "persistence")
    ps = PersistenceSubscriber(sub, logger)

    assert ps.handleSample(_s(topic="raw.obd.RPM", value=3500.0, unit="rpm")) is True

    assert logger.logReading.call_count == 1
    reading = logger.logReading.call_args.args[0]
    assert isinstance(reading, LoggedReading)
    assert reading.parameterName == "RPM"
    assert reading.value == 3500.0
    assert reading.unit == "rpm"


def test_handleSample_derivesParameterNameFromTopicTail():
    logger = MagicMock()
    ps = PersistenceSubscriber(MagicMock(), logger)
    ps.handleSample(_s(topic="raw.obd.COOLANT_TEMP", value=92.0, unit="degC"))
    assert logger.logReading.call_args.args[0].parameterName == "COOLANT_TEMP"


def test_handleSample_ignoresNonRawObdTopics():
    logger = MagicMock()
    ps = PersistenceSubscriber(MagicMock(), logger)
    assert ps.handleSample(_s(topic="derived.gear", value=3.0)) is False
    logger.logReading.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/bus/test_persistence_subscriber.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pi.bus.persistence_subscriber'`.

- [ ] **Step 3: Implement `PersistenceSubscriber`**

Create `src/pi/bus/persistence_subscriber.py`:

```python
################################################################################
# File Name: persistence_subscriber.py
# Purpose/Description: Bus subscriber that persists raw.obd.* samples to the
#     realtime_data table by reusing the existing ObdDataLogger.logReading()
#     write path (guaranteeing byte-identical rows). EDR slice 1.
# Author: (assign)
# Creation Date: 2026-06-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

from __future__ import annotations

import logging
import threading
from datetime import datetime

from .bus import Subscription
from .sample import Sample

logger = logging.getLogger(__name__)

_RAW_OBD_PREFIX = "raw.obd."
_DRAIN_TIMEOUT_S = 0.5


class PersistenceSubscriber:
    """Drains a Subscription and writes each raw.obd.* Sample to realtime_data.

    Reuses ``ObdDataLogger.logReading`` so the persisted row is identical to the
    pre-bus inline path (drive_id, data_source, timestamp are derived exactly as
    before). Runs its own daemon thread; a stuck write cannot stall the producer.
    """

    def __init__(self, subscription: Subscription, dataLogger) -> None:
        self._sub = subscription
        self._dataLogger = dataLogger
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="PersistenceSubscriber", daemon=True)
        self._thread.start()

    def stop(self, timeoutS: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeoutS)

    def _loop(self) -> None:
        while not self._stop.is_set():
            sample = self._sub.get(timeoutS=_DRAIN_TIMEOUT_S)
            if sample is None:
                continue
            try:
                self.handleSample(sample)
            except Exception as e:  # subscriber isolation: never crash the loop
                logger.warning(f"PersistenceSubscriber write failed: {e}")

    def handleSample(self, sample: Sample) -> bool:
        """Write one raw.obd.* sample via the existing logReading path.

        Returns:
            True if a write was attempted; False if the topic was ignored.
        """
        if not sample.topic.startswith(_RAW_OBD_PREFIX):
            return False
        from pi.obdii.data.types import LoggedReading
        parameterName = sample.topic[len(_RAW_OBD_PREFIX):]
        reading = LoggedReading(
            parameterName=parameterName,
            value=sample.value,
            timestamp=datetime.now(),  # logReading stamps utcIsoNow() anyway
            unit=sample.unit,
            profileId=None,            # logReading falls back to dataLogger.profileId
        )
        self._dataLogger.logReading(reading)
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/bus/test_persistence_subscriber.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Write the golden-master integration test (real SQLite)**

Create `tests/pi/bus/test_persistence_golden_master.py`. This proves byte-identical
rows: the same readings written (a) directly via `logReading` and (b) via the
bus → `PersistenceSubscriber.handleSample` produce equal `realtime_data` rows on
the columns that matter (`parameter_name, value, unit, profile_id, drive_id,
data_source`; `id` and write-time `timestamp` are excluded).

```python
import pytest
from datetime import datetime

from pi.obdii.database import ObdDatabase
from pi.obdii.data.logger import ObdDataLogger
from pi.obdii.data.types import LoggedReading
from pi.bus.sample import Sample, QoS
from pi.bus.bus import SampleBus
from pi.bus.persistence_subscriber import PersistenceSubscriber

_COLS = "parameter_name, value, unit, profile_id, drive_id, data_source"


def _rows(db):
    with db.connect() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLS} FROM realtime_data ORDER BY id")
        return cur.fetchall()


def _newDb(tmp_path, name):
    db = ObdDatabase(str(tmp_path / name))
    db.initialize()
    return db


READINGS = [
    ("RPM", 3500.0, "rpm"),
    ("COOLANT_TEMP", 92.0, "degC"),
    ("SPEED", 64.0, "km/h"),
]


def test_busPathProducesByteIdenticalRealtimeRows(tmp_path):
    # (a) old path: logReading directly
    dbA = _newDb(tmp_path, "a.db")
    loggerA = ObdDataLogger(connection=None, database=dbA, profileId="daily",
                            dataSource="real")
    for name, val, unit in READINGS:
        loggerA.logReading(LoggedReading(name, val, datetime.now(), unit, None))

    # (b) new path: publish -> PersistenceSubscriber
    dbB = _newDb(tmp_path, "b.db")
    loggerB = ObdDataLogger(connection=None, database=dbB, profileId="daily",
                            dataSource="real")
    bus = SampleBus()
    sub = bus.subscribe(["raw.obd.*"], QoS.LOSSLESS, "persistence")
    ps = PersistenceSubscriber(sub, loggerB)
    for i, (name, val, unit) in enumerate(READINGS, start=1):
        bus.publish(Sample(topic=f"raw.obd.{name}", source="obd", value=val,
                           unit=unit, tsUtc="2026-06-18T00:00:00Z",
                           tsCapture=float(i), driveId=None, dataSource="real",
                           seq=i))
        ps.handleSample(sub.poll())   # drain inline -> deterministic

    assert _rows(dbA) == _rows(dbB)
```

> Note: if `ObdDataLogger.__init__` requires a different argument shape, adjust
> the two constructor calls to match `src/pi/obdii/data/logger.py` (the test's
> contract is "same constructor for both paths"). Verify the signature before
> running.

- [ ] **Step 6: Run the golden-master test**

Run: `pytest tests/pi/bus/test_persistence_golden_master.py -v`
Expected: PASS — both row sets equal.

- [ ] **Step 7: Commit**

```bash
git add src/pi/bus/persistence_subscriber.py tests/pi/bus/test_persistence_subscriber.py tests/pi/bus/test_persistence_golden_master.py
git commit -m "feat(bus): PersistenceSubscriber writes realtime_data; byte-identical golden master"
```

---

### Task 7: `RealtimeDataLogger` publish seam (the producer side)

**Files:**
- Modify: `src/pi/obdii/data/realtime.py` (`__init__` gains `bus`/`producerSource`; add `_seq`; branch `_logReadingSafe`; add `_publishReading`; add `dataLogger` property)
- Test: `tests/pi/obdii/data/test_realtime_bus_publish.py`

**Interfaces:**
- Consumes: `SampleBus.publish`, `Sample` (Tasks 1, 3); existing `LoggedReading`, `utcIsoNow` (`common.time.helper`), `getCurrentDriveId` (already imported in realtime.py).
- Produces: when `RealtimeDataLogger` is constructed with `bus=<SampleBus>`, `_logReadingSafe(reading)` publishes a `Sample` on `raw.obd.<parameterName>` instead of writing the DB; `dataLogger` property exposes the internal `ObdDataLogger` for the `PersistenceSubscriber` wiring.

- [ ] **Step 1: Write the failing test**

Create `tests/pi/obdii/data/test_realtime_bus_publish.py`:

```python
from datetime import datetime
from unittest.mock import MagicMock

from pi.obdii.data.realtime import RealtimeDataLogger
from pi.obdii.data.types import LoggedReading


def _logger(bus):
    # Minimal construction: real wiring is covered by lifecycle tests. We only
    # exercise the publish branch of _logReadingSafe here.
    rdl = RealtimeDataLogger.__new__(RealtimeDataLogger)
    rdl._bus = bus
    rdl._producerSource = "obd"
    rdl._seq = 0
    rdl._dataSource = "real"
    rdl._stats = MagicMock()
    rdl._markRowWritten = MagicMock()
    return rdl


def test_logReadingSafe_publishesSampleWhenBusPresent():
    bus = MagicMock()
    rdl = _logger(bus)
    reading = LoggedReading("RPM", 3500.0, datetime.now(), "rpm", None)

    assert rdl._logReadingSafe(reading) is True

    assert bus.publish.call_count == 1
    sample = bus.publish.call_args.args[0]
    assert sample.topic == "raw.obd.RPM"
    assert sample.value == 3500.0
    assert sample.unit == "rpm"
    assert sample.source == "obd"
    assert sample.seq == 1            # per-producer monotonic


def test_publishReading_incrementsSeqPerCall():
    bus = MagicMock()
    rdl = _logger(bus)
    rdl._logReadingSafe(LoggedReading("RPM", 1.0, datetime.now(), "rpm", None))
    rdl._logReadingSafe(LoggedReading("SPEED", 2.0, datetime.now(), "km/h", None))
    assert bus.publish.call_args_list[0].args[0].seq == 1
    assert bus.publish.call_args_list[1].args[0].seq == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/obdii/data/test_realtime_bus_publish.py -v`
Expected: FAIL — `_logReadingSafe` writes the DB (no `bus.publish`) / `_bus` attr absent.

- [ ] **Step 3: Add the bus seam to `realtime.py`**

In `src/pi/obdii/data/realtime.py`:

(3a) Add imports near the top (if not present):

```python
import time
from pi.bus.sample import Sample
```

(3b) In `__init__` (after the existing parameter assignments), add the new optional params to the signature and store them. Change the signature to include `bus` and `producerSource`:

```python
    def __init__(
        self,
        config: dict[str, Any],
        connection: Any,
        database: Any,
        profileId: str | None = None,
        dataSource: str | None = None,
        *,
        captureErrorHandler: Callable[[BaseException], CaptureErrorClass] | None = None,
        onFatalError: Callable[[BaseException], None] | None = None,
        ecuSilentMultiplier: int = DEFAULT_ECU_SILENT_MULTIPLIER,
        bus: Any = None,
        producerSource: str = "obd",
    ):
```

And in the body add:

```python
        self._bus = bus
        self._producerSource = producerSource
        self._seq = 0
```

(3c) Add a `dataLogger` property (so the subscriber can reuse the exact same `ObdDataLogger`):

```python
    @property
    def dataLogger(self):
        """The internal ObdDataLogger (reused by the bus PersistenceSubscriber)."""
        return self._dataLogger
```

(3d) Replace `_logReadingSafe` so it branches to publish when a bus is present:

```python
    def _logReadingSafe(self, reading: LoggedReading) -> bool:
        """Persist a reading. With a bus wired, publish a Sample instead of
        writing directly -- the PersistenceSubscriber owns the DB write."""
        if self._bus is not None:
            return self._publishReading(reading)
        try:
            self._dataLogger.logReading(reading)
            self._stats.totalLogged += 1
            self._markRowWritten()
            return True
        except Exception as e:
            logger.warning(f"Failed to log reading: {e}")
            self._stats.totalErrors += 1
            return False

    def _publishReading(self, reading: LoggedReading) -> bool:
        """Publish a raw.obd.<param> Sample to the bus (producer role)."""
        self._seq += 1
        sample = Sample(
            topic=f"raw.obd.{reading.parameterName}",
            source=self._producerSource,
            value=reading.value,
            unit=reading.unit,
            tsUtc=utcIsoNow(),
            tsCapture=time.monotonic(),
            driveId=getCurrentDriveId(),
            dataSource=self._dataSource or "real",
            seq=self._seq,
        )
        self._bus.publish(sample)
        self._stats.totalLogged += 1
        self._markRowWritten()
        return True
```

> Verify `utcIsoNow` and `getCurrentDriveId` are already imported in
> `realtime.py` (they are used by the existing write path per logger.py); if the
> import lives only in `logger.py`, add `from common.time.helper import utcIsoNow`
> and the existing `getCurrentDriveId` import to `realtime.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pi/obdii/data/test_realtime_bus_publish.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the existing realtime suite to confirm no regression (bus default off)**

Run: `pytest tests/pi/obdii/data/ -v`
Expected: PASS — with no `bus` argument, `_logReadingSafe` keeps the original write behavior.

- [ ] **Step 6: Commit**

```bash
git add src/pi/obdii/data/realtime.py tests/pi/obdii/data/test_realtime_bus_publish.py
git commit -m "feat(bus): RealtimeDataLogger publish seam (producer role, default off)"
```

---

### Task 8: Config flag `pi.bus.enabled` (default off)

**Files:**
- Modify: `src/common/config/validator.py` (DEFAULTS)
- Modify: `config.json` (add `pi.bus`)
- Test: `tests/test_config_validator.py` (add a default assertion)

**Interfaces:**
- Produces: `config['pi']['bus']['enabled']` resolves to `False` by default; settable to `True` in `config.json`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config_validator.py` (within an appropriate test class):

```python
    def test_validate_busDefault_disabled(self):
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate(self._minimalTierConfig())
        assert result['pi']['bus']['enabled'] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_validator.py -k busDefault -v`
Expected: FAIL — `KeyError: 'bus'`.

- [ ] **Step 3: Add the default + config entry**

In `src/common/config/validator.py` DEFAULTS registry, add (near the other `pi.*` entries):

```python
    'pi.bus.enabled': False,
```

In `config.json`, add a `bus` block inside the `pi` section (sibling of `sync`):

```json
    "bus": {
      "enabled": false
    },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config_validator.py -v && python validate_config.py`
Expected: PASS; `validate_config.py` reports all validations passed.

- [ ] **Step 5: Commit**

```bash
git add src/common/config/validator.py config.json tests/test_config_validator.py
git commit -m "feat(bus): pi.bus.enabled config flag (default off)"
```

---

### Task 9: Orchestrator wiring (flag-gated) + end-to-end integration

**Files:**
- Modify: `src/pi/obdii/orchestrator/lifecycle.py` (`_initializeDataLogger` builds bus + subscriber when flag on, injects bus into the logger)
- Modify: `src/pi/obdii/data/__init__.py` (`createRealtimeLoggerFromConfig` forwards a `bus` argument) — verify the factory signature first.
- Test: `tests/pi/obdii/orchestrator/test_lifecycle_bus_wiring.py`

**Interfaces:**
- Consumes: `SampleBus`, `PersistenceSubscriber`, `QoS`, the `dataLogger` property (Tasks 3, 6, 7), `createRealtimeLoggerFromConfig`.
- Produces: when `pi.bus.enabled` is True, the orchestrator owns a `SampleBus`, starts a `PersistenceSubscriber` on `["raw.obd.*"]` (LOSSLESS) bound to the logger's `dataLogger`, and the logger publishes to that bus; when False, behavior is exactly as today.

- [ ] **Step 1: Write the failing test**

Create `tests/pi/obdii/orchestrator/test_lifecycle_bus_wiring.py`:

```python
from unittest.mock import MagicMock, patch


def _orch(busEnabled):
    from pi.obdii.orchestrator.lifecycle import LifecycleMixin  # adjust to real class
    orch = LifecycleMixin.__new__(LifecycleMixin)
    orch._config = {"pi": {"bus": {"enabled": busEnabled}}}
    orch._connection = MagicMock()
    orch._database = MagicMock()
    orch.handleCaptureError = MagicMock()
    orch._onCaptureFatalError = MagicMock()
    return orch


def test_busDisabled_noSubscriberNoBus():
    orch = _orch(busEnabled=False)
    with patch("pi.obdii.data.createRealtimeLoggerFromConfig") as factory:
        factory.return_value = MagicMock()
        orch._initializeDataLogger()
    assert getattr(orch, "_sampleBus", None) is None
    # factory called without a bus kwarg
    assert factory.call_args.kwargs.get("bus") is None


def test_busEnabled_buildsBusAndStartsPersistenceSubscriber():
    orch = _orch(busEnabled=True)
    fakeLogger = MagicMock()
    with patch("pi.obdii.data.createRealtimeLoggerFromConfig", return_value=fakeLogger):
        orch._initializeDataLogger()
    assert orch._sampleBus is not None
    assert orch._persistenceSubscriber is not None
    # the logger was given the bus
    assert orch._dataLogger is fakeLogger
```

> Adjust `LifecycleMixin` / attribute names to the actual class in
> `src/pi/obdii/orchestrator/lifecycle.py` (verify before writing the impl).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pi/obdii/orchestrator/test_lifecycle_bus_wiring.py -v`
Expected: FAIL — `_sampleBus` attribute absent / factory not passed a bus.

- [ ] **Step 3: Wire it in `_initializeDataLogger`**

In `src/pi/obdii/orchestrator/lifecycle.py`, replace the body of `_initializeDataLogger` with:

```python
    def _initializeDataLogger(self) -> None:
        """Initialize the realtime data logger; when pi.bus.enabled, route the
        OBD reader through the SampleBus and a PersistenceSubscriber."""
        logger.info("Starting dataLogger...")
        self._sampleBus = None
        self._persistenceSubscriber = None
        busEnabled = bool(
            self._config.get("pi", {}).get("bus", {}).get("enabled", False))
        try:
            from ..data import createRealtimeLoggerFromConfig
            bus = None
            if busEnabled:
                from pi.bus.bus import SampleBus
                bus = SampleBus()
                self._sampleBus = bus
            self._dataLogger = createRealtimeLoggerFromConfig(
                self._config, self._connection, self._database,
                captureErrorHandler=self.handleCaptureError,
                onFatalError=self._onCaptureFatalError,
                bus=bus,
            )
            if busEnabled:
                from pi.bus.sample import QoS
                from pi.bus.persistence_subscriber import PersistenceSubscriber
                sub = bus.subscribe(["raw.obd.*"], QoS.LOSSLESS, "persistence")
                self._persistenceSubscriber = PersistenceSubscriber(
                    sub, self._dataLogger.dataLogger)
                self._persistenceSubscriber.start()
                logger.info("SampleBus + PersistenceSubscriber started (pi.bus.enabled).")
            logger.info("DataLogger started successfully")
        except ImportError:
            logger.warning("DataLogger not available, skipping")
        except Exception as e:
            logger.error(f"Failed to initialize dataLogger: {e}")
            raise ComponentInitializationError(
                f"DataLogger initialization failed: {e}",
                component='dataLogger') from e
```

(3b) In `src/pi/obdii/data/__init__.py`, ensure `createRealtimeLoggerFromConfig`
accepts and forwards `bus` (and `producerSource` if desired). Verify its current
signature; add `bus=None` and pass it through to `RealtimeDataLogger(...)`.

- [ ] **Step 4: Add shutdown handling for the subscriber**

Find where the orchestrator stops the data logger (the reverse-init shutdown path)
and add, before/after stopping the logger:

```python
        if getattr(self, "_persistenceSubscriber", None) is not None:
            self._persistenceSubscriber.stop()
```

- [ ] **Step 5: Run the wiring test + targeted suites**

Run: `pytest tests/pi/obdii/orchestrator/test_lifecycle_bus_wiring.py tests/pi/bus/ tests/pi/obdii/data/ -v`
Expected: PASS.

- [ ] **Step 6: Full fast suite (no regression with flag off)**

Run: `pytest tests/ -m "not slow" -q`
Expected: PASS — default-off means the running system is unchanged.

- [ ] **Step 7: Commit**

```bash
git add src/pi/obdii/orchestrator/lifecycle.py src/pi/obdii/data/__init__.py tests/pi/obdii/orchestrator/test_lifecycle_bus_wiring.py
git commit -m "feat(bus): orchestrator wiring behind pi.bus.enabled (slice 1 cutover, default off)"
```

---

## Post-plan notes

- **Shipping dark:** the flag defaults off, so slice 1 merges with zero behavioral change. Flipping `pi.bus.enabled=true` on the Pi (and observing byte-identical `realtime_data` + sync) is a separate, CIO/PM-gated deploy step — not part of this plan.
- **Deferred to later slices (per spec §7):** durable spill for lossless overflow (slice 1 emits the gap marker directly; realistic OBD load never overflows); display → subscriber (slice 2); detector → subscriber (slice 3); IMU/light producers + structured IMU table (slice 4); transform tier + safety triggers + EDR vault (slice 5).
- **Deferred robustness (spec §5):** auto-detaching a chronically-failing subscriber after repeated exceptions. Slice 1 provides loop-level isolation (an exception in `PersistenceSubscriber._loop` is caught and logged, never crashing the producer or other subscribers); automatic detach-after-N-failures is a later hardening with one trusted subscriber in play.
- **Deferred correctness refinement:** writing `drive_id` from the captured `Sample.driveId` (capture-time attribution) rather than `getCurrentDriveId()` at write time. Slice 1 reuses `logReading` verbatim for byte-identical proof; capture-time attribution is a follow-up that also hardens against the A-9 boundary-race class.
- **Verify-before-impl flags in the plan:** the exact `ObdDataLogger.__init__` signature (Task 6 golden master), the `createRealtimeLoggerFromConfig` signature and the orchestrator class/attribute names (Task 9), and whether `utcIsoNow`/`getCurrentDriveId` are already imported in `realtime.py` (Task 7). Each is called out at its step.
