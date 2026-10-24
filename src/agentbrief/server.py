"""Local web UI. Stdlib only; manifests are re-read on every request so agents' edits show up live."""

from __future__ import annotations

import json
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

from . import core

# One pytest run at a time; concurrent runs would race on the results cache.
_test_lock = threading.Lock()


def make_handler(root: Path, base: Optional[str], token: str):
    page = resources.files("agentbrief").joinpath("static/index.html").read_text(encoding="utf-8")
    page = page.replace("__AGENTBRIEF_TOKEN__", token)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # keep the terminal quiet
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: Any, status: int = 200) -> None:
            self._send(status, json.dumps(data).encode(), "application/json")

        def _local_host(self) -> bool:
            # Guards against DNS rebinding: only answer to requests addressed to localhost.
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return host in ("127.0.0.1", "localhost", "[::1]")

        def do_GET(self) -> None:
            if not self._local_host():
                return self._json({"error": "forbidden host"}, HTTPStatus.FORBIDDEN)
            url = urlparse(self.path)
            if url.path == "/":
                return self._send(200, page.encode(), "text/html; charset=utf-8")
            if url.path == "/api/overview":
                return self._json(core.overview(root, base))
            if url.path.startswith("/api/features/"):
                feature = core.find_feature(root, unquote(url.path[len("/api/features/"):]))
                if feature is None:
                    return self._json({"error": "unknown feature"}, HTTPStatus.NOT_FOUND)
                view = core.feature_view(root, feature, core.load_results(root),
                                         core.load_reviews(root), detail=True, base=base)
                return self._json(view)
            if url.path == "/api/diff":
                path = parse_qs(url.query).get("path", [""])[0]
                return self._json({"path": path, "diff": core.file_diff(root, path, base)})
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if not self._local_host() or self.headers.get("X-Agentbrief-Token") != token:
                return self._json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json({"error": "bad json"}, HTTPStatus.BAD_REQUEST)
            url = urlparse(self.path)

            if url.path == "/api/run-tests":
                fid = body.get("feature_id")
                nodeids = []
                if fid:
                    feature = core.find_feature(root, fid)
                    if feature is None:
                        return self._json({"error": "unknown feature"}, HTTPStatus.NOT_FOUND)
                    nodeids = [t.nodeid for t in feature.tests]
                    if not nodeids:
                        return self._json({"error": "feature lists no tests"}, HTTPStatus.BAD_REQUEST)
                if not _test_lock.acquire(blocking=False):
                    return self._json({"error": "a test run is already in progress"}, HTTPStatus.CONFLICT)
                try:
                    return self._json(core.run_tests(root, nodeids))
                finally:
                    _test_lock.release()

            if url.path == "/api/review":
                feature = core.find_feature(root, body.get("feature_id", ""))
                if feature is None:
                    return self._json({"error": "unknown feature"}, HTTPStatus.NOT_FOUND)
                # Refuse to approve code the reviewer hasn't seen (agent edited it after page load).
                view = core.feature_view(root, feature, core.load_results(root), {}, base=base)
                if body.get("status") and body.get("fingerprint") != view["fingerprint"]:
                    return self._json({"error": "the code changed since you opened it; reload and re-check"},
                                      HTTPStatus.CONFLICT)
                quiz = None
                if body.get("status") == "approved":
                    # Approval means "I read the code and checked my understanding", so require both.
                    quiz = core.approval_gate(feature, body.get("checked_code"), body.get("answers"))
                    if quiz is None:
                        return self._json({"error": "check every code block and answer every question first"},
                                          HTTPStatus.BAD_REQUEST)
                try:
                    core.save_review(root, feature.id, body.get("status"), body.get("note", ""),
                                     view["fingerprint"], quiz)
                except ValueError as exc:
                    return self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return self._json({"ok": True})

            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    return Handler


def serve(root: Path, host: str = "127.0.0.1", port: int = 8765,
          base: Optional[str] = None, open_browser: bool = True) -> None:
    token = secrets.token_urlsafe(16)
    httpd = ThreadingHTTPServer((host, port), make_handler(root, base, token))
    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{httpd.server_port}/"
    print(f"Agentbrief for {root}\n  -> {url}  (Ctrl+C to stop)")
    if open_browser:
        import webbrowser
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        httpd.server_close()
