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

# ntfyの自分専用トピック名。環境変数 NTFY_TOPIC があればそれを使う（クラウド用）。
NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or "disney-hotel-watch-CHANGE-ME-x7k2"

# ローカルでループする場合の確認間隔（秒）。180 = 3分。
CHECK_INTERVAL_SEC = 180

# 監視したい条件のリスト。いくつでも追加できる。
WATCHES = [
    {
        "label": "ミラコスタ 9/16→9/17 大人2名",
        "hotelNo": "74733",        # 楽天のホテル番号（下の一覧参照）
        "checkin": "2026-09-16",   # チェックイン   YYYY-MM-DD
        "checkout": "2026-09-17",  # チェックアウト YYYY-MM-DD
        "adultNum": 2,             # 大人の人数
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


API_URL = "https://app.rakuten.co.jp/services/api/Travel/VacantHotelSearch/20170426"
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
        "format": "json",
        "checkinDate": watch["checkin"],
        "checkoutDate": watch["checkout"],
        "hotelNo": watch["hotelNo"],
        "adultNum": watch.get("adultNum", 2),
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=20)
    except Exception as e:
        print(f"  ⚠ 通信エラー: {e}")
        return None, None, None

    if resp.status_code != 200:
        # 設定ミス系のエラーだけ知らせる。not_found 等は「空きなし」として扱う。
        try:
            err = resp.json().get("error", "")
        except Exception:
            err = ""
        if err in ("wrong_parameter", "not_authorized", "application_not_found"):
            print(f"  ⚠ 設定エラーかも（{err}）→ アプリIDや hotelNo を確認してください")
        return False, None, None

    try:
        data = resp.json()
    except Exception:
        return False, None, None

    hotels = data.get("hotels")
    if not hotels:
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
