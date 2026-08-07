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
# ================================================================================
################################################################################

"""Localhost-only, token-gated state server (read-only GET + the US-403 action).

GET is read-only (states + same-origin assets). US-403 adds exactly ONE write
route -- POST /service-control -- so the unprivileged chromium kiosk can request
a `systemctl restart/stop` on the install-fixed allow-list. The endpoint is a
thin transport: the allow-list gate is the ``service_control`` SSOT and the real
privilege is the 51- polkit rule; the kiosk never runs as root.
"""

from __future__ import annotations

import hmac
import json
import mimetypes
from collections.abc import Callable, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from common.config.overlay import applyConfigOverlay
from pi.splash import dtc_clear, service_control

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
_DISPLAY_CAROUSEL_PLACEHOLDER = '"__DISPLAY_CAROUSEL__"'

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

# The `dtc` state file the clear gate re-check reads (matches dtc_emitter).
_DTC_STATE_FILENAME = "dtc"

# Largest action request body we will read (tiny {unit, verb} / {confirm} JSON).
_MAX_ACTION_BODY = 4096


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
    carousel falls back to its built-in grounded defaults.

    ``carouselConfig`` (US-506) is the ``pi.display.carousel`` sub-config -- the
    auto-rotate period, pause self-expiry and swipe velocity/travel thresholds --
    injected the same way, with the same ``None`` -> grounded-defaults fallback.

    ``deployVersionPath`` (US-501) is the ``.deploy-version`` release record whose
    ``version`` fills the dashboard header chip. ``None``, absent, unreadable or
    malformed -> the honest ``V?.?.?`` sentinel; the placeholder is substituted
    either way so a raw ``__DEPLOY_VERSION__`` can never reach the panel.
    """
    assetsDirs = _normalizeAssetsDirs(assetsDir)
    # Serialize once: the JSON object literal substituted for the quoted
    # placeholder (json.dumps(None) -> "null", the honest no-config fallback).
    displayConfigJson = json.dumps(displayConfig)
    carouselConfigJson = json.dumps(carouselConfig)

    class _StatesHandler(BaseHTTPRequestHandler):
        # Silence default stderr request logging -- the journal captures stdout.
        def log_message(self, *args, **kwargs):  # noqa: N802 (stdlib signature)
            return

        def _send(self, status: int, body: bytes, contentType: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", contentType)
            self.send_header("Content-Length", str(len(body)))
            # Always no-store: the kiosk polls at 250ms and must never see stale.
            self.send_header("Cache-Control", "no-store")
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
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            rawBody = self.rfile.read(length) if 0 < length <= _MAX_ACTION_BODY else b""

            # Exactly two write routes (US-403 service-control, US-407 dtc-clear).
            # Everything else is 404 (the server is otherwise read-only).
            rawPath = unquote(urlsplit(self.path).path)
            if rawPath == _ACTION_PATH:
                self._handleServiceControl(rawBody)
                return
            if rawPath == _CLEAR_PATH:
                self._handleDtcClear()
                return
            self._send(404, b'{"error":"not found"}', "application/json")

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

            outcome = dtc_clear.performClear(dtcState, clearRunner=clearRunner)
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
            return (
                html.replace(_TOKEN_PLACEHOLDER, token)
                .replace(_DISPLAY_AUTODIM_PLACEHOLDER, displayConfigJson)
                .replace(_DISPLAY_CAROUSEL_PLACEHOLDER, carouselConfigJson)
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
        config = applyConfigOverlay(config, configPath)
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
    )
    server.serveForever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
