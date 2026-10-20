"""OCR の結果から HTML タグを取り除く.

Indra OCR の Markdown には, 表が HTML (``<table>`` / ``<tr>`` / ``<th>``) として
入ることがある. そのまま描画するとタグが文字列として見えてしまうため, タグだけを
取り除いて文章だけに戻す. セルの間は空白, 行の間は改行として残す.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# 取り除く HTML タグの名前. ここに無いタグは消さずにそのまま残す.
KNOWN_TAGS = frozenset(
    """a abbr b big blockquote br caption center cite code col colgroup dd del
    div dl dt em figcaption figure font h1 h2 h3 h4 h5 h6 hr i img ins kbd li
    mark ol p pre q s samp section small span strike strong sub sup table tbody
    td tfoot th thead tr tt u ul var wbr""".split()
)

# 中身の直前に改行を足すタグ (開始タグ).
BREAK_BEFORE = frozenset(
    """br p div li h1 h2 h3 h4 h5 h6 hr""".split()
)

# 中身の直後に改行を足すタグ (終了タグ).
BREAK_AFTER = frozenset(
    """p div h1 h2 h3 h4 h5 h6 tr blockquote pre section figure figcaption
    ul ol dl dt dd""".split()
)

# セルの終了タグ (セルの最後に空白を足す).
CELL_END = frozenset({"td", "th"})

_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+(?=\n)")


class _PlainText(HTMLParser):
    """HTML をタグ無しの文章にする."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._in_table = False

    # --- タグ ---------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._in_table = True
        elif tag in BREAK_BEFORE:
            self._parts.append("\n")
        elif tag not in KNOWN_TAGS:
            self._parts.append(self.get_starttag_text() or "")

    def handle_startendtag(self, tag, attrs):
        if tag in BREAK_BEFORE:
            self._parts.append("\n")
        elif tag not in KNOWN_TAGS:
            self._parts.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag):
        if tag == "table":
            self._in_table = False
        elif tag in BREAK_AFTER:
            self._parts.append("\n")
        elif tag in CELL_END:
            self._parts.append(" ")
        elif tag not in KNOWN_TAGS:
            self._parts.append(f"</{tag}>")

    # --- 中身 ---------------------------------------------------------------
    def handle_data(self, data):
        if self._in_table and not data.strip():
            return  # 表の中の空白はタグが区切りを持つので捨てる
        self._parts.append(data)

    def handle_comment(self, data):
        pass

    def handle_decl(self, decl):
        pass

    def handle_pi(self, data):
        pass

    def unknown_decl(self, data):
        pass

    # --- 結果 ---------------------------------------------------------------
    def result(self) -> str:
        text = "".join(self._parts)
        text = _TRAILING_SPACE.sub("", text)
        text = _BLANK_LINES.sub("\n\n", text)
        return text.strip()


def strip_html_tags(text: str) -> str:
    """HTML タグを取り除いたテキストを返す.

    表はセルを空白で区切った行として残る. タグ以外の文字は変えない.
    """
    if not text or "<" not in text:
        return text or ""
    parser = _PlainText()
    parser.feed(text)
    parser.close()
    return parser.result()
