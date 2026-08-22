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
from datetime import datetime

OUTPUT_PATH = "data/warehouse_stock.json"

# ------------------------------------------------------------------
# 알려진 공급사/브랜드 목록. 창고 시스템의 "브랜드" 테이블 컬럼이 일부 항목에서
# 내부 관리코드(날짜형 숫자, 예: "2022021602110001")를 담고 있어서 신뢰할 수
# 없다는 게 확인됐다. 그래서 품목명 텍스트에서 이 목록에 있는 이름을 직접
# 찾는 방식을 우선으로 쓰고, 못 찾으면 브랜드 컬럼값(단, 숫자코드처럼 보이면
# 버림)으로 폴백한다.
# 새 공급사가 추가되면 이 목록에 넣어주면 된다.
# ------------------------------------------------------------------
KNOWN_SUPPLIERS = [
    "ACC", "AGROSUPER", "SEARA", "PATEL", "ALEJANDRO", "SMITHFIELD",
    "AVINYO", "SEABOARD", "RIVASAM", "OLYMEL", "THOMAS", "MAFRIGES",
    "INCARLOPSA", "RODRIGUEZ", "TEYS", "ASSA", "NBP", "FRIBIN",
    "COSTABRAVA", "IOWA", "VJG7", "VJG", "MARCHER", "HKSCAN", "GATINE",
    "ECT", "DEWAELE", "AFFCO", "DARLING DOWNS", "FAENADORA SUPER",
    "KAMOURASKA", "EXC", "NATIONAL", "LORIENTE", "GREENIA", "LORFOOD",
    "PERDIGAO", "SADIA", "DUMECO", "LAR", "QAF",
]
# 길이가 짧아서 오탐 위험이 큰 것들은 단어경계 정규식으로만 매칭 (A/S 등)
_SUPPLIER_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in sorted(KNOWN_SUPPLIERS, key=len, reverse=True)) + r")\b"
)


def _looks_like_code(text: str) -> bool:
    """'2022021602110001' 같은 날짜형 내부관리코드처럼 보이면 True."""
    digits = sum(ch.isdigit() for ch in text)
    return len(text) >= 8 and digits >= len(text) * 0.8


def extract_supplier(품목명: str, raw_brand: str) -> str:
    """품목명에서 알려진 공급사명을 우선 찾고, 없으면 브랜드 컬럼값(코드성 문자열 제외)으로 폴백."""
    match = _SUPPLIER_PATTERN.search(품목명 or "")
    if match:
        return match.group(1)
    raw_brand = (raw_brand or "").strip()
    if raw_brand and not _looks_like_code(raw_brand):
        return raw_brand
    return "기타/미상"

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
        "id_env": "NWILL_SINWOO_LIVESTOCK_UNCLEARED_ID",
        "pw_env": "NWILL_SINWOO_LIVESTOCK_UNCLEARED_PW",
        "계정용도": "미통관(축산물)",
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


def _to_number(text: str):
    """
    "1,272" / "23,010.31" / "18.09KG" 처럼 천단위 콤마나 단위(KG 등)가 붙은
    셀 텍스트에서 숫자만 뽑아 변환. 빈 값/파싱 불가능한 값은 0으로 처리
    (대시보드가 숫자 필드로 합산하기 때문에 문자열이 섞이면 NaN이 발생한다).
    """
    if text is None:
        return 0
    cleaned = str(text).replace(",", "").strip()
    if not cleaned:
        return 0
    match = re.match(r"-?\d+(\.\d+)?", cleaned)
    if not match:
        return 0
    val = float(match.group())
    return int(val) if val.is_integer() else val


# 대시보드가 숫자로 계산/정렬하는 필드들 (콤마 제거 + 숫자 변환 필요)
NUMERIC_FIELDS = ["재고수량", "중량_kg", "단위중량", "허용수량", "적재수량", "PLT수량"]


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
        raw_brand = record.pop("브랜드", "")
        record["공급사"] = extract_supplier(record["품목명"], raw_brand)
        record["저장위치"] = record.pop("저장구역", "")
        record["중량_kg"] = record.pop("중량", "")
        # 유통기한 컬럼명이 창고마다 다름 (유통기한 / 소비기한)
        record["유통기한"] = record.pop("소비기한", None) or record.pop("유통기한", "")

        pass_raw = record.pop("통관구분", "").strip()
        record["통관상태"] = pass_raw if pass_raw else None  # 후처리 단계에서 계정 기본값 적용

        for field in NUMERIC_FIELDS:
            if field in record:
                record[field] = _to_number(record[field])

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


def classify_animal(품목명: str) -> str:
    """
    축종(소/돼지/닭/염소) 추정. index.html의 classifyAnimal()과 동일한 규칙
    (품목명 텍스트 키워드 기반 추정치, 완벽하지 않을 수 있음).
    """
    name = 품목명 or ""
    if re.search(r"염소", name):
        return "염소"
    if re.match(r"^\(?돈", name):
        return "돼지"
    if re.search(r"항정살|삼겹살|가브리|갈매기살|시트밸리|등갈비|전지|후지|돈가스", name):
        return "돼지"
    if re.match(r"^\(?닭", name) or re.match(r"^\(?계", name) or re.search(r"계육|장각", name):
        return "닭"
    if re.match(r"^\(?우", name):
        return "소"
    if re.search(r"갈비|양지|차돌|채끝|척갈비|볼라전각|빽립|설도|우둔|홍두깨|토시|안창|제비추리|아롱사태|업진|알목심|스페어립", name):
        return "소"
    return "미분류"


HISTORY_PATH = "data/warehouse_history.json"


def append_daily_history(all_rows: list) -> None:
    """
    창고별/축종별 하루치 요약(재고수량/중량_kg 합계)을 별도의 가벼운 이력
    파일에 누적한다. 원본 데이터(행 단위 전체)를 매일 그대로 쌓으면 1년 뒤
    수만~십만 행이 되어 느려질 수 있어서, 요약값만 남기는 방식으로 설계.
    같은 날짜에 여러 번 실행되면 그날 기록을 덮어써서 중복 누적을 막는다.
    """
    today = datetime.now().strftime("%Y-%m-%d")

    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = {"기록": []}

    history["기록"] = [h for h in history["기록"] if h.get("날짜") != today]

    totals = {}
    for r in all_rows:
        key = (r.get("창고명"), classify_animal(r.get("품목명", "")))
        bucket = totals.setdefault(key, {"재고수량": 0, "중량_kg": 0})
        bucket["재고수량"] += r.get("재고수량", 0) or 0
        bucket["중량_kg"] += r.get("중량_kg", 0) or 0

    for (창고명, 축종), vals in totals.items():
        history["기록"].append({
            "날짜": today,
            "창고명": 창고명,
            "축종": 축종,
            "재고수량": vals["재고수량"],
            "중량_kg": round(vals["중량_kg"], 2),
        })

    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_existing() -> dict:
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"수집시각": None, "총건수": 0, "데이터": []}
