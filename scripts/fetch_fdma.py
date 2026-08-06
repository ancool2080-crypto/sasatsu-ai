#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
総務省消防庁サイトから通知・通達の書誌情報と、標準マニュアルの本文を取得する。

  使い方:
    pip install pdfplumber
    python scripts/fetch_fdma.py              # 書誌インデックス＋本文収録対象を取得
    python scripts/fetch_fdma.py --index-only # 書誌インデックスだけ更新

出典：消防庁ホームページ（https://www.fdma.go.jp/）
消防庁のコンテンツは公共データ利用規約（PDL1.0）に基づき、出典と加工の明示のうえ利用できる。
また通知・通達は著作権法第13条第2号により著作権の目的とならない。

本文はPDFからページ単位で抽出する。ページ単位にするのは、
「違反処理標準マニュアル P.47」のように原典の該当ページを示せるようにするため。
PDFのページ指定リンク（#page=N）も併せて持たせる。
"""

import argparse
import html
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = "https://www.fdma.go.jp"
TUTATSU = BASE + "/laws/tutatsu/{year}/"
YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
JST = timezone(timedelta(hours=9))
INTERVAL = 1.0                      # 個人利用。常識的な間隔を空ける
UA = "sasatsu-ai/4.0 (personal inspection support tool)"

# 予防・査察の実務に関係する通知だけを索引に残すための語
PREVENTION_HINTS = [
    "予防", "査察", "立入検査", "違反処理", "防火", "防炎", "避難", "消防用設備", "消火設備",
    "自動火災報知", "スプリンクラー", "誘導灯", "危険物", "指定可燃物", "少量危険物",
    "防火管理", "統括防火", "点検報告", "用途判定", "特定防火対象物", "住宅用火災警報器",
    "消防同意", "建築基準", "建築物", "内装", "屋外催し", "個室", "民泊", "住宅宿泊",
    "特定小規模", "二酸化炭素消火設備", "直通階段", "火気", "たき火", "喫煙",
    "執務資料", "火災予防条例",
]
# 明らかに予防と関係の薄いもの
EXCLUDE_HINTS = [
    "救急", "救助", "感染", "ワクチン", "コロナ", "インフルエンザ", "消防団", "採用", "人事",
    "ハラスメント", "給与", "定年", "国民保護", "弾道ミサイル", "地震", "台風", "降積雪",
    "訓練礼式", "無線", "統計", "白書", "建築費指数", "予防技術検定",
]

# 本文まで収録する文書。改正のたびにここのURLを差し替える。
FULL_TEXT_DOCS = [
    {
        "id": "manual_tachiiri",
        "kind": "マニュアル",
        "title": "立入検査標準マニュアル",
        "notice_no": "消防予第175号",
        "date": "2023-03-16",
        "url": BASE + "/laws/tutatsu/items/230316_yobou_175.pdf",
        "note": "令和5年3月16日改正。冒頭に改正通知、以降が本文。",
    },
    {
        "id": "manual_ihan",
        "kind": "マニュアル",
        "title": "違反処理標準マニュアル",
        "notice_no": "消防予第470号",
        "date": "2025-10-16",
        "url": BASE + "/laws/tutatsu/items/b520437325d69c99eb63ecf5babac5c20a54c8eb.pdf",
        "note": "令和7年10月16日改正。冒頭に改正通知、以降が本文。",
    },
]

ERA_START = {"令和": 2018, "平成": 1988, "昭和": 1925}


def fetch(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as res:
        data = res.read()
    return data if binary else data.decode("utf-8", errors="replace")


def to_iso(text):
    """「令和4年11月21日」→ 2022-11-21"""
    m = re.search(r"(令和|平成|昭和)\s*([0-9０-９元]+)\s*年\s*([0-9０-９]+)\s*月\s*([0-9０-９]+)\s*日", text)
    if not m:
        return ""
    z = str.maketrans("０１２３４５６７８９", "0123456789")
    era, y, mo, d = m.group(1), m.group(2).translate(z), m.group(3).translate(z), m.group(4).translate(z)
    year = ERA_START[era] + (1 if y == "元" else int(y))
    return "{:04d}-{:02d}-{:02d}".format(year, int(mo), int(d))


def parse_year_page(year):
    """通知・通達の年別ページから (番号, 件名, 日付, URL) を拾う。"""
    try:
        page = fetch(TUTATSU.format(year=year))
    except Exception as exc:                                  # noqa: BLE001
        print("  ! {}年のページを取得できません: {}".format(year, exc), file=sys.stderr)
        return []

    entries = []
    for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        text = html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
        text = re.sub(r"\s+", " ", text)
        if not text or not href.lower().endswith(".pdf"):
            continue

        # 「消防予第598号」「消防情第217号」「【事務連絡】」など先頭の識別子を切り出す
        no, kind, title = "", "通知", text
        m = re.match(r"^\s*[【\[]?\s*(消防[一-龥]{1,2}\s*第?\s*[0-9０-９]+\s*号|事務連絡)\s*[】\]]?\s*",
                     text)
        if m:
            no = re.sub(r"\s+", "", m.group(1))
            title = text[m.end():].strip()
            if no == "事務連絡":
                kind, no = "事務連絡", ""
        elif "事務連絡" in text[:12]:
            kind = "事務連絡"
            title = re.sub(r"^\s*[【\[]?\s*事務連絡\s*[】\]]?\s*", "", text)

        # 末尾の（令和○年○月○日）は date に持つので件名からは外す
        title = re.sub(r"[（(]\s*(令和|平成|昭和)[^）)]*[）)]\s*$", "", title).strip()

        entries.append({
            "no": no,
            "kind": kind,
            "title": title or text,
            "date": to_iso(text),
            "url": href if href.startswith("http") else BASE + href,
            "year": year,
        })
    return entries


def is_prevention(entry):
    text = entry["title"]
    if any(w in text for w in EXCLUDE_HINTS):
        return False
    return any(w in text for w in PREVENTION_HINTS)


def build_index():
    print("通知・通達の書誌情報を集めます")
    all_entries, seen = [], set()
    for i, year in enumerate(YEARS):
        if i:
            time.sleep(INTERVAL)
        entries = parse_year_page(year)
        kept = [e for e in entries if is_prevention(e)]
        for e in kept:
            if e["url"] in seen:
                continue
            seen.add(e["url"])
            all_entries.append(e)
        print("  {}年: {} 件中 {} 件が予防関係".format(year, len(entries), len(kept)))

    all_entries.sort(key=lambda e: (e["date"] or "", e["no"]), reverse=True)
    return all_entries


def extract_pdf_pages(path):
    """PDFをページ単位のテキストにする。見出しらしき行を各ページに引き継ぐ。"""
    import pdfplumber

    heading_re = re.compile(r"^第[0-9０-９一二三四五六七八九十]+\s*[　 ]?\S{2,30}$")
    pages, current_heading = [], ""

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            raw = page.extract_text() or ""
            lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
            # 目次の行（・・・でページ番号に繋ぐ行）はノイズになりやすいので落とす
            lines = [ln for ln in lines if not re.search(r"[・･]{6,}", ln)]
            for ln in lines[:6]:
                if heading_re.match(ln):
                    current_heading = ln
                    break
            text = "\n".join(lines)
            if not text.strip():
                continue
            pages.append({"page": i, "heading": current_heading, "text": text})
    return pages


def fetch_full_texts(root):
    cache = root / "data" / "fdma_cache"
    cache.mkdir(parents=True, exist_ok=True)
    docs = []

    for i, spec in enumerate(FULL_TEXT_DOCS):
        if i:
            time.sleep(INTERVAL)
        name = spec["url"].rsplit("/", 1)[-1]
        pdf_path = cache / name
        if not pdf_path.exists():
            print("  取得中: {} …".format(spec["title"]), flush=True)
            pdf_path.write_bytes(fetch(spec["url"], binary=True))
        else:
            print("  キャッシュ利用: {}".format(spec["title"]))

        pages = extract_pdf_pages(pdf_path)
        chars = sum(len(p["text"]) for p in pages)
        print("    {} ページ / {:,} 文字".format(len(pages), chars))

        doc = dict(spec)
        doc["pages"] = pages
        doc["page_count"] = len(pages)
        docs.append(doc)
    return docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-only", action="store_true", help="書誌インデックスだけ更新する")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    out_dir = root / "data"
    out_dir.mkdir(exist_ok=True)
    fetched_at = datetime.now(JST).isoformat(timespec="seconds")

    notices = build_index()

    docs = []
    if not args.index_only:
        print("\n標準マニュアルの本文を取得します")
        docs = fetch_full_texts(root)

    payload = {
        "fetched_at": fetched_at,
        "source": "総務省消防庁ホームページ",
        "source_url": BASE + "/laws/tutatsu/",
        "license": "公共データ利用規約（PDL1.0）。通知・通達は著作権法第13条第2号により著作権の目的とならない。",
        "note": "本アプリの作成者が、PDFからページ単位でテキストを抽出して再構成したものです。"
                "内容について消防庁が保証したものではありません。",
        "notices": notices,
        "documents": docs,
    }
    if args.index_only and (out_dir / "fdma.json").exists():
        prev = json.loads((out_dir / "fdma.json").read_text(encoding="utf-8"))
        payload["documents"] = prev.get("documents", [])

    path = out_dir / "fdma.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print("\ndata/fdma.json を生成しました")
    print("  通知・通達（予防関係）: {} 件".format(len(payload["notices"])))
    print("  本文収録: {} 件 / 計 {} ページ".format(
        len(payload["documents"]), sum(d["page_count"] for d in payload["documents"])))
    print("  {:,} bytes".format(path.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
