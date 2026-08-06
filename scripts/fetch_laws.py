#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
e-Gov 法令API Version 2 から査察支援に必要な法令を取得し、
条文単位に分解した静的JSONを data/laws/ に生成する。

  使い方:  python scripts/fetch_laws.py

出典: e-Gov法令検索 (https://laws.e-gov.go.jp/)
      法令データは政府標準利用規約(第2.0版) / CC BY 4.0 互換。出典明示のうえ利用する。

ブラウザから e-Gov へ直接 fetch すると CORS で弾かれるため、
取得はビルド時にこのスクリプトで行い、結果をリポジトリに同梱する運用とする。
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

API_BASE = "https://laws.e-gov.go.jp/api/2"
LAW_PAGE = "https://laws.e-gov.go.jp/law/{law_id}"
JST = timezone(timedelta(hours=9))

# 取得対象。short は UI 上のバッジ表示に使う略称。
TARGET_LAWS = [
    {"law_id": "323AC1000000186", "short": "法",       "note": "消防法"},
    {"law_id": "336CO0000000037", "short": "令",       "note": "消防法施行令"},
    {"law_id": "336M50000008006", "short": "規則",     "note": "消防法施行規則"},
    {"law_id": "325AC0000000201", "short": "建基法",   "note": "建築基準法"},
    {"law_id": "325CO0000000338", "short": "建基令",   "note": "建築基準法施行令"},
    # 少量危険物・指定可燃物の指摘で必ず参照するため収録する
    {"law_id": "334CO0000000306", "short": "危政令",   "note": "危険物の規制に関する政令"},
]

# 法令XML要素名 → e-Gov 本文ページのアンカー接頭辞
# （実機の DOM id を確認して確定。例: #Mp-Ch_2-Se_3-Ss_1-At_8）
ANCHOR_PREFIX = {
    "Part": "Pa",
    "Chapter": "Ch",
    "Section": "Se",
    "Subsection": "Ss",
    "Division": "Dv",
}
CONTAINERS = list(ANCHOR_PREFIX.keys())

REQUEST_INTERVAL_SEC = 1.0  # 個人利用。常識的な間隔を空ける


# --------------------------------------------------------------------------
# 漢数字
# --------------------------------------------------------------------------
_KANJI_DIGIT = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
                "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_KANJI_UNIT = {"十": 10, "百": 100, "千": 1000}


def kanji_to_int(text):
    """「三十三」→33、「百二十」→120。変換できない場合は None。"""
    if not text:
        return None
    if all(c in _KANJI_DIGIT for c in text):        # 「〇一二」形式
        n = 0
        for c in text:
            n = n * 10 + _KANJI_DIGIT[c]
        return n
    total, current = 0, 0
    for c in text:
        if c in _KANJI_DIGIT:
            current = _KANJI_DIGIT[c]
        elif c in _KANJI_UNIT:
            unit = _KANJI_UNIT[c]
            total += (current if current else 1) * unit
            current = 0
        else:
            return None
    return total + current


_KANJI = "〇一二三四五六七八九十百千"
# 「第十七条及び第十八条　削除」のような複数条をまとめた見出しには e-Gov 側の
# アンカーが存在しないため、単一の条を指す見出しのみをアンカー化する（末尾を $ で固定）。
_ARTICLE_RE = re.compile(r"^第([{k}]+)条((?:の[{k}]+)*)$".format(k=_KANJI))
_CONTAINER_RE = re.compile(r"^第([{k}]+)[編章節款目]((?:の[{k}]+)*)".format(k=_KANJI))
_BRANCH_RE = re.compile(r"の([{k}]+)".format(k=_KANJI))


def _numbering(base, branches):
    """「二」+「の二の三」→ '2_2_3'。読めない部分があれば None。"""
    num = kanji_to_int(base)
    if num is None:
        return None
    parts = [str(num)]
    for branch in _BRANCH_RE.findall(branches or ""):
        b = kanji_to_int(branch)
        if b is None:
            return None
        parts.append(str(b))
    return "_".join(parts)


def article_anchor_part(article_title):
    """「第四条の二の三」→ 'At_4_2_3'。解析できなければ None。"""
    m = _ARTICLE_RE.match(article_title or "")
    if not m:
        return None
    numbering = _numbering(m.group(1), m.group(2))
    return "At_" + numbering if numbering else None


def container_anchor_part(kind, title, fallback_index):
    """「第七章の二の二　…」→ 'Ch_7_2_2'。番号が読めなければ出現順で代用する。"""
    m = _CONTAINER_RE.match(title or "")
    numbering = _numbering(m.group(1), m.group(2)) if m else None
    if numbering is None:
        numbering = str(fallback_index)
    return "{}_{}".format(ANCHOR_PREFIX[kind], numbering)


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
def api_get(path, **params):
    url = API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            # 個人利用のツールであることが分かるようにしておく
            "User-Agent": "sasatsu-ai/4.0 (personal inspection support tool)",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read().decode("utf-8"))


def as_list(value):
    """法令JSONは要素が1つだと dict、複数だと list で返ることがある。"""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def sentences_text(node):
    """Sentence 配列を1つの文字列にまとめる。"""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(sentences_text(x) for x in node)
    if isinstance(node, dict):
        for key in ("Sentence", "Column", "Text"):
            if key in node:
                return sentences_text(node[key])
    return ""


# --------------------------------------------------------------------------
# 本文パース
# --------------------------------------------------------------------------
def parse_items(container, level=1):
    """号・イロハ（Item / Subitem1..3）を再帰的に取り出す。"""
    key = "Item" if level == 1 else "Subitem{}".format(level - 1)
    title_key = "ItemTitle" if level == 1 else "Subitem{}Title".format(level - 1)
    sent_key = "ItemSentence" if level == 1 else "Subitem{}Sentence".format(level - 1)

    results = []
    for node in as_list(container.get(key)):
        if not isinstance(node, dict):
            continue
        entry = {
            "title": node.get(title_key) or "",
            "text": sentences_text(node.get(sent_key)),
        }
        children = parse_items(node, level + 1)
        if children:
            entry["children"] = children
        results.append(entry)
    return results


def parse_paragraphs(article):
    paragraphs = []
    for node in as_list(article.get("Paragraph")):
        if not isinstance(node, dict):
            continue
        entry = {
            "num": str(node.get("Num") or ""),
            "text": sentences_text(node.get("ParagraphSentence")),
        }
        items = parse_items(node)
        if items:
            entry["items"] = items
        paragraphs.append(entry)
    return paragraphs


def walk(node, law_id, crumb_titles, anchor_parts, out):
    """本則を再帰的に歩いて条文を平坦なリストに集める。"""
    if not isinstance(node, dict):
        return

    for kind in CONTAINERS:
        for index, child in enumerate(as_list(node.get(kind)), start=1):
            if not isinstance(child, dict):
                continue
            title = sentences_text(child.get(kind + "Title")) or ""
            walk(
                child,
                law_id,
                crumb_titles + ([title] if title else []),
                anchor_parts + [container_anchor_part(kind, title, index)],
                out,
            )

    for article in as_list(node.get("Article")):
        if not isinstance(article, dict):
            continue
        title = article.get("ArticleTitle") or ""
        anchor_at = article_anchor_part(title)
        anchor = None
        if anchor_at:
            anchor = "-".join(["Mp"] + anchor_parts + [anchor_at])

        paras = parse_paragraphs(article)
        record = {
            "title": title,
            "caption": article.get("ArticleCaption") or "",
            "crumbs": list(crumb_titles),
            "paras": paras,
        }
        # 「削除」だけの条は検索結果から外せるよう印を付ける
        if paras and all(p.get("text", "").strip() == "削除" for p in paras):
            record["deleted"] = True
        if anchor:
            record["anchor"] = anchor
            record["url"] = LAW_PAGE.format(law_id=law_id) + "#" + anchor
        else:
            # アンカーを組み立てられない条文は法令トップへのリンクにフォールバック
            record["url"] = LAW_PAGE.format(law_id=law_id)
        out.append(record)


def parse_appdx_tables(body):
    """別表（令別表第一など）を行単位のテキストに落とす。"""
    tables = []
    for appdx in as_list(body.get("AppdxTable")):
        if not isinstance(appdx, dict):
            continue
        rows = []
        for struct in as_list(appdx.get("TableStruct")):
            table = struct.get("Table") if isinstance(struct, dict) else None
            if not isinstance(table, dict):
                continue
            for row in as_list(table.get("TableRow")):
                if not isinstance(row, dict):
                    continue
                cells = []
                for column in as_list(row.get("TableColumn")):
                    lines = as_list(column.get("Sentence")) if isinstance(column, dict) else []
                    cells.append("\n".join(sentences_text(x) for x in lines))
                if any(c.strip() for c in cells):
                    rows.append(cells)
        tables.append({
            "title": sentences_text(appdx.get("AppdxTableTitle")),
            "related": appdx.get("RelatedArticleNum") or "",
            "rows": rows,
        })
    return tables


# --------------------------------------------------------------------------
# メイン
# --------------------------------------------------------------------------
def fetch_law(spec, fetched_at):
    law_id = spec["law_id"]
    print("  取得中: {} ({})".format(spec["note"], law_id), flush=True)

    payload = api_get(
        "/law_data/{}".format(law_id),
        response_format="json",
        law_full_text_format="json",
        json_format="light",
        omit_amendment_suppl_provision="true",
    )

    law_info = payload.get("law_info", {})
    revision = payload.get("revision_info", {})
    body = payload["law_full_text"]["Law"]["LawBody"]

    articles = []
    walk(body.get("MainProvision") or {}, law_id, [], [], articles)

    for article in articles:
        article["id"] = "{}:{}".format(law_id, article["title"])

    return {
        "law_id": law_id,
        "law_title": revision.get("law_title") or spec["note"],
        "short": spec["short"],
        "law_num": law_info.get("law_num", ""),
        "law_type": law_info.get("law_type", ""),
        "category": revision.get("category", ""),
        "promulgation_date": law_info.get("promulgation_date", ""),
        # 施行日・最終改正はUIの鮮度表示に使う
        "enforcement_date": revision.get("amendment_enforcement_date", ""),
        "last_amendment_date": revision.get("amendment_promulgate_date", ""),
        "last_amendment_law": revision.get("amendment_law_title", ""),
        "revision_id": revision.get("law_revision_id", ""),
        "source_url": LAW_PAGE.format(law_id=law_id),
        "fetched_at": fetched_at,
        "articles": articles,
        "appdx": parse_appdx_tables(body),
    }


def main():
    root = Path(__file__).resolve().parent.parent
    laws_dir = root / "data" / "laws"
    laws_dir.mkdir(parents=True, exist_ok=True)

    fetched_at = datetime.now(JST).isoformat(timespec="seconds")
    print("e-Gov 法令API v2 から取得します（取得日時: {}）".format(fetched_at))

    index = []
    for i, spec in enumerate(TARGET_LAWS):
        if i:
            time.sleep(REQUEST_INTERVAL_SEC)
        try:
            law = fetch_law(spec, fetched_at)
        except Exception as exc:                      # noqa: BLE001
            print("  ! 失敗: {} - {}".format(spec["note"], exc), file=sys.stderr)
            return 1

        path = laws_dir / "{}.json".format(law["law_id"])
        path.write_text(
            json.dumps(law, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print("    条文 {:>4} 件 / 別表 {} 件 / {:,} bytes".format(
            len(law["articles"]), len(law["appdx"]), path.stat().st_size))

        index.append({
            "law_id": law["law_id"],
            "law_title": law["law_title"],
            "short": law["short"],
            "law_num": law["law_num"],
            "enforcement_date": law["enforcement_date"],
            "last_amendment_date": law["last_amendment_date"],
            "source_url": law["source_url"],
            "article_count": len(law["articles"]),
            "file": "data/laws/{}.json".format(law["law_id"]),
        })

    (root / "data" / "laws_index.json").write_text(
        json.dumps(
            {
                "fetched_at": fetched_at,
                "source": "e-Gov法令検索 法令API Version 2",
                "source_url": "https://laws.e-gov.go.jp/",
                "license": "政府標準利用規約(第2.0版) / CC BY 4.0 互換",
                "laws": index,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print("完了: data/laws_index.json を更新しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
