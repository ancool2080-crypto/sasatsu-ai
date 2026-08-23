#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
index.html の静的検査。

  使い方:  python scripts/check_html.py

タグの対応、ID参照、関数の重複、CSS変数、タブとモジュールの一致に加え、
node があれば JavaScript の構文も検査する。
正規表現リテラルの中に生の改行が入ってしまう事故があり、
HTMLの検査だけでは素通りしたため、構文検査を必ず通すようにしている。
"""

import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr'}


class TagChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.errors, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append('</{}>'.format(tag))


def main():
    root = Path(__file__).resolve().parent.parent
    src = (root / 'index.html').read_text(encoding='utf-8')
    problems = []

    checker = TagChecker()
    checker.feed(src)
    if checker.errors or checker.stack:
        problems.append('タグの対応: 余分={} 未閉={}'.format(
            checker.errors[:3], checker.stack[-3:]))

    ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', src))
    refs = set(re.findall(r'getElementById\(.([A-Za-z0-9_-]+).\)', src))
    if refs - ids:
        problems.append('存在しないID参照: {}'.format(sorted(refs - ids)))

    funcs = re.findall(r'function\s+([A-Za-z0-9_]+)\s*\(', src)
    dupes = sorted({f for f in funcs if funcs.count(f) > 1})
    if dupes:
        problems.append('関数の重複定義: {}'.format(dupes))

    style = src.split('</style>')[0]
    declared = set(re.findall(r'(--[a-z-]+)\s*:', style))
    used = set(re.findall(r'var\((--[a-z-]+)\)', src))
    if used - declared:
        problems.append('未定義のCSS変数: {}'.format(sorted(used - declared)))

    mods = set(re.findall(r'id="mod-([a-z]+)"', src))
    tabs = set(re.findall(r'data-mod="([a-z]+)"', src))
    if mods != tabs:
        problems.append('タブとモジュールの不一致: {}'.format(sorted(mods ^ tabs)))

    node = shutil.which('node')
    if node:
        blocks = re.findall(r'(?s)<script(?![^>]*src)[^>]*>(.*?)</script>', src)
        js = max(blocks, key=len) if blocks else ''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'app.js'
            path.write_text(js, encoding='utf-8')
            r = subprocess.run([node, '--check', str(path)],
                               capture_output=True, text=True, encoding='utf-8')
            if r.returncode != 0:
                head = (r.stderr or '').strip().split('\n')[:6]
                problems.append('JavaScript構文エラー:\n      ' + '\n      '.join(head))
    else:
        print('（node が無いので JavaScript の構文検査は省略しました）')

    print('index.html: {:,} bytes / タブ {} / 関数 {}'.format(
        len(src.encode('utf-8')), len(tabs), len(set(funcs))))
    if problems:
        print('\n!! {} 件'.format(len(problems)))
        for p in problems:
            print('   - ' + p)
        return 1
    print('問題はありません。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
