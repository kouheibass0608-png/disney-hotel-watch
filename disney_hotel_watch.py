#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ディズニーホテル 空室通知（楽天トラベルAPI版）/ ローカル・クラウド両対応
==========================================================================
楽天トラベル空室検索APIで、指定したディズニーホテル・日程の空きをチェックし、
新しく空室が出たら ntfy 経由でスマホに通知します。

2つの動かし方:
  ・ローカル（自分のPCで動かし続ける）:   python3 disney_hotel_watch.py
        → CHECK_INTERVAL_SEC ごとにずっとループします（Ctrl+Cで停止）
  ・クラウド（GitHub Actionsなどで定期実行）: python3 disney_hotel_watch.py --once
        → 1回だけチェックして終了します（スケジューラ側で繰り返す）

アプリIDとntfyトピックは、環境変数（GitHub Secrets）があればそちらを優先して使います。
ローカルだけで使うなら、下の【設定】に直接書いてもOKです。
"""

import time
import json
import os
import sys
from datetime import datetime

try:
    import requests
except ImportError:
    print("requests が見つかりません。ターミナルで次を実行してください：")
    print("    pip3 install requests")
    sys.exit(1)


# ============ 【設定】 ============

# 楽天アプリID。環境変数 RAKUTEN_APP_ID があればそれを使う（クラウド用）。
RAKUTEN_APP_ID = os.environ.get("RAKUTEN_APP_ID") or "ここに楽天のアプリIDを貼る"

# 楽天アクセスキー。2026年のAPI刷新でapplicationIdに加えて必須になった。
# 環境変数 RAKUTEN_ACCESS_KEY があればそれを使う（クラウド用）。
RAKUTEN_ACCESS_KEY = os.environ.get("RAKUTEN_ACCESS_KEY") or "ここに楽天のアクセスキーを貼る"

# APIに送るReferer/Origin。楽天アプリ設定の「許可されたWebサイト」に載っている
# ドメインでないと HTTP_REFERRER_NOT_ALLOWED で弾かれる。github.com等は登録できない
# （楽天系ドメインしか受け付けない）ため、既定で許可済みの楽天ドメインを送る。
RAKUTEN_APP_URL = os.environ.get("RAKUTEN_APP_URL") or "https://webservice.rakuten.co.jp/"

# ntfyの自分専用トピック名。環境変数 NTFY_TOPIC があればそれを使う（クラウド用）。
NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or "disney-hotel-watch-CHANGE-ME-x7k2"

# ローカルでループする場合の確認間隔（秒）。180 = 3分。
CHECK_INTERVAL_SEC = 180

# 監視したい条件のリスト。いくつでも追加できる。
WATCHES = [
    {
        "label": "セレブレーションホテル 7/5→7/6 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-05",
        "checkout": "2026-07-06",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/6→7/7 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-06",
        "checkout": "2026-07-07",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/7→7/8 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-07",
        "checkout": "2026-07-08",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/8→7/9 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-08",
        "checkout": "2026-07-09",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/9→7/10 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-09",
        "checkout": "2026-07-10",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/10→7/11 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-10",
        "checkout": "2026-07-11",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/11→7/12 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-11",
        "checkout": "2026-07-12",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/12→7/13 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-12",
        "checkout": "2026-07-13",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/13→7/14 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-13",
        "checkout": "2026-07-14",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/14→7/15 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-14",
        "checkout": "2026-07-15",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/15→7/16 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-15",
        "checkout": "2026-07-16",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/16→7/17 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-16",
        "checkout": "2026-07-17",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/17→7/18 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-17",
        "checkout": "2026-07-18",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/18→7/19 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-18",
        "checkout": "2026-07-19",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/19→7/20 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-19",
        "checkout": "2026-07-20",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/20→7/21 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-20",
        "checkout": "2026-07-21",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/21→7/22 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-21",
        "checkout": "2026-07-22",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/22→7/23 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-22",
        "checkout": "2026-07-23",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/23→7/24 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-23",
        "checkout": "2026-07-24",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/24→7/25 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-24",
        "checkout": "2026-07-25",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/25→7/26 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-25",
        "checkout": "2026-07-26",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/26→7/27 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-26",
        "checkout": "2026-07-27",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/27→7/28 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-27",
        "checkout": "2026-07-28",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/28→7/29 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-28",
        "checkout": "2026-07-29",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/29→7/30 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-29",
        "checkout": "2026-07-30",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/30→7/31 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-30",
        "checkout": "2026-07-31",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 7/31→8/1 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-07-31",
        "checkout": "2026-08-01",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/1→8/2 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-01",
        "checkout": "2026-08-02",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/2→8/3 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-02",
        "checkout": "2026-08-03",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/3→8/4 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-03",
        "checkout": "2026-08-04",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/4→8/5 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-04",
        "checkout": "2026-08-05",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/5→8/6 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-05",
        "checkout": "2026-08-06",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/6→8/7 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-06",
        "checkout": "2026-08-07",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/7→8/8 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-07",
        "checkout": "2026-08-08",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/8→8/9 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-08",
        "checkout": "2026-08-09",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/9→8/10 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-09",
        "checkout": "2026-08-10",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/10→8/11 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-10",
        "checkout": "2026-08-11",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/11→8/12 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-11",
        "checkout": "2026-08-12",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/12→8/13 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-12",
        "checkout": "2026-08-13",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/13→8/14 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-13",
        "checkout": "2026-08-14",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/14→8/15 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-14",
        "checkout": "2026-08-15",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/15→8/16 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-15",
        "checkout": "2026-08-16",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/16→8/17 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-16",
        "checkout": "2026-08-17",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/17→8/18 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-17",
        "checkout": "2026-08-18",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/18→8/19 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-18",
        "checkout": "2026-08-19",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/19→8/20 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-19",
        "checkout": "2026-08-20",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/20→8/21 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-20",
        "checkout": "2026-08-21",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/21→8/22 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-21",
        "checkout": "2026-08-22",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/22→8/23 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-22",
        "checkout": "2026-08-23",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/23→8/24 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-23",
        "checkout": "2026-08-24",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/24→8/25 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-24",
        "checkout": "2026-08-25",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/25→8/26 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-25",
        "checkout": "2026-08-26",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/26→8/27 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-26",
        "checkout": "2026-08-27",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/27→8/28 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-27",
        "checkout": "2026-08-28",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/28→8/29 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-28",
        "checkout": "2026-08-29",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/29→8/30 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-29",
        "checkout": "2026-08-30",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/30→8/31 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-30",
        "checkout": "2026-08-31",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 8/31→9/1 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-08-31",
        "checkout": "2026-09-01",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 9/1→9/2 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-09-01",
        "checkout": "2026-09-02",
        "adultNum": 2,
    },
    {
        "label": "セレブレーションホテル 9/2→9/3 大人2名",
        "hotelNo": "151431",
        "checkin": "2026-09-02",
        "checkout": "2026-09-03",
        "adultNum": 2,
    },
    # ↓ 増やす場合はこの形式でコピーして追加（例）
    # {
    #     "label": "ファンタジースプリングス 10/3→10/4 大人2名",
    #     "hotelNo": "189000",
    #     "checkin": "2026-10-03",
    #     "checkout": "2026-10-04",
    #     "adultNum": 2,
    # },
]

# 【ディズニーホテルの楽天ホテル番号 一覧】（hotelNo に使う）
#   74732  : 東京ディズニーランドホテル
#   74733  : 東京ディズニーシー・ホテルミラコスタ
#   72737  : ディズニーアンバサダーホテル
#   183493 : トイ・ストーリーホテル
#   189000 : ファンタジースプリングスホテル（楽天はファンタジーシャトーのみ取扱い）
#   151431 : 東京ディズニーセレブレーションホテル

# =================================


API_URL = "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watch_state.json")


def now():
    return datetime.now().strftime("%H:%M:%S")


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  （状態の保存に失敗: {e}）")


def send_ntfy(title, message, click_url=None, priority=3, tags=None):
    """ntfy にプッシュ通知を送る（JSON形式なので日本語タイトルもOK）"""
    payload = {
        "topic": NTFY_TOPIC,
        "title": title,
        "message": message,
        "priority": priority,
    }
    if click_url:
        payload["click"] = click_url
    if tags:
        payload["tags"] = tags
    try:
        requests.post("https://ntfy.sh", json=payload, timeout=15)
    except Exception as e:
        print(f"  ⚠ 通知の送信に失敗: {e}")


_debug_dump_count = 0


def _debug_dump(resp, reason, limit=3):
    """API調査用の一時ログ。最初のlimit回だけステータスと本文先頭を出力する。"""
    global _debug_dump_count
    if _debug_dump_count >= limit:
        return
    _debug_dump_count += 1
    print(f"  🔍 DEBUG[{_debug_dump_count}] {reason} / HTTP {resp.status_code}")
    print(f"  🔍 DEBUG[{_debug_dump_count}] body先頭400字: {resp.text[:400]}")


def check_watch(watch):
    """
    1件分の空室をチェックする。
    戻り値: (available, info, url)
      available: True=空きあり / False=空きなし / None=通信エラー（今回スキップ）
      info: (hotel_name, rooms_text)   ※available=True のときのみ
      url:  予約ページURL               ※available=True のときのみ
    """
    params = {
        "applicationId": RAKUTEN_APP_ID,
        "accessKey": RAKUTEN_ACCESS_KEY,
        "format": "json",
        "checkinDate": watch["checkin"],
        "checkoutDate": watch["checkout"],
        "hotelNo": watch["hotelNo"],
        "adultNum": watch.get("adultNum", 2),
    }
    headers = {
        "Origin": RAKUTEN_APP_URL,
        "Referer": RAKUTEN_APP_URL,
    }
    try:
        resp = requests.get(API_URL, params=params, headers=headers, timeout=20)
    except Exception as e:
        print(f"  ⚠ 通信エラー: {e}")
        return None, None, None

    if resp.status_code != 200:
        # 「空きなし」を意味する not_found だけを空きなし扱いにし、
        # それ以外のエラーは警告を出してスキップ（状態を変えない）。
        try:
            body = resp.json()
        except Exception:
            body = {}
        err = body.get("error", "")
        err_desc = body.get("error_description", "")
        # 2026年新APIのエラー形式 {"errors": {"errorCode":..., "errorMessage":...}} にも対応
        new_err = body.get("errors") if isinstance(body.get("errors"), dict) else {}
        err_msg = new_err.get("errorMessage", "")

        if resp.status_code == 404 and (err == "not_found" or "NOT_FOUND" in err_msg.upper()):
            return False, None, None  # 空きなし

        if err_msg == "HTTP_REFERRER_NOT_ALLOWED":
            print(f"  ⚠ Refererが楽天に拒否されました（送信値: {RAKUTEN_APP_URL}）。"
                  "楽天アプリ設定の「許可されたWebサイト」に載っている楽天ドメインに合わせてください")
        elif err in ("wrong_parameter", "not_authorized", "application_not_found"):
            print(f"  ⚠ 設定エラーかも（{err}: {err_desc}）→ アプリIDや hotelNo を確認してください")
        else:
            print(f"  ⚠ APIエラー（HTTP {resp.status_code}: {err or err_msg or resp.text[:120]}）")
        return None, None, None  # エラーはスキップ（空きなしとは区別する）

    try:
        data = resp.json()
    except Exception:
        _debug_dump(resp, "JSONパース失敗")
        return False, None, None

    hotels = data.get("hotels")
    if not hotels:
        _debug_dump(resp, f"200だがhotelsなし（トップレベルキー: {list(data.keys())}）")
        return False, None, None  # 空きなし

    # ここまで来たら空きあり。部屋情報を取り出す。
    hotel_name = ""
    hotel_url = None
    lines = []
    for wrapper in hotels:
        parts = wrapper.get("hotel", []) if isinstance(wrapper, dict) else []
        if not parts:
            continue
        basic = parts[0].get("hotelBasicInfo", {}) if isinstance(parts[0], dict) else {}
        hotel_name = basic.get("hotelName") or hotel_name
        hotel_url = basic.get("hotelInformationUrl") or hotel_url
        for p in parts[1:]:
            room_info = p.get("roomInfo") if isinstance(p, dict) else None
            if not room_info:
                continue
            room_basic = {}
            charge = {}
            for ri in room_info:
                if not isinstance(ri, dict):
                    continue
                if "roomBasicInfo" in ri:
                    room_basic = ri["roomBasicInfo"]
                if "dailyCharge" in ri:
                    charge = ri["dailyCharge"]
            room_name = room_basic.get("roomName", "")
            plan_name = room_basic.get("planName", "")
            total = charge.get("total")
            price = f"¥{total:,}" if isinstance(total, int) else ""
            label = " / ".join([x for x in (room_name, plan_name) if x])
            line = f"・{label} {price}".rstrip()
            if line and line not in lines:
                lines.append(line)

    rooms_text = "\n".join(lines[:8]) if lines else "空室あり"
    return True, (hotel_name, rooms_text), hotel_url


def run_pass(state):
    """全watchを1回チェックして通知。state（前回までの空室状況）を更新して返す。"""
    for watch in WATCHES:
        key = watch["label"]
        available, info, url = check_watch(watch)

        if available is None:
            continue  # 通信エラーは今回スキップ（状態は変えない）

        was_available = state.get(key, False)

        if available and not was_available:
            hotel_name, rooms_text = info
            title = f"🏨 空室発見: {hotel_name or key}"
            message = (
                f"{key}\n"
                f"{watch['checkin']} → {watch['checkout']}（大人{watch.get('adultNum', 2)}名）\n\n"
                f"{rooms_text}"
            )
            send_ntfy(title, message, click_url=url, priority=5, tags=["hotel", "tada"])
            print(f"[{now()}] 🔔 空室あり→通知送信: {key}")
        elif available and was_available:
            print(f"[{now()}] ○ 継続して空室あり: {key}")
        else:
            print(f"[{now()}] × 空きなし: {key}")

        state[key] = available
        time.sleep(1)  # 楽天APIに優しく（呼び出しの間隔を少し空ける）

    return state


def main():
    # --- 設定チェック ---
    if "貼る" in RAKUTEN_APP_ID or not RAKUTEN_APP_ID.strip():
        print("⚠ RAKUTEN_APP_ID が未設定です。設定欄に入れるか、環境変数で渡してください。")
        sys.exit(1)
    if "貼る" in RAKUTEN_ACCESS_KEY or not RAKUTEN_ACCESS_KEY.strip():
        print("⚠ RAKUTEN_ACCESS_KEY が未設定です。設定欄に入れるか、環境変数で渡してください。")
        sys.exit(1)
    if "CHANGE-ME" in NTFY_TOPIC:
        print("⚠ NTFY_TOPIC を自分専用の文字列に変えてください（推測されにくいものに）。")
        sys.exit(1)

    once = "--once" in sys.argv
    state = load_state()

    if once:
        # クラウド（GitHub Actions等）用：1回だけ実行して終了
        run_pass(state)
        save_state(state)
        return

    # ローカル用：起動通知 → ずっとループ
    print("=" * 52)
    print(" ディズニーホテル空室通知（楽天トラベル版）を開始")
    print(f"  チェック間隔: {CHECK_INTERVAL_SEC}秒 / 監視数: {len(WATCHES)}件")
    print(f"  ntfyトピック: {NTFY_TOPIC}")
    print("=" * 52)
    print(" 止めるときは Ctrl + C\n")

    send_ntfy(
        title="✅ 監視スタート",
        message=f"ディズニーホテルの空室監視を開始しました（{len(WATCHES)}件）。\n"
                f"この通知が見えていれば設定はOKです。",
        priority=3,
        tags=["white_check_mark"],
    )

    while True:
        run_pass(state)
        save_state(state)
        print(f"[{now()}] --- 次のチェックまで {CHECK_INTERVAL_SEC}秒待機 ---")
        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n監視を終了しました。おつかれさまでした。")
