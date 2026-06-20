################################################################################
# File Name: bus.py
# Purpose/Description: In-process publish/subscribe SampleBus + Subscription for
#     the Pi data pipeline (EDR slice 1). US-380 adds topicMatches() + the
#     Subscription bounded-queue/QoS-overflow core; SampleBus (US-381+) appends
#     here later. See docs/superpowers/specs/
#     2026-06-18-edr-dedicated-reader-bus-contract-design.md (4-5).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-19    | Rex          | Initial implementation for US-380 (topicMatches,
#               |              | SubStats, Subscription)
# 2026-06-19    | Rex          | US-381: add SampleBus (subscribe/publish fan-out,
#               |              | STREAM, never-block)
# 2026-06-19    | Rex          | US-382: activate STATE retained topics (last-value
#               |              | -cache + replay-on-subscribe) + emit
#               |              | event.integrity.gap on LOSSLESS overflow
# ================================================================================
################################################################################

"""Topic matching + the per-consumer Subscription queue for the SampleBus."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass

from .sample import QoS, Sample

DEFAULT_MAX_QUEUE = 10000


def topicMatches(pattern: str, topic: str) -> bool:
    """Return True if a subscription ``pattern`` matches a sample ``topic``.

    Patterns are dotted segment-prefix with an optional trailing ``*``:
    ``"raw.*"`` matches ``"raw"`` and any ``"raw.<...>"``; an exact pattern
    matches only itself. Not a regex (by design).

    Args:
        pattern: The subscription pattern (exact, or dotted prefix + ``.*``).
        topic: The published sample's topic.

    Returns:
        True on a match, else False.
    """
    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        return topic == prefix or topic.startswith(prefix + ".")
    return topic == pattern


@dataclass(frozen=True)
class SubStats:
    """Point-in-time observability snapshot for a Subscription.

    Args:
        depth: Current number of queued samples.
        highWater: Greatest depth ever observed (post-enqueue).
        droppedCount: Samples dropped (LOSSY) or refused (LOSSLESS overflow).
        lastSeqBySource: Most recent ``seq`` seen per producer ``source``.
    """

    depth: int
    highWater: int
    droppedCount: int
    lastSeqBySource: dict[str, int]


class Subscription:
    """A consumer's view of the bus: a bounded queue + QoS overflow policy.

    The owning consumer drains via :meth:`get` (blocking) or :meth:`poll`
    (non-blocking) on its own thread. Producers never call these.
    """

    def __init__(
        self,
        name: str,
        topics: list[str],
        qos: QoS,
        maxQueue: int = DEFAULT_MAX_QUEUE,
    ):
        """Create a subscription.

        Args:
            name: Human-readable subscription id (used in gap markers).
            topics: Patterns this subscription matches (see :func:`topicMatches`).
            qos: Overflow policy when the bounded queue is full.
            maxQueue: Maximum queued samples before the QoS policy applies.
        """
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

        Args:
            sample: The sample to enqueue.

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
        """Mark this subscription closed (consumer-side lifecycle flag)."""
        self._closed = True

    def stats(self) -> SubStats:
        """Return a point-in-time observability snapshot."""
        return SubStats(
            depth=self._queue.qsize(),
            highWater=self._highWater,
            droppedCount=self._droppedCount,
            lastSeqBySource=dict(self._lastSeqBySource),
        )


class SampleBus:
    """In-process publish/subscribe broker.

    One producer per source publishes; every consumer subscribes. Fan-out is
    synchronous within :meth:`publish` (a non-blocking ``_offer`` into each
    matching subscription), so the bounded subscription queue is the only async
    boundary -- ``publish`` NEVER blocks, even when a consumer never drains.

    STREAM topics carry no history: a subscriber created after a publish does
    not receive that earlier sample. STATE topics (``publish(retain=True)``) are
    a last-value-cache, replayed once to every new matching subscriber. A
    LOSSLESS subscription overflow is an honest instrument: instead of silently
    dropping, the bus publishes ``event.integrity.gap`` to the OTHER subscribers.
    """

    def __init__(self) -> None:
        """Create an empty broker with no subscribers and no retained state."""
        self._subs: list[Subscription] = []
        self._lock = threading.Lock()
        self._retained: dict[str, Sample] = {}

    def subscribe(
        self,
        topics: list[str],
        qos: QoS,
        name: str,
        maxQueue: int = DEFAULT_MAX_QUEUE,
    ) -> Subscription:
        """Register and return a new Subscription.

        Args:
            topics: Patterns the subscription matches (see :func:`topicMatches`).
            qos: Overflow policy for the subscription's bounded queue.
            name: Human-readable subscription id (used in gap markers).
            maxQueue: Maximum queued samples before the QoS policy applies.

        Returns:
            A usable :class:`Subscription` the caller drains on its own thread.
        """
        sub = Subscription(name, topics, qos, maxQueue=maxQueue)
        with self._lock:
            self._subs.append(sub)
            # Replay the current retained value for any matching STATE topic, so
            # a late subscriber sees the latest slowly-changing state at once.
            retained = [s for t, s in self._retained.items() if sub.matches(t)]
        for s in retained:
            sub._offer(s)
        return sub

    def publish(self, sample: Sample, retain: bool = False) -> None:
        """Fan ``sample`` out to every matching subscription. Never blocks.

        When ``retain`` is True the sample becomes the last-value-cache for its
        topic (STATE), delivered immediately to future matching subscribers. A
        LOSSLESS subscription that overflows triggers an ``event.integrity.gap``
        marker to the other subscribers -- a loss is recorded, never silent.

        Args:
            sample: The sample to deliver.
            retain: When True, store ``sample`` as the STATE last-value-cache for
                its topic (replayed on subscribe). STREAM publishes are not kept.
        """
        with self._lock:
            if retain:
                self._retained[sample.topic] = sample
            subs = list(self._subs)
        gaps: list[tuple[str, int]] = []  # (subscriptionName, lostSeq)
        for sub in subs:
            if sub.matches(sample.topic):
                delivered = sub._offer(sample)
                if not delivered:
                    gaps.append((sub.name, sample.seq))
        # Honest instrument: a LOSSLESS loss is recorded explicitly, never silent.
        for subName, lostSeq in gaps:
            self._emitIntegrityGap(subName, lostSeq, sample.topic)

    def _emitIntegrityGap(self, subName: str, lostSeq: int, lostTopic: str) -> None:
        """Publish an ``event.integrity.gap`` marker for a LOSSLESS overflow.

        The marker carries the overflowed subscription name in ``unit`` and the
        lost sample's ``seq``. It is offered to every OTHER matching subscriber
        (never back to the overflowing one, which would just overflow again).

        Args:
            subName: Name of the subscription that overflowed.
            lostSeq: The ``seq`` of the sample that could not be delivered.
            lostTopic: The topic whose delivery was lost (context only).
        """
        marker = Sample(
            topic="event.integrity.gap",
            source="bus",
            value=1.0,
            unit=subName,
            tsUtc="",
            tsCapture=0.0,
            driveId=None,
            dataSource="real",
            seq=lostSeq,
        )
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            if sub.name != subName and sub.matches(marker.topic):
                sub._offer(marker)
