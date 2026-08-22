# -*- coding: utf-8 -*-
"""
창고 재고 데이터 자동 수집 스크립트 - Playwright(실제 Chromium) 버전

requests 라이브러리로 직접 login.do 를 호출하는 방식(fetch_all_warehouses.py)이
브라우저에서는 되고 requests/curl로는 계속 404가 나서(원인 특정 못함),
실제 브라우저 엔진을 그대로 띄워서 로그인하는 방식으로 우회한다.

사전 준비 (최초 1회):
  pip install playwright beautifulsoup4
  playwright install chromium

사용 방법 (기존과 동일하게 환경변수 설정 후):
  python scripts/fetch_all_warehouses_playwright.py
"""

import json
import os
import sys
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from fetch_all_warehouses import (
    WAREHOUSE_CONFIGS,
    TABLE_COLUMNS,
    OUTPUT_PATH,
    parse_stock_table,
    apply_default_customs_status,
    load_existing,
)


def fetch_one_with_browser(playwright, cfg: dict) -> list:
    login_id = os.environ.get(cfg["id_env"])
    login_pw = os.environ.get(cfg["pw_env"])
    if not login_id or not login_pw:
        raise RuntimeError(
            f"[{cfg['창고명']}/{cfg['계정용도']}] 환경변수 {cfg['id_env']} / {cfg['pw_env']} 가 설정되지 않았습니다."
        )

    browser = playwright.chromium.launch(headless=True)
    try:
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )

        # 1) 메인 페이지 접속 -> login.do 로 리다이렉트됨
        page.goto(cfg["base_url"] + "/", wait_until="networkidle", timeout=30000)

        # 2) 로그인 폼 채우고 제출 (실제 사람이 누르는 것과 동일)
        page.fill("input[name='id']", login_id)
        page.fill("input[name='pw']", login_pw)
        with page.expect_navigation(wait_until="networkidle", timeout=30000):
            page.click("button[type='submit']")

        # 로그인 성공 확인 (좌측 메뉴/logout 링크 존재 여부)
        if "logout.do" not in page.content():
            raise RuntimeError(
                f"[{cfg['창고명']}/{cfg['계정용도']}] 로그인 실패로 추정됩니다 (logout.do 없음). "
                "id/pw를 확인하세요."
            )

        # 3) 재고조회(셀분리) 화면으로 이동해서 hidden 필드 읽고, 전체조회 실행
        page.goto(
            f"{cfg['base_url']}/rtv_stock02.do?nav_num=0107",
            wait_until="networkidle",
            timeout=30000,
        )

        today = datetime.now().strftime("%Y%m%d")
        # 통관구분을 "전체"로 설정. 재고기준일자(dt)는 사이트에 따라 readonly인 경우가 있는데,
        # 그럴 때는 이미 오늘 날짜로 기본 채워져 있으므로 건드리지 않고 넘어간다.
        page.select_option("select[name='pass_fg']", "*")
        date_input = page.locator("input[name='dt']")
        is_readonly = date_input.get_attribute("readonly") is not None
        if not is_readonly:
            date_input.fill("")
            date_input.fill(today)

        with page.expect_navigation(wait_until="networkidle", timeout=30000):
            page.click("button[type='submit']:has-text('조회')")

        html = page.content()
        rows = parse_stock_table(html, cfg["창고명"])
        if not rows:
            debug_path = f"debug_{cfg['창고명']}_{cfg['계정용도']}.html"
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(
                f"  -> 0건 파싱됨. 원본 페이지를 {debug_path} 에 저장했으니 "
                "이 파일을 보내주시면 표 구조를 확인할 수 있습니다.",
                file=sys.stderr,
            )
        return rows
    finally:
        browser.close()


def main():
    existing = load_existing()
    existing_rows = existing.get("데이터", [])

    all_new_rows = []
    had_error = False

    with sync_playwright() as p:
        for cfg in WAREHOUSE_CONFIGS:
            try:
                rows = fetch_one_with_browser(p, cfg)
                apply_default_customs_status(rows, cfg)
                print(f"[{cfg['창고명']}/{cfg['계정용도']}] {len(rows)}건 수집")
                all_new_rows.extend(rows)
            except Exception as e:  # noqa: BLE001
                had_error = True
                print(f"[오류] {cfg['창고명']}/{cfg['계정용도']} 수집 실패: {e}", file=sys.stderr)

    if not all_new_rows and had_error:
        print("모든 신규 창고 수집이 실패하여 기존 데이터를 유지합니다.", file=sys.stderr)
        sys.exit(1)

    collected_warehouse_names = {cfg["창고명"] for cfg in WAREHOUSE_CONFIGS}
    kept_rows = [r for r in existing_rows if r.get("창고명") not in collected_warehouse_names]
    merged_rows = kept_rows + all_new_rows

    output = {
        "수집시각": datetime.now().isoformat(),
        "총건수": len(merged_rows),
        "데이터": merged_rows,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"완료: 총 {len(merged_rows)}건 저장 ({OUTPUT_PATH})")


if __name__ == "__main__":
    main()
