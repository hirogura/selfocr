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
def server():
    app = App(SETTINGS)
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
