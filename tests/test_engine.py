"""Indra OCR で画像と PDF が読めることの確認."""

from __future__ import annotations

import numpy as np
import pytest

from selfocr.engine import Engine


def make_image(text: str = "Hello selfOCR 12345"):
    import cv2

    img = np.full((200, 700), 255, np.uint8)
    cv2.putText(img, text, (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


@pytest.fixture(scope="module")
def engine():
    return Engine(threads=2)


def test_upload_and_read_image(engine):
    data = make_image()
    doc = engine.upload(data, "hello.png")
    assert doc["pages"] == 1
    assert doc["is_pdf"] is False

    page = engine.page(doc["id"], 0, {"mode": "auto"})
    assert "selfOCR" in page["markdown"]
    assert page["source"] in ("ocr", "text", "hybrid")
    assert page["lines"]
    assert page["img"].startswith("data:image/jpeg;base64,")
    assert page["timings"]["total_ms"] > 0


def test_upload_rejects_garbage(engine):
    from indra_ocr import InputError

    with pytest.raises(InputError):
        engine.upload(b"not an image at all", "x.txt")


def test_read_pdf(engine):
    import tempfile
    from pathlib import Path

    from PIL import Image, ImageDraw

    imgs = []
    for i in range(2):
        im = Image.new("RGB", (900, 300), "white")
        ImageDraw.Draw(im).text((40, 120), f"Page {i + 1} of selfOCR test", fill="black")
        imgs.append(im)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.pdf"
        imgs[0].save(path, save_all=True, append_images=imgs[1:])
        data = path.read_bytes()

    doc = engine.upload(data, "test.pdf")
    assert doc["pages"] == 2
    assert doc["is_pdf"] is True

    page = engine.page(doc["id"], 1, {"mode": "ocr", "dpi": 200})
    assert "Page 2" in page["markdown"]
    assert page["page"] == 2
    assert page["pages"] == 2


def test_unknown_document(engine):
    from indra_ocr import InputError

    with pytest.raises(InputError):
        engine.page("deadbeef", 0, {})
