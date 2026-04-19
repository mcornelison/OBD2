"""
Pi-tier network detection package (US-188, B-043 component 1).

Detection-only building block for the future PowerLossOrchestrator (US-189,
Sprint 14).  Answers two questions:

* Is the Pi on the home WiFi (SSID match AND subnet match)?
* Is the Chi-Srv-01 companion service reachable (bounded ping)?

The composed :meth:`HomeNetworkDetector.getHomeNetworkState` folds both
into a single :class:`HomeNetworkState` enum the orchestrator will branch
on at shutdown time.  Scope is strictly detection -- no subscriptions, no
shutdown, no sync.  See ``offices/pm/backlog/B-043`` for the orchestrator
piece.
"""

from __future__ import annotations

from src.pi.network.home_detector import HomeNetworkDetector, HomeNetworkState

__all__ = ["HomeNetworkDetector", "HomeNetworkState"]
