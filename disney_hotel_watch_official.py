#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ディズニーホテル 空室通知（公式サイト版）/ PCローカル実行専用
==============================================================
東京ディズニーリゾート公式予約サイト（reserve.tokyodisneyresort.jp）から
空き情報を取得し、空室が出たら ntfy でスマホに通知します。

※ 公式サイトはクラウド（GitHub Actionsなど）のIPをブロックするため、
   このスクリプトは自宅のPCで動かす前提です。

使い方（2ステップ）:
  ステップ1) まず「調査モード」で公式サイトの応答を確認します:
        python3 disney_hotel_watch_official.py --probe
     → 画面に出た内容（probe_result.txt にも保存されます）を
        開発者に貼ってください。空室判定ロジックを確定します。

  ステップ2) 通常実行（監視ループ・スリープ防止つき）:
        python3 disney_hotel_watch_official.py

スリープ防止:
  実行中は自動でPCのスリープを防ぎます（Windows / Mac 対応）。
  ※ ノートPCのフタを閉じるとスリープするので、フタは開けたままに。
"""

import ctypes
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    print("requests が見つかりません。ターミナルで次を実行してください：")
    print("    pip3 install requests")
    sys.exit(1)


# ============ 【設定】 ============

# ntfyの自分専用トピック名。環境変数 NTFY_TOPIC があればそれを使う。
NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or "disney-hotel-watch-CHANGE-ME-x7k2"

# チェック間隔（秒）。公式サイトに負荷をかけないよう5分以上を推奨。
CHECK_INTERVAL_SEC = 300

# 監視したい条件のリスト。
#   hotelCD  : 公式サイトのホテルコード（下の一覧参照。--probe で実際の値を確認できます）
#   useDate  : チェックイン日 YYYYMMDD
#   stayingDays / adultNum : 泊数・大人人数
WATCHES = [
    {
        "label": "セレブレーションホテル 9/15〜 1泊 大人2名",
        "hotelCD": "TCH",
        "useDate": "20260915",
        "stayingDays": 1,
        "adultNum": 2,
    },
    # ↓ 増やす場合はこの形式でコピーして追加
    # {
    #     "label": "ミラコスタ 9/19〜 1泊 大人2名",
    #     "hotelCD": "DHM",
    #     "useDate": "20260919",
    #     "stayingDays": 1,
    #     "adultNum": 2,
    # },
]

# 【ホテルコードの目安】（公式サイトURLの searchHotelCD より。--probe で要確認）
#   TDH : 東京ディズニーランドホテル
#   DHM : 東京ディズニーシー・ホテルミラコスタ
#   DAH : ディズニーアンバサダーホテル
#   TSH : トイ・ストーリーホテル
#   FSH : ファンタジースプリングスホテル
#   TCH : 東京ディズニーセレブレーションホテル

# =================================


BASE = "https://reserve.tokyodisneyresort.jp"
LIST_URL = BASE + "/hotel/list/"
STOCK_API_URL = BASE + "/hotel/api/queryHotelPriceStock/"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watch_state_official.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Accept-Language": "ja,en;q=0.8",
})


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
    """ntfy にプッシュ通知を送る"""
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


# ---------- スリープ防止（Windows / Mac 対応） ----------

def prevent_sleep():
    """実行中PCがスリープしないようにする。戻り値は解除用の関数。"""
    system = platform.system()
    if system == "Windows":
        ES_CONTINUOUS = 0x80000000
        ES_SYSTEM_REQUIRED = 0x00000001
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            print("💤 スリープ防止: ON（Windows）")

            def release():
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            return release
        except Exception as e:
            print(f"💤 スリープ防止の設定に失敗: {e}")
            return lambda: None
    if system == "Darwin":
        try:
            proc = subprocess.Popen(
                ["caffeinate", "-i", "-w", str(os.getpid())])
            print("💤 スリープ防止: ON（Mac / caffeinate）")

            def release():
                try:
                    proc.terminate()
                except Exception:
                    pass
            return release
        except Exception as e:
            print(f"💤 スリープ防止の設定に失敗: {e}")
            return lambda: None
    print("💤 このOSではスリープ防止を自動設定できません。OS設定でスリープをオフにしてください。")
    return lambda: None


# ---------- 公式サイトへのアクセス ----------

def fetch_hotel_list(watch):
    """ホテル一覧ページ（HTML）を取得する。"""
    params = {
        "useDate": watch["useDate"],
        "stayingDays": str(watch.get("stayingDays", 1)),
        "adultNum": str(watch.get("adultNum", 2)),
        "childNum": "0",
        "roomsNum": "1",
        "searchHotelCD": watch.get("hotelCD", ""),
        "displayType": "hotel-search",
    }
    return session.get(LIST_URL, params=params, timeout=30)


def check_watch(watch):
    """
    1件分の空室をチェックする。
    戻り値: (available, detail_text, url)
      available: True=空きあり / False=空きなし / None=エラー・判定不能（スキップ）
    ※ 空室判定ロジックは --probe の結果を見て確定します。
       それまでは暫定判定（判定不能時はHTMLを保存して知らせる）です。
    """
    try:
        resp = fetch_hotel_list(watch)
    except Exception as e:
        print(f"  ⚠ 通信エラー: {e}")
        return None, None, None

    if resp.status_code != 200:
        print(f"  ⚠ HTTP {resp.status_code} が返りました（ブロックの可能性）")
        return None, None, None

    html = resp.text

    # --- 暫定の空室判定（probe結果で更新予定） ---
    # 満室・空きなしを示す典型的な文言
    no_vacancy_markers = ["満室", "空室はありません", "該当するプランがありません", "ご希望の条件では見つかりません"]
    for marker in no_vacancy_markers:
        if marker in html:
            return False, None, None

    # 部屋詳細・予約リンクらしきものがあれば空きありとみなす
    if re.search(r"/hotel/(detail|room|plan)/", html) or "予約する" in html:
        page_url = resp.url
        return True, "空室の可能性があります（公式サイトで確認してください）", page_url

    # 判定できない → HTMLを保存して知らせる
    dump_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "last_unknown_page.html")
    try:
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  ❓ 空室判定できないページでした。{dump_path} を開発者に共有してください")
    except Exception:
        pass
    return None, None, None


# ---------- 調査モード ----------

def run_probe():
    """公式サイトの応答を調査して、結果を画面と probe_result.txt に出す。"""
    lines = []

    def out(text=""):
        print(text)
        lines.append(str(text))

    out("=" * 60)
    out(" 公式サイト調査モード（--probe）")
    out(f" 実行時刻: {datetime.now().isoformat()}")
    out("=" * 60)

    watch = WATCHES[0]
    out(f"\n[1] ホテル一覧ページの取得: {watch['label']}")
    try:
        resp = fetch_hotel_list(watch)
        out(f"  HTTP {resp.status_code} / content-type: {resp.headers.get('content-type', '')}")
        html = resp.text
        compact = " ".join(html.split())
        out(f"  本文先頭600字: {compact[:600]}")

        # ホテルコードらしきものを列挙
        cds = sorted(set(re.findall(r"searchHotelCD=([A-Z0-9]+)", html)))
        out(f"  HTML内の searchHotelCD 一覧: {cds}")
        # API らしきURLを列挙
        apis = sorted(set(re.findall(r"/hotel/api/[A-Za-z0-9_/]+", html)))
        out(f"  HTML内の /hotel/api/ URL一覧: {apis}")
        # 満室・空室関連の文言を探す
        for kw in ["満室", "空室", "予約する", "検索結果"]:
            out(f"  文言「{kw}」: {'あり' if kw in html else 'なし'}")
    except Exception as e:
        out(f"  ✗ 取得失敗: {e}")

    out(f"\n[2] 空室API（queryHotelPriceStock）へのPOST")
    payload = {
        "useDate": watch["useDate"],
        "stayingDays": str(watch.get("stayingDays", 1)),
        "adultNum": str(watch.get("adultNum", 2)),
        "childNum": "0",
        "roomsNum": "1",
    }
    try:
        resp = session.post(
            STOCK_API_URL, json=payload,
            headers={"Referer": LIST_URL, "Origin": BASE,
                     "Accept": "application/json, text/plain, */*"},
            timeout=30)
        out(f"  HTTP {resp.status_code} / content-type: {resp.headers.get('content-type', '')}")
        compact = " ".join(resp.text.split())
        out(f"  本文先頭800字: {compact[:800]}")
    except Exception as e:
        out(f"  ✗ 取得失敗: {e}")

    out("\n" + "=" * 60)
    out(" 調査おわり。この出力（probe_result.txt）を開発者に貼ってください。")
    out("=" * 60)

    result_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "probe_result.txt")
    try:
        with open(result_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"\n→ 結果を保存しました: {result_path}")
    except Exception as e:
        print(f"（結果ファイルの保存に失敗: {e}）")


# ---------- メイン ----------

def run_pass(state):
    for watch in WATCHES:
        key = watch["label"]
        available, detail, url = check_watch(watch)

        if available is None:
            continue  # エラー・判定不能はスキップ（状態を変えない）

        was_available = state.get(key, False)

        if available and not was_available:
            title = f"🏨 空室発見: {key}"
            message = f"{key}\n{detail or ''}"
            send_ntfy(title, message, click_url=url, priority=5, tags=["hotel", "tada"])
            print(f"[{now()}] 🔔 空室あり→通知送信: {key}")
        elif available:
            print(f"[{now()}] ○ 継続して空室あり: {key}")
        else:
            print(f"[{now()}] × 空きなし: {key}")

        state[key] = available
        time.sleep(3)  # 公式サイトに優しく

    return state


def main():
    if "--probe" in sys.argv:
        run_probe()
        return

    if "CHANGE-ME" in NTFY_TOPIC:
        print("⚠ NTFY_TOPIC を自分専用の文字列に変えてください。")
        sys.exit(1)

    release_sleep = prevent_sleep()
    state = load_state()

    print("=" * 52)
    print(" ディズニーホテル空室通知（公式サイト版）を開始")
    print(f"  チェック間隔: {CHECK_INTERVAL_SEC}秒 / 監視数: {len(WATCHES)}件")
    print(f"  ntfyトピック: {NTFY_TOPIC}")
    print("=" * 52)
    print(" 止めるときは Ctrl + C\n")

    send_ntfy(
        title="✅ 監視スタート（公式サイト版）",
        message=f"ディズニーホテルの空室監視を開始しました（{len(WATCHES)}件）。",
        priority=3,
        tags=["white_check_mark"],
    )

    try:
        while True:
            run_pass(state)
            save_state(state)
            print(f"[{now()}] --- 次のチェックまで {CHECK_INTERVAL_SEC}秒待機 ---")
            time.sleep(CHECK_INTERVAL_SEC)
    finally:
        release_sleep()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n監視を終了しました。おつかれさまでした。")
