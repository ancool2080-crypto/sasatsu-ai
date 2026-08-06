#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自治体の例規集で保存した火災予防条例のHTMLを、匿名化スクリプトに渡せるテキストに変換する。

  使い方:
    python scripts/ordinance_from_html.py 保存したページ.html -o data/ordinances_src/asahi.txt

例規集サイトの体裁はまちまちなので、ブロック要素で改行し、表はセルを全角スペースで
つないだ素朴な変換にしている。変換後のテキストは目視で確認すること。

条例は著作権法第13条により著作権の目的とならないが、取得元サイトの利用条件は
各自で確認すること。取得は手動・都度に留め、連続アクセスはしない。
"""

import argparse
import html
import re
import sys
from pathlib import Path

BLOCK = r'(?:br|/p|/div|/tr|/li|/h[1-6]|/table|/caption|/dt|/dd)'


def html_to_text(src):
    # スクリプト・スタイル・コメントを丸ごと除去
    src = re.sub(r'(?is)<script.*?</script>', '', src)
    src = re.sub(r'(?is)<style.*?</style>', '', src)
    src = re.sub(r'(?s)<!--.*?-->', '', src)

    body = re.search(r'(?is)<body[^>]*>(.*)</body>', src)
    if body:
        src = body.group(1)

    # 表のセル区切りは全角スペースにして1行に残す
    src = re.sub(r'(?i)</t[dh]>\s*<t[dh][^>]*>', '　', src)
    # ブロック要素の終わりで改行
    src = re.sub(r'(?i)<' + BLOCK + r'[^>]*>', '\n', src)
    # 残りのタグは削除（インライン要素）
    src = re.sub(r'<[^>]+>', '', src)

    src = html.unescape(src)

    lines = []
    for raw in src.split('\n'):
        line = raw.replace('　', ' ').strip()
        line = re.sub(r'[ \t]{2,}', ' ', line)
        if not line:
            continue
        # ページ末尾に出るアンカーID（e000003610 等）は本文ではない
        if re.fullmatch(r'[a-z]\d{5,}', line):
            continue
        lines.append(line)
    return lines


def take_main_provision(lines):
    """目次と附則・末尾の索引を落として本則だけを返す。

    例規集のページは 題名 → 目次 → 本則 → 附則(複数) → 索引 の順に並ぶ。
    目次にも「附則」の行があるため、本則の開始位置を決めてから附則を探す。
    """
    # 「第1章」は 目次・本則・末尾の索引 の3か所に現れる。
    # 直後に本文を伴う条見出しが来るものだけが本則の頭。
    body_head = re.compile(r'^第[0-9〇一二三四五六七八九十]+条[ 　]')
    start = None
    for i, line in enumerate(lines):
        if not re.match(r'^第[1一]章', line):
            continue
        for look in lines[i + 1:i + 6]:
            if body_head.match(look) and len(look) > 40:
                start = i
                break
        if start is not None:
            break
    if start is None:
        return lines, 0, 0

    end = len(lines)
    for i in range(start, len(lines)):
        if re.match(r'^附則', lines[i]):
            end = i
            break
    return lines[start:end], start, len(lines) - end


def join_articles(lines):
    """「第3条」と本文が別行に割れているので、条見出しの行に本文をつなぐ。"""
    head = re.compile(r'^(第[〇一二三四五六七八九十百千0-9]+条(?:の[〇一二三四五六七八九十百千0-9]+)*)$')
    out = []
    for line in lines:
        if out and head.match(out[-1]) and not head.match(line):
            out[-1] = out[-1] + '　' + line
        else:
            out.append(line)
    return out


def main():
    ap = argparse.ArgumentParser(description='例規集のHTMLを条例テキストに変換する')
    ap.add_argument('input', help='保存したHTMLファイル')
    ap.add_argument('-o', '--output', required=True, help='出力するテキストファイル')
    ap.add_argument('--whole', action='store_true',
                    help='目次・附則も含めてすべて出力する（既定は本則のみ）')
    args = ap.parse_args()

    path = Path(args.input)
    if not path.exists():
        print('ファイルがありません: {}'.format(path), file=sys.stderr)
        return 1

    raw = path.read_bytes()
    for enc in ('utf-8', 'cp932', 'euc-jp'):
        try:
            src = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        print('文字コードを判別できませんでした', file=sys.stderr)
        return 1

    all_lines = join_articles(html_to_text(src))
    if args.whole:
        lines, dropped_head, dropped_tail = all_lines, 0, 0
    else:
        lines, dropped_head, dropped_tail = take_main_provision(all_lines)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    arts = sum(1 for l in lines if re.match(r'^第[〇一二三四五六七八九十百千0-9]+条', l))
    print('{} 行 / 条見出し {} 件 / {:,} 文字 を {} に書き出しました'.format(
        len(lines), arts, sum(len(l) for l in lines), out))
    if dropped_head or dropped_tail:
        print('（目次 {} 行と、附則以降 {} 行を除いています。'
              '附則の経過措置も要る場合は --whole を付けてください）'.format(dropped_head, dropped_tail))
    print('※ 変換結果を目視で確認してから anonymize_ordinance.py にかけてください。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
