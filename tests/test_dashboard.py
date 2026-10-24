"""Tests for the Gemba Board: telemetry capture and the stdlib server.

Run:  python -m pytest tests/ -q
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from cimemory.dashboard.capture import build  # noqa: E402
from cimemory.dashboard.server import (  # noqa: E402
    Handler, STATIC_DIR, load_demo,
)

FRAME_KEYS = {
    "i", "sim_ts", "cycle", "kind", "title", "text", "agent", "step",
    "steps_done", "steps_tally", "cap", "problem_id", "andon_id",
    "line", "board", "store", "a3", "extra",
}
STORE_KEYS = {
    "n_observation", "standards", "problems", "countermeasures",
    "root_causes", "whys", "andons", "spreads",
}
VIEWS = ["andon", "wheel", "staircase", "a3", "whys", "ledger", "yokoten"]


@pytest.fixture(scope="module")
def data():
    return build()


# --------------------------------------------------------------------------
# telemetry
# --------------------------------------------------------------------------

def test_meta_is_complete(data):
    m = data["meta"]
    assert m["agent"] == "balboa"
    assert len(m["stations"]) == 5
    assert m["n_frames"] == len(data["frames"])
    assert m["n_cycles"] >= 7
    assert len(m["steps"]) == 10
    # every step is classified into a PDCA phase
    assert set(m["pdca"]) == set(m["steps"])
    assert sum(1 for s in m["steps"] if m["pdca"][s] == "Plan") == 5


def test_every_frame_shape(data):
    m, frames = data["meta"], data["frames"]
    for f in frames:
        assert FRAME_KEYS <= set(f), f"frame {f['i']} missing keys"
        assert set(f["store"]) == STORE_KEYS
        # the station board is complete on every frame
        assert set(f["board"]) == set(m["stations"])
        for cap, st in f["board"].items():
            assert st["status"] in ("normal", "abnormal", "stopped")
            assert {"standard", "actual", "goal", "waste", "unit"} <= set(st)
        if f["line"]:
            assert f["line"]["capability"] in m["stations"]
            assert "control" in f["line"]


def test_frames_are_sequential(data):
    for i, f in enumerate(data["frames"]):
        assert f["i"] == i
    ts = [f["sim_ts"] for f in data["frames"]]
    assert ts == sorted(ts) and len(set(ts)) == len(ts)
    cycles = [f["cycle"] for f in data["frames"]]
    assert cycles == sorted(cycles)


def test_capture_is_deterministic(data):
    again = build()
    assert again["meta"] == data["meta"]

    def strip(frames):
        """Drop generated record ids so two runs can be compared."""
        out = []
        for f in frames:
            # generated ids live in store/a3/extra — compare the story, not the uuids
            g = {k: v for k, v in f.items()
                 if k not in ("store", "a3", "extra", "problem_id", "andon_id")}
            g["n_std"] = len(f["store"]["standards"])
            g["n_cm"] = len(f["store"]["countermeasures"])
            g["n_andon"] = len(f["store"]["andons"])
            g["n_why"] = len(f["store"]["whys"])
            g["n_spread"] = len(f["store"]["spreads"])
            g["board"] = f["board"]
            g["line"] = f["line"]
            out.append(g)
        return out

    assert strip(again["frames"]) == strip(data["frames"])

    # the shape of `extra` per kind must also be stable
    def extras(frames):
        shape = {}
        for f in frames:
            shape.setdefault(f["kind"], set()).update(f["extra"])
        return {k: sorted(v) for k, v in shape.items()}
    assert extras(again["frames"]) == extras(data["frames"])


def test_the_programme_actually_improves(data):
    """Each station ends inside its standard and the standard moved."""
    first, last = data["frames"][0], data["frames"][-1]
    for cap in data["meta"]["stations"]:
        assert last["board"][cap]["status"] == "normal", cap
        assert last["board"][cap]["standard"] < first["board"][cap]["standard"], cap
    actives = {s["capability"]: s for s in last["store"]["standards"] if s["active"]}
    assert set(actives) == set(data["meta"]["stations"])
    # the v2 capability is the one that ran a second cycle
    assert max(s["version"] for s in actives.values()) >= 2


def test_discipline_events_are_captured(data):
    kinds = [f["kind"] for f in data["frames"]]
    assert kinds.count("refusal") >= 3
    assert kinds.count("andon") >= 1
    assert kinds.count("kaikaku") >= 1
    assert kinds.count("standard") >= 5
    assert kinds.count("yokoten") >= 4
    # every refusal must carry the reason it was refused
    for f in data["frames"]:
        if f["kind"] == "refusal":
            assert f["extra"].get("refused")


def test_a3_is_populated_for_most_frames(data):
    with_a3 = [f for f in data["frames"] if f["a3"]]
    assert len(with_a3) > 100
    a3 = with_a3[-1]["a3"]
    assert {"problem", "whys", "countermeasures", "therefore_ok"} <= set(a3)
    # the last problem is fully worked through
    assert a3["root_cause"]["verified_by"]
    assert a3["check"]["results_met"] is True
    assert a3["hansei"]["went_poorly"]
    assert a3["standard"]["version"] >= 1


def test_countermeasure_strength_uses_the_store_vocabulary(data):
    """The frontend keys on the python enum values — guard the contract."""
    strengths = set()
    for f in data["frames"]:
        for c in f["store"]["countermeasures"]:
            strengths.add(c["strength"])
    assert strengths <= {"taisho", "taisaku", "mizen_boushi"}
    assert "mizen_boushi" in strengths


def test_wheel_step_counts_are_cumulative(data):
    prev = {}
    for f in data["frames"]:
        for k, v in f["steps_tally"].items():
            assert v >= prev.get(k, 0)
        prev = dict(f["steps_tally"])


# --------------------------------------------------------------------------
# static assets and the server
# --------------------------------------------------------------------------

def test_static_assets_exist(tmp_path):
    idx = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for v in VIEWS:
        assert (STATIC_DIR / f"js/views/{v}.js").is_file(), v
        assert f'id="view-{v}"' in idx, f"index.html has no section for {v}"
        assert f"/static/js/views/{v}.js" in idx, f"index.html does not load {v}.js"
    assert (STATIC_DIR / "css/style.css").is_file()
    assert (STATIC_DIR / "js/app.js").is_file()


def test_every_view_declares_its_id():
    for v in VIEWS:
        src = (STATIC_DIR / f"js/views/{v}.js").read_text(encoding="utf-8")
        assert f'id: "{v}"' in src, f"{v}.js does not register id {v!r}"
        assert "GEMBA_VIEWS.push" in src, v
    app = (STATIC_DIR / "js/app.js").read_text(encoding="utf-8")
    assert "GEMBA_VIEWS" in app


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """A real server on an ephemeral port, pinned to the demo source.

    The live source reads production memory; tests must not depend on a
    running Tarantool, so the fixture points it at a dead port and asks for
    ``demo`` explicitly.
    """
    load_demo(regen=False)
    Handler.source = "demo"
    Handler.tnt_host = "127.0.0.1"
    Handler.tnt_port = 9  # discard port: probe fails fast, deterministic
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.headers, r.read()


def test_health_endpoint(server):
    status, _, body = _get(server + "/api/health")
    assert status == 200
    j = json.loads(body)
    assert j["ok"] is True
    assert j["default_source"] == "demo"
    assert j["demo"]["cached_frames"] > 0
    # the live probe is reported honestly, not assumed
    assert j["live"]["reachable"] is False
    assert j["live"]["readonly"] is True


def test_data_endpoint_and_gzip(server):
    status, headers, body = _get(server + "/api/data")
    assert status == 200
    data = json.loads(body)
    assert set(data) == {"meta", "frames"}
    assert len(data["frames"]) == data["meta"]["n_frames"]

    status, headers, gz = _get(server + "/api/data",
                               {"Accept-Encoding": "gzip"})
    assert status == 200
    assert headers.get("Content-Encoding") == "gzip"
    import gzip as _gz
    assert json.loads(_gz.decompress(gz))["meta"] == data["meta"]
    assert len(gz) < len(body) / 5      # gzip must actually pay for itself


def test_index_and_static_served(server):
    status, headers, body = _get(server + "/")
    assert status == 200 and b"Gemba Board" in body
    assert "text/html" in headers.get("Content-Type", "")
    for p, ctype in (("/static/css/style.css", "text/css"),
                     ("/static/js/app.js", "text/javascript")):
        status, headers, _ = _get(server + p)
        assert status == 200 and ctype in headers.get("Content-Type", ""), p


def test_path_traversal_is_refused(server):
    import urllib.error
    try:
        status, _, _ = _get(server + "/static/../../pyproject.toml")
    except urllib.error.HTTPError as e:
        assert e.code in (403, 404)
    except Exception:
        pass


def test_unknown_route_is_404(server):
    import urllib.error
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(server + "/nope")
    assert e.value.code == 404
