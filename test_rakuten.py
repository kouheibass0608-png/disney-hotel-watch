#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
楽天トラベルAPI 接続テスト（自宅PCから実行）
==============================================
楽天APIがこのPC（家庭用回線）から使えるかを確認します。
クラウド（GitHub Actions）からはIPで拒否されましたが、
自宅の回線なら通る可能性が高いため、それを検証します。

使い方:
    RAKUTEN_APP_ID=アプリID RAKUTEN_ACCESS_KEY=アクセスキー \
        ~/disney-venv/bin/python3 test_rakuten.py

結果は画面と test_rakuten_result.txt に出ます。
"""

import json
import os
import sys
import time
from datetime import date, timedelta

try:
    import requests
except ImportError:
    print("requests が見つかりません:  ~/disney-venv/bin/pip install requests")
    sys.exit(1)

APP_ID = os.environ.get("RAKUTEN_APP_ID", "").strip()
ACCESS_KEY = os.environ.get("RAKUTEN_ACCESS_KEY", "").strip()

API_URL = "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426"

# 試すReferer（楽天アプリ設定の「許可されたWebサイト」に載っているもの中心）
REFERERS = [
    "https://webservice.rakuten.co.jp/",
    "https://webservice.rakuten.co.jp",
    "https://rakuten.co.jp/",
    "https://www.rakuten.co.jp/",
    None,  # Refererを送らない場合
]

# テスト対象: ミラコスタ(74733) の近い日程と、監視したい9/27
TARGETS = [
    ("ミラコスタ 2週間後", "74733", date.today() + timedelta(days=14)),
    ("ミラコスタ 9/27", "74733", date(2026, 9, 27)),
]

lines = []


def out(text=""):
    print(text)
    lines.append(str(text))


def try_request(referer, hotel_no, checkin):
    params = {
        "applicationId": APP_ID,
        "accessKey": ACCESS_KEY,
        "format": "json",
        "checkinDate": checkin.isoformat(),
        "checkoutDate": (checkin + timedelta(days=1)).isoformat(),
        "hotelNo": hotel_no,
        "adultNum": 2,
    }
    headers = {}
    if referer:
        headers["Referer"] = referer
        headers["Origin"] = referer.rstrip("/")
    try:
        r = requests.get(API_URL, params=params, headers=headers, timeout=20)
    except Exception as e:
        return None, f"通信エラー: {e}"
    body = r.text
    try:
        body_json = r.json()
    except Exception:
        body_json = None
    return r.status_code, (body_json if body_json is not None else body[:300])


def describe(status, body):
    """結果を人間に分かる一言にする。"""
    if status is None:
        return f"✗ {body}"
    if status == 200:
        return "✓ 成功（データ取得OK）"
    msg = ""
    if isinstance(body, dict):
        errs = body.get("errors")
        if isinstance(errs, dict):
            msg = errs.get("errorMessage", "")
        msg = msg or body.get("error", "") or body.get("message", "")
    text = str(msg or body)
    if "IP address" in text:
        return f"✗ IPアドレス拒否（{text[:80]}）"
    if "REFERRER" in text.upper():
        return f"✗ Referer拒否（{text[:80]}）"
    if status == 404:
        return "○ 空室なし（404 not_found ＝ 正常動作）"
    if status == 429:
        return "△ レート制限（呼びすぎ。間隔を空ければOK）"
    return f"✗ HTTP {status}: {text[:100]}"


def main():
    out("=" * 60)
    out(" 楽天トラベルAPI 接続テスト（自宅PCから）")
    out("=" * 60)

    if not APP_ID or not ACCESS_KEY:
        out("⚠ RAKUTEN_APP_ID と RAKUTEN_ACCESS_KEY を指定して実行してください。")
        out("  例: RAKUTEN_APP_ID=xxx RAKUTEN_ACCESS_KEY=yyy \\")
        out("        ~/disney-venv/bin/python3 test_rakuten.py")
        sys.exit(1)

    out(f"\nアプリID: {APP_ID[:8]}...（先頭のみ表示）")

    # --- 1) どのRefererが通るかを判定 ---
    out("\n[1] Refererごとの結果（ミラコスタ 2週間後で試行）")
    label, hotel_no, checkin = TARGETS[0]
    working_referer = "NOT_FOUND"
    for ref in REFERERS:
        status, body = try_request(ref, hotel_no, checkin)
        out(f"  {str(ref or '（Refererなし）'):40s} → {describe(status, body)}")
        if status in (200, 404) and working_referer == "NOT_FOUND":
            working_referer = ref
        time.sleep(2)  # レート制限を避ける

    if working_referer == "NOT_FOUND":
        out("\n結論: ✗ このPCからも楽天APIは使えませんでした。")
        out("      → 上の結果を開発者に貼ってください。")
    else:
        out(f"\n結論: ✓ 楽天APIが使えます！ 有効なReferer: {working_referer or '（なし）'}")

        # --- 2) 実際の監視対象で中身を確認 ---
        out("\n[2] 実際の日程での取得内容")
        for label, hotel_no, checkin in TARGETS:
            status, body = try_request(working_referer, hotel_no, checkin)
            out(f"\n  ◆ {label}（{checkin} 1泊 大人2名）: {describe(status, body)}")
            if status == 200 and isinstance(body, dict):
                hotels = body.get("hotels") or []
                count = 0
                for wrapper in hotels:
                    parts = wrapper.get("hotel", []) if isinstance(wrapper, dict) else []
                    for p in parts[1:]:
                        info = p.get("roomInfo") if isinstance(p, dict) else None
                        if info:
                            count += 1
                out(f"     → 予約可能な部屋・プラン: 約{count}件")
                sample = json.dumps(body, ensure_ascii=False)[:600]
                out(f"     → 応答の先頭: {sample}")
            time.sleep(2)

    out("\n" + "=" * 60)
    out(" テストおわり。この内容を開発者に貼ってください。")
    out("=" * 60)

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "test_rakuten_result.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"\n→ 結果を保存しました: {path}")
    except Exception as e:
        print(f"（保存に失敗: {e}）")


if __name__ == "__main__":
    main()
