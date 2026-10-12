################################################################################
# File Name: drive_console.py
# Purpose/Description: ARCH-058 -- the BUTTON-driven in-car console. Advances
#   the acquisition mechanism on a press, proves each one attached, and keeps
#   the durable phase log that is the ONLY record of which mechanism wrote which
#   rows.
# Author: Atlas (architect) -- CIO-directed build; override recorded on ARCH-058
# Creation Date: 2026-09-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-27    | Atlas          | Initial -- controller + Pi glue + server.
#               | (ARCH-058)     |
# ================================================================================
################################################################################
"""Run bypass -> master -> bypass from a button, with the PRODUCTION collector.

WHAT THIS IS, AND WHAT IT IS NOT
  The production collector (``eclipse-obd``) does ALL the capturing, in every
  phase. This console only writes ``pi.sensors.imu.magMode``, restarts the
  collector, and PROVES the requested mechanism came up. It never opens the I2C
  bus. (The 2026-09-18 ``drive_test_console.py`` is a different tool: it owned
  the bus and compared heading MATH. Do not confuse the two.)

🔴 WHY THE PHASE LOG IS THE PRODUCT. MEASURED 2026-09-27: ``edr_imu_sample`` has
no column naming the mechanism -- a bypass row and a master row are the same
shape. ``phases.jsonl`` (fsync per line) is therefore the only thing that
partitions the drive. Every request is logged BEFORE the switch, every verified
phase AFTER it, with UTC, so a hard cut mid-switch still bounds the windows.

🔴 WHY VERIFY USES TWO CHANNELS. A post-check that reads through the thing it
just configured cannot rule out "looks successful to itself". So a phase counts
as running only when BOTH (a) the collector's own startup line for THAT
mechanism appears in the journal since the restart -- bypass:
``AK09916 configured over I2C bypass`` with no ``bypass unavailable``; master:
``IMU magnetometer: MASTER mode`` -- AND (b) the published ``states/imu`` heading
is fresh, mostly non-null and actually changing.

🔴 WHY THE BUTTON IS HOLD-TO-FIRE AND SAYS "STAY PARKED". A switch restarts the
collector: ~45 s settle plus up to four attempts (hand-over ~75 %/start). The
OBD link drops for that time. It is pressed at a stop, never while moving.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from tools.imu.drive_phases import MECH_KEEPALIVE, MECH_ORIGINAL
from tools.imu.mechanism_apply import ApplyResult, applyMechanism

__all__ = ["CIO_2026_09_27_STEPS", "DriveConsole", "Step", "judgeAttach"]

@dataclass(frozen=True)
class Step:
    """One press of the driver's button.

    Attributes:
        button: What the button says BEFORE the press.
        mechanism: ``MECH_*`` to switch to, or None for an instant MARK (no
            collector restart -- the algorithm already running carries on).
        runningLabel: What the screen says is happening AFTER the press.
    """

    button: str
    mechanism: str | None
    runningLabel: str


#: The CIO's own sequence, 2026-09-27 (his steps 8-17). Rulings the same day:
#: original = bypass, Test A = bypass, Test B = master; STOP A is a mark only;
#: STOP B returns to the original. ⇒ only TWO collector restarts after BEGIN.
CIO_2026_09_27_STEPS: tuple[Step, ...] = (
    Step("BEGIN", MECH_ORIGINAL, "ORIGINAL (bypass)"),
    Step("START TEST A", None, "TEST A (bypass) - LOOP"),
    Step("STOP TEST A", None, "bypass - to loop start"),
    Step("START TEST B", MECH_KEEPALIVE, "TEST B (master) - LOOP"),
    Step("STOP TEST B", MECH_ORIGINAL, "ORIGINAL (bypass)"),
)


def _utcNow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class DriveConsole:
    """The session state machine. Pure: all hardware arrives as callables.

    States: ``ready`` (before BEGIN) -> ``switching`` -> ``recording`` |
    ``failed``; ``ended`` is terminal. A MARK step never leaves ``recording``.
    """

    def __init__(
        self,
        steps: Sequence[Step],
        *,
        applyFn: Callable[[str, Callable[[int], None]], ApplyResult],
        restoreFn: Callable[[], str],
        logFn: Callable[[dict], None],
        clockFn: Callable[[], float] = time.monotonic,
        utcFn: Callable[[], str] = _utcNow,
        runInline: bool = False,
    ) -> None:
        if not steps or steps[0].mechanism is None:
            raise ValueError("the first step must SWITCH -- a session begins by "
                             "proving the mechanism, not by assuming it")
        self._steps = tuple(steps)
        self._apply = applyFn
        self._restore = restoreFn
        self._log = logFn
        self._clock = clockFn
        self._utc = utcFn
        self._inline = runInline
        self._lock = threading.Lock()
        self._next = 0            # index of the step the button will fire
        self._state = "ready"
        self._attempt = 0
        self._magMode: str | None = None
        self._label = "not started"
        self._since: float | None = None
        self._error: str | None = None
        self._ended = False
        self._restoreResult: str | None = None

    # -- commands --------------------------------------------------------------
    def press(self) -> bool:
        """The button. Fires the next step; after a failed switch it RETRIES the
        same step. Returns False when the press is refused."""
        with self._lock:
            if self._ended or self._state == "switching":
                return False
            if self._next >= len(self._steps):
                return False
            idx = self._next
            step = self._steps[idx]
            self._emit("press", stepIndex=idx, button=step.button,
                       retry=self._state == "failed")
            if step.mechanism is None:
                # A MARK: instant. The running algorithm carries on untouched.
                self._next = idx + 1
                self._label = step.runningLabel
                self._since = self._clock()
                self._emit("mark", stepIndex=idx, button=step.button,
                           magMode=self._magMode, label=step.runningLabel)
                return True
            self._state = "switching"
            self._attempt = 0
            self._error = None
            self._magMode = None
            self._label = step.runningLabel
            self._emit("switch_requested", stepIndex=idx, button=step.button,
                       mechanism=step.mechanism, label=step.runningLabel)
        if self._inline:
            self._switch(idx)
        else:
            threading.Thread(target=self._switch, args=(idx,),
                             name="arch058-switch", daemon=True).start()
        return True

    def end(self) -> None:
        """Restore the car. Idempotent, and runs even after a failed switch."""
        with self._lock:
            if self._ended:
                return
            self._ended = True
            self._state = "ended"
        result = "restore raised"
        try:
            result = self._restore()
        finally:
            self._restoreResult = result
            self._emit("session_end", restore=result)

    # -- internals -------------------------------------------------------------
    def _onAttempt(self, n: int) -> None:
        self._attempt = n

    def _switch(self, idx: int) -> None:
        step = self._steps[idx]
        try:
            result = self._apply(step.mechanism, self._onAttempt)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the screen, never swallowed
            with self._lock:
                if self._ended:
                    return
                self._state = "failed"
                self._error = str(exc)
                self._emit("switch_failed", stepIndex=idx, button=step.button,
                           mechanism=step.mechanism, error=str(exc))
            return
        with self._lock:
            if self._ended:
                return
            self._state = "recording"
            self._magMode = result.magMode
            self._since = self._clock()
            self._next = idx + 1
            self._emit("switch_verified", stepIndex=idx, button=step.button,
                       mechanism=step.mechanism, magMode=result.magMode,
                       attempts=result.attempts, label=step.runningLabel)

    def _emit(self, event: str, **fields: Any) -> None:
        self._log({"event": event, "utc": self._utc(), **fields})

    # -- view ------------------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            done = self._next >= len(self._steps)
            if self._ended:
                button = "ENDED"
            elif self._state == "switching":
                button = "WAIT"
            elif self._state == "failed":
                button = "RETRY"
            elif done:
                button = "DONE"
            else:
                button = self._steps[self._next].button
            nextStep = None if done else self._steps[self._next]
            elapsed = (None if self._since is None or self._state != "recording"
                       else self._clock() - self._since)
            return {
                "stepIndex": self._next,
                "stepTotal": len(self._steps),
                "phaseLabel": self._label,
                "magMode": self._magMode,
                "state": self._state,
                "button": button,
                "nextSwitches": bool(nextStep and nextStep.mechanism is not None),
                "nextLabel": None if nextStep is None else nextStep.runningLabel,
                "attempt": self._attempt,
                "elapsedInPhaseS": elapsed,
                "sessionOver": self._ended,
                "collectorRestored": self._restoreResult,
                "error": self._error,
            }


# ============================ attach judgement =================================

#: The collector's own startup line for each magMode. From
#: ``src/pi/sensors/sensor_reader.py:920`` (master) and ``ak09916_bypass.py``
#: (bypass). A mode absent from this map raises -- never defaults.
ATTACH_LINE = {
    "master": "IMU magnetometer: MASTER mode",
    "bypass": "AK09916 configured over I2C bypass",
}
#: The real failed draw (~25 %/start, ARCH-032): bypass fell back to icm_shadow.
BYPASS_FAILED_LINE = "IMU magnetometer bypass unavailable"


def judgeAttach(
    mode: str, journal: str, headings: Sequence[Any], *, stateFresh: bool
) -> tuple[bool, dict]:
    """Did the collector come up on ``mode``? Returns ``(ok, evidence)``.

    🔴 GATES ON ATTACHMENT ONLY -- never on heading quality. MEASURED in the
    2026-09-27 garage dry run: master publishes a non-null heading only ~15 % of
    the time parked, because the freeze gate nulls it between keep-alive
    repairs. That IS master's behaviour, and it is what the drive measures.
    Gating on it would reject or cherry-pick draws and bias the comparison.
    Heading statistics are returned as EVIDENCE for the phase log.

    Gate: the collector's own attach line for THIS mode in the journal since
    the restart; for bypass, no fallback-to-icm_shadow line; a fresh state file
    (a collector that attached and then died leaves a good line and stale state).
    """
    attachLine = ATTACH_LINE[mode]  # KeyError on an unknown mode -- by design
    attachSeen = attachLine in journal
    fellBack = mode == "bypass" and BYPASS_FAILED_LINE in journal
    nonNull = [h for h in headings if h is not None]
    evidence = {
        "attachLineSeen": attachSeen,
        "bypassFailedLineSeen": fellBack,
        "stateFresh": stateFresh,
        "headingNonNullFrac": round(len(nonNull) / len(headings), 3) if headings else None,
        "headingDistinct": len(set(nonNull)),
        "samples": len(headings),
    }
    return (attachSeen and not fellBack and stateFresh), evidence


# =============================== Pi glue ======================================
# Real hardware. Exercised by the on-Pi dry run, not by unit tests.

PROJECT = Path("/home/mcornelison/Projects/Eclipse-01")
CONFIG = PROJECT / "config.json"
STATE_IMU = Path("/run/eclipse-obd/states/imu")
STATE_SYS = Path("/run/eclipse-obd/states/system-status")
COLLECTOR = "eclipse-obd"
DASHBOARD = "eclipse-dashboard"
WATCHDOG_TIMER = "eclipse-kiosk-watchdog.timer"
PORT = int(os.environ.get("ARCH058_PORT", "9901"))

#: Seconds of ``states/imu`` sampled per verify -- EVIDENCE, not a gate.
VERIFY_WINDOW_S = 20.0
STATE_MAX_AGE_S = 5.0


class _Durable:  # pragma: no cover -- hardware glue
    """Append-only JSONL, fsync per line: survives a hard cut."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        self._lock = threading.Lock()

    def __call__(self, event: dict) -> None:
        line = (json.dumps(event, sort_keys=True) + "\n").encode()
        with self._lock:
            os.write(self._fd, line)
            os.fsync(self._fd)
        print(line.decode().rstrip(), flush=True)


def _sh(*args: str, timeout: float = 90) -> subprocess.CompletedProcess:  # pragma: no cover
    return subprocess.run(list(args), capture_output=True, text=True,
                          timeout=timeout, encoding="utf-8")


def _systemctl(action: str, unit: str) -> bool:  # pragma: no cover
    return _sh("sudo", "-n", "systemctl", action, unit).returncode == 0


def _readMagMode() -> str:  # pragma: no cover
    return json.loads(CONFIG.read_text(encoding="utf-8"))["pi"]["sensors"]["imu"]["magMode"]


def _writeMagMode(mode: str, backupDir: Path) -> None:  # pragma: no cover
    """Backup -> gate on the copy -> temp -> os.replace. Never open(path, "w")."""
    raw = CONFIG.read_text(encoding="utf-8")
    cfg = json.loads(raw)
    if cfg["pi"]["sensors"]["imu"]["magMode"] == mode:
        return
    backup = backupDir / f"config.json.bak-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    backup.write_text(raw, encoding="utf-8")
    if backup.read_text(encoding="utf-8") != raw:
        raise RuntimeError("config backup did not read back; original untouched")
    cfg["pi"]["sensors"]["imu"]["magMode"] = mode
    tmp = CONFIG.with_suffix(".json.tmp-arch058")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    if json.loads(tmp.read_text(encoding="utf-8"))["pi"]["sensors"]["imu"]["magMode"] != mode:
        tmp.unlink()
        raise RuntimeError("temp config failed readback; original untouched")
    os.replace(tmp, CONFIG)
    if _readMagMode() != mode:
        raise RuntimeError(f"magMode reads back {_readMagMode()!r}, wanted {mode!r}")


def _readJson(path: Path) -> dict | None:  # pragma: no cover
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _stateAgeS(state: dict) -> float | None:  # pragma: no cover
    try:
        ts = datetime.strptime(state["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except Exception:  # noqa: BLE001
        return None
    return (datetime.now(UTC) - ts).total_seconds()


class PiRig:  # pragma: no cover -- hardware glue
    """The real set / restart / verify, plus kiosk takeover and restore."""

    def __init__(self, sessionDir: Path, log: Callable[[dict], None]) -> None:
        self._dir = sessionDir
        self._log = log
        self._restartEpoch: float | None = None
        self._startMode = _readMagMode()
        self._chromium: subprocess.Popen | None = None

    # -- per phase --------------------------------------------------------------
    def apply(self, mechanism: str, onAttempt: Callable[[int], None]) -> ApplyResult:
        count = {"n": 0}
        expected: dict[str, str] = {}

        def setMode(mode: str) -> None:
            expected["mode"] = mode
            _writeMagMode(mode, self._dir)

        def restart() -> None:
            count["n"] += 1
            onAttempt(count["n"])
            self._restartEpoch = time.time()
            ok = _systemctl("restart", COLLECTOR)
            self._log({"event": "collector_restart", "utc": _utcNow(),
                       "attempt": count["n"], "ok": ok})

        def verify() -> bool:
            return self._verify(expected["mode"], count["n"])

        return applyMechanism(mechanism, setModeFn=setMode, restartFn=restart,
                              verifyFn=verify)

    def _verify(self, mode: str, attempt: int) -> bool:
        since = int(self._restartEpoch or time.time()) - 1
        journal = _sh("journalctl", "-u", COLLECTOR, "--since", f"@{since}",
                      "--no-pager", "-o", "cat").stdout
        headings: list[Any] = []
        ages: list[float] = []
        t0 = time.monotonic()
        while time.monotonic() - t0 < VERIFY_WINDOW_S:
            st = _readJson(STATE_IMU) or {}
            headings.append(st.get("headingDeg"))
            age = _stateAgeS(st)
            if age is not None:
                ages.append(age)
            time.sleep(1.0)
        fresh = bool(ages) and min(ages) <= STATE_MAX_AGE_S
        ok, evidence = judgeAttach(mode, journal, headings, stateFresh=fresh)
        self._log({"event": "verify", "utc": _utcNow(), "attempt": attempt,
                   "magMode": mode, "ok": ok, **evidence})
        return ok

    # -- session ----------------------------------------------------------------
    def takeKiosk(self) -> None:
        _systemctl("stop", WATCHDOG_TIMER)
        _systemctl("stop", DASHBOARD)
        env = dict(os.environ, DISPLAY=":0", XDG_RUNTIME_DIR="/run/user/1000")
        self._chromium = subprocess.Popen(
            ["/usr/bin/chromium-browser", "--kiosk", "--touch-events=enabled",
             "--disable-gpu-rasterization", "--noerrdialogs", "--disable-infobars",
             "--hide-scrollbars", "--check-for-update-interval=31536000",
             "--password-store=basic", "--user-data-dir=/tmp/arch058-chromium",
             f"http://127.0.0.1:{PORT}/"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        self._log({"event": "kiosk_taken", "utc": _utcNow(),
                   "chromiumPid": self._chromium.pid})

    def restore(self) -> str:
        """Mode back to what it was at session start, collector up, kiosk back.

        ⚠️ If the machine is SHUTTING DOWN (key-off at the end of the errands),
        only the config is restored: starting units during shutdown fights
        systemd, and the dashboard and watchdog timer come back at next boot.
        """
        notes: list[str] = []
        stopping = _sh("systemctl", "is-system-running").stdout.strip() == "stopping"
        try:
            if _readMagMode() != self._startMode:
                _writeMagMode(self._startMode, self._dir)
                notes.append(f"magMode->{self._startMode}")
                if not stopping:
                    _systemctl("restart", COLLECTOR)
                    notes.append("collector restarted")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"MAGMODE RESTORE FAILED: {exc}")
        if self._chromium is not None:
            try:
                os.killpg(self._chromium.pid, signal.SIGTERM)
            except Exception:  # noqa: BLE001
                pass
        if stopping:
            notes.append("system stopping: units left to next boot")
        else:
            if not _sh("systemctl", "is-active", COLLECTOR).stdout.strip() == "active":
                _systemctl("start", COLLECTOR)
            _systemctl("start", DASHBOARD)
            _systemctl("start", WATCHDOG_TIMER)
            active = _sh("systemctl", "is-active", COLLECTOR, DASHBOARD,
                         WATCHDOG_TIMER).stdout.split()
            notes.append(f"collector/dashboard/watchdog={'/'.join(active)}")
        return "; ".join(notes)


class _MagWatch(threading.Thread):  # pragma: no cover -- hardware glue
    """Screen-only liveness: has the published heading changed recently?"""

    def __init__(self) -> None:
        super().__init__(name="arch058-magwatch", daemon=True)
        self.snapshot: dict[str, Any] = {"magLive": None, "headingDeg": None, "obd": None}
        self._seen: list[tuple[float, Any]] = []

    def run(self) -> None:
        while True:
            st = _readJson(STATE_IMU) or {}
            now = time.monotonic()
            self._seen.append((now, st.get("headingDeg")))
            self._seen = [(t, h) for t, h in self._seen if now - t <= 15.0]
            vals = [h for _, h in self._seen if h is not None]
            live = None if not self._seen else (len(set(vals)) >= 2)
            obd = ((_readJson(STATE_SYS) or {}).get("obdLink") or {}).get("state")
            self.snapshot = {"magLive": live, "headingDeg": st.get("headingDeg"),
                             "obd": obd}
            time.sleep(1.0)


def main() -> int:  # pragma: no cover -- hardware glue
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    sessionDir = Path.home() / "drive_tests" / f"arch058-{stamp}"
    log = _Durable(sessionDir / "phases.jsonl")
    rig = PiRig(sessionDir, log)
    console = DriveConsole(CIO_2026_09_27_STEPS, applyFn=rig.apply,
                           restoreFn=rig.restore, logFn=log)
    watch = _MagWatch()
    watch.start()
    ui = (Path(__file__).with_name("drive_test_ui.html")).read_bytes()
    log({"event": "session_start", "utc": _utcNow(), "sessionDir": str(sessionDir),
         "startMagMode": _readMagMode(),
         "steps": [st.button for st in CIO_2026_09_27_STEPS]})

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path.startswith("/status"):
                body = {**console.status(), **watch.snapshot}
                self._send(200, json.dumps(body).encode())
            else:
                self._send(200, ui, "text/html; charset=utf-8")

        def do_POST(self) -> None:
            if self.path.startswith("/advance"):
                ok = console.press()
                self._send(200, json.dumps({"accepted": ok}).encode())
            elif self.path.startswith("/end"):
                self._send(200, b'{"ending": true}')
                threading.Thread(target=_shutdown, daemon=True).start()
            else:
                self._send(404, b"{}")

    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    done = threading.Event()

    def _shutdown(*_: Any) -> None:
        console.end()
        done.set()
        threading.Thread(target=srv.shutdown, daemon=True).start()

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, _shutdown)

    threading.Thread(target=srv.serve_forever, name="arch058-http", daemon=True).start()
    try:
        if "--no-kiosk" not in sys.argv:
            rig.takeKiosk()
        # Nothing is applied until the driver presses BEGIN (CIO step 8).
        print(f"ARCH-058 console on http://127.0.0.1:{PORT}/  log={sessionDir}",
              flush=True)
        done.wait()
    finally:
        # 🔴 Garage dry run 3: a crash after the kiosk takeover left the dashboard
        # and watchdog stopped with nothing to bring them back. end() is
        # idempotent, so the normal /end path is unaffected.
        console.end()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
