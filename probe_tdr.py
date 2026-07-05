#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
東京ディズニーリゾート公式予約サイトの調査用スクリプト（一時的なもの）
=======================================================================
GitHub Actions のランナーから公式サイトにアクセスできるか、
空室APIがどんな形式のリクエスト/レスポンスなのかを確認する。
結果はログに出すだけで、通知は送らない。
"""

import sys

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Accept-Language": "ja,en;q=0.8",
})


def show(name, resp, limit=800):
    print("=" * 60)
    print(f"[{name}] HTTP {resp.status_code} / content-type: {resp.headers.get('content-type', '')}")
    body = " ".join(resp.text.split())  # 改行を潰して読みやすく
    print(body[:limit])
    print()


# --- 1. ホテル一覧ページ（HTML）: そもそもブロックされるかの確認 ---
try:
    r = session.get(
        "https://reserve.tokyodisneyresort.jp/hotel/list/",
        params={
            "useDate": "20260915",
            "stayingDays": "1",
            "adultNum": "2",
            "childNum": "0",
            "roomsNum": "1",
            "displayType": "hotel-search",
        },
        timeout=30,
    )
    show("hotel/list GET", r)
except Exception as e:
    print("hotel/list GET 失敗:", e)

# --- 2. 空室API queryHotelPriceStock: 形式を変えて試す ---
payload = {
    "commodityCD": "HODHMCTG0001N",  # ミラコスタ（コミュニティ情報のコード）
    "useDate": "20260915",
    "stayingDays": "1",
    "adultNum": "2",
    "childNum": "0",
    "roomsNum": "1",
    "stockQueryType": "1",
    "rrc3005ProcessingType": "0",
}
api_url = "https://reserve.tokyodisneyresort.jp/hotel/api/queryHotelPriceStock/"
api_headers = {
    "Referer": "https://reserve.tokyodisneyresort.jp/hotel/list/",
    "Origin": "https://reserve.tokyodisneyresort.jp",
    "Accept": "application/json, text/plain, */*",
}

try:
    r = session.post(api_url, json=payload, headers=api_headers, timeout=30)
    show("queryHotelPriceStock POST(json)", r)
except Exception as e:
    print("POST(json) 失敗:", e)

try:
    r = session.post(api_url, data=payload, headers=api_headers, timeout=30)
    show("queryHotelPriceStock POST(form)", r)
except Exception as e:
    print("POST(form) 失敗:", e)

try:
    r = session.get(api_url, params=payload, headers=api_headers, timeout=30)
    show("queryHotelPriceStock GET", r)
except Exception as e:
    print("GET 失敗:", e)

print("調査おわり")
sys.exit(0)
