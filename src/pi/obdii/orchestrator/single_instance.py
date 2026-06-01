################################################################################
# File Name: single_instance.py
# Purpose/Description: Single-instance guard for the eclipse-obd orchestrator.
#                      Prevents two concurrent ApplicationOrchestrator processes
#                      from running at once -- the F-107 Mechanism B from the
#                      US-360 RCA: the Drive 23/24 production dual-attribution was
#                      two concurrent emitter processes, each with its own
#                      DriveDetector + process-global drive_id, both minting from
#                      the shared drive_counter and time-overlapping one physical
#                      leg.  A pidfile lock with a process-liveness check makes the
#                      second starter refuse, so one leg cannot be split across two
#                      minting processes.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-361) | Initial -- pidfile guard with an injectable
#                               process-liveness seam.  Defense-in-depth partner
#                               to the detector.py ECU-silence continuation guard
#                               (Mechanism A).  Wired default-OFF into the
#                               orchestrator lifecycle pending Atlas Rule 10 +
#                               CIO review (see F-107 PRD / US-361).
# ================================================================================
################################################################################

"""Single-instance guard for the orchestrator (F-107 Mechanism B prevention).

The guard is a classic pidfile lock:

* :meth:`SingleInstanceGuard.acquire` writes the current process id to the lock
  path.  If the path already holds a *different, still-alive* pid, it raises
  :class:`SingleInstanceError` -- this is the structural prevention of two
  concurrent orchestrators double-minting drive_ids.  A pidfile holding our own
  pid or a *stale* (dead) foreign pid is reclaimed.
* :meth:`SingleInstanceGuard.release` removes the pidfile only if this guard
  owns it (so a refused acquire never deletes the live holder's lock).

Process liveness is resolved through an injectable ``isAliveFn`` seam so the
behavior is unit-testable without spawning real processes.  The default
implementation (:func:`processIsAlive`) is cross-platform and -- importantly on
Windows -- never uses ``os.kill(pid, 0)``, which would terminate the target
process rather than probe it.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class SingleInstanceError(RuntimeError):
    """Raised when another live orchestrator already holds the instance lock."""


def processIsAlive(pid: int) -> bool:
    """Return whether a process with ``pid`` is currently running.

    Cross-platform and non-destructive:

    * POSIX: ``os.kill(pid, 0)`` probes without delivering a signal -- a
      ``ProcessLookupError`` means dead; ``PermissionError`` means alive but
      owned by another user (still alive).
    * Windows: ``os.kill(pid, 0)`` would call ``TerminateProcess`` (it would
      KILL the target), so we probe via ``OpenProcess`` + ``GetExitCodeProcess``
      through ``ctypes`` instead.

    Args:
        pid: Candidate process id.

    Returns:
        ``True`` if a process with that id appears to be running.
    """
    if pid <= 0:
        return False

    if os.name == "nt":  # pragma: no cover - exercised only on Windows dev boxes
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259  # STILL_ACTIVE

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if not handle:
            return False
        try:
            exitCode = wintypes.DWORD()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exitCode))
            if not ok:
                return False
            return exitCode.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class SingleInstanceGuard:
    """Pidfile-based single-instance lock for the orchestrator.

    Args:
        lockPath: Filesystem path of the pidfile.
        pid: Process id to stamp; defaults to the current process.
        isAliveFn: Liveness probe for a foreign pid.  Defaults to
            :func:`processIsAlive`; tests inject a deterministic stub.
    """

    def __init__(
        self,
        lockPath: str | os.PathLike[str],
        *,
        pid: int | None = None,
        isAliveFn: Callable[[int], bool] | None = None,
    ) -> None:
        self._lockPath = Path(lockPath)
        self._pid = pid if pid is not None else os.getpid()
        self._isAlive = isAliveFn if isAliveFn is not None else processIsAlive
        self._owned = False

    def acquire(self) -> None:
        """Acquire the instance lock or refuse if a live peer holds it.

        Raises:
            SingleInstanceError: When the pidfile is held by a different,
                still-alive process.
        """
        holder = self._readHolderPid()
        if holder is not None and holder != self._pid and self._isAlive(holder):
            raise SingleInstanceError(
                f"another eclipse-obd orchestrator (pid={holder}) is already "
                f"running; refusing to start a second instance "
                f"(lock={self._lockPath})"
            )

        if holder is not None and holder != self._pid:
            logger.warning(
                "reclaiming stale orchestrator lock | lock=%s | stale_pid=%s",
                self._lockPath, holder,
            )

        self._lockPath.parent.mkdir(parents=True, exist_ok=True)
        self._lockPath.write_text(str(self._pid), encoding="utf-8")
        self._owned = True
        logger.info(
            "single-instance lock acquired | lock=%s | pid=%s",
            self._lockPath, self._pid,
        )

    def release(self) -> None:
        """Remove the pidfile, but only if this guard owns the lock."""
        if not self._owned:
            return
        try:
            self._lockPath.unlink(missing_ok=True)
        except OSError as e:  # pragma: no cover - filesystem edge
            logger.warning(
                "failed to remove single-instance lock | lock=%s | error=%s",
                self._lockPath, e,
            )
        finally:
            self._owned = False

    def _readHolderPid(self) -> int | None:
        """Read the pid currently stamped in the lockfile, or None if absent."""
        try:
            raw = self._lockPath.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError as e:  # pragma: no cover - filesystem edge
            logger.warning(
                "unreadable single-instance lock | lock=%s | error=%s",
                self._lockPath, e,
            )
            return None
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            # Corrupt lock content -- treat as no holder so we can reclaim it.
            logger.warning(
                "corrupt single-instance lock content %r | lock=%s",
                raw, self._lockPath,
            )
            return None
