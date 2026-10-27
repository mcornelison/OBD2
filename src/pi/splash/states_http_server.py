################################################################################
# File Name: states_http_server.py
# Purpose/Description: F-103 localhost state HTTP server [Atlas A-4]. The only
#   IPC the chromium kiosk can fetch -- chromium cannot fetch('file:///run/...')
#   cleanly. Serves the read-only states/* JSON the emitters write, token-gated
#   (US-393 DoD: token SSOT). Bind 127.0.0.1 ONLY; stdlib only; hard-coded base
#   dir; path traversal -> 404; Cache-Control: no-store so the kiosk's 250ms
#   polls always see fresh data. The kiosk index is served same-origin with the
#   token injected, so the token never lands in an on-disk asset.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Ralph (Rex)  | Initial implementation (US-393 F-103 boot splash)
# 2026-06-30    | Ralph (Rex)  | US-399 [A-2]: multi-assets-dir support (serve the
#               |              | carousel dashboard kit same-origin alongside the
#               |              | splash) -- full-runtime extension of the server.
# 2026-06-30    | Ralph (Rex)  | US-403 [A-7]: one token-gated POST /service-control
#               |              | action endpoint (delegates the allow-list gate to
#               |              | service_control). GET stays read-only.
# 2026-08-01    | Ralph (Rex)  | US-501: inject the deployed version into the
#               |              | dashboard header chip from .deploy-version (read
#               |              | PER REQUEST -- see _DEPLOY_VERSION_PLACEHOLDER).
# 2026-08-07    | Ralph (Rex)  | US-531 [F-126]: THIRD token-gated POST route
#               |              | /settings -- persists the US-530 Pi-local config
#               |              | overlay (the kiosk is sandboxed JS and cannot
#               |              | write files). Gate delegated to the overlay SSOT.
# 2026-10-14    | Rex (US-881-d) | FOURTH token-gated POST route /fuel-reset --
#               |              | asks eclipse-obd to zero fuel_since_reset over
#               |              | fuel_reset_channel; /dtc-clear's status mapping.
# 2026-10-18    | Rex (US-890-f) | DISPLAY_STALE gains fuelResetConfirmSec
#               |              | (pi.display.stale.fuelResetConfirmSec), same
#               |              | validation + default fallback as imuSec.
# 2026-10-20    | Rex (US-897-c) | FIFTH token-gated POST route /alerts-ack {ids}
#               |              | -- asks eclipse-obd to acknowledge alerts for
#               |              | this boot over alerts_ack_channel; 400 before
#               |              | any file, 409 all-or-nothing.
# 2026-10-20    | Rex (US-899-a1)| DISPLAY_STALE gains alertsAckConfirmSec and
#               |              | alertsAckNoticeSec (the takeover ack windows),
#               |              | the fuelResetConfirmSec rules.
# 2026-10-22    | Atlas (ARCH) | POST drains an over-bound body (to 64 KB, in
#               |              | 4 KB chunks) before answering, so the answer is
#               |              | never a reset; above 64 KB, 413 + close. One
#               |              | reader, _readBoundedBody. Handler socket timeout
#               |              | 2.0 s, so a stalled client cannot hang the server.
# 2026-10-23    | Rex (US-878-c)| POST /settings refuses a write that breaks a
#               |              | cross-key rule (overlay.crossKeyRefusal); both
#               |              | 400s are {ok, key, value (re-read), error}.
#               |              | DISPLAY_SETTINGS entries are {found, value}.
# 2026-10-23    | Rex (US-895-b)| DISPLAY_AUTODIM resolved PER REQUEST through
#               |              | the overlay seam (construction cache retired).
# 2026-10-27    | Rex (US-870-d)| SIXTH token-gated POST route
#               |              | /shutdown-splash-done: 403 without a token;
#               |              | else states/shutdown-splash-done {bootId, ts},
#               |              | atomic, bootId stamped server-side.
# ================================================================================
################################################################################

"""Localhost-only, token-gated state server (read-only GET + six write routes).

GET is read-only (states + same-origin assets). Writes are an explicit, closed
set of POST routes -- US-403 ``/service-control``, US-407 ``/dtc-clear``,
US-531 ``/settings``, US-881-d ``/fuel-reset``, US-897-c ``/alerts-ack`` and
US-870-d ``/shutdown-splash-done`` --
each token-gated by the same ``_tokenOk``, each a thin
transport that delegates its gate to a SSOT module rather than carrying its own
copy of an allow-list. For ``/service-control`` that SSOT is ``service_control``
(the real privilege is the 51- polkit rule; the kiosk never runs as root); for
``/settings`` it is ``common.config.overlay`` (US-530), whose allow-list is
consulted at BOTH read and write so the two can never disagree.
"""

from __future__ import annotations

import hmac
import json
import math
import mimetypes
from collections.abc import Callable, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import unquote, urlsplit

from common.config import overlay
from common.config.validator import DEFAULTS
from common.time.helper import utcIsoNow
from pi.diagnostics.boot_reason import readCurrentBootId
from pi.power.power_watch.splash_done import SHUTDOWN_SPLASH_DONE_FILENAME
from pi.splash import (
    alerts_ack_channel,
    dtc_clear,
    dtc_clear_channel,
    fuel_reset_channel,
    service_control,
)
from pi.splash.boot_state_emitter import writeStateAtomic

# Placeholder substituted with the live token when the kiosk HTML is served.
_TOKEN_PLACEHOLDER = "__SPLASH_TOKEN__"

# US-483-b: the QUOTED placeholder the served HTML carries for the display
# auto-dim config (pi.display.autoDim). Substituted with the JSON config object at
# serve time so tuning is a config change, not a code change. Quoted so an
# un-substituted preview stays valid JS (a string the carousel ignores); the
# substitution replaces the quotes too, yielding a real JS object literal (or
# ``null`` when no config was provided -> the carousel uses its grounded
# defaults, honest -- never a fabricated curve).
_DISPLAY_AUTODIM_PLACEHOLDER = '"__DISPLAY_AUTODIM__"'

# US-506 (F-124): the same quoted-placeholder seam for the carousel NAVIGATION
# config (pi.display.carousel) -- auto-rotate period, pause self-expiry and the
# swipe velocity/travel thresholds. Kept a SEPARATE placeholder rather than
# widening the auto-dim one: the two sub-configs have different owners and
# different tuning cadences, and merging them would make an auto-dim edit able
# to break carousel navigation.
#
# US-533 B1 (CIO-ratified 2026-08-08): resolved PER REQUEST whenever a
# ``configPath`` is wired, joining _DEPLOY_VERSION_PLACEHOLDER and
# _DISPLAY_SETTINGS_PLACEHOLDER. This was the LAST resolved-at-construction value
# in _injectHtml and it had the same staleness bug they were each moved to fix:
# the F-126 settings band writes pi.display.carousel.autoRotateS, and a cached
# blob meant the new period could only reach the kiosk via an
# eclipse-states-http restart -- which polkit DENIES by design (the unit runs
# User=mcornelison and the manage-units grant deliberately excludes the state
# server, BL-030 B1). Resolving here DELETES the privilege requirement instead of
# asking for it: the toggle writes the overlay, the UI reloads itself, and the
# reload picks the new value up.
_DISPLAY_CAROUSEL_PLACEHOLDER = '"__DISPLAY_CAROUSEL__"'

# US-882-c (F-159, Atlas gap 6): the same quoted-placeholder seam for the page's
# stale windows -- the IMU card's (pi.display.stale.imuSec), which was a
# carousel.js literal, and since US-890-f the Fuel page's reset confirm window
# (pi.display.stale.fuelResetConfirmSec). Resolved PER REQUEST like the carousel section, so a
# tuned window reaches the kiosk on its next reload with no unit restart.
_DISPLAY_STALE_PLACEHOLDER = '"__DISPLAY_STALE__"'

# The validator-owned key the injected imuSec resolves, and its default (the
# value served whenever the key is absent, unreadable or not a finite number > 0).
_STALE_IMU_SEC_KEY = "pi.display.stale.imuSec"
# US-890-f: the kiosk's wait for the re-read after a /fuel-reset 200, injected
# beside imuSec under the same rules.
_STALE_FUEL_RESET_CONFIRM_KEY = "pi.display.stale.fuelResetConfirmSec"
# US-899-a1: the takeover ack's wait for the acknowledged re-read after a
# /alerts-ack 200, and how long its failure notice holds -- the same rules.
_STALE_ALERTS_ACK_CONFIRM_KEY = "pi.display.stale.alertsAckConfirmSec"
_STALE_ALERTS_ACK_NOTICE_KEY = "pi.display.stale.alertsAckNoticeSec"

# US-532 (F-126): the same quoted-placeholder seam for the 5 Slice-1 operator
# settings at their CURRENT EFFECTIVE values, keyed by the overlay's own flat
# dot-paths. Deliberately NOT a GET route: the effective values already reach the
# dashboard through this injection, so a read endpoint would be a SECOND source
# for the same fact and the two could disagree (US-531 ruling).
#
# Resolved PER REQUEST, like _DEPLOY_VERSION_PLACEHOLDER and unlike the two
# config placeholders above -- see _effectiveSettingsJson for why a value cached
# at handler construction would make this band lie.
_DISPLAY_SETTINGS_PLACEHOLDER = '"__DISPLAY_SETTINGS__"'

# US-501 (F-123): the dashboard header version chip. UNQUOTED -- this one is HTML
# text content, not a JS value, so there is no quoted-preview trick to play.
#
# Unlike the two config placeholders above, this is resolved PER REQUEST rather
# than once at handler construction. deploy-pi.sh restarts this unit in
# step_install_state_server_units but writes .deploy-version LAST, in
# step_write_deploy_version (deliberately, so a failed restart cannot bump the
# stamp on a Pi still running old code -- US-354). A value cached at startup
# would therefore be the PREVIOUS deploy's version on every deploy, which is the
# stale literal the chip already suffered from. The read is one small JSON file
# per HTML serve (the kiosk loads the page once), so per-request costs nothing.
_DEPLOY_VERSION_PLACEHOLDER = "__DEPLOY_VERSION__"

# Honest "the build could not be determined" sentinel. Deliberately the SAME
# string the splash chip uses (boot-state-poll.js / deploy-pi.sh), so one glyph
# means "unknown build" on both surfaces -- never a fabricated or stale version.
_VERSION_UNKNOWN = "V?.?.?"

# HTML entry points get the token injected; treated as the same-origin bootstrap.
_INDEX_NAMES = frozenset({"", "index.html"})

# US-403 [A-7]: the service-control write route.
_ACTION_PATH = "/service-control"

# US-407 [F-111]: the Mode-04 DTC clear write route. The gate is re-checked here
# from the server's own `dtc` state (never the request body) before the injected
# clear runner is ever invoked -- a tampered/stale UI can't force a clear.
_CLEAR_PATH = "/dtc-clear"

# US-531 [F-126]: the settings write route. The kiosk is sandboxed chromium JS
# and cannot touch the filesystem, so a settings toggle POSTs here and THIS
# process writes the Pi-local overlay. Deliberately NOT paired with a GET: the
# effective values already reach the dashboard through the injected config, so
# adding a read surface here would create a second source for the same fact.
_SETTINGS_PATH = "/settings"

# US-881-d [F-159]: zero the since-reset fuel totals. This process holds no
# database; the injected runner asks eclipse-obd (the row's owner) over
# fuel_reset_channel, and eclipse-obd refuses while a drive is recording.
_FUEL_RESET_PATH = "/fuel-reset"

# The outcome wait budget (validator default; config.json may override).
_FUEL_RESET_TIMEOUT_KEY = "pi.fuel.resetTimeoutSec"

# US-897-c [F-127]: acknowledge states/alerts entries for this boot. This process
# holds neither the arbiter nor the ack store; the injected runner asks
# eclipse-obd (their one writer) over alerts_ack_channel. Body {ids: [...]} ONLY,
# all or nothing (Atlas Q26).
_ALERTS_ACK_PATH = "/alerts-ack"

# Its outcome wait budget (validator default 5; short, the server is
# single-threaded and the wait blocks every GET -- Atlas Q22).
_ALERTS_ACK_TIMEOUT_KEY = "pi.warnings.ackTimeoutSec"

# US-870-d [F-103]: the shutdown page has played its ending (3 turns, the
# vanish). This process writes states/shutdown-splash-done {bootId, ts}; the
# shutdown sequencer waits for it before poweroff. The body is ignored: bootId
# is stamped HERE from the kernel, so a page cannot answer for another boot.
_SPLASH_DONE_PATH = "/shutdown-splash-done"

# /alerts-ack refusals answered 409 (nothing written); any other failure is 503.
_ALERTS_ACK_REFUSALS = frozenset({"unknown_id", "not_ackable"})

# The `dtc` state file the clear gate re-check reads (matches dtc_emitter).
_DTC_STATE_FILENAME = "dtc"

# Largest action request body we will read (tiny {unit, verb} / {confirm} JSON).
_MAX_ACTION_BODY = 4096

# Largest over-bound body we read and DISCARD before answering. Answering while
# the client is still sending resets the connection (WinError 10053 on Windows),
# so the route's answer must follow the drain. Above this: 413 + close.
_MAX_DRAIN_BODY = 65536

# The discard reads happen in chunks of this size, so memory stays bounded.
_DRAIN_CHUNK = 4096

# Socket timeout for every request (Atlas B1, 2026-10-22). The server is
# single-threaded, so a stalled client freezes every kiosk poll until this
# fires: it must stay under pi.display.stale.obdLiveSec (5 s), and a localhost
# request finishes in milliseconds.
_SOCKET_TIMEOUT_SEC = 2.0


def _readBoundedBody(rfile: BinaryIO, length: int) -> tuple[bytes, bool]:
    """Read a POST body within the bounds. The ONLY reader of ``rfile``.

    Args:
        rfile: The request stream.
        length: The request's Content-Length (already parsed, may be <= 0).

    Returns:
        ``(body, tooLarge)``. Up to ``_MAX_ACTION_BODY`` the body is returned.
        Up to ``_MAX_DRAIN_BODY`` it is read in ``_DRAIN_CHUNK`` pieces and
        discarded, so the route sees ``b""`` exactly as for an empty body.
        Above that nothing is read and ``tooLarge`` is True: the caller answers
        413 and closes the connection.
    """
    if length > _MAX_DRAIN_BODY:
        return b"", True
    if length > _MAX_ACTION_BODY:
        remaining = length
        while remaining > 0:
            chunk = rfile.read(min(_DRAIN_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
        return b"", False
    if length > 0:
        return rfile.read(length), False
    return b"", False


def _isSafeFile(baseDir: str, name: str) -> Path | None:
    """Resolve ``name`` under ``baseDir`` and return it only if it stays inside.

    Defends against ``..`` traversal and absolute-path escapes: the resolved
    candidate MUST be within the resolved base directory and be a regular file.
    """
    base = Path(baseDir).resolve()
    try:
        candidate = (base / name).resolve()
        candidate.relative_to(base)
    except (ValueError, OSError):
        return None
    return candidate if candidate.is_file() else None


def _normalizeAssetsDirs(
    assetsDir: str | Sequence[str] | None,
) -> tuple[str, ...]:
    """Normalize the assets-dir argument to a search-ordered tuple of dirs.

    Accepts a single path string (the US-393 single-kit call sites), a sequence
    of paths (US-399: splash kit first, dashboard kit second -- both served
    same-origin so the token is injected into either kit's HTML), or ``None``.
    The order is the lookup order; the first dir holding a requested name wins.
    """
    if assetsDir is None:
        return ()
    if isinstance(assetsDir, str):
        return (assetsDir,)
    return tuple(assetsDir)


def makeStatesHandler(
    statesDir: str,
    token: str,
    assetsDir: str | Sequence[str] | None = None,
    clearRunner: Callable[[], object] | None = None,
    displayConfig: dict[str, Any] | None = None,
    carouselConfig: dict[str, Any] | None = None,
    deployVersionPath: str | None = None,
    configPath: str | None = None,
    fuelResetRunner: Callable[[], dict[str, Any]] | None = None,
    alertsAckRunner: Callable[[list[str]], dict[str, Any]] | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Build a request-handler class bound to one states dir + token + assets.

    ``assetsDir`` may be a single path or an ordered sequence of paths (searched
    in order, first match wins) so one server can serve multiple co-located kits
    (the splash + the carousel dashboard) same-origin with the token injected.

    ``clearRunner`` (US-407) is the injected Mode-04 clear runner owned by the OBD
    connection holder (the orchestrator on the Pi). When ``None`` the POST
    /dtc-clear route returns an honest 503 (the standalone server has no OBD
    connection) rather than fabricating a success.

    ``displayConfig`` (US-483-b) is the ``pi.display.autoDim`` sub-config injected
    into the served kiosk HTML so the carousel's auto-dim curve is tunable via
    config (not code). ``None`` -> the placeholder becomes ``null`` and the
    carousel falls back to its built-in grounded defaults. US-895-b: when
    ``configPath`` is supplied this section is RE-READ per request (through the
    overlay seam, so a saved lux end lands on the next reload) and this argument
    is only the config-less fallback -- the ``carouselConfig`` posture below.

    ``carouselConfig`` (US-506) is the ``pi.display.carousel`` sub-config -- the
    auto-rotate period, pause self-expiry and swipe velocity/travel thresholds --
    injected the same way, with the same ``None`` -> grounded-defaults fallback.
    US-533 B1: when ``configPath`` is supplied this section is RE-READ per
    request and this argument is only the fallback for config-less servers; the
    two are the same file, so the re-read is the fresher answer, never a
    different one.

    ``deployVersionPath`` (US-501) is the ``.deploy-version`` release record whose
    ``version`` fills the dashboard header chip. ``None``, absent, unreadable or
    malformed -> the honest ``V?.?.?`` sentinel; the placeholder is substituted
    either way so a raw ``__DEPLOY_VERSION__`` can never reach the panel.

    ``configPath`` (US-531) is config.json, whose sibling overlay the POST
    /settings route writes. ``None`` -> that route returns an honest 503 (this
    server has no config to overlay) rather than reporting a save that no reader
    would ever see -- the same posture as ``clearRunner``.

    ``fuelResetRunner`` (US-881-d) is the ``fuel_reset_channel`` bridge runner
    that asks eclipse-obd to zero the since-reset fuel totals. ``None`` -> POST
    /fuel-reset returns an honest 503 (no states channel to ask over).

    ``alertsAckRunner`` (US-897-c) is the ``alerts_ack_channel`` bridge runner,
    called with the request's ids, that asks eclipse-obd to acknowledge them.
    ``None`` -> POST /alerts-ack returns an honest 503.

    POST /shutdown-splash-done (US-870-d) takes no parameter: its bootId is the
    kernel's, read per request through ``readCurrentBootId``. An unreadable id
    is written as null, which no reader ever matches.
    """
    assetsDirs = _normalizeAssetsDirs(assetsDir)
    # Nothing display-side is cached here any more. US-895-b (Atlas B15) retired
    # the last construction-time blob, auto-dim: its lux ends are now operator
    # settings, so it is re-read per request like the carousel section (US-533
    # B1). ``displayConfig`` / ``carouselConfig`` are kept as the fallback for
    # servers constructed WITHOUT a configPath, where there is no file to re-read
    # and the caller-supplied section is the only truth available.

    class _StatesHandler(BaseHTTPRequestHandler):
        # Applied to the connection by StreamRequestHandler.setup; the stdlib
        # closes the connection on the TimeoutError (handle_one_request).
        timeout = _SOCKET_TIMEOUT_SEC

        # Silence default stderr request logging -- the journal captures stdout.
        def log_message(self, *args, **kwargs):  # noqa: N802 (stdlib signature)
            return

        def _send(
            self, status: int, body: bytes, contentType: str, *, close: bool = False
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", contentType)
            self.send_header("Content-Length", str(len(body)))
            # Always no-store: the kiosk polls at 250ms and must never see stale.
            self.send_header("Cache-Control", "no-store")
            if close:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _tokenOk(self) -> bool:
            presented = self.headers.get("X-Splash-Token")
            if presented is None:
                auth = self.headers.get("Authorization", "")
                if auth.startswith("Bearer "):
                    presented = auth[len("Bearer ") :]
            if not presented:
                return False
            # Constant-time compare -- no early-exit timing leak on the token.
            return hmac.compare_digest(presented, token)

        def do_GET(self) -> None:  # noqa: N802 (stdlib signature)
            rawPath = unquote(urlsplit(self.path).path)
            name = rawPath.lstrip("/")

            # Spec §8 hard guard: ANY path-traversal segment is rejected
            # outright (404), even one that would resolve back inside the base.
            if ".." in name.replace("\\", "/").split("/"):
                self._send(404, b'{"error":"not found"}', "application/json")
                return

            # Kiosk bootstrap: serve index with the token injected (same origin).
            if name in _INDEX_NAMES:
                self._serveIndex()
                return

            # Public static asset (svg/js/css). Never token-gated -- the page
            # must load before it can authenticate the state polls. Search the
            # asset dirs in order (first match wins) so co-located kits (splash
            # + dashboard) are both served by the one runtime server.
            for assetsBase in assetsDirs:
                assetFile = _isSafeFile(assetsBase, name)
                if assetFile is not None:
                    self._serveAsset(assetFile)
                    return

            # Everything else is treated as a read-only state file -> token-gated.
            if not self._tokenOk():
                self._send(401, b'{"error":"unauthorized"}', "application/json")
                return
            stateFile = _isSafeFile(statesDir, name)
            if stateFile is None:
                self._send(404, b'{"error":"not found"}', "application/json")
                return
            self._send(
                200, stateFile.read_bytes(), "application/json"
            )

        do_HEAD = do_GET  # noqa: N815 (stdlib alias)

        def do_POST(self) -> None:  # noqa: N802 (stdlib signature)
            # Drain the request body FIRST (bounded). Responding to a POST before
            # consuming its body resets the connection on some clients/platforms
            # (WinError 10053); read it up front so every error path is clean.
            # An over-bound body is drained and discarded, so the route answers
            # it as an empty body; only a body past the drain bound is refused.
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            rawBody, tooLarge = _readBoundedBody(self.rfile, length)
            if tooLarge:
                self._send(
                    413, b'{"error":"payload too large"}', "application/json", close=True
                )
                return

            # Exactly six write routes (US-403 service-control, US-407
            # dtc-clear, US-531 settings, US-881-d fuel-reset, US-897-c
            # alerts-ack, US-870-d shutdown-splash-done). Everything else is
            # 404 -- the server is otherwise read-only and must not grow a
            # catch-all writer.
            rawPath = unquote(urlsplit(self.path).path)
            if rawPath == _ACTION_PATH:
                self._handleServiceControl(rawBody)
                return
            if rawPath == _CLEAR_PATH:
                self._handleDtcClear()
                return
            if rawPath == _SETTINGS_PATH:
                self._handleSettingsWrite(rawBody)
                return
            if rawPath == _FUEL_RESET_PATH:
                self._handleFuelReset()
                return
            if rawPath == _ALERTS_ACK_PATH:
                self._handleAlertsAck(rawBody)
                return
            if rawPath == _SPLASH_DONE_PATH:
                self._handleSplashDone()
                return
            self._send(404, b'{"error":"not found"}', "application/json")

        def _handleSplashDone(self) -> None:
            # US-870-d: 403 (not the other routes' 401) and no file without a
            # valid token, as the story's acceptance specifies. The body was
            # drained and is ignored; bootId and ts are this server's own.
            if not self._tokenOk():
                self._send(403, b'{"ok":false,"error":"forbidden"}', "application/json")
                return
            record = {"bootId": readCurrentBootId(), "ts": utcIsoNow()}
            try:
                writeStateAtomic(str(Path(statesDir) / SHUTDOWN_SPLASH_DONE_FILENAME), record)
            except OSError as exc:
                body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
                self._send(500, body, "application/json")
                return
            self._send(200, b'{"ok":true}', "application/json")

        def _handleServiceControl(self, rawBody: bytes) -> None:
            # Token-gated -- same gate as the state reads.
            if not self._tokenOk():
                self._send(401, b'{"error":"unauthorized"}', "application/json")
                return

            try:
                payload = json.loads(rawBody.decode("utf-8"))
                unit = payload["unit"]
                verb = payload["verb"]
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                self._send(400, b'{"error":"bad request"}', "application/json")
                return

            # Action-path gate: an off-list (unit, verb) is rejected (403) and
            # never executed. The same allow-list SSOT backs runServiceAction's
            # own re-check (defense-in-depth).
            if not service_control.isAllowed(unit, verb):
                self._send(
                    403,
                    b'{"ok":false,"error":"action not on the allow-list"}',
                    "application/json",
                )
                return

            result = service_control.runServiceAction(unit, verb)
            body = json.dumps(
                {
                    "ok": result.ok,
                    "unit": result.unit,
                    "verb": result.verb,
                    "returnCode": result.returnCode,
                    "reason": result.reason,
                }
            ).encode("utf-8")
            # The action ran (the gate passed); the body's ok flag carries the
            # honest systemctl outcome -- a failed stop is a 200 with ok:false,
            # never a fabricated success.
            self._send(200, body, "application/json")

        def _handleDtcClear(self) -> None:
            # US-407: the privileged Mode-04 clear path. The gate is re-checked
            # HERE against the server's OWN `dtc` state (never the request body),
            # so a tampered/stale UI cannot force a clear (S-10 / F-3).
            if not self._tokenOk():
                self._send(401, b'{"error":"unauthorized"}', "application/json")
                return
            # Honest unavailability: the standalone server holds no OBD connection
            # unless a clear runner was wired in -- never fabricate a success.
            if clearRunner is None:
                self._send(
                    503,
                    b'{"error":"clear runner not available on this server"}',
                    "application/json",
                )
                return
            # Load the server's authoritative copy of the `dtc` state.
            stateFile = _isSafeFile(statesDir, _DTC_STATE_FILENAME)
            if stateFile is None:
                self._send(
                    409,
                    b'{"error":"no dtc state -- nothing to clear"}',
                    "application/json",
                )
                return
            try:
                dtcState = json.loads(stateFile.read_text(encoding="utf-8"))
            except (ValueError, OSError, UnicodeDecodeError):
                self._send(
                    409, b'{"error":"dtc state unreadable"}', "application/json"
                )
                return

            # ARCH-023: the runner now crosses a PROCESS boundary, so it can
            # fail in ways an in-process one never could.  Every such failure is
            # reported as itself and NEVER as a clear that did not happen --
            # `performClear` would faithfully render an empty readback as
            # "cleared, 0 stored", which is a fabricated ECU write.
            try:
                outcome = dtc_clear.performClear(dtcState, clearRunner=clearRunner)
            except dtc_clear_channel.ClearBridgeTimeout as exc:
                # 504: we genuinely do not know.  A Mode 04 may or may not have
                # reached the ECU; the next `dtc` refresh is what settles it.
                self._send(
                    504,
                    json.dumps({"error": str(exc), "issued": None}).encode("utf-8"),
                    "application/json",
                )
                return
            except dtc_clear_channel.ClearBridgeError as exc:
                # 502: the OBD service answered, and the answer was a refusal
                # (no connection, adapter write failed).  A named cause, not a
                # timeout the operator cannot act on.
                self._send(
                    502,
                    json.dumps({"error": str(exc), "issued": False}).encode("utf-8"),
                    "application/json",
                )
                return
            body = json.dumps(
                {
                    "issued": outcome.issued,
                    "reason": outcome.reason,
                    "cleared": outcome.cleared,
                    "storedAfter": outcome.storedAfter,
                    "pendingAfter": outcome.pendingAfter,
                    "milAfter": outcome.milAfter,
                    "reSetCodes": outcome.reSetCodes,
                }
            ).encode("utf-8")
            # Gate rejected the clear -> 403, the vehicle-write never happened.
            if not outcome.issued:
                self._send(403, body, "application/json")
                return
            self._send(200, body, "application/json")

        def _handleFuelReset(self) -> None:
            # US-881-d: the status mapping is /dtc-clear's. The token is checked
            # BEFORE the runner, so a bad token never writes a request file.
            if not self._tokenOk():
                self._send(401, b'{"error":"unauthorized"}', "application/json")
                return
            if fuelResetRunner is None:
                self._send(
                    503,
                    b'{"ok":false,"error":"no states channel on this server"}',
                    "application/json",
                )
                return
            try:
                outcome = fuelResetRunner()
            except fuel_reset_channel.ResetBridgeTimeout as exc:
                # 504: we do not know whether eclipse-obd reset the totals; the
                # next states/fuel-economy is what settles it.
                self._send(
                    504,
                    json.dumps({"ok": None, "error": str(exc)}).encode("utf-8"),
                    "application/json",
                )
                return
            except fuel_reset_channel.ResetBridgeError as exc:
                self._send(
                    503,
                    json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"),
                    "application/json",
                )
                return
            if not outcome.get("ok"):
                # 409: eclipse-obd refused (``driving`` while a drive records);
                # nothing changed.
                body = {"ok": False, "reason": outcome.get("reason")}
                self._send(409, json.dumps(body).encode("utf-8"), "application/json")
                return
            body = {"ok": True, "resetAtTs": outcome.get("resetAtTs")}
            self._send(200, json.dumps(body).encode("utf-8"), "application/json")

        def _handleAlertsAck(self, rawBody: bytes) -> None:
            # US-897-c: /fuel-reset's status mapping. The token is checked
            # FIRST, and the body before the runner, so neither a bad token nor
            # a malformed body ever writes a request file.
            if not self._tokenOk():
                self._send(401, b'{"error":"unauthorized"}', "application/json")
                return
            if alertsAckRunner is None:
                self._send(
                    503,
                    b'{"ok":false,"error":"no states channel on this server"}',
                    "application/json",
                )
                return
            ids = _parseAlertsAckIds(rawBody)
            if ids is None:
                self._send(400, b'{"ok":false,"error":"bad request"}', "application/json")
                return
            try:
                outcome = alertsAckRunner(ids)
            except alerts_ack_channel.AckBridgeTimeout as exc:
                # 504: we do not know whether eclipse-obd recorded it; the next
                # states/alerts is what settles it.
                self._send(
                    504,
                    json.dumps({"ok": None, "error": str(exc)}).encode("utf-8"),
                    "application/json",
                )
                return
            except alerts_ack_channel.AckBridgeError as exc:
                self._send(
                    503,
                    json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"),
                    "application/json",
                )
                return
            if outcome.get("ok"):
                self._send(200, b'{"ok":true}', "application/json")
                return
            error = outcome.get("error")
            if error in _ALERTS_ACK_REFUSALS:
                # 409: all or nothing -- the bad ids are named, nothing written.
                body = {"ok": False, "error": error, "ids": outcome.get("ids") or []}
                self._send(409, json.dumps(body).encode("utf-8"), "application/json")
                return
            # store_write_failed (or an unexpected failure): unavailable, said so.
            self._send(
                503,
                json.dumps({"ok": False, "error": error}).encode("utf-8"),
                "application/json",
            )

        def _handleSettingsWrite(self, rawBody: bytes) -> None:
            # US-531: persist ONE operator setting into the US-530 Pi-local
            # overlay. The kiosk cannot write files, so this process does it.
            #
            # NOTE the gate below is `overlay`'s, not a local copy. US-530 made
            # the overlay a FLAT dot-path map precisely so "is this writable?"
            # is a literal key comparison here -- two allow-lists that can drift
            # would be worse than one, because they LOOK like defense in depth.
            if not self._tokenOk():
                self._send(401, b'{"error":"unauthorized"}', "application/json")
                return
            # Honest unavailability: with no config.json wired there is nothing
            # to overlay, and a "saved" reply would describe a value no reader
            # could ever resolve.
            if configPath is None:
                self._send(
                    503,
                    b'{"ok":false,"error":"no config path configured on this server"}',
                    "application/json",
                )
                return

            try:
                payload = json.loads(rawBody.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise TypeError("settings payload must be an object")
                key = payload["key"]
                value = payload["value"]
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                self._send(400, b'{"error":"bad request"}', "application/json")
                return

            # Key gate (403 = "not yours to write") and value gate (400 = "that
            # is not a legal value") are split so the UI can tell an operator
            # mistake from an unsupported setting. Both reject BEFORE any write.
            if key not in overlay.OVERRIDABLE_KEYS:
                self._send(
                    403,
                    b'{"ok":false,"error":"key is not operator-overridable"}',
                    "application/json",
                )
                return
            isValid, stored = overlay.validateOverlayValue(key, value)
            if not isValid:
                self._refuseSetting(configPath, key, "invalid value for this setting")
                return
            # US-878-c: the cross-key seam judges the write on the EFFECTIVE
            # config (the stored overlay + config.json + DEFAULTS), so a value
            # the read seam would drop at boot is never stored in the first place.
            brokenRule = overlay.crossKeyRefusal(configPath, key, stored)
            if brokenRule is not None:
                self._refuseSetting(configPath, key, brokenRule.error)
                return

            wrote = overlay.writeOverlayValue(
                overlay.overlayPathFor(configPath), key, stored
            )
            # Re-READ from disk through the shared seam rather than echoing the
            # request. If the write failed, or the resolver coerces the stored
            # value, this is the value the carousel and the
            # orchestrator will actually see -- so the UI cannot show a setting
            # that is not really stored.
            found, effective = overlay.readEffectiveValue(configPath, key)
            body = json.dumps(
                {
                    "ok": wrote,
                    "key": key,
                    "value": effective if found else None,
                }
            ).encode("utf-8")
            if not wrote:
                self._send(500, body, "application/json")
                return
            self._send(200, body, "application/json")

        def _refuseSetting(self, readPath: str, key: str, error: str) -> None:
            # US-878-c B7: ONE 400 shape for a bad value and a broken cross-key
            # rule alike. It carries the RE-READ effective value, so the band
            # snaps back to what is really stored rather than to its request.
            found, effective = overlay.readEffectiveValue(readPath, key)
            body = {
                "ok": False,
                "key": key,
                "value": effective if found else None,
                "error": error,
            }
            self._send(400, json.dumps(body).encode("utf-8"), "application/json")

        def _injectHtml(self, html: str) -> str:
            # Same-origin injection at serve time: the token SSOT (US-393), the
            # display auto-dim config (US-483-b), the carousel navigation config
            # (US-506) and the deployed version (US-501). No placeholder value
            # ever lands in an on-disk asset.
            #
            # The version is read HERE, not closed over above: the deploy writes
            # .deploy-version after restarting this unit, so anything cached at
            # construction is a deploy behind (see _DEPLOY_VERSION_PLACEHOLDER).
            version = readDeployVersion(deployVersionPath) or _VERSION_UNKNOWN
            # US-532: likewise resolved HERE rather than closed over -- the POST
            # /settings route writes the overlay this reads, so a value cached at
            # construction would render the PRE-SAVE setting on every page reload
            # that is not preceded by a unit bounce. The band exists to report
            # what is actually stored; a stale blob would make it lie.
            settingsJson = json.dumps(loadEffectiveSettings(configPath))
            # US-533 B1: and likewise the carousel navigation section, so a
            # toggled autoRotateS applies on the reload the UI triggers itself
            # instead of on a unit restart the kiosk is not authorised to make.
            # With no configPath there is nothing to re-read -- the section the
            # caller supplied at construction stands (US-506 behaviour intact).
            carouselJson = json.dumps(
                carouselConfig
                if configPath is None
                else loadDisplayCarouselConfig(configPath)
            )
            # US-882-c: the stale windows, per request for the same reason.
            staleJson = json.dumps(loadDisplayStaleConfig(configPath))
            # US-895-b (Atlas B15): and auto-dim, whose luxMin / luxFull the
            # band now writes -- a construction-time blob would hand the page
            # the pre-save ends on every reload (the US-532 defect). Same
            # no-configPath fallback as the carousel section.
            displayConfigJson = json.dumps(
                displayConfig
                if configPath is None
                else loadDisplayAutoDimConfig(configPath)
            )
            return (
                html.replace(_TOKEN_PLACEHOLDER, token)
                .replace(_DISPLAY_AUTODIM_PLACEHOLDER, displayConfigJson)
                .replace(_DISPLAY_CAROUSEL_PLACEHOLDER, carouselJson)
                .replace(_DISPLAY_STALE_PLACEHOLDER, staleJson)
                .replace(_DISPLAY_SETTINGS_PLACEHOLDER, settingsJson)
                .replace(_DEPLOY_VERSION_PLACEHOLDER, version)
            )

        def _serveIndex(self) -> None:
            # The first asset dir holding an index.html owns `/` (the splash kit
            # in the runtime config); the dashboard is reached by its own name.
            for assetsBase in assetsDirs:
                indexFile = _isSafeFile(assetsBase, "index.html")
                if indexFile is not None:
                    html = self._injectHtml(indexFile.read_text(encoding="utf-8"))
                    self._send(
                        200, html.encode("utf-8"), "text/html; charset=utf-8"
                    )
                    return
            self._send(404, b"not found", "text/plain")

        def _serveAsset(self, assetFile: Path) -> None:
            contentType, _ = mimetypes.guess_type(str(assetFile))
            if assetFile.suffix == ".svg":
                contentType = "image/svg+xml"
            # HTML assets (e.g. dashboard.html) also get the token + display
            # config injected same-origin.
            if assetFile.suffix in (".html", ".htm"):
                html = self._injectHtml(assetFile.read_text(encoding="utf-8"))
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return
            self._send(
                200, assetFile.read_bytes(), contentType or "application/octet-stream"
            )

    return _StatesHandler


class StatesHttpServer:
    """Thin wrapper around stdlib HTTPServer bound to 127.0.0.1 (never 0.0.0.0)."""

    def __init__(
        self,
        statesDir: str,
        token: str,
        host: str = "127.0.0.1",
        port: int = 9899,
        assetsDir: str | Sequence[str] | None = None,
        clearRunner: Callable[[], object] | None = None,
        displayConfig: dict[str, Any] | None = None,
        carouselConfig: dict[str, Any] | None = None,
        deployVersionPath: str | None = None,
        configPath: str | None = None,
        fuelResetRunner: Callable[[], dict[str, Any]] | None = None,
        alertsAckRunner: Callable[[list[str]], dict[str, Any]] | None = None,
    ) -> None:
        self.host = host
        self.statesDir = statesDir
        handler = makeStatesHandler(
            statesDir,
            token,
            assetsDir,
            clearRunner,
            displayConfig,
            carouselConfig,
            deployVersionPath,
            configPath,
            fuelResetRunner,
            alertsAckRunner,
        )
        # Bind eagerly so a port conflict fails loudly at construction (the unit
        # then exits non-zero -> the kiosk's fetch errors -> splash DEGRADED;
        # no silent green-when-broken, spec §8 listen-failure semantics).
        self._httpd = HTTPServer((host, port), handler)

    @property
    def actualPort(self) -> int:
        """The bound port (resolves an ephemeral port=0 to the OS-assigned one)."""
        return self._httpd.server_address[1]

    def serveForever(self) -> None:
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def _loadDisplaySection(configPath: str, name: str) -> dict[str, Any] | None:
    """Read one effective ``pi.display.<name>`` sub-config, fail-safe.

    A LIGHT raw ``json.load`` (no secrets loader / validator) -- these display
    values are plain numbers with no ``${ENV}`` placeholders, so a full config
    load would only add failure modes to this standalone server. ANY problem
    (missing file, unreadable, malformed, section absent) returns ``None`` so the
    server still serves the dashboard and the carousel falls back to its built-in
    grounded defaults (honest -- never crash the kiosk over a config read).

    US-530: the raw read is then resolved through the shared config-overlay seam
    (``common.config.overlay``, itself stdlib-only, so this server keeps its
    no-third-party posture) so an operator setting written on the Pi is honoured
    here exactly as the orchestrator honours it.

    Args:
        configPath: Path to config.json (relative paths resolve against the
            process CWD -- the unit's WorkingDirectory).
        name: The sub-key under ``pi.display`` to read.

    Returns:
        The requested dict, or ``None`` when it cannot be read.
    """
    try:
        with open(configPath, encoding="utf-8") as fh:
            config = json.load(fh)
        # US-530: resolve through the SHARED overlay seam, not a local merge --
        # this reader and the orchestrator's loadConfigWithSecrets must return
        # the identical effective value or the A-4 divergence returns.
        config = overlay.applyConfigOverlay(config, configPath)
        section = config.get("pi", {}).get("display", {}).get(name)
        return section if isinstance(section, dict) else None
    except (OSError, ValueError):
        return None


def loadDisplayAutoDimConfig(configPath: str) -> dict[str, Any] | None:
    """Read ``pi.display.autoDim`` from config.json (US-483-b), fail-safe."""
    return _loadDisplaySection(configPath, "autoDim")


def loadDisplayCarouselConfig(configPath: str) -> dict[str, Any] | None:
    """Read ``pi.display.carousel`` from config.json (US-506), fail-safe.

    The carousel navigation model's tuning SSOT: auto-rotate period, pause
    self-expiry, the swipe distance/velocity/travel thresholds, and the US-511
    parked-signal debounce (parkedOnS/parkedOffS). The section is passed through
    WHOLESALE -- no key allow-list here -- so adding a tunable is a config +
    display change with no server edit; the display's own resolver is what
    rejects malformed values.
    """
    return _loadDisplaySection(configPath, "carousel")


def loadDisplayStaleConfig(configPath: str | None) -> dict[str, float]:
    """Resolve the page's stale windows at their effective values (US-882-c).

    ``imuSec`` is ``pi.display.stale.imuSec``, ``fuelResetConfirmSec``
    (US-890-f) is ``pi.display.stale.fuelResetConfirmSec``, and
    ``alertsAckConfirmSec`` / ``alertsAckNoticeSec`` (US-899-a1) are
    ``pi.display.stale.alertsAckConfirmSec`` / ``alertsAckNoticeSec``, each from
    the effective config (config.json resolved through the shared overlay seam).
    Anything that is not a finite number > 0 -- absent key, no config wired,
    unreadable file, or a value the validator would refuse -- serves the
    validator default, so the page always receives the window production runs
    with, never a fabricated one. All are config.json engineering keys,
    deliberately NOT in the overlay allow-list (Atlas ruled B), so a
    config.local.json value is ignored.

    Args:
        configPath: Path to config.json, or ``None`` when this server has no
            config wired.

    Returns:
        ``{"imuSec", "fuelResetConfirmSec", "alertsAckConfirmSec",
        "alertsAckNoticeSec"}``, each in seconds.
    """
    return {
        "imuSec": _effectiveStaleSec(configPath, _STALE_IMU_SEC_KEY),
        "fuelResetConfirmSec": _effectiveStaleSec(configPath, _STALE_FUEL_RESET_CONFIRM_KEY),
        "alertsAckConfirmSec": _effectiveStaleSec(configPath, _STALE_ALERTS_ACK_CONFIRM_KEY),
        "alertsAckNoticeSec": _effectiveStaleSec(configPath, _STALE_ALERTS_ACK_NOTICE_KEY),
    }


def _effectiveStaleSec(configPath: str | None, key: str) -> float:
    """One seconds key (a stale window, the ack wait): the effective value if a
    finite number > 0, else the validator default."""
    if configPath is not None:
        found, value = overlay.readEffectiveValue(configPath, key)
        if (
            found
            and not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value > 0
        ):
            return value
    return DEFAULTS[key]


def loadFuelResetTimeoutSec(configPath: str | None) -> float:
    """Resolve ``pi.fuel.resetTimeoutSec``, the POST /fuel-reset wait (US-881-d).

    Read from config.json through the shared overlay seam. Anything that is not
    a finite number > 0 -- absent key, no config wired, unreadable file -- is the
    validator default, never a fabricated budget.

    Args:
        configPath: Path to config.json, or ``None`` when none is wired.

    Returns:
        Seconds to wait for eclipse-obd's outcome.
    """
    timeoutSec = DEFAULTS[_FUEL_RESET_TIMEOUT_KEY]
    if configPath is not None:
        found, value = overlay.readEffectiveValue(configPath, _FUEL_RESET_TIMEOUT_KEY)
        if (
            found
            and not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and value > 0
        ):
            timeoutSec = value
    return float(timeoutSec)


def loadAlertsAckTimeoutSec(configPath: str | None) -> float:
    """Resolve ``pi.warnings.ackTimeoutSec``, the POST /alerts-ack wait (US-897-c).

    The same rule as :func:`loadFuelResetTimeoutSec`: the effective config.json
    value when it is a finite number > 0, else the validator default.

    Args:
        configPath: Path to config.json, or ``None`` when none is wired.

    Returns:
        Seconds to wait for eclipse-obd's outcome.
    """
    return float(_effectiveStaleSec(configPath, _ALERTS_ACK_TIMEOUT_KEY))


def _parseAlertsAckIds(rawBody: bytes) -> list[str] | None:
    """The ids of a POST /alerts-ack body, or None when it is malformed.

    The body is ``{"ids": [...]}`` and nothing else (Atlas Q26): 1..N ids, each
    a non-empty string. An empty body (absent, or over ``_MAX_ACTION_BODY`` and
    so never read) is malformed.
    """
    try:
        payload = json.loads(rawBody.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or set(payload) != {"ids"}:
        return None
    ids = payload["ids"]
    if (
        not isinstance(ids, list)
        or not ids
        or not all(isinstance(i, str) and i for i in ids)
    ):
        return None
    return list(ids)


def loadEffectiveSettings(configPath: str | None) -> dict[str, Any] | None:
    """Read the Slice-1 operator settings at their effective values (US-532).

    The read half of the F-126 settings band. Every key in the overlay's
    allow-list is resolved through ``overlay.readEffectiveValue`` -- the SAME
    seam the POST /settings route re-reads through after a write -- so the value
    the band renders at page load and the value it renders after a save come from
    one resolver, not two.

    Iterating ``OVERRIDABLE_KEYS`` rather than a local list is deliberate: a
    Slice-2 key added to the SSOT reaches the band with no edit here, and cannot
    be surfaced under a name that has drifted from the one the write route
    accepts (the injected keys ARE the POST body keys).

    Honest-instrument: each entry is ``{"found", "value"}`` (US-878-c, Atlas
    B13), so a key that RESOLVES to null (overrideLevel = auto) is told apart
    from one that cannot be resolved -- absent, or blocked by a non-dict parent
    branch -- which is ``{"found": false, "value": null}`` (rendered "unknown"),
    never a fabricated default. An unreadable config.json yields every key
    not-found rather than raising, so a bad config degrades one band instead of
    taking the whole kiosk page down.

    Args:
        configPath: Path to config.json (relative paths resolve against the
            process CWD -- the unit's WorkingDirectory), or ``None`` when this
            server has no config wired.

    Returns:
        A flat dot-path -> ``{"found", "value"}`` map, or ``None`` when no config
        path is configured (the band then renders every row as unknown).
    """
    if configPath is None:
        return None
    settings: dict[str, Any] = {}
    for key in overlay.OVERRIDABLE_KEYS:
        found, value = overlay.readEffectiveValue(configPath, key)
        settings[key] = {"found": found, "value": value if found else None}
    return settings


def readDeployVersion(versionPath: str | None) -> str | None:
    """Read the ``version`` string from a ``.deploy-version`` record, fail-safe.

    Same LIGHT raw ``json.load`` rationale as ``_loadDisplaySection``: the release
    record is plain JSON with no ``${ENV}`` placeholders, so a full config load
    would only add failure modes to a cosmetic header chip.

    Returns ``None`` -- never a guess -- for every way this can go wrong (no path
    configured, file absent/unreadable, malformed JSON, ``version`` key missing,
    blank, or not a string). The caller renders the honest ``V?.?.?`` sentinel;
    an unreadable stamp must never become a confident wrong build number.

    Args:
        versionPath: Path to the ``.deploy-version`` record (relative paths
            resolve against the process CWD -- the unit's WorkingDirectory), or
            ``None`` when no version source is configured.

    Returns:
        The stripped version string, or ``None`` when it cannot be determined.
    """
    if not versionPath:
        return None
    try:
        with open(versionPath, encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    version = record.get("version")
    if not isinstance(version, str):
        return None
    return version.strip() or None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for eclipse-states-http.service.

    Provisions the states dir + token SSOT, then binds + serves. A bind failure
    (port already in use) raises -> the unit exits non-zero -> the kiosk fetch
    errors -> splash falls to DEGRADED (spec §8 listen-failure semantics).
    """
    import argparse

    from pi.splash.boot_state_emitter import ensureStatesDir
    from pi.splash.token import loadOrCreateToken

    parser = argparse.ArgumentParser(description="F-103 localhost state server")
    parser.add_argument("--states-dir", default="/run/eclipse-obd/states")
    # Repeatable: pass once per co-located kit (splash first, dashboard second).
    # Searched in order, first match wins. Defaults to the splash kit alone.
    parser.add_argument("--assets-dir", action="append", dest="assets_dirs")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9899)
    parser.add_argument("--token-path", default="/run/eclipse-obd/states/.http-token")
    # US-483-b / US-506: config.json (relative to the unit's WorkingDirectory by
    # default) supplies the pi.display.autoDim curve AND the pi.display.carousel
    # navigation model injected into the dashboard HTML.
    parser.add_argument("--config", default="config.json")
    # US-501: the release record whose `version` fills the dashboard header chip.
    # Same WorkingDirectory-relative default as --config, and the same place
    # deploy-pi.sh stamps it (${PI_PATH}/.deploy-version) -- so the unit file
    # needs no new argument. Unreadable -> the honest V?.?.? sentinel.
    parser.add_argument("--deploy-version-path", default=".deploy-version")
    args = parser.parse_args(argv)

    assetsDirs = args.assets_dirs if args.assets_dirs else ["/opt/splash"]

    ensureStatesDir(args.states_dir)
    token = loadOrCreateToken(args.token_path)
    server = StatesHttpServer(
        statesDir=args.states_dir,
        token=token,
        host=args.host,
        port=args.port,
        assetsDir=assetsDirs,
        displayConfig=loadDisplayAutoDimConfig(args.config),
        carouselConfig=loadDisplayCarouselConfig(args.config),
        deployVersionPath=args.deploy_version_path,
        # US-531: the same config.json the display sections are read from is the
        # one whose sibling overlay the settings route writes -- so a saved
        # toggle and the injected config can never point at different files.
        configPath=args.config,
        # ARCH-023: THE INJECTION THAT WAS MISSING.  US-407 shipped the whole
        # Mode-04 surface -- button, gate, performClear, this route -- and
        # nothing ever supplied a `clearRunner`, so /dtc-clear answered 503 and
        # the button was inert.  It could not be a direct call: this process
        # holds no OBD connection and must never open one (the orchestrator is
        # the single owner -- A-17 / A-26).  The bridge asks the process that
        # already owns it, and raises rather than inventing a readback when it
        # cannot get a real answer.
        clearRunner=dtc_clear_channel.makeBridgeClearRunner(args.states_dir),
        # US-881-d: the since-reset fuel reset crosses the same process
        # boundary for the same reason -- eclipse-obd owns the row.
        fuelResetRunner=fuel_reset_channel.makeBridgeResetRunner(
            args.states_dir,
            timeoutSeconds=loadFuelResetTimeoutSec(args.config),
        ),
        # US-897-c: the ack store and states/alerts have one writer,
        # eclipse-obd, so the ack crosses the same boundary.
        alertsAckRunner=alerts_ack_channel.makeBridgeAckRunner(
            args.states_dir,
            timeoutSeconds=loadAlertsAckTimeoutSec(args.config),
        ),
    )
    server.serveForever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
