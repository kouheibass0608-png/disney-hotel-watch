#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ディズニーホテル 空室チェック（手動確認おたすけツール）
========================================================
公式サイトは自動監視を拒否しているため、確認は「自分のブラウザで見る」
のが唯一の正しいやり方です。このツールはその手間だけを減らします。

やること: 見たい日程のURLを組み立てて、ブラウザのタブで順番に開くだけ。
（サイトの操作も判定も、すべてあなた自身が目で行います）

使い方:
    python3 check_now.py            # ブラウザで順番に開く
    python3 check_now.py --list     # URLを表示するだけ（開かない）

Macなら check_now.command をダブルクリックでも実行できます
（作り方は下の【ダブルクリックで使う】を参照）。
"""

import sys
import time
import webbrowser
from datetime import date, timedelta
from urllib.parse import urlencode

# ============ 【設定】 ============

# 見たい条件のリスト。日付は "YYYY-MM-DD"。
# 「連続した日程をまとめて見たい」ときは下の DATE_RANGES を使ってください。
WATCHES = [
    {"hotel": "DHM", "date": "2026-09-27", "nights": 1, "adults": 2},
]

# 連続した日程をまとめて見たい場合はここに書く（使わないなら空のまま）
#   例: ミラコスタの 9/20〜9/30 を1泊ずつ全部見る
#       {"hotel": "DHM", "from": "2026-09-20", "to": "2026-09-30", "nights": 1, "adults": 2},
DATE_RANGES = [
]

# タブを開く間隔（秒）。一気に開くとサイトに負担なので少し空ける。
OPEN_INTERVAL_SEC = 6

# ホテルコード
#   TDH: ディズニーランドホテル      DHM: ホテルミラコスタ
#   DAH: アンバサダーホテル          TSH: トイ・ストーリーホテル
#   FSH: ファンタジースプリングスホテル
#   DCH: セレブレーションホテル
HOTEL_NAMES = {
    "TDH": "ディズニーランドホテル",
    "DHM": "ホテルミラコスタ",
    "DAH": "アンバサダーホテル",
    "TSH": "トイ・ストーリーホテル",
    "FSH": "ファンタジースプリングスホテル",
    "DCH": "セレブレーションホテル",
}

# =================================

LIST_URL = "https://reserve.tokyodisneyresort.jp/hotel/list/"


def build_url(hotel, day, nights, adults):
    params = {
        "useDate": day.strftime("%Y%m%d"),
        "stayingDays": str(nights),
        "adultNum": str(adults),
        "childNum": "0",
        "roomsNum": "1",
        "searchHotelCD": hotel,
        "displayType": "hotel-search",
    }
    return LIST_URL + "?" + urlencode(params)


def parse_day(s):
    y, m, d = (int(x) for x in s.split("-"))
    return date(y, m, d)


def collect_targets():
    targets = []
    for w in WATCHES:
        day = parse_day(w["date"])
        targets.append((w["hotel"], day, w.get("nights", 1), w.get("adults", 2)))
    for r in DATE_RANGES:
        day = parse_day(r["from"])
        last = parse_day(r["to"])
        while day <= last:
            targets.append((r["hotel"], day, r.get("nights", 1), r.get("adults", 2)))
            day += timedelta(days=1)
    return targets


def main():
    targets = collect_targets()
    if not targets:
        print("見たい日程が設定されていません。ファイル上部の WATCHES を編集してください。")
        return

    list_only = "--list" in sys.argv

    print("=" * 56)
    print(" ディズニーホテル 空室チェック（手動確認おたすけ）")
    print(f" 対象: {len(targets)}件")
    print("=" * 56)

    for i, (hotel, day, nights, adults) in enumerate(targets, 1):
        name = HOTEL_NAMES.get(hotel, hotel)
        url = build_url(hotel, day, nights, adults)
        label = f"{name} {day.month}/{day.day} {nights}泊 大人{adults}名"
        print(f"\n[{i}/{len(targets)}] {label}")
        print(f"  {url}")
        if not list_only:
            webbrowser.open(url)
            if i < len(targets):
                time.sleep(OPEN_INTERVAL_SEC)

    print("\n" + "-" * 56)
    if list_only:
        print("URLを表示しました。クリックまたはコピーして開いてください。")
    else:
        print("ブラウザのタブで開きました。")
        print("※ 混雑時は順番待ち画面が出ます。閉じずにお待ちください。")
    print("\n【見方】")
    print("  ・「総額 ○○円」と「予約する」がある → 空きあり🎉")
    print("  ・「○月○日は全室満室です」        → 空きなし")
    print("-" * 56)


if __name__ == "__main__":
    main()
