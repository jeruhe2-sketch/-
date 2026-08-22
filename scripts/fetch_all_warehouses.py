# -*- coding: utf-8 -*-
"""
창고 재고 데이터 공용 설정/파싱 모듈.

실제 수집 실행은 scripts/fetch_all_warehouses_playwright.py 에서 한다.
(이 파일에 원래 있던 requests 기반 로그인 방식은 이 사이트들 앞단의 무언가가
브라우저가 아닌 요청을 계속 막아서 - 헤더를 브라우저와 완전히 동일하게
맞춰도 404 - 결국 포기했고, 실제 Chromium을 띄우는 Playwright 방식으로
교체되어 정상 작동 중이다. 그 삽질 과정은 git log 참고.)

이 파일은 두 스크립트가 공유하는 것만 남겨뒀다:
  - WAREHOUSE_CONFIGS: 창고/계정 목록
  - parse_stock_table: 재고조회(셀분리) 결과 HTML 파싱 (헤더 기반, 창고별
    컬럼 개수/이름 차이에 대응)
  - apply_default_customs_status: 통관상태 빈값일 때 계정 기본값 적용
  - load_existing / OUTPUT_PATH: 기존 데이터 파일 로드
"""

import json
import os
import re

OUTPUT_PATH = "data/warehouse_stock.json"

# ------------------------------------------------------------------
# 창고별 접속 설정
# 계정마다 로그인 시 통관/미통관 여부가 자동으로 라벨링되는 게 아니라,
# 응답 테이블의 '통관구분' 컬럼 실제값을 그대로 신뢰하도록 설계했다.
# (창고 직원이 수동으로 옮겨서 계정과 실제상태가 다를 수 있기 때문)
#
# wms_cd/co_stel/scustcd 필드는 requests 기반 방식에서나 필요했던 값이라
# Playwright 방식(실제 브라우저가 폼을 그대로 제출)에서는 안 써도 되지만,
# 참고 기록 차원에서 알고 있는 값은 남겨뒀다.
# ------------------------------------------------------------------
WAREHOUSE_CONFIGS = [
    {
        "창고명": "대청냉장",
        "base_url": "http://211.239.173.91:8080/dchdst",
        "id_env": "NWILL_DAECHEONG_UNCLEARED_ID",
        "pw_env": "NWILL_DAECHEONG_UNCLEARED_PW",
        "계정용도": "미통관",
    },
    {
        "창고명": "신우냉장",
        "base_url": "http://nwill.net:8080/swdst",
        "id_env": "NWILL_SINWOO_UNCLEARED_ID",
        "pw_env": "NWILL_SINWOO_UNCLEARED_PW",
        "계정용도": "미통관(계육)",  # 실제로는 계육(닭) 관련 미통관 계정
    },
    {
        "창고명": "한라냉장",
        "base_url": "http://211.239.173.91:8080/hlgdst",
        "id_env": "NWILL_HALLA_CLEARED_ID",
        "pw_env": "NWILL_HALLA_CLEARED_PW",
        "계정용도": "통관",
    },
    {
        "창고명": "한라냉장",
        "base_url": "http://211.239.173.91:8080/hlgdst",
        "id_env": "NWILL_HALLA_UNCLEARED_ID",
        "pw_env": "NWILL_HALLA_UNCLEARED_PW",
        "계정용도": "미통관",
    },
    {
        "창고명": "대청냉장",
        "base_url": "http://211.239.173.91:8080/dchdst",
        "id_env": "NWILL_DAECHEONG_CLEARED_ID",
        "pw_env": "NWILL_DAECHEONG_CLEARED_PW",
        "계정용도": "통관",
    },
    {
        "창고명": "신우냉장",
        "base_url": "http://nwill.net:8080/swdst",
        "id_env": "NWILL_SINWOO_LIVESTOCK_CLEARED_ID",
        "pw_env": "NWILL_SINWOO_LIVESTOCK_CLEARED_PW",
        "계정용도": "통관(축산물)",
    },
    {
        "창고명": "신우냉장",
        "base_url": "http://nwill.net:8080/swdst",
        "id_env": "NWILL_SINWOO_POULTRY_CLEARED_ID",
        "pw_env": "NWILL_SINWOO_POULTRY_CLEARED_PW",
        "계정용도": "통관(계육)",
    },
    {
        "창고명": "삼진1냉장",
        "base_url": "http://nwill.net:8080/sjn1dst",
        "id_env": "NWILL_SAMJIN1_ID",
        "pw_env": "NWILL_SAMJIN1_PW",
        "계정용도": "전체",  # 통관/미통관 구분 계정 없이 단일 계정
    },
    {
        "창고명": "삼진2냉장",
        "base_url": "http://nwill.net:8080/sjn2dst",
        "id_env": "NWILL_SAMJIN2_ID",
        "pw_env": "NWILL_SAMJIN2_PW",
        "계정용도": "전체",
    },
    {
        "창고명": "오로라씨에스",
        "base_url": "http://211.239.173.90:8080/aurdst",
        "id_env": "NWILL_AURORA_ID",
        "pw_env": "NWILL_AURORA_PW",
        "계정용도": "전체",
    },
    # 강동냉장: 점검중이라 보류
]


def parse_stock_table(html: str, 창고명: str) -> list:
    """
    재고조회(셀분리) 결과 테이블 파싱.

    창고마다 컬럼 개수/순서/이름이 다르다 (예: 신우는 19개, 대청/한라는 23~24개,
    유통기한 컬럼명도 신우는 "유통기한", 대청/한라는 "소비기한"). 그래서 고정된
    컬럼 순서를 가정하지 않고, 매번 <thead>에서 실제 헤더 텍스트를 읽어와
    그 이름 그대로 딕셔너리 키로 사용한 뒤 공통 스키마로 매핑한다.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.dataTables-example")
    if table is None:
        raise RuntimeError("재고조회 결과 테이블을 찾지 못했습니다 (페이지 구조 변경 가능성).")

    thead = table.find("thead")
    if thead is None:
        raise RuntimeError("재고조회 결과 테이블에 헤더(thead)가 없습니다.")
    headers = [th.get_text(strip=True) for th in thead.find_all("th")]

    rows = []
    tbody = table.find("tbody")
    if tbody is None:
        return rows

    for tr in tbody.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]

        # "조회된 결과가 없습니다" 같은 안내행(칸 수가 헤더보다 훨씬 적음) 스킵
        if len(cells) < len(headers) * 0.5:
            continue

        record = dict(zip(headers, cells))

        record["창고명"] = 창고명
        record["품목명"] = record.pop("수탁품", "")
        brand = record.pop("브랜드", "").strip()
        if not brand:
            # 일부 창고(한라 등)는 브랜드 컬럼이 비어있고 품목명 텍스트 안에만 있음.
            # 지금은 ACC만 우선 대응 (다른 브랜드는 필요해지면 목록 추가).
            if re.search(r"\bACC\b", record["품목명"]):
                brand = "ACC"
        record["공급사"] = brand or "기타/미상"
        record["저장위치"] = record.pop("저장구역", "")
        record["중량_kg"] = record.pop("중량", "")
        # 유통기한 컬럼명이 창고마다 다름 (유통기한 / 소비기한)
        record["유통기한"] = record.pop("소비기한", None) or record.pop("유통기한", "")

        pass_raw = record.pop("통관구분", "").strip()
        record["통관상태"] = pass_raw if pass_raw else None  # 후처리 단계에서 계정 기본값 적용

        rows.append(record)

    return rows


def apply_default_customs_status(rows: list, cfg: dict) -> None:
    """
    통관구분 값이 비어있는 행에 한해 계정 기본값 적용.

    cfg["계정용도"]는 "통관(축산물)", "미통관(계육)", "전체" 처럼 참고용 라벨이라
    괄호 설명을 그대로 쓰면 대시보드가 인식 못하는 이상한 값이 들어간다.
    "통관"/"미통관"만 실제 기본값으로 쓰고, 그 외("전체" 등)는 빈 값 그대로 둔다.
    """
    label = cfg["계정용도"]
    base_label = re.sub(r"\(.*\)", "", label).strip()
    default_status = base_label if base_label in ("통관", "미통관") else None

    for r in rows:
        if not r.get("통관상태"):
            r["통관상태"] = default_status


def load_existing() -> dict:
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"수집시각": None, "총건수": 0, "데이터": []}
