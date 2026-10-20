"""設定値 (環境変数で上書きできる)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class Settings:
    host: str = os.environ.get("SELFOCR_HOST", "127.0.0.1")
    port: int = _env_int("SELFOCR_PORT", 3369)
    threads: int = _env_int("SELFOCR_THREADS", 0)  # 0: CPU コア数に合わせる
    max_upload_bytes: int = _env_int("SELFOCR_MAX_UPLOAD", 200 * 1024 * 1024)
    keep_documents: int = _env_int("SELFOCR_KEEP_DOCUMENTS", 8)
    repo_root: Path = REPO_ROOT
    admin_token: str = os.environ.get("SELFOCR_ADMIN_TOKEN", "")
    model_dir: Path | None = field(
        default_factory=lambda: (
            Path(os.environ["INDRA_OCR_MODEL_DIR"])
            if os.environ.get("INDRA_OCR_MODEL_DIR")
            else None
        )
    )

    @property
    def static_dir(self) -> Path:
        return Path(__file__).resolve().parent / "static"


SETTINGS = Settings()
