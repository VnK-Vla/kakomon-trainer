"""選択肢へのページ外テキスト混入を検知する共有ヘルパー(検知専用・非破壊)。

放射線系過去問 PDF では、図の注釈(「T1 強調画像」「線量分布図」等)や
ページ見出し(核医学 News Letter バナー・ページ番号)、「問題は次ページに
続く」といった版面要素が、選択肢の物理的な近くに配置される。PDF 抽出時、
これらが選択肢テキスト(特に区切り記号を持たない選択肢)に連結されやすい。

ここでは「取り込んだ選択肢が汚染されていないか」を検査するだけで、テキストを
書き換えることはしない。取込ツールの警告と、DB を後から再監査するスクリプトの
両方から使う。

検知は誤検知を出さない高精度な信号のみに限定する:
  1. 図付き問題で、選択肢が文末の句点で終わっているのに、その後ろにさらに
     本文が続く(= 付加された図キャプション)。正当な選択肢は最後の句点で
     終わるため誤検知はまず起きない。
  2. ページ見出し/フッター(「■核医学News Letter■」バナー、
     「問題は次ページに続く」等)を含む。これらは選択肢の一部になり得ない。

上記の高精度規則では拾えない「無句点の名詞句選択肢に図ラベルが融合した」
ケースは、幾何情報無しでは正当な選択肢と機械的に区別できない。そのため
過去に人手で確定・修正した問題 ID を KNOWN_FIXED_IDS として保持し、
再取込などで再混入していないかを別途チェックできるようにしている。
"""

from __future__ import annotations

import re
import sys

# --- ページ見出し/フッター(選択肢の一部になり得ない版面要素) ---
FOOTER_RE = re.compile(r"■\s*核医学\s*News\s*Letter\s*■|〈\s*問題は次ページに続く\s*〉|問題は次ページに続く")

# --- 文末の句点の後ろに残る本文(= 付加テキスト) ---
_PERIOD_TAIL = re.compile(r"[。．](\s*\S.*)$")


def _strip_letter(choice: str) -> str:
    """先頭の "e. " などの選択肢記号を除いた本文を返す。"""
    return re.sub(r"^\s*[a-eａ-ｅ]\s*[.．)]\s*", "", choice).strip()


def caption_contamination(choice: str) -> str | None:
    """choice にページ外テキスト混入があれば疑わしい末尾部分を返す。無ければ None。

    破壊的な整形はしない(呼び出し側が人手で確認する前提)。
    """
    body = _strip_letter(choice)
    if not body:
        return None

    m = FOOTER_RE.search(body)
    if m:
        return body[m.start():].strip()

    # 文末句点より後ろに本文が続く → 付加キャプション。ただし最後の要素が
    # それ自体句点で終わる(= 複数文の正当な選択肢)場合は除外する。
    m = _PERIOD_TAIL.search(body)
    if m:
        tail = m.group(1).strip()
        if tail and not tail.endswith(("。", "．")):
            return tail

    return None


# 過去に人手で確定・修正した「図キャプション/版面要素の混入」問題 ID。
# 再取込などで再混入していないかの回帰チェックに用いる(2026-07-06 時点、計44件)。
KNOWN_FIXED_IDS = frozenset({
    # 図キャプションが選択肢 e 等に混入していたもの
    1141, 1185, 1186, 1404, 1438, 1559, 2491, 2494, 2512, 2729, 2748, 2749,
    2820, 2886, 2892, 2893, 2895, 2899, 2976, 2980, 3007, 3081, 3082, 3093, 3167,
    # 核医学 News Letter バナー / ページ番号 / 次ページ継続が選択肢に混入していたもの
    1814, 1821, 1828, 1835, 1842, 1849, 1854, 1859, 1864, 1868,
    1875, 1881, 1887, 1893, 1898, 1905, 1911, 1928, 3092,
})


def find_contaminated(questions):
    """(識別子, 選択肢リスト, 画像リスト) の列から汚染候補を洗い出す。

    questions: iterable of (ident, choices, images)
    返り値: [(ident, choice_index, choice_text, suspect_tail), ...]

    高精度規則(句点後テキスト・フッター)で検出できたものを返す。句点後テキスト
    規則は図付き問題に限定する(図キャプション混入は図付き問題でのみ起きるため
    誤検知を避ける)。フッター規則は画像有無に関わらず適用する。
    """
    hits = []
    for ident, choices, images in questions:
        for i, choice in enumerate(choices):
            body = _strip_letter(choice)
            footer = FOOTER_RE.search(body)
            if footer:
                hits.append((ident, i, choice, body[footer.start():].strip()))
                continue
            if not images:
                continue
            tail = caption_contamination(choice)
            if tail:
                hits.append((ident, i, choice, tail))
    return hits


def warn_payload(items, stream=sys.stderr) -> int:
    """取込ペイロード(dict のリスト)を検査し、混入候補を stream に警告する。

    各 item は "choices"(list)と "images"(list)を持つ想定。"question" があれば
    識別に使う。破壊はしない。検出件数を返す。
    """
    letters = "abcde"
    rows = []
    for idx, item in enumerate(items):
        ident = item.get("question", f"#{idx}") if isinstance(item, dict) else f"#{idx}"
        rows.append((ident, item.get("choices", []), item.get("images", [])))
    hits = find_contaminated(rows)
    if hits:
        print(
            f"[警告] 選択肢へのキャプション/版面要素の混入候補が {len(hits)} 件あります "
            "(取込は続行します。tools/audit_choice_captions.py で確認してください):",
            file=stream,
        )
        for ident, i, choice, tail in hits:
            letter = letters[i] if i < len(letters) else str(i)
            head = ident if isinstance(ident, str) else str(ident)
            print(f"  - {head} 選択肢{letter}: 疑い箇所 {tail!r}", file=stream)
            print(f"      現在値: {choice!r}", file=stream)
    return len(hits)
