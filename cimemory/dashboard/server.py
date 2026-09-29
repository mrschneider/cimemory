"""Gemba Board server — stdlib only, no dependencies.

Serves the board and its telemetry. Two sources:

* ``live``  — production agent memory in Tarantool, READ-ONLY (the default
  when the memory is reachable). Nothing is written back.
* ``demo``  — the scripted seven-cycle programme in ``dashboard/capture.py``,
  used as the design reference and as the fallback.

    python3 -m cimemory.dashboard                   # live, falling back to demo
    python3 -m cimemory.dashboard --source demo     # the scripted programme
    python3 -m cimemory.dashboard --source live --tnt-host 127.0.0.1 --tnt-port 3301
    python3 -m cimemory.dashboard --host 0.0.0.0 --port 8700

Endpoints
    /                    the board (static)
    /api/data            {meta, frames} — telemetry (gzip); ?source=live|demo
    /api/data?regen=1    re-read the source before answering
    /api/health          liveness, active source, and reachability of each
    /static/...          css/js

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

# A live read hits production memory, so it is cached briefly: the board is an
# observation instrument, not a poller.
LIVE_TTL = float(os.environ.get("CIMEMORY_LIVE_TTL", "60"))

_CACHE: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------

def load_demo(regen: bool = False) -> dict[str, Any]:
    """The scripted seven-cycle programme (no external dependency)."""
    slot = _CACHE.setdefault("demo", {})
    if regen or slot.get("data") is None:
        if regen or not FRAMES_FILE.exists():
            from .capture import build
            data = build()
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            FRAMES_FILE.write_text(json.dumps(data, separators=(",", ":")))
        else:
            data = json.loads(FRAMES_FILE.read_text())
        slot["data"] = data
    slot["loaded_at"] = time.time()
    return slot["data"]


def load_live(regen: bool = False, *, host: str = "127.0.0.1",
              port: int = 3301, ttl: float = LIVE_TTL) -> dict[str, Any]:
    """Read production agent memory (read-only) and build the board.

    Raises whatever the source raised — the caller decides whether to fall
    back. The memory is never written to.
    """
    from ..live.capture_live import build_live
    from ..live.source import ReadOnlyTarantool

    slot = _CACHE.setdefault("live", {})
    fresh = slot.get("data") is not None and \
        (time.time() - slot.get("loaded_at", 0)) < ttl
    if not regen and fresh:
        return slot["data"]

    src = ReadOnlyTarantool(host=host, port=port)
    src.verify_read_only()
    data = build_live(src)
    slot["data"] = data
    slot["loaded_at"] = time.time()
    slot["stats"] = src.stats()
    return data


def resolve_source(requested: str, *, host: str, port: int,
                   regen: bool = False) -> tuple:
    """Return ``(source, data, note)``. Falls back to demo, and says so."""
    if requested == "demo":
        return "demo", load_demo(regen=regen), None
    try:
        return "live", load_live(regen=regen, host=host, port=port), None
    except Exception as exc:
        note = f"live source unavailable ({type(exc).__name__}: {exc}); served demo"
        return "demo", load_demo(regen=False), note


def probe_live(host: str, port: int) -> dict[str, Any]:
    try:
        from ..live.source import probe
        return probe(host=host, port=port)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "host": host, "port": port, "readonly": True}


# ---------------------------------------------------------------------------
# http
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "GembaBoard/0.2"

    # set in main()
    source = "live"
    tnt_host = "127.0.0.1"
    tnt_port = 3301

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
        qs = parse_qs(url.query)

        if route in ("/", "/index.html"):
            return self._file(STATIC_DIR / "index.html")

        if route == "/api/data":
            regen = qs.get("regen", ["0"])[0] in ("1", "true")
            want = qs.get("source", [self.source])[0]
            source, data, note = resolve_source(
                want, host=self.tnt_host, port=self.tnt_port, regen=regen)
            payload = dict(data)
            meta = dict(payload.get("meta", {}))
            meta["served_source"] = source
            meta["requested_source"] = want
            if note:
                meta["source_note"] = note
            payload["meta"] = meta
            return self._json(payload, gzip_it=True)

        if route == "/api/health":
            live = probe_live(self.tnt_host, self.tnt_port)
            demo_slot = _CACHE.get("demo", {})
            live_slot = _CACHE.get("live", {})
            return self._json({
                "ok": True,
                "default_source": self.source,
                "live": {
                    "reachable": bool(live.get("ok")),
                    "space": live.get("space"),
                    "rows": live.get("rows", 0),
                    "endpoint": f"{self.tnt_host}:{self.tnt_port}",
                    "readonly": True,
                    "cached_frames": (live_slot.get("data") or {}).get(
                        "meta", {}).get("n_frames", 0),
                    "error": live.get("error"),
                },
                "demo": {
                    "cached_frames": (demo_slot.get("data") or {}).get(
                        "meta", {}).get("n_frames", 0),
                },
                "loaded_at": max(demo_slot.get("loaded_at") or 0,
                                 live_slot.get("loaded_at") or 0) or None,
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
    ap.add_argument("--source", default="live", choices=("live", "demo"),
                    help="default source the UI asks for (live falls back to demo)")
    ap.add_argument("--tnt-host", default=os.environ.get("CIMEMORY_TNT_HOST", "127.0.0.1"))
    ap.add_argument("--tnt-port", type=int,
                    default=int(os.environ.get("CIMEMORY_TNT_PORT", "3301")))
    ap.add_argument("--regen", action="store_true",
                    help="rebuild the demo telemetry before serving")
    args = ap.parse_args()

    Handler.source = args.source
    Handler.tnt_host = args.tnt_host
    Handler.tnt_port = args.tnt_port

    live = probe_live(args.tnt_host, args.tnt_port)
    if args.regen:
        load_demo(regen=True)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"gemba board -> http://{args.host}:{args.port}")
    print(f"  default source: {args.source}")
    print(f"  live memory   : {args.tnt_host}:{args.tnt_port} "
          f"{'reachable, ' + str(live.get('rows', 0)) + ' rows' if live.get('ok') else 'UNREACHABLE — demo will be served'}"
          f" (read-only)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nboard stopped")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
