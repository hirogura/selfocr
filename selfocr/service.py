"""サービスの操作: GitHub からのアップデートと再起動.

* アップデート: リポジトリを ``git pull --ff-only`` してから依存関係を入れ直し、
  最後にプロセス自身を再実行する.
* 再起動: プロセス自身を ``exec`` で置き換える (systemd なら同じ PID のまま
  新しいコードで動き直す).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

LOG_LIMIT = 400  # 保持するログ行数

# アップデートの取得元 (selfOCR 本体のリポジトリ)
REPO_URL = "https://github.com/hirogura/selfocr.git"


class ServiceManager:
    """アップデートと再起動の状態を管理する."""

    def __init__(self, repo_root: Path, restart_hook=None, state_file: Path | None = None) -> None:
        self.repo_root = Path(repo_root)
        self._restart_hook = restart_hook or default_restart
        self._lock = threading.Lock()
        self._state_file = Path(state_file or (self.repo_root / ".state" / "service.json"))
        self._job: dict[str, Any] = self._load() or {
            "state": "idle",
            "message": "",
            "steps": [],
            "log": [],
            "started_at": None,
            "finished_at": None,
        }
        if self._job.get("state") == "restarting":
            # 前回の再起動は完了している (このプロセスは再起動後に動いている)
            self._job["state"] = "idle"
            self._job["message"] = "再起動しました"
        self._running = False

    # --- 状態の保存 ---------------------------------------------------------
    def _load(self) -> dict | None:
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _save(self) -> None:
        """再起動しても消えないように状態をファイルに残す."""
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_file.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._job, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            tmp.replace(self._state_file)
        except OSError:
            pass

    # --- 状態 ---------------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            return {
                **self._job,
                "steps": [dict(s) for s in self._job["steps"]],
                "log": list(self._job["log"]),
            }

    def _log(self, line: str) -> None:
        with self._lock:
            self._job["log"].append(line.rstrip())
            if len(self._job["log"]) > LOG_LIMIT:
                del self._job["log"][:-LOG_LIMIT]
            self._save()

    def _step(self, name: str, state: str, output: str = "") -> None:
        with self._lock:
            for step in self._job["steps"]:
                if step["name"] == name:
                    step["state"] = state
                    if output:
                        step["output"] = output
                    self._save()
                    return
            self._job["steps"].append({"name": name, "state": state, "output": output})
            self._save()

    # --- アップデート -------------------------------------------------------
    def start_update(self) -> dict:
        """バックグラウンドでアップデートを始める. 既に走っていればその状態."""
        with self._lock:
            if self._running:
                return self.status()
            self._running = True
            self._job = {
                "state": "running",
                "message": "アップデートを開始しました",
                "steps": [],
                "log": [],
                "started_at": time.time(),
                "finished_at": None,
            }
            self._save()
        thread = threading.Thread(target=self._update, name="selfocr-update", daemon=True)
        thread.start()
        return self.status()

    def _update(self) -> None:
        try:
            branch = self._current_branch()
            self._step("fetch", "running")
            self._ensure_remote()
            self._run(["git", "fetch", "--prune", "origin"], "fetch")
            self._step("fetch", "done")

            self._step("pull", "running")
            self._run(["git", "pull", "--ff-only", "origin", branch], "pull")
            self._step("pull", "done")

            self._step("dependencies", "running")
            self._install_dependencies()
            self._step("dependencies", "done")

            with self._lock:
                self._job["state"] = "done"
                self._job["message"] = "アップデート完了. 再起動します..."
                self._job["finished_at"] = time.time()
                self._save()
            self._log("restarting the service...")
            self._restart_hook()
        except Exception as exc:  # noqa: BLE001  エラーは画面に出す
            self._step("failed", "error", str(exc))
            with self._lock:
                self._job["state"] = "error"
                self._job["message"] = f"アップデート失敗: {exc}"
                self._job["finished_at"] = time.time()
                self._save()
            self._log(f"error: {exc}")

    def _current_branch(self) -> str:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or "main"

    def _ensure_remote(self) -> None:
        """origin が selfOCR のリポジトリを指していることを確認する."""
        current = ""
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            current = proc.stdout.strip()
        if current == REPO_URL:
            self._log(f"origin: {REPO_URL}")
            return
        self._log(f"origin を {REPO_URL} に設定します (旧: {current or 'なし'})")
        self._run(["git", "remote", "set-url", "origin", REPO_URL], "remote")

    def _run(self, cmd: list[str], label: str, skip_prefixes: tuple[str, ...] = ()) -> str:
        self._log("$ " + " ".join(cmd))
        proc = subprocess.run(
            cmd,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        for line in (proc.stdout + proc.stderr).splitlines():
            if not line.strip():
                continue
            if skip_prefixes and line.startswith(skip_prefixes):
                continue
            self._log(line)
        if proc.returncode != 0:
            raise RuntimeError(
                f"{' '.join(cmd)} が失敗しました (終了コード {proc.returncode})"
            )
        return proc.stdout

    def _install_dependencies(self) -> None:
        req = self.repo_root / "requirements.txt"
        if not req.exists():
            self._log("requirements.txt がありません. 依存関係の更新はスキップします")
            return
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "-r", str(req)]
        self._run(cmd, "dependencies", skip_prefixes=("Requirement already satisfied",))

    # --- 再起動 -------------------------------------------------------------
    def restart(self) -> dict:
        """再起動を予約する (応答を送ってから実行する)."""
        with self._lock:
            self._job["state"] = "restarting"
            self._job["message"] = "再起動しています..."
            self._save()
        self._log("restart requested")

        def do_restart() -> None:
            time.sleep(0.6)  # HTTP 応答を届ける時間
            self._restart_hook()

        threading.Thread(target=do_restart, name="selfocr-restart", daemon=True).start()
        return {"ok": True, "message": "再起動しています..."}


def default_restart() -> None:
    """プロセスを再実行する. 同じ PID で新しいコードが動き出す."""
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, [sys.executable, "-m", "selfocr"])
