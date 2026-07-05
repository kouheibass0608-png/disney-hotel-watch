#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
東京ディズニーリゾート公式予約サイトの調査用スクリプト・ブラウザ版（一時的なもの）
==================================================================================
requests直叩きは全てタイムアウトでブロックされたため、
本物のブラウザ（Playwright/Chromium）経由でアクセスできるかを確認する。
ページ本体の応答と、裏で飛ぶ空室API（/hotel/api/）の応答をキャプチャしてログに出す。
"""

from playwright.sync_api import sync_playwright

LIST_URL = ("https://reserve.tokyodisneyresort.jp/hotel/list/"
            "?useDate=20260915&stayingDays=1&adultNum=2&childNum=0"
            "&roomsNum=1&displayType=hotel-search")

api_responses = []


def on_response(resp):
    if "/hotel/api/" in resp.url:
        api_responses.append(resp)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        locale="ja-JP",
        timezone_id="Asia/Tokyo",
        viewport={"width": 1280, "height": 900},
    )
    page = context.new_page()
    page.on("response", on_response)

    try:
        page.goto(LIST_URL, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(20000)  # XHRが飛ぶのを待つ
        print("=" * 60)
        print("ページタイトル:", page.title())
        html = " ".join(page.content().split())
        print("HTML先頭1000字:", html[:1000])
        print()
        print(f"キャプチャした /hotel/api/ 応答: {len(api_responses)}件")
        for r in api_responses[:5]:
            print("-" * 60)
            print("URL:", r.url)
            print("HTTP", r.status)
            try:
                body = " ".join(r.text().split())
                print("body先頭800字:", body[:800])
            except Exception as e:
                print("body取得失敗:", e)
    except Exception as e:
        print("アクセス失敗:", e)

    browser.close()

print("調査おわり（ブラウザ版）")
