"""Gemba Board server — stdlib only, no dependencies.

Serves the captured telemetry and the static UI.

    python3 -m cimemory.dashboard              # http://127.0.0.1:8700
    python3 -m cimemory.dashboard --regen      # rebuild the telemetry first
    python3 -m cimemory.dashboard --host 0.0.0.0 --port 8700

Endpoints
    /                the board (static)
    /api/data        {meta, frames} — the full telemetry trace (gzip)
    /api/health      liveness + capture info
    /static/...      css/js

Implemented on http.server so the board ships with the plugin and runs
anywhere Python runs — no framework, no venv, no install.
"""

from __future__ import annotations

import argparse
import gzip
import json
import mimetypes
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
DATA_DIR = HERE / "data"
FRAMES_FILE = DATA_DIR / "frames.json"

_CACHE: dict[str, Any] = {}


def load_data(regen: bool = False) -> dict[str, Any]:
    """Load (and cache) the telemetry. Rebuilds if missing or --regen."""
    if regen or not FRAMES_FILE.exists():
        from .capture import build
        data = build()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        FRAMES_FILE.write_text(json.dumps(data, separators=(",", ":")))
        _CACHE["data"] = data
    elif _CACHE.get("data") is None:
        _CACHE["data"] = json.loads(FRAMES_FILE.read_text())
    _CACHE["loaded_at"] = time.time()
    return _CACHE["data"]


class Handler(BaseHTTPRequestHandler):
    server_version = "GembaBoard/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - keep the console quiet
        if os.environ.get("CIMEMORY_DASHBOARD_VERBOSE"):
            super().log_message(format, *args)

    # -- helpers -----------------------------------------------------------

    def _send(self, status: int, body: bytes, ctype: str,
              extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj: Any, gzip_it: bool = False) -> None:
        body = json.dumps(obj, separators=(",", ":")).encode()
        extra = {}
        accept = self.headers.get("Accept-Encoding", "")
        if gzip_it and "gzip" in accept and len(body) > 1024:
            body = gzip.compress(body, 6)
            extra["Content-Encoding"] = "gzip"
        self._send(200, body, "application/json; charset=utf-8", extra)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self._send(404, b"not found", "text/plain")
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if path.suffix in (".js", ".mjs"):
            ctype = "text/javascript"
        if ctype.startswith("text/") or path.suffix in (".js", ".css", ".json", ".svg"):
            ctype += "; charset=utf-8"
        self._send(200, path.read_bytes(), ctype)

    # -- routes ------------------------------------------------------------

    def do_GET(self) -> None:
        url = urlparse(self.path)
        route = url.path

        if route in ("/", "/index.html"):
            return self._file(STATIC_DIR / "index.html")

        if route == "/api/data":
            qs = parse_qs(url.query)
            regen = qs.get("regen", ["0"])[0] in ("1", "true")
            return self._json(load_data(regen=regen), gzip_it=True)

        if route == "/api/health":
            data = _CACHE.get("data")
            return self._json({
                "ok": True,
                "captured": data is not None,
                "n_frames": data["meta"]["n_frames"] if data else 0,
                "n_cycles": data["meta"]["n_cycles"] if data else 0,
                "loaded_at": _CACHE.get("loaded_at"),
            })

        if route.startswith("/static/"):
            rel = route[len("/static/"):]
            target = (STATIC_DIR / rel).resolve()
            if not str(target).startswith(str(STATIC_DIR.resolve())):
                return self._send(403, b"forbidden", "text/plain")
            return self._file(target)

        self._send(404, b"not found", "text/plain")

    do_HEAD = do_GET


def main() -> None:
    ap = argparse.ArgumentParser(description="cimemory Gemba Board")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8700)
    ap.add_argument("--regen", action="store_true",
                    help="rebuild the telemetry before serving")
    args = ap.parse_args()

    data = load_data(regen=args.regen)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"gemba board -> http://{args.host}:{args.port}")
    print(f"  {data['meta']['n_frames']} frames · {data['meta']['n_cycles']} cycles "
          f"· {len(data['meta']['stations'])} stations")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nboard stopped")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
