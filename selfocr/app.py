"""selfOCR の HTTP サーバー.

標準ライブラリだけで動く. 静的なページと小さな JSON API だけBlueprint である.

    GET  /                  画面 (selfOCR)
    GET  /api/info          バージョンなどの情報
    GET  /api/health        ヘルスチェック
    POST /api/upload        ファイル (画像 / PDF) のアップロード
    POST /api/page          1 ページ分の OCR 結果
    POST /api/restart       サービス再起動
    POST /api/update        GitHub からのアップデート
    GET  /api/update/status アップデートの進行状況
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import APP_NAME, VERSION_LABEL, __version__
from .config import SETTINGS
from .engine import Engine
from .service import REPO_URL, ServiceManager

MAX_LOG_LINES = 200
CHUNK = 64 * 1024


def render_markdown(text: str) -> str:
    """Markdown を HTML にする (依存が無いときは.pre でそのまま)."""
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        import html

        return f"<pre>{html.escape(text)}</pre>"
    md = MarkdownIt("commonmark", {"html": False, "linkify": True}).enable(
        ["table", "strikethrough"]
    )
    return md.render(text)


class App:
    """アプリケーションの状態 (エンジンと操作)."""

    def __init__(self, settings=SETTINGS) -> None:
        self.settings = settings
        self.engine = Engine(
            threads=settings.threads,
            model_path=settings.model_dir,
            keep_documents=settings.keep_documents,
        )
        self.service = ServiceManager(settings.repo_root)
        self.started_at = time.time()

    def info(self) -> dict:
        try:
            from indra_ocr import __version__ as indra_version
        except ImportError:
            indra_version = "unknown"
        update = self.service.status()
        update.pop("log", None)  # ログは /api/update/status だけ
        return {
            "name": APP_NAME,
            "version": __version__,
            "version_label": VERSION_LABEL,
            "indra_version": indra_version,
            "uptime": round(time.time() - self.started_at, 1),
            "threads": self.engine.threads,
            "repo": REPO_URL,
            "update": update,
        }


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"{APP_NAME}/{__version__}"
        protocol_version = "HTTP/1.1"

        # --- ヘルパ ---------------------------------------------------------
        def log_message(self, fmt, *args):  # 静かにする
            if self.path.startswith("/api/"):
                print(f"{self.address_string()} {fmt % args}", flush=True)

        def _send(self, code: int, body: bytes, ctype: str = "application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code: int, data: dict):
            self._send(code, json.dumps(data, ensure_ascii=False).encode())

        def _error(self, code: int, message: str):
            self._json(code, {"error": message})

        def _body(self) -> bytes:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length > app.settings.max_upload_bytes:
                raise ValueError("ファイルが大きすぎます")
            data = bytearray()
            while len(data) < length:
                chunk = self.rfile.read(min(CHUNK, length - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            return bytes(data)

        def _authorized(self) -> bool:
            """破壊的な操作 (再起動 / アップデート) の認可.

            SELFOCR_ADMIN_TOKEN が設定されていれば一致が必要. 未設定なら
            (自分専用のサーバーのため) 許可する.
            """
            token = app.settings.admin_token
            if not token:
                return True
            given = self.headers.get("X-Selfocr-Token", "")
            return given == token

        def _static(self, name: str):
            root = app.settings.static_dir.resolve()
            path = (root / name).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                self._error(404, "not found")
                return
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in (
                "application/javascript",
                "image/svg+xml",
            ):
                ctype += "; charset=utf-8"
            data = path.read_bytes()
            if name == "index.html":
                data = data.replace(b"__VERSION__", VERSION_LABEL.encode())
            self._send(200, data, ctype)

        # --- GET ------------------------------------------------------------
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._static("index.html")
            elif path.startswith("/static/"):
                self._static(path[len("/static/") :])
            elif path == "/api/info":
                self._json(200, app.info())
            elif path == "/api/health":
                self._json(200, {"status": "ok", "version": __version__})
            elif path == "/api/update/status":
                self._json(200, app.service.status())
            else:
                self._error(404, "not found")

        # --- POST -----------------------------------------------------------
        def do_POST(self):
            path = self.path.split("?", 1)[0]
            try:
                if path == "/api/upload":
                    data = self._body()
                    name = unquote(self.headers.get("X-Filename", ""))
                    self._json(200, app.engine.upload(data, name))
                elif path == "/api/page":
                    req = json.loads(self._body() or b"{}")
                    opts = dict(req.get("opts") or {})
                    result = app.engine.page(req["id"], int(req["n"]), opts)
                    result["html"] = render_markdown(result.get("markdown") or "")
                    self._json(200, result)
                elif path == "/api/restart":
                    if not self._authorized():
                        return self._error(403, "不正なトークンです")
                    self._json(200, app.service.restart())
                elif path == "/api/update":
                    if not self._authorized():
                        return self._error(403, "不正なトークンです")
                    self._json(200, app.service.start_update())
                else:
                    self._error(404, "not found")
            except Exception as exc:  # noqa: BLE001  エラーを画面へ返す
                traceback.print_exc()
                self._error(400, str(exc))

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="selfocr", description="selfOCR サーバー")
    ap.add_argument("--host", default=SETTINGS.host)
    ap.add_argument("--port", type=int, default=SETTINGS.port)
    ap.add_argument("--threads", type=int, default=SETTINGS.threads)
    ap.add_argument(
        "--no-warmup", action="store_true", help="起動時のモデル読み込みをしない"
    )
    args = ap.parse_args(argv)

    settings = SETTINGS
    settings.host = args.host
    settings.port = args.port
    if args.threads:
        settings.threads = args.threads

    app = App(settings)
    if not args.no_warmup:
        threading.Thread(target=app.engine.warm_up, daemon=True).start()

    httpd = Server((settings.host, settings.port), make_handler(app))
    print(
        f"{APP_NAME} {VERSION_LABEL} (indra {app.info()['indra_version']}) "
        f"-> http://{settings.host}:{settings.port}/",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
