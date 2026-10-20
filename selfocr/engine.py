"""Indra OCR のラッパー: アップロードされた文書を保持し、1 ページずつ読み出す.

Model はindra_ocr の API をそのまま使う:

    OrtOCR(model_dir(...))        認識器 (ONNX Runtime)
    Converter(ocr, dpi=..., mode=...)  PDF のテキスト層と OCR の切り分け

認識器の生成は 1 度高 (``math`` / ``keep_furniture`` の組み合わせごとに 1 個),
以後は使い回す。
"""

from __future__ import annotations

import base64
import os
import tempfile
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from indra_ocr import Converter, InputError, OrtOCR, model_dir
from indra_ocr.models import ModelError

MAX_SIDE = 1600  # ブラウザに送るプレビュー画像の長辺
MODES = ("auto", "ocr", "text")
PREVIEW_QUALITY = 82


class Engine:
    """アップロードされた文書と OCR 認識器を持つ."""

    def __init__(
        self,
        threads: int = 0,
        model_path: Path | None = None,
        keep_documents: int = 8,
    ) -> None:
        self.threads = threads or max(1, (os.cpu_count() or 4))
        self.model_path = model_path
        self.keep_documents = max(1, keep_documents)
        self._ocrs: dict[tuple[bool, bool], OrtOCR] = {}
        self._lock = threading.RLock()  # page() の中から _ocr() を呼べるように
        self._docs: dict[str, dict[str, Any]] = {}
        self._tmp = tempfile.TemporaryDirectory(prefix="selfocr_")

    # --- 認識器 -------------------------------------------------------------
    def _ocr(self, math: bool, furniture: bool) -> OrtOCR:
        key = (math, furniture)
        with self._lock:
            ocr = self._ocrs.get(key)
            if ocr is None:
                onnx = model_dir(self.model_path, math=math)
                ocr = OrtOCR(onnx, threads=self.threads, furniture=furniture, math=math)
                ocr(np.full((200, 200), 255, np.uint8))  # 初回はウォームアップ
                self._ocrs[key] = ocr
            return ocr

    def warm_up(self) -> None:
        """起動時にモデルを溜めておく (最初のアクセスを速くする)."""
        try:
            self._ocr(False, False)
        except (ModelError, OSError) as exc:  # モデル取得失敗でも起動は続ける
            print(f"selfOCR: model warm-up failed: {exc}", flush=True)

    # --- アップロード -------------------------------------------------------
    def upload(self, data: bytes, name: str = "") -> dict:
        """バイト列を受け取って、文書 ID とページ数を返す."""
        if not data:
            raise InputError("empty file")
        is_pdf = data[:5] == b"%PDF-"
        did = uuid.uuid4().hex[:12]
        path = Path(self._tmp.name) / (did + (".pdf" if is_pdf else ".bin"))
        path.write_bytes(data)
        if is_pdf:
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(str(path))
            try:
                pages = len(doc)
            finally:
                doc.close()
        else:
            self._decode(data)  # 読めない画像ならここでエラー
            pages = 1
        with self._lock:
            self._docs[did] = {
                "path": path,
                "is_pdf": is_pdf,
                "pages": pages,
                "name": name or path.name,
                "size": len(data),
                "at": time.time(),
            }
            self._trim()
        return {
            "id": did,
            "pages": pages,
            "name": name,
            "size": len(data),
            "is_pdf": is_pdf,
        }

    def _trim(self) -> None:
        """古いアップロードを捨てる (直近の documents 件だけ保持)."""
        while len(self._docs) > self.keep_documents:
            oldest = min(self._docs.items(), key=lambda kv: kv[1]["at"])[0]
            doc = self._docs.pop(oldest)
            try:
                os.remove(doc["path"])
            except OSError:
                pass

    # --- ページの読み出し ----------------------------------------------------
    def page(self, did: str, n: int, opts: dict | None = None) -> dict:
        opts = opts or {}
        mode = opts.get("mode", "auto")
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        math = bool(opts.get("math"))
        furniture = bool(opts.get("furniture"))
        dpi = float(opts.get("dpi") or 200.0)
        with self._lock:
            doc = self._docs.get(did)
        if doc is None:
            raise InputError("unknown document id")
        if not 0 <= n < doc["pages"]:
            raise InputError("page out of range")

        import cv2

        with self._lock:
            ocr = self._ocr(math, furniture)
            converter = Converter(
                ocr, dpi=dpi, mode=mode, image_ocr=bool(opts.get("image_ocr", True))
            )
            t0 = time.perf_counter()
            if doc["is_pdf"]:
                import pypdfium2 as pdfium

                pdf = pdfium.PdfDocument(str(doc["path"]))
                try:
                    scale = converter.page_scale(pdf[n])
                    arr = pdf[n].render(scale=scale, grayscale=True).to_numpy()
                    gray = np.ascontiguousarray(
                        arr[..., 0] if arr.ndim == 3 else arr
                    )
                    page = converter.pdf_page(str(doc["path"]), pdf, n)
                finally:
                    pdf.close()
            else:
                gray, angle = self._decode(doc["path"].read_bytes())
                if angle:
                    gray = np.ascontiguousarray(np.rot90(gray, -angle))
                page = ocr(gray)
            render_ms = 1000 * (time.perf_counter() - t0)

        if page.rotation:  # ボックスは補正後のページ座標
            gray = np.ascontiguousarray(np.rot90(gray, -(page.rotation // 90)))
        h, w = gray.shape
        scale = min(1.0, MAX_SIDE / max(h, w))
        small = (
            cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            if scale < 1
            else gray
        )
        ok, jpg = cv2.imencode(
            ".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_QUALITY]
        )
        if not ok:
            raise RuntimeError("could not encode the preview image")

        def scaled(box):
            return [round(v * scale, 1) for v in box[:4]]

        markdown = page.markdown if page.markdown is not None else page.text
        timings = {k: round(float(v), 1) for k, v in (page.timings or {}).items()}
        return {
            "page": n + 1,
            "pages": doc["pages"],
            "name": doc["name"],
            "w": small.shape[1],
            "h": small.shape[0],
            "img": "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode(),
            "lines": [
                {"box": scaled(ln.box), "text": ln.text, "conf": ln.conf}
                for ln in page.lines
            ],
            "blocks": [
                {"label": b["label"], "box": scaled(b["bbox"]), "text": b.get("text", "")}
                for b in page.blocks
            ],
            "markdown": markdown,
            "text": page.text,
            "source": page.source,
            "note": page.note,
            "rotation": page.rotation,
            "skew": page.skew,
            "vertical": page.vertical,
            "timings": {"render_ms": round(render_ms, 1), **timings},
            "json": {
                "page": n,
                "source": page.source,
                "rotation": page.rotation,
                "skew": page.skew,
                "vertical": page.vertical,
                "note": page.note,
                "lines": [asdict(ln) for ln in page.lines],
                "markdown": page.markdown,
                "blocks": page.blocks,
                "timings": page.timings,
            },
        }

    # --- 画像のデコード -----------------------------------------------------
    @staticmethod
    def _decode(data: bytes) -> tuple[np.ndarray, int]:
        """バイト列をグレースケール画像にする. EXIF の向きも反映する."""
        import cv2

        try:
            from PIL import Image, ImageOps  # type: ignore
        except ImportError:
            Image = None
        if Image is not None:
            import io

            try:
                with Image.open(io.BytesIO(data)) as im:
                    im = ImageOps.exif_transpose(im).convert("RGB")
                    gray = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2GRAY)
                return np.ascontiguousarray(gray), 0
            except Exception as exc:  # noqa: BLE001  壊れた画像は後でエラーにする
                raise InputError(f"not a readable image ({exc})") from exc
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise InputError("not a PDF or a readable image")
        return np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)), 0
