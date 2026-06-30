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
# ================================================================================
################################################################################

"""Localhost-only, token-gated, read-only HTTP server for the splash states."""

from __future__ import annotations

import hmac
import mimetypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

# Placeholder substituted with the live token when the kiosk HTML is served.
_TOKEN_PLACEHOLDER = "__SPLASH_TOKEN__"

# HTML entry points get the token injected; treated as the same-origin bootstrap.
_INDEX_NAMES = frozenset({"", "index.html"})


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


def makeStatesHandler(
    statesDir: str, token: str, assetsDir: str | None = None
) -> type[BaseHTTPRequestHandler]:
    """Build a request-handler class bound to one states dir + token + assets."""

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
            # must load before it can authenticate the state polls.
            if assetsDir is not None:
                assetFile = _isSafeFile(assetsDir, name)
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

        def _serveIndex(self) -> None:
            if assetsDir is None:
                self._send(404, b"not found", "text/plain")
                return
            indexFile = _isSafeFile(assetsDir, "index.html")
            if indexFile is None:
                self._send(404, b"not found", "text/plain")
                return
            html = indexFile.read_text(encoding="utf-8").replace(
                _TOKEN_PLACEHOLDER, token
            )
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

        def _serveAsset(self, assetFile: Path) -> None:
            contentType, _ = mimetypes.guess_type(str(assetFile))
            if assetFile.suffix == ".svg":
                contentType = "image/svg+xml"
            # HTML assets (e.g. shutdown.html) also get the token injected.
            if assetFile.suffix in (".html", ".htm"):
                html = assetFile.read_text(encoding="utf-8").replace(
                    _TOKEN_PLACEHOLDER, token
                )
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
        assetsDir: str | None = None,
    ) -> None:
        self.host = host
        self.statesDir = statesDir
        handler = makeStatesHandler(statesDir, token, assetsDir)
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
    parser.add_argument("--assets-dir", default="/opt/splash")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9899)
    parser.add_argument("--token-path", default="/run/eclipse-obd/states/.http-token")
    args = parser.parse_args(argv)

    ensureStatesDir(args.states_dir)
    token = loadOrCreateToken(args.token_path)
    server = StatesHttpServer(
        statesDir=args.states_dir,
        token=token,
        host=args.host,
        port=args.port,
        assetsDir=args.assets_dir,
    )
    server.serveForever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
