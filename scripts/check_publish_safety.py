#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公開（public化）の前に、リポジトリに入るファイルへ識別情報が混ざっていないか点検する。

  使い方:  python scripts/check_publish_safety.py [--names ○○市,○○県]

査察メモは端末の localStorage にしか無いのでリポジトリには入らないが、
findings_map.json に実務メモを書き足すと公開される。そこを主に見る。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# 所属固有の運用・事案を示唆する語（アプリ内の注意喚起と同じ観点）
INTERNAL = [
    (re.compile(r'当本部|当署|当消防本部|当市|当町|当村|本市|本町|本村'), '所属を指す語'),
    (re.compile(r'内規|申し?合わせ|申合せ|運用指針|運用基準|事務処理要領|事務処理基準|査察規程'), '内部運用の呼称'),
    (re.compile(r'事案番号|受理番号|整理番号|台帳番号'), '事案を特定する番号'),
    (re.compile(r'[一-龥]{2,4}(?:氏|さん|様)'), '人名らしき語'),
    (re.compile(r'株式会社[^、。\s]{0,14}|有限会社[^、。\s]{0,14}'), '法人名'),
    (re.compile(r'\d{2,4}-\d{2,4}-\d{3,4}'), '電話番号らしき数字'),
]

# 自治体名らしき語（一般的な法令用語は除く）
MUNI = re.compile(r'[一-龥ァ-ヶー々]{1,5}(?:市|町|村|区)(?![域分画内間場政策民切])')
MUNI_SAFE = {
    '市町村', '都道府県', '各市町村', '当該市町村', '市街', '都市', '町内', '村落',
    '特別区', '指定都市', '中核市', '政令指定都市', '市区町村', '地区', '街区', '区',
}

SKIP_DIRS = {'.git', 'icons', '__pycache__', 'node_modules'}
# e-Gov 由来の法令データは国の公開データなので対象外
# 消防庁由来のデータも国の公開コンテンツなので対象外
SKIP_FILES = {'data/laws_index.json', 'data/fdma.json'}

# コード類は検知パターンそのものを含むため、一般パターンでの走査対象にしない。
# （指定された自治体名が埋め込まれていないかだけは全ファイルで見る）
CODE_SUFFIXES = {'.py', '.js', '.html', '.json'}
CONTENT_FILES = {'README.md', 'data/findings_map.json', 'data/ordinances.json'}


# README で機能そのものを説明するために出てくる語。検知例なので実データではない。
DOC_EXAMPLES = {
    '当本部', '当署', '当市', '当町', '当村', '本市', '本町', '本村',
    '内規', '申し合わせ', '申合せ', '運用指針', '運用基準', '事務処理要領',
    '事務処理基準', '査察規程', '事案番号', '受理番号', '整理番号', '台帳番号',
}


def is_content_file(rel):
    if rel in CONTENT_FILES:
        return True
    return rel.startswith('data/') and rel not in SKIP_FILES


def tracked_files(root):
    try:
        out = subprocess.check_output(['git', 'ls-files'], cwd=root, text=True, encoding='utf-8')
    except Exception:                                    # noqa: BLE001
        return []
    files = []
    for rel in out.splitlines():
        if not rel:
            continue
        parts = Path(rel).parts
        if any(p in SKIP_DIRS for p in parts):
            continue
        if rel in SKIP_FILES or rel.startswith('data/laws/'):
            continue
        files.append(rel)
    return files


def scan(text, names, deep):
    """deep=False のときは、指定された自治体名が埋め込まれていないかだけを見る。"""
    findings = []
    for name in names:
        if name and name in text:
            findings.append((name, '指定した自治体名'))
    if not deep:
        return findings
    for token in set(MUNI.findall(text)):
        if token not in MUNI_SAFE:
            findings.append((token, '自治体名らしき語'))
    for pattern, label in INTERNAL:
        for token in set(pattern.findall(text)):
            findings.append((token, label))
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--names', default='', help='伏せたい自治体名（カンマ区切り）')
    args = ap.parse_args()
    names = [n.strip() for n in args.names.split(',') if n.strip()]

    root = Path(__file__).resolve().parent.parent
    files = tracked_files(root)
    if not files:
        print('git 管理下のファイルを取得できませんでした', file=sys.stderr)
        return 1

    print('公開前チェック：{} ファイルを点検します'.format(len(files)))
    print('（e-Gov由来の法令データ data/laws/ は国の公開データのため対象外）\n')

    total = 0
    for rel in files:
        path = root / rel
        try:
            text = path.read_text(encoding='utf-8')
        except Exception:                                # noqa: BLE001
            continue

        findings = scan(text, names, deep=is_content_file(rel))
        # 匿名化済みの条例は、マスク語そのものが出るのは正常
        if rel == 'data/ordinances.json':
            findings = [f for f in findings if '非表示' not in f[0]]
        # README は機能説明のために検知例そのものを載せている
        if rel == 'README.md':
            findings = [f for f in findings if f[0] not in DOC_EXAMPLES]

        if findings:
            total += len(findings)
            print('■ {}'.format(rel))
            seen = set()
            for token, label in findings:
                if token in seen:
                    continue
                seen.add(token)
                print('   {}  … {}'.format(token, label))
            print()

    # 条例データの状態も出す
    ord_path = root / 'data' / 'ordinances.json'
    if ord_path.exists():
        data = json.loads(ord_path.read_text(encoding='utf-8'))
        for o in data.get('ordinances', []):
            print('条例：{} / 本則{}条 / マスク {}'.format(
                o.get('title'), o.get('article_count'), o.get('masked_counts')))
        if data.get('review_candidates'):
            print('! 条例に要確認候補が残っています:',
                  [c['token'] for c in data['review_candidates']][:10])
            total += len(data['review_candidates'])
        print()

    if total:
        print('!! {} 件の要確認箇所があります。公開前に内容を確認してください。'.format(total))
        return 1
    print('要確認箇所はありません。公開して差し支えない状態です。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
