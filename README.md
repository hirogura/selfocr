# selfOCR

自分でホストする OCR サービス. [Indra OCR](https://github.com/datalab-to/indra) (CPU で動く
高速な OCR モデル) を使う. ブラウザから画像を / PDF を投げると Markdown として読み上げてくれる.

- バージョン: **v.0.1.0**
- ポート: **3369**

## できること

| 機能 | 説明 |
| --- | --- |
| ファイルから OCR | 画像 (PNG / JPG / TIFF など) と PDF をアップロードして OCR |
| 画面キャプチャから OCR | 画面を取り込み, 範囲を選んでその部分だけをスキャン |
| 検出枠の重ね表示 | 読み取った行とレイアウト枠を画像の上に表示 |
| Markdown / テキスト / JSON で保存 | ページごとにコピー・ダウンロード |
| アップデート | GitHub (https://github.com/hirogura/selfocr.git) から最新版に更新して自動再起動 |
| 再起動 | 画面の上のボタンでサービスを再起動 |

PDF では, テキスト層が使えるページはそのまま読み, 画像ページの部分だけ OCR する
(モードで「常に OCR」「テキスト層のみ」も選べる).

## インストール

```shell
sudo ./scripts/install.sh
```

やること:

1. `.venv` を作って `requirements.txt` を入れる (Indra OCR は GitHub の `main` から入れる)
2. `systemd/selfocr.service` を `/etc/systemd/system/` に置いて有効化する
3. `tailscale serve` で 3369 番を公開する (この端末だけの tailnet なら `tailscale serve --bg 3369`)

手動で起動する場合:

```shell
.venv/bin/python -m selfocr --host 127.0.0.1 --port 3369
```

## 画面キャプチャについて

ブラウザの画面キャプチャ (`getDisplayMedia`) は **secure context**  才能使える. つまり

- `https://` で開いたとき (tailscale serve 経由ならこれ)
- `http://localhost` で開いたとき

のどちらかで開くと有効. 素の HTTP で LAN へ直接アクセスしたときはブラウザの制限で
画面キャプチャが使えないので, 同じ画面を **Ctrl+V で貼り付ける** 方法が用意されている
(貼り付けた画像でも同じ範囲選択ができる).

## 設定 (環境変数)

| 変数 | 既定値 | 内容 |
| --- | --- | --- |
| `SELFOCR_HOST` | `127.0.0.1` | 待ち受けるアドレス. `0.0.0.0` で LAN 全体から直接受け付ける |
| `SELFOCR_PORT` | `3369` | ポート |
| `SELFOCR_THREADS` | CPU コア数 | OCR に使うスレッド数 |
| `SELFOCR_MAX_UPLOAD` | 200 (MB) | アップロードできる最大サイズ |
| `SELFOCR_ADMIN_TOKEN` | (なし) | 設定すると再起動・アップデートのボタンにトークンが必要 |
| `INDRA_OCR_MODEL_DIR` | (なし) | モデルの保存場所 (既定は Hugging Face のキャッシュ) |

## 内部 API

| メソッド | パス | 内容 |
| --- | --- | --- |
| GET | `/api/info` | バージョン・実行時間など |
| GET | `/api/health` | ヘルスチェック |
| POST | `/api/upload` | ファイル本体 (raw) を投げる. `X-Filename` ヘッダで名前 |
| POST | `/api/page` | `{"id": ..., "n": 0, "opts": {...}}` で 1 ページ分の結果 |
| POST | `/api/restart` | サービス再起動 |
| POST | `/api/update` | GitHub からのアップデート (バックグラウンド) |
| GET | `/api/update/status` | アップデートの進行状況 |

## 開発

```shell
.venv/bin/python -m pytest tests -q
```

構成:

```
selfocr/
  app.py       HTTP サーバーと API
  engine.py    Indra OCR のラッパー (アップロードとページ読み出し)
  service.py   アップデート (git pull) と再起動
  config.py    設定
  static/      画面 (HTML / CSS / JS)
systemd/selfocr.service
scripts/install.sh
```

## ライセンス

Indra OCR は Apache 2.0 (モデルの重みは OpenRAIL-M). 詳細は
[Indra OCR](https://github.com/datalab-to/indra) を参照.
