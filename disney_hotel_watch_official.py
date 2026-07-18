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

使い方:
  通常実行（監視ループ・スリープ防止つき）:
        ~/disney-venv/bin/python3 disney_hotel_watch_official.py
     ※ 実行するとChromeのウィンドウが自動で開きます（公式サイトが
        裏側モードのブラウザをブロックするため、見えるモードが標準です）。
        監視中はウィンドウを閉じないでください。

  調査モード（うまく動かない時の診断用）:
        ~/disney-venv/bin/python3 disney_hotel_watch_official.py --probe
     → probe_result.txt / probe_screenshot.png に状況が保存されます。

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

# チェック間隔（秒）。短くしすぎると機械的アクセスと判定されて
# 一時ブロック（Access Denied）される。15分以上を推奨。
CHECK_INTERVAL_SEC = 900

# 監視したい条件のリスト。
#   hotelCD  : 公式サイトのホテルコード（下の一覧参照。--probe で実際の値を確認できます）
#   useDate  : チェックイン日 YYYYMMDD
#   stayingDays / adultNum : 泊数・大人人数
WATCHES = [
    {
        "label": "ミラコスタ 9/27〜9/28 1泊 大人2名",
        "hotelCD": "DHM",
        "useDate": "20260927",
        "stayingDays": 1,
        "adultNum": 2,
    },
    # ↓ 増やす場合はこの形式でコピーして追加
    # {
    #     "label": "セレブレーションホテル 9/15〜 1泊 大人2名",
    #     "hotelCD": "DCH",
    #     "useDate": "20260915",
    #     "stayingDays": 1,
    #     "adultNum": 2,
    # },
]

# 【ホテルコード一覧】（公式サイトのホテル選択ドロップダウンで確認済みの正式コード）
#   TDH : 東京ディズニーランドホテル
#   DHM : 東京ディズニーシー・ホテルミラコスタ
#   DAH : ディズニーアンバサダーホテル
#   TSH : 東京ディズニーリゾート・トイ・ストーリーホテル
#   FSH : 東京ディズニーシー・ファンタジースプリングスホテル
#   DCH : 東京ディズニーセレブレーションホテル（※TCHではない）

# ホテル検索ページで操作するときの目印（画面上のホテル名）
HOTEL_NAMES = {
    "TDH": "ディズニーランドホテル",
    "DHM": "ホテルミラコスタ",
    "DAH": "アンバサダーホテル",
    "TSH": "トイ・ストーリーホテル",
    "FSH": "ファンタジースプリングスホテル",
    "DCH": "セレブレーションホテル",
}

# =================================


BASE = "https://reserve.tokyodisneyresort.jp"
LIST_URL = BASE + "/hotel/list/"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watch_state_official.json")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 公式サイトは「裏側モード（ヘッドレス）」のブラウザを検知してブロックするため、
# 画面が見える通常モードで動かすのが標準。実行するとChromeのウィンドウが開きます。
# （--headless を付けると裏側モードになるが、現状はブロックされて動かない）
HEADLESS = "--headless" in sys.argv


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


PROFILE_DIR = os.path.join(SCRIPT_DIR, "browser_profile")


def new_context(p):
    """
    Cookie等を保存する「永続プロファイル」でブラウザを起動する。
    毎回まっさらなブラウザで順番待ちに並び直すと機械的アクセスと
    判定されやすいため、人間が同じブラウザを使い続けるのと同じ状態にする。
    （browser_profile フォルダが自動で作られます。消さないでください）
    """
    context = p.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=HEADLESS,
        locale="ja-JP",
        timezone_id="Asia/Tokyo",
        viewport={"width": 1280, "height": 900},
    )
    return context


def _is_denied(html):
    """Akamaiの一時ブロック（Access Denied）ページかどうか。"""
    return ("errors.edgesuite.net" in html) or ("<title>Access Denied</title>" in html)


def safe_content(page, retries=6, interval_ms=2000):
    """ページ遷移中でも安全にHTMLを取り出す（遷移中なら少し待って再試行）。"""
    last_error = None
    for _ in range(retries):
        try:
            return page.content()
        except Exception as e:
            last_error = e
            page.wait_for_timeout(interval_ms)
    raise last_error


def _is_queue_page(html):
    # 待機画面の判定。通過後の本物のページにも queue-it 関連の部品が残ることが
    # あるため、待機画面テンプレート固有のマーカーだけを見る。
    return ('queue-it_log' in html) or ("順番にご案内" in html and "混雑して" in html)


def _wait_out_queue(page, queue_wait_s):
    """混雑待機画面（Queue-it）が消えるまで待つ。経過秒数を返す。"""
    queue_start = time.time()
    deadline = queue_start + queue_wait_s
    while time.time() < deadline:
        if not _is_queue_page(safe_content(page)):
            return int(time.time() - queue_start)
        page.wait_for_timeout(3000)
    return int(time.time() - queue_start)


def fetch_page(context, watch, queue_wait_s=300):
    """
    公式サイトの検索結果ページをブラウザで開く。
    ・Queue-it（混雑待機画面）が出たら通過するまで最大 queue_wait_s 秒待つ
    ・待機通過後に別ページ（トップ等）へ飛ばされていたら、検索URLへ入り直す
    ・検索結果らしき内容（金額・満室表示・API通信）が出るまで最大90秒待つ
    戻り値: dict(title, url, html, text, apis, queue_seconds)
      apis: [(url, status, body先頭2000字), ...]  XHR/fetch通信のうち公式サイト宛のもの
    """
    target_url = build_list_url(watch)
    page = context.new_page()
    captured = []

    def on_response(resp):
        try:
            req = resp.request
            if req.resource_type not in ("xhr", "fetch"):
                return
            if "tokyodisneyresort.jp" not in resp.url:
                return
            try:
                body = resp.text()[:2000]
            except Exception:
                body = "(body取得失敗)"
            captured.append((resp.url, resp.status, body))
        except Exception:
            pass

    page.on("response", on_response)
    try:
        page.goto(target_url, timeout=90000, wait_until="domcontentloaded")
        queue_seconds = _wait_out_queue(page, queue_wait_s)

        # 待機通過後、検索結果URLに居なければ入り直す（2回目は待機をスキップできる想定）
        if "/hotel/list" not in page.url:
            page.goto(target_url, timeout=90000, wait_until="domcontentloaded")
            queue_seconds += _wait_out_queue(page, 60)

        def body_text():
            try:
                return page.evaluate("document.body ? document.body.innerText : ''")
            except Exception:
                return ""

        def wait_for_results(max_s):
            """部屋一覧らしき内容（金額・満室表示）が描画されるまで待つ。"""
            ready_markers = ("満室", "円", "空室")
            deadline = time.time() + max_s
            while time.time() < deadline:
                t = body_text()
                if any(m in t for m in ready_markers):
                    return True
                page.wait_for_timeout(3000)
            return False

        # アクセス拒否（一時ブロック）ページなら以降の待ちや操作は不要
        clicked = "操作不要（最初から結果表示）"
        card_html = ""
        if _is_denied(safe_content(page)):
            pass  # そのまま記録に進む（check_watch側で拒否として扱う）
        # 結果が自動表示されない場合は、検索フォームのホテル選択ドロップダウン
        # （select#hotelCdSelecter）で対象ホテルを選び、「再検索」を押して進む。
        elif not wait_for_results(45):
            clicked = None
            hotel_cd = watch.get("hotelCD", "")

            # フォームをJavaScriptで直接操作する（カスタムUIでも確実に効くように）
            try:
                outcome = page.evaluate(
                    """(cd) => {
                        const sel = document.getElementById('hotelCdSelecter');
                        if (!sel) return 'select無し';
                        sel.value = cd;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        const els = Array.from(
                            document.querySelectorAll('a,button,input,p,span,div'));
                        const btn = els.find(
                            e => ((e.value || e.textContent) || '').trim() === '再検索');
                        if (!btn) return 'ボタン無し';
                        btn.click();
                        return 'OK';
                    }""",
                    hotel_cd)
                if outcome == "OK":
                    clicked = f"ホテル選択（{hotel_cd}）＋再検索"
                else:
                    clicked = None
                    card_html = f"フォーム操作の結果: {outcome}"
            except Exception as e:
                card_html = f"フォーム操作でエラー: {e}"

            if clicked:
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=30000)
                except Exception:
                    pass
                queue_seconds += _wait_out_queue(page, 60)  # 操作後に再度待機画面が出る場合
            # フォーム操作の成否にかかわらず、描画完了をもう一度待つ
            # （描画が遅れているだけのケースで早すぎる記録をしないため）
            wait_for_results(90)

        page.wait_for_timeout(5000)  # 最後の描画待ち
        title = page.title()
        html = safe_content(page)
        try:
            text = page.evaluate("document.body ? document.body.innerText : ''")
        except Exception:
            text = ""
        final_url = page.url
        try:
            page.screenshot(path=os.path.join(SCRIPT_DIR, "probe_screenshot.png"),
                            full_page=False)
        except Exception:
            pass
    finally:
        page.close()
    return {
        "title": title,
        "url": final_url,
        "html": html,
        "text": text,
        "apis": captured,
        "queue_seconds": queue_seconds,
        "clicked": clicked,
        "card_html": card_html,
    }


def check_watch(context, watch):
    """
    1件分の空室をチェックする。
    戻り値: (available, detail_text, url)
      available: True=空きあり / False=空きなし / None=エラー・判定不能（スキップ）
    ※ 空室判定ロジックは --probe の結果を見て確定します。
       それまでは暫定判定（判定不能時はHTMLを保存して知らせる）です。
    """
    try:
        result = fetch_page(context, watch)
        if result["queue_seconds"]:
            print(f"  （混雑待機画面を {result['queue_seconds']}秒で通過）")
    except Exception as e:
        print(f"  ⚠ ページ取得エラー: {e}")
        return None, None, None

    title = result["title"]
    html = result["html"]
    text = result["text"] or html

    if _is_denied(html):
        print("  ⛔ 公式サイトにアクセス拒否されました（機械的アクセスと判定された一時ブロック）。"
              "今回はスキップします。続く場合は1時間ほど止めてから再開してください")
        return None, None, None

    # --- 空室判定（実際の部屋一覧ページで確認済みのロジック） ---
    # 予約できる部屋には「総額：xx,xxx円」の金額表示が出る。
    # 全て満室の日は「○月○日は全室満室です」と表示され、金額は一切出ない。
    prices = re.findall(r"総額：([\d,]+)円", text)
    if prices:
        nums = sorted(int(p.replace(",", "")) for p in prices)
        detail = (f"予約可能な部屋: {len(nums)}件\n"
                  f"総額 ¥{nums[0]:,} 〜 ¥{nums[-1]:,}")
        return True, detail, build_list_url(watch)

    no_vacancy_markers = ["全室満室", "満室", "空室はありません", "該当するプランがありません",
                          "ご希望の条件では見つかりません", "ご用意できる客室はありません"]
    for marker in no_vacancy_markers:
        if marker in text:
            return False, None, None

    # 金額なし・満室表示もなし・予約ボタンだけある、という珍しい状態
    if "予約する" in text:
        return True, "予約可能な部屋があります（公式サイトで確認してください）", build_list_url(watch)

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
        context = new_context(p)
        try:
            result = fetch_page(context, watch)
            html = result["html"]
            text = result["text"]
            queue_seconds = result["queue_seconds"]
            out(f"  混雑待機画面の通過: {queue_seconds}秒" if queue_seconds else "  混雑待機画面: なし（即表示）")
            out(f"  クリック操作: {result.get('clicked') or '✗ クリック対象が見つからなかった'}")
            if result.get("card_html"):
                out(f"  ホテルカードのHTML構造（先頭1500字）: {' '.join(result['card_html'].split())[:1500]}")
            out(f"  最終的なURL: {result['url']}")
            out(f"  ページタイトル: {result['title']}")
            out(f"  画面の文字（先頭1500字）: {' '.join((text or '').split())[:1500]}")
            out()

            hrefs = []
            for h in re.findall(r'href="([^"]*hotel[^"]*)"', html):
                if h not in hrefs:
                    hrefs.append(h)
            out(f"  hotelを含むリンク（先頭20件）:")
            for h in hrefs[:20]:
                out(f"    {h}")

            cds = sorted(set(re.findall(r"searchHotelCD=([A-Z0-9]+)", html)))
            out(f"  HTML内の searchHotelCD 一覧: {cds}")
            for kw in ["満室", "空室", "予約する", "検索結果", "円"]:
                out(f"  文言「{kw}」: {'あり' if kw in html else 'なし'}")

            out(f"\n[2] ページ表示中の公式サイト宛XHR/fetch通信: {len(result['apis'])}件")
            for url, status, body in result["apis"][:10]:
                out("-" * 60)
                out(f"  URL: {url}")
                out(f"  HTTP {status}")
                out(f"  body先頭800字: {' '.join(body.split())[:800]}")

            # HTML全体とスクリーンショットも保存しておく（判定ロジック作成用）
            html_path = os.path.join(SCRIPT_DIR, "probe_page.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            out(f"\n  → ページ全体を保存: {html_path}")
            out(f"  → 画面の写真を保存: {os.path.join(SCRIPT_DIR, 'probe_screenshot.png')}")
        except Exception as e:
            out(f"  ✗ 取得失敗: {e}")
            out("  ※ 開いたブラウザ画面に何が表示されていたか（待機画面・エラー等）を")
            out("     開発者に伝えてください。")
        finally:
            context.close()

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
            context = new_context(p)
            try:
                while True:
                    run_pass(context, state)
                    save_state(state)
                    print(f"[{now()}] --- 次のチェックまで {CHECK_INTERVAL_SEC}秒待機 ---")
                    time.sleep(CHECK_INTERVAL_SEC)
            finally:
                context.close()
    finally:
        release_sleep()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n監視を終了しました。おつかれさまでした。")
