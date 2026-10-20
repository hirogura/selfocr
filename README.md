# selfOCR

自分でホストする OCR サービス. [Indra OCR](https://github.com/datalab-to/indra) (CPU で動く
高速な OCR モデル) を使う. ブラウザから画像を / PDF を投げると Markdown として読み上げてくれる.

- バージョン: **v.0.2.0**
- ポート: **3369**

## できること

| 機能 | 説明 |
| --- | --- |
| ファイルから OCR | 画像 (PNG / JPG / TIFF など) と PDF をアップロードして OCR |
| 画面キャプチャから OCR | 画面を取り込み, 範囲を選んでその部分だけをスキャン |
| 検出枠の重ね表示 | 読み取った行とレイアウト枠を画像の上に表示 |
| HTMLタグ除去 | 表などの HTML タグを取り除いて表示 (オプション, 既定は On) |
| Markdown / テキスト / JSON で保存 | ページごとにコピー・ダウンロード |
| アップデート | GitHub (https://github.com/hirogura/selfocr.git) から最新版に更新して自動再起動 |
| 再起動 | 画面の上のボタンでサービスを再起動 |

PDF では, テキスト層が使えるページはそのまま読み, 画像ページの部分だけ OCR する
(モードで「常に OCR」「テキスト層のみ」も選べる).

## オプション

| 項目 | 既定値 | 内容 |
| --- | --- | --- |
| テキスト取得 | 自動 | PDF のテキスト層を優先するか, 常に OCR するか |
| 解像度 (PDF) | 200 dpi | PDF を画像に読み込む時の解像度 |
| 数式を LaTeX で | Off | 数式を `$...$` として書き出す |
| ヘッダ・フッタを保持 | Off | ページ上部・下部の繰り返しを消さない |
| HTMLタグ除去 | On | 表などに出た HTML タグ (`<table>` / `<tr>` / `<th>`) を取り除いて表示する |

「HTMLタグ除去」を Off にすると, OCR の結果に含まれた HTML タグがそのまま
(文字列として) 残る. 表はセルを空白で区切った行として表示される.

## インストール

```shell
git clone https://github.com/hirogura/selfocr.git /opt/selfocr
cd /opt/selfocr
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

`opts` の値:

| キー | 既定値 | 内容 |
| --- | --- | --- |
| `mode` | `auto` | `auto` / `ocr` / `text` |
| `dpi` | `200` | PDF を画像に読み込む時の解像度 |
| `math` | `false` | 数式を LaTeX で書く |
| `furniture` | `false` | ヘッダ・フッタを保持する |
| `strip_html` | `true` | HTML タグを取り除く |
| `image_ocr` | `true` | PDF の画像ページも OCR する |

## 開発

```shell
.venv/bin/python -m pytest tests -q
```

構成:

```
selfocr/
  app.py       HTTP サーバーと API
  engine.py    Indra OCR のラッパー (アップロードとページ読み出し)
  htmltext.py  HTML タグの除去
  service.py   アップデート (git pull) と再起動
  config.py    設定
  static/      画面 (HTML / CSS / JS)
systemd/selfocr.service
scripts/install.sh
```

## ライセンス

Indra OCR は Apache 2.0 (モデルの重みは OpenRAIL-M). 詳細は
[Indra OCR](https://github.com/datalab-to/indra) を参照.
