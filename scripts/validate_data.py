#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
アプリが使うデータの整合性をまとめて点検する。

  使い方:  python scripts/validate_data.py

* findings_map.json / boka_kanri.json / enforcement.json の参照先条文が実在するか
* boka_kanri.json の用途区分が令別表第一を漏れなく覆っているか
* enforcement.json の検索語で標準マニュアルの本文がヒットするか
"""

import json
import sys
from pathlib import Path


def load(root, rel):
    path = root / rel
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def check_refs(laws, refs, where, problems):
    for ref in refs:
        law = laws.get(ref["law_id"])
        if law is None:
            problems.append("{}: 未収録の法令 {}".format(where, ref["law_id"]))
            continue
        article = law["articles"].get(ref["article"])
        if article is None:
            problems.append("{}: 存在しない条 {} {}".format(where, law["title"], ref["article"]))
        elif article.get("deleted"):
            problems.append("{}: 削除された条 {} {}".format(where, law["title"], ref["article"]))


def main():
    root = Path(__file__).resolve().parent.parent
    index = load(root, "data/laws_index.json")
    if index is None:
        print("先に scripts/fetch_laws.py を実行してください", file=sys.stderr)
        return 1

    laws = {}
    for meta in index["laws"]:
        law = load(root, meta["file"])
        laws[law["law_id"]] = {
            "title": law["law_title"],
            "articles": {a["title"]: a for a in law["articles"]},
        }

    problems = []
    counts = {}

    # 指摘辞書
    findings = load(root, "data/findings_map.json")
    if findings:
        n = 0
        for entry in findings["entries"]:
            check_refs(laws, entry["refs"], "指摘辞書/" + entry["id"], problems)
            n += len(entry["refs"])
        counts["指摘辞書"] = "{}パターン / {}参照".format(len(findings["entries"]), n)

    # 防火管理者判定
    boka = load(root, "data/boka_kanri.json")
    yoto = load(root, "data/yoto.json")
    if boka:
        check_refs(laws, boka["source_refs"], "防火管理/source_refs", problems)
        for f in boka["follow_ups"]:
            check_refs(laws, f["refs"], "防火管理/" + f["label"], problems)

        if yoto:
            covered = set()
            for rule in boka["rules"]:
                covered |= set(rule["kou"]) | set(rule.get("kou_conditional", []))
            excluded = set(boka["excluded_kou"])

            for item in yoto["items"]:
                key = item["kou"] + "項" + item["branch"]
                key_plain = item["kou"] + "項"
                if key in excluded or key_plain in excluded:
                    continue
                if key not in covered and key_plain not in covered:
                    problems.append("防火管理: 令別表第一 {} がどのルールにも入っていません".format(key))
            counts["防火管理"] = "{}ルール / 用途{}区分を判定".format(
                len(boka["rules"]), len(yoto["items"]))

    # 執行手続き
    enf = load(root, "data/enforcement.json")
    fdma = load(root, "data/fdma.json")
    if enf:
        stages = 0
        for flow in enf["flows"]:
            doc = None
            if fdma:
                doc = next((d for d in fdma["documents"] if d["id"] == flow["manual"]), None)
                if doc is None:
                    problems.append("執行手続き/{}: マニュアル {} が未収録".format(flow["id"], flow["manual"]))
            for st in flow["stages"]:
                stages += 1
                check_refs(laws, st.get("refs", []), "執行手続き/" + st["id"], problems)
                if doc:
                    hit = any(
                        any(k in p["text"] for k in st["keywords"])
                        for p in doc["pages"]
                    )
                    if not hit:
                        problems.append("執行手続き/{}: 検索語がマニュアル本文に見つかりません {}".format(
                            st["id"], st["keywords"]))
        counts["執行手続き"] = "{}フロー / {}段階".format(len(enf["flows"]), stages)

    for k, v in counts.items():
        print("{:<10} {}".format(k, v))
    print()

    if problems:
        print("!! 要修正 {} 件".format(len(problems)))
        for p in problems:
            print("   - " + p)
        return 1
    print("すべての参照先とマニュアル検索語が有効です。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
