#!/usr/bin/env bash
# selfOCR のインストール (venv の作成 → systemd への登録 → 起動).
#
#   sudo ./scripts/install.sh
#
# 既存のvenv があれば使い回す. 引数でポートとホストを変えられる.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${SELFOCR_PORT:-3369}"
HOST="${SELFOCR_HOST:-127.0.0.1}"
VENV="$ROOT/.venv"
SERVICE_FILE="/etc/systemd/system/selfocr.service"

command -v python3 >/dev/null || { echo "python3 が必要です" >&2; exit 1; }
command -v git >/dev/null || { echo "git が必要です" >&2; exit 1; }

echo "==> venv を作る ($VENV)"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip setuptools wheel >/dev/null

echo "==> 依存関係を入れる"
"$VENV/bin/pip" install -r "$ROOT/requirements.txt"

echo "==> systemd ユニット installing"
sed -e "s#^WorkingDirectory=.*#WorkingDirectory=$ROOT#" \
    -e "s#^ExecStart=.*#ExecStart=$VENV/bin/python -m selfocr#" \
    -e "s#^Environment=SELFOCR_HOST=.*#Environment=SELFOCR_HOST=$HOST#" \
    -e "s#^Environment=SELFOCR_PORT=.*#Environment=SELFOCR_PORT=$PORT#" \
    "$ROOT/systemd/selfocr.service" > "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable selfocr.service >/dev/null
systemctl restart selfocr.service

sleep 2
if systemctl is-active --quiet selfocr.service; then
  echo "==> 起動しました: http://$HOST:$PORT/"
  systemctl --no-pager --lines=5 status selfocr.service || true
else
  echo "==> 起動に失敗しました. journalctl -u selfocr.service を見てください" >&2
  journalctl -u selfocr.service --no-pager --lines=30 >&2 || true
  exit 1
fi

if command -v tailscale >/dev/null && tailscale serve --help >/dev/null 2>&1; then
  echo "==> tailscale serve で公開する (https://<端末名>:$PORT/)"
  tailscale serve --bg --https="$PORT" "http://127.0.0.1:$PORT" >/dev/null || \
    echo "   (tailscale serve に失敗しました. 手動で設定してください)"
fi
