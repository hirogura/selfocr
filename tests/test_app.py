"""HTTP API の確認."""

from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from selfocr import VERSION_LABEL
from selfocr.app import App, Server, make_handler
from selfocr.config import SETTINGS


@pytest.fixture(scope="module")
def app():
    return App(SETTINGS)


@pytest.fixture(scope="module")
def server(app):
    httpd = Server(("127.0.0.1", 0), make_handler(app))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=30) as res:
        return res.status, res.read().decode()


def post(url, data: bytes, headers: dict | None = None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.status, res.read().decode()


def test_index_has_version(server):
    status, body = get(f"{server}/")
    assert status == 200
    assert VERSION_LABEL in body
    assert "アップデート" in body
    assert "再起動" in body


def test_index_has_strip_html_option(server):
    status, body = get(f"{server}/")
    assert status == 200
    assert "opt-strip-html" in body
    assert "HTMLタグ除去" in body


def test_info(server):
    status, body = get(f"{server}/api/info")
    data = json.loads(body)
    assert status == 200
    assert data["version_label"] == VERSION_LABEL
    assert data["name"] == "selfOCR"
    assert data["indra_version"]


def test_health(server):
    status, body = get(f"{server}/api/health")
    assert json.loads(body)["status"] == "ok"


def test_upload_and_page(server):
    import cv2
    import numpy as np

    img = np.full((200, 700), 255, np.uint8)
    cv2.putText(img, "Hello selfOCR 12345", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
    ok, buf = cv2.imencode(".png", img)
    assert ok

    status, body = post(
        f"{server}/api/upload",
        buf.tobytes(),
        {"Content-Type": "application/octet-stream", "X-Filename": "hello.png"},
    )
    doc = json.loads(body)
    assert status == 200
    assert doc["pages"] == 1

    status, body = post(
        f"{server}/api/page",
        json.dumps({"id": doc["id"], "n": 0, "opts": {"mode": "ocr"}}).encode(),
        {"Content-Type": "application/json"},
    )
    page = json.loads(body)
    assert status == 200
    assert "selfOCR" in page["markdown"]
    assert "<p>" in page["html"]


def test_update_status(server):
    status, body = get(f"{server}/api/update/status")
    data = json.loads(body)
    assert status == 200
    assert data["state"] in ("idle", "running", "done", "error", "restarting")


def test_page_strips_html(server, app, monkeypatch):
    import cv2
    import numpy as np

    table = "<table>\n<tr><th>Name</th></tr>\n<tr><td>Apple</td></tr>\n</table>"
    monkeypatch.setattr(
        app.engine,
        "_recognize",
        lambda *a, **k: {
            "page": 1,
            "pages": 1,
            "name": "table.png",
            "w": 10,
            "h": 10,
            "img": "data:image/jpeg;base64,",
            "lines": [],
            "blocks": [],
            "markdown": table,
            "text": "Name Apple",
            "source": "ocr",
            "note": "",
            "rotation": 0,
            "skew": 0,
            "vertical": False,
            "timings": {"total_ms": 1},
            "json": {"page": 0, "markdown": table},
        },
    )

    img = np.full((60, 60), 255, np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    status, body = post(
        f"{server}/api/upload",
        buf.tobytes(),
        {"Content-Type": "application/octet-stream", "X-Filename": "table.png"},
    )
    did = json.loads(body)["id"]

    def page(strip_html):
        status, body = post(
            f"{server}/api/page",
            json.dumps(
                {"id": did, "n": 0, "opts": {"mode": "ocr", "strip_html": strip_html}}
            ).encode(),
            {"Content-Type": "application/json"},
        )
        assert status == 200
        return json.loads(body)

    stripped = page(True)
    assert stripped["markdown"] == "Name\nApple"
    assert "<table>" not in stripped["markdown"]
    assert "<table>" not in stripped["html"]
    assert stripped["json"]["markdown"] == "Name\nApple"

    kept = page(False)
    assert kept["markdown"] == table
    assert "<table>" in kept["markdown"]
