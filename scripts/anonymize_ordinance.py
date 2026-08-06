#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
火災予防条例のテキストから自治体を特定できる情報を除去し、data/ordinances.json を生成する。

  使い方:
    1. data/ordinances_src/ に条例の本文をテキストで置く（このフォルダはコミットしない）
       ファイル名の例: chukakushi_a.txt
    2. python scripts/anonymize_ordinance.py --names 〇〇市,〇〇県 --type 中核市
    3. 出力された「要確認候補」を目視で確認し、漏れがあれば --names に足して再実行する

方針:
  * 条文の法的内容（基準値・手続き）は保持し、自治体が特定できる固有名詞だけを伏せる
  * 正規表現による自動マスキングは取りこぼす前提。候補を必ず人が確認する二段構えとする
  * 既定でマスク済みの状態を正として保存する（原文はリポジトリに含めない）

e-Gov法令検索には市町村条例は収録されていないため、条例は各自治体の例規集等から
利用者自身が取得したものを手動で投入する。
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))

MASK_MUNI = "（自治体名非表示）"
MASK_ORG = "（消防本部名非表示）"
MASK_PLACE = "（地名非表示）"
MASK_FORM = "（様式番号非表示）"

# 「◯◯市」等の形をしていても自治体名ではない一般的な法令用語。マスクしない。
GENERIC_TERMS = {
    "市町村", "都道府県", "各都道府県", "当該市町村", "当該都道府県",
    "市街地", "市街", "都市", "都市計画", "市場", "区域", "区分", "区画",
    "地区", "町内", "村落", "区間", "特別区", "指定都市", "中核市",
    "政令指定都市", "市町村長", "都道府県知事", "市区町村",
}

# 自治体名を含みやすい語のパターン（人が確認するための候補抽出用）。
# 地名の語幹は漢字・カタカナが大半なので接頭辞をそれらに限定する。
# 「市街地」「区域」のような一般語を拾わないよう、直後の文字で足切りする。
CANDIDATE_RE = re.compile(
    r"[一-龥ァ-ヶー々]{1,5}(?:都|道|府|県|市|区|町|村)(?![町村民街域分画内間場政策])"
)
ORG_RE = re.compile(r"([一-龥ァ-ヶー々]{1,8})(消防局|消防本部|消防署|消防団|出張所)")
FORM_RE = re.compile(r"(?:様式|要綱|要領|告示|訓令)第?[〇一二三四五六七八九十百千0-9０-９]+号?")

# 消防本部等の直前に付いても自治体名ではない語。マスクせずそのまま残す。
GENERIC_ORG_PREFIX = {"当該", "他", "各", "管轄", "所轄", "最寄"}


def build_name_pattern(names):
    """利用者が指定した自治体名（および「市」等を落とした語幹）をまとめて拾う。"""
    variants = set()
    for name in names:
        name = name.strip()
        if not name:
            continue
        variants.add(name)
        stem = re.sub(r"(?:都|道|府|県|市|区|町|村)$", "", name)
        if len(stem) >= 2:
            variants.add(stem)
    if not variants:
        return None
    ordered = sorted(variants, key=len, reverse=True)
    return re.compile("|".join(re.escape(v) for v in ordered))


def anonymize(text, name_pattern):
    """自動マスキングを適用し、(マスク後テキスト, 要確認候補) を返す。"""
    counts = {"自治体名": 0, "消防本部等": 0, "様式・要綱番号": 0}

    def mask_org(m):
        prefix, org = m.group(1), m.group(2)
        # 「当該消防本部」のような一般的な言い回しは自治体を特定しないので残す
        if prefix in GENERIC_ORG_PREFIX:
            return m.group(0)
        counts["消防本部等"] += 1
        return MASK_ORG

    text = ORG_RE.sub(mask_org, text)

    if name_pattern is not None:
        def mask_name(m):
            counts["自治体名"] += 1
            return MASK_MUNI
        text = name_pattern.sub(mask_name, text)

    def mask_form(m):
        counts["様式・要綱番号"] += 1
        return MASK_FORM

    text = FORM_RE.sub(mask_form, text)

    # 残っている「◯◯市」形の語を候補として洗い出す（自動では消さない）
    candidates = {}
    for m in CANDIDATE_RE.finditer(text):
        token = m.group(0)
        if token in GENERIC_TERMS:
            continue
        candidates[token] = candidates.get(token, 0) + 1

    return text, counts, candidates


def split_articles(text):
    """「第◯条」で条文単位に分割する。見出しが無ければ全体を1件として扱う。"""
    lines = text.replace("\r\n", "\n").split("\n")
    articles = []
    current = None
    heading = re.compile(r"^\s*(第[〇一二三四五六七八九十百千]+条(?:の[〇一二三四五六七八九十百千]+)*)")

    for line in lines:
        m = heading.match(line)
        if m:
            current = {"title": m.group(1), "text": line.strip()}
            articles.append(current)
        elif current is not None:
            if line.strip():
                current["text"] += "\n" + line.strip()
        elif line.strip():
            current = {"title": "", "text": line.strip()}
            articles.append(current)
    return articles


def main():
    parser = argparse.ArgumentParser(description="火災予防条例を匿名化して JSON 化する")
    parser.add_argument("--names", default="",
                        help="伏せる自治体名をカンマ区切りで指定（例: 〇〇市,〇〇県）")
    parser.add_argument("--type", dest="muni_type", default="",
                        help="条文の性質理解に必要な最小限の属性（例: 中核市, 政令指定都市）")
    parser.add_argument("--src", default="data/ordinances_src",
                        help="原文テキストを置いたフォルダ")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    src_dir = root / args.src
    if not src_dir.exists():
        print("原文フォルダがありません: {}".format(src_dir), file=sys.stderr)
        print("条例本文のテキストを置いてから再実行してください。", file=sys.stderr)
        return 1

    name_pattern = build_name_pattern(args.names.split(","))
    if name_pattern is None:
        print("! --names が未指定です。自治体名の自動マスクは行われません。", file=sys.stderr)

    generated_at = datetime.now(JST).isoformat(timespec="seconds")
    ordinances = []
    all_candidates = {}

    for path in sorted(src_dir.glob("*.txt")):
        raw = path.read_text(encoding="utf-8")
        masked, counts, candidates = anonymize(raw, name_pattern)
        for token, n in candidates.items():
            all_candidates[token] = all_candidates.get(token, 0) + n

        articles = []
        for article in split_articles(masked):
            articles.append({
                "title": article["title"],
                "text": article["text"],
            })

        ordinances.append({
            "id": path.stem,
            # 題名も自治体名を伏せた形で持つ
            "title": "{}火災予防条例".format(MASK_MUNI),
            "muni_type": args.muni_type,
            "article_count": len(articles),
            "articles": articles,
            "masked_counts": counts,
            "note": "自治体特定情報をマスク済み。最終確認は自治体公報・例規集の原典で行うこと。",
        })
        print("{}: 条文 {} 件 / マスク {}".format(path.name, len(articles), counts))

    out = {
        "generated_at": generated_at,
        "source": "利用者が各自治体の例規集等から取得した火災予防条例（原文は非同梱）",
        "anonymized": True,
        "ordinances": ordinances,
        # 目視確認用。空になるまで --names に追加して再実行するのが望ましい
        "review_candidates": sorted(
            [{"token": t, "count": c} for t, c in all_candidates.items()],
            key=lambda x: -x["count"],
        ),
    }
    (root / "data" / "ordinances.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\ndata/ordinances.json を生成しました（条例 {} 件）".format(len(ordinances)))
    if out["review_candidates"]:
        print("\n要確認候補（自治体が特定できる語が残っていないか目視で確認してください）:")
        for c in out["review_candidates"][:20]:
            print("   {} ({}回)".format(c["token"], c["count"]))
    else:
        print("要確認候補はありません。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
