#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
消防法施行令 別表第一（令別表第一）から用途区分データ data/yoto.json を生成する。

  使い方:  python scripts/build_yoto.py   （先に fetch_laws.py を実行しておくこと）

特定防火対象物の別（tokutei）は消防法第17条の2の5第2項第4号・令別表第一の
列挙に基づく静的な対応表として持つ。法改正時はこの表も点検すること。
"""

import json
import re
import sys
from pathlib import Path

LAW_ID = "336CO0000000037"          # 消防法施行令
BRANCH_RE = re.compile(r"^([イロハニホヘトチリヌルヲ])[　\s]+(.*)$")

# 特定防火対象物に該当する 項／イロハ の組み合わせ。
# 値が None の場合はその項全体が特定防火対象物。
TOKUTEI = {
    "（一）": None,
    "（二）": None,
    "（三）": None,
    "（四）": None,
    "（五）": ["イ"],
    "（六）": None,
    "（九）": ["イ"],
    "（十六）": ["イ"],
    "（十六の二）": None,
    "（十六の三）": None,
}


def is_tokutei(kou, branch):
    if kou not in TOKUTEI:
        return False
    allowed = TOKUTEI[kou]
    return True if allowed is None else branch in allowed


def split_branches(text):
    """セル内の「イ　…／ロ　…」をイロハ単位に割る。分岐が無ければ1件返す。"""
    entries = []
    current = None
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = BRANCH_RE.match(line)
        if m:
            current = {"branch": m.group(1), "name": m.group(2), "detail": []}
            entries.append(current)
        elif current is not None:
            current["detail"].append(line)
        else:
            current = {"branch": "", "name": line, "detail": []}
            entries.append(current)
    return entries


def main():
    root = Path(__file__).resolve().parent.parent
    law_path = root / "data" / "laws" / "{}.json".format(LAW_ID)
    if not law_path.exists():
        print("先に scripts/fetch_laws.py を実行してください", file=sys.stderr)
        return 1

    law = json.loads(law_path.read_text(encoding="utf-8"))
    table = next((t for t in law["appdx"] if t["title"].startswith("別表第一")), None)
    if table is None:
        print("別表第一が見つかりません", file=sys.stderr)
        return 1

    items = []
    for row in table["rows"]:
        if len(row) < 2:
            continue
        kou = row[0].strip()
        if not kou.startswith("（"):
            continue
        for entry in split_branches(row[1]):
            label = "{}項{} {}".format(kou, entry["branch"], entry["name"])
            items.append({
                "kou": kou,
                "branch": entry["branch"],
                "name": entry["name"],
                "detail": entry["detail"],
                "tokutei": is_tokutei(kou, entry["branch"]),
                "label": re.sub(r"\s+", " ", label).strip(),
            })

    out = {
        "source": "消防法施行令 別表第一",
        "source_url": "{}#{}".format(law["source_url"], "AppdxTable_1"),
        "law_enforcement_date": law["enforcement_date"],
        "fetched_at": law["fetched_at"],
        "note": "特定防火対象物の別は消防法第17条の2の5第2項第4号等に基づく整理。最終確認は原典で行うこと。",
        "items": items,
    }
    (root / "data" / "yoto.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print("用途区分 {} 件を生成しました（うち特定防火対象物 {} 件）".format(
        len(items), sum(1 for i in items if i["tokutei"])))
    for i in items[:6]:
        print("   {}{}".format(i["label"][:44], "  ★特定" if i["tokutei"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
