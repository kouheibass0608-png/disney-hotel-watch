#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ディズニーホテル 空室通知（公式サイト版・ブラウザ方式）/ PCローカル実行専用
============================================================================
東京ディズニーリゾート公式予約サイト（reserve.tokyodisneyresort.jp）を
本物のブラウザエンジン（Playwright/Chromium）で開いて空き情報を取得し、
空室が出たら ntfy でスマホに通知します。

※ 公式サイトはPythonからの直接アクセス（requests）を家庭用回線でも
   ブロックするため、本物のブラウザを使う方式にしています。
※ クラウド（GitHub Actions等）のIPもブロックされるため、自宅PCで動かします。

準備（最初に一度だけ）:
        ~/disney-venv/bin/pip install playwright requests
        ~/disney-venv/bin/python3 -m playwright install chromium

使い方（2ステップ）:
  ステップ1) まず「調査モード」で公式サイトの応答を確認します:
        ~/disney-venv/bin/python3 disney_hotel_watch_official.py --probe
     → 画面に出た内容（probe_result.txt にも保存されます）を
        開発者に貼ってください。空室判定ロジックを確定します。
     ※ うまくいかない時は --probe --show を付けると実際のブラウザ画面が
        表示されるので、何が起きているか目で確認できます。

  ステップ2) 通常実行（監視ループ・スリープ防止つき）:
        ~/disney-venv/bin/python3 disney_hotel_watch_official.py

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
from urllib.parse import urlencode

try:
    import requests  # ntfy通知の送信に使用
except ImportError:
    print("requests が見つかりません。ターミナルで次を実行してください：")
    print("    ~/disney-venv/bin/pip install requests")
    sys.exit(1)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright が見つかりません。ターミナルで次の2つを実行してください：")
    print("    ~/disney-venv/bin/pip install playwright")
    print("    ~/disney-venv/bin/python3 -m playwright install chromium")
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
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watch_state_official.json")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# --show を付けるとブラウザ画面を表示しながら動く（動作確認用）
HEADLESS = "--show" not in sys.argv


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


# ---------- ブラウザで公式サイトを開く ----------

def build_list_url(watch):
    params = {
        "useDate": watch["useDate"],
        "stayingDays": str(watch.get("stayingDays", 1)),
        "adultNum": str(watch.get("adultNum", 2)),
        "childNum": "0",
        "roomsNum": "1",
        "searchHotelCD": watch.get("hotelCD", ""),
        "displayType": "hotel-search",
    }
    return LIST_URL + "?" + urlencode(params)


def new_context(p):
    browser = p.chromium.launch(headless=HEADLESS)
    context = browser.new_context(
        locale="ja-JP",
        timezone_id="Asia/Tokyo",
        viewport={"width": 1280, "height": 900},
    )
    return browser, context


def fetch_page(context, watch, wait_ms=15000):
    """
    公式サイトの検索結果ページをブラウザで開く。
    戻り値: (title, html, api_responses)
      api_responses: [(url, status, body先頭2000字), ...]  /hotel/api/ のXHRのみ
    """
    page = context.new_page()
    captured = []

    def on_response(resp):
        if "/hotel/api/" in resp.url:
            try:
                body = resp.text()[:2000]
            except Exception:
                body = "(body取得失敗)"
            captured.append((resp.url, resp.status, body))

    page.on("response", on_response)
    try:
        page.goto(build_list_url(watch), timeout=60000,
                  wait_until="domcontentloaded")
        page.wait_for_timeout(wait_ms)  # XHRや描画を待つ
        title = page.title()
        html = page.content()
    finally:
        page.close()
    return title, html, captured


def check_watch(context, watch):
    """
    1件分の空室をチェックする。
    戻り値: (available, detail_text, url)
      available: True=空きあり / False=空きなし / None=エラー・判定不能（スキップ）
    ※ 空室判定ロジックは --probe の結果を見て確定します。
       それまでは暫定判定（判定不能時はHTMLを保存して知らせる）です。
    """
    try:
        title, html, api_responses = fetch_page(context, watch)
    except Exception as e:
        print(f"  ⚠ ページ取得エラー: {e}")
        return None, None, None

    text = html

    # --- 暫定の空室判定（probe結果で更新予定） ---
    no_vacancy_markers = ["満室", "空室はありません", "該当するプランがありません",
                          "ご希望の条件では見つかりません"]
    for marker in no_vacancy_markers:
        if marker in text:
            return False, None, None

    if re.search(r"/hotel/(detail|room|plan)/", text) or "予約する" in text:
        return True, "空室の可能性があります（公式サイトで確認してください）", build_list_url(watch)

    # 判定できない → HTMLを保存して知らせる
    dump_path = os.path.join(SCRIPT_DIR, "last_unknown_page.html")
    try:
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  ❓ 空室判定できないページでした（タイトル: {title}）。"
              f"{dump_path} を開発者に共有してください")
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
    out(" 公式サイト調査モード（--probe / ブラウザ方式）")
    out(f" 実行時刻: {datetime.now().isoformat()}")
    out("=" * 60)

    watch = WATCHES[0]
    out(f"\n[1] 検索結果ページをブラウザで開く: {watch['label']}")
    out(f"    URL: {build_list_url(watch)}")

    with sync_playwright() as p:
        browser, context = new_context(p)
        try:
            title, html, api_responses = fetch_page(context, watch, wait_ms=20000)
            compact = " ".join(html.split())
            out(f"  ページタイトル: {title}")
            out(f"  HTML先頭800字: {compact[:800]}")
            out()

            cds = sorted(set(re.findall(r"searchHotelCD=([A-Z0-9]+)", html)))
            out(f"  HTML内の searchHotelCD 一覧: {cds}")
            for kw in ["満室", "空室", "予約する", "検索結果", "円"]:
                out(f"  文言「{kw}」: {'あり' if kw in html else 'なし'}")

            out(f"\n[2] ページ表示中に飛んだ /hotel/api/ の通信: {len(api_responses)}件")
            for url, status, body in api_responses[:6]:
                out("-" * 60)
                out(f"  URL: {url}")
                out(f"  HTTP {status}")
                out(f"  body先頭1000字: {' '.join(body.split())[:1000]}")

            # HTML全体も保存しておく（判定ロジック作成用）
            html_path = os.path.join(SCRIPT_DIR, "probe_page.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            out(f"\n  → ページ全体を保存: {html_path}")
        except Exception as e:
            out(f"  ✗ 取得失敗: {e}")
            out("  ※ --probe --show を付けて再実行すると、ブラウザ画面が見えるので")
            out("     何が起きているか（認証画面・混雑ページ等）を確認できます。")
        finally:
            browser.close()

    out("\n" + "=" * 60)
    out(" 調査おわり。この出力（probe_result.txt）を開発者に貼ってください。")
    out("=" * 60)

    result_path = os.path.join(SCRIPT_DIR, "probe_result.txt")
    try:
        with open(result_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"\n→ 結果を保存しました: {result_path}")
    except Exception as e:
        print(f"（結果ファイルの保存に失敗: {e}）")


# ---------- メイン ----------

def run_pass(context, state):
    for watch in WATCHES:
        key = watch["label"]
        available, detail, url = check_watch(context, watch)

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
        with sync_playwright() as p:
            browser, context = new_context(p)
            try:
                while True:
                    run_pass(context, state)
                    save_state(state)
                    print(f"[{now()}] --- 次のチェックまで {CHECK_INTERVAL_SEC}秒待機 ---")
                    time.sleep(CHECK_INTERVAL_SEC)
            finally:
                browser.close()
    finally:
        release_sleep()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n監視を終了しました。おつかれさまでした。")
