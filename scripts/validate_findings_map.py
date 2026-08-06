#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data/findings_map.json の参照先条文が実在するかを検証し、条見出しを一覧表示する。

  使い方:  python scripts/validate_findings_map.py [--quiet]

存在しない条を参照していると F1 の結果が空になるため、辞書を編集したら必ず実行する。
条見出しは目視確認用。指摘内容と見出しが噛み合っているかを人が確かめること。
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true", help="不一致だけを表示する")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    index = json.loads((root / "data" / "laws_index.json").read_text(encoding="utf-8"))

    laws = {}
    for meta in index["laws"]:
        law = json.loads((root / meta["file"]).read_text(encoding="utf-8"))
        laws[law["law_id"]] = {
            "title": law["law_title"],
            "short": law["short"],
            "articles": {a["title"]: a for a in law["articles"]},
        }

    findings = json.loads((root / "data" / "findings_map.json").read_text(encoding="utf-8"))
    categories = set(findings.get("categories", []))

    missing = []
    ids = set()
    for entry in findings["entries"]:
        if entry["id"] in ids:
            missing.append("重複ID: {}".format(entry["id"]))
        ids.add(entry["id"])
        if entry["category"] not in categories:
            missing.append("未定義カテゴリ: {} ({})".format(entry["category"], entry["id"]))

        if not args.quiet:
            print("\n■ {}  [{}]".format(entry["label"], entry["category"]))
        for ref in entry["refs"]:
            law = laws.get(ref["law_id"])
            if law is None:
                missing.append("未収録の法令: {} ({})".format(ref["law_id"], entry["id"]))
                continue
            article = law["articles"].get(ref["article"])
            if article is None:
                missing.append("存在しない条: {} {} ({})".format(
                    law["title"], ref["article"], entry["id"]))
                continue
            if article.get("deleted"):
                missing.append("削除された条を参照: {} {} ({})".format(
                    law["title"], ref["article"], entry["id"]))
            if not args.quiet:
                print("   {:<6} {:<12} {}{}".format(
                    law["short"], ref["article"],
                    article["caption"] or "（見出しなし）",
                    "  ※" + ref["point"] if ref.get("point") else ""))

    total_refs = sum(len(e["refs"]) for e in findings["entries"])
    print("\n{} 件の指摘パターン / {} 件の条文参照".format(len(findings["entries"]), total_refs))
    if missing:
        print("\n!! 要修正 {} 件".format(len(missing)))
        for m in missing:
            print("   - " + m)
        return 1
    print("参照先の条文はすべて実在します。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
