# -*- coding: utf-8 -*-
"""
창고 재고 데이터 자동 수집 스크립트
엔윌정보기술(nwill.net) 기반 물류정보서비스 로그인 + 재고조회(셀분리) 크롤링

현재 구현된 계정:
  - 대청냉장 미통관 (DAECHEONG_UNCLEARED)

TODO (계정 준비/HTML 구조 확인 후 순차 추가):
  - 대청냉장 통관 (기존 수동 수집 로직을 이 구조로 이관 필요)
  - 신우냉장 통관 / 미통관
  - 한라 통관 / 미통관

사용 방법:
  python scripts/fetch_all_warehouses.py

환경변수 (GitHub Secrets):
  NWILL_DAECHEONG_UNCLEARED_ID / NWILL_DAECHEONG_UNCLEARED_PW
  (추후 창고 추가 시 WAREHOUSE_CONFIGS 에 항목 추가 + 동일 규칙으로 Secrets 등록)
"""

import json
import os
import re
import sys
from datetime import datetime

import requests
from bs4 import BeautifulSoup

OUTPUT_PATH = "data/warehouse_stock.json"

# 재고조회(셀분리) 테이블의 컬럼 순서 (24개, thead 기준)
TABLE_COLUMNS = [
    "사업부", "관리번호", "품목코드", "수탁품", "위탁자품목코드", "규격",
    "단위중량", "단위", "LOT번호", "BL번호", "식별번호", "브랜드",
    "저장위치", "재고수량", "중량_kg", "허용수량", "적재수량", "PLT수량",
    "유통기한", "제조일자", "통관상태_원본", "통관일자", "상태", "비고",
]

# ------------------------------------------------------------------
# 창고별 접속 설정
# 계정마다 로그인 시 통관/미통관 여부가 자동으로 라벨링되는 게 아니라,
# 응답 테이블의 '통관구분' 컬럼 실제값을 그대로 신뢰하도록 설계했다.
# (창고 직원이 수동으로 옮겨서 계정과 실제상태가 다를 수 있기 때문)
# ------------------------------------------------------------------
WAREHOUSE_CONFIGS = [
    {
        "창고명": "대청냉장",
        "base_url": "http://211.239.173.91:8080/dchdst",
        "login_url": "http://211.239.173.91:8080/dchdst/login.do",
        "wms_cd": "1B6",
        "co_stel": "031-761-3002",
        "scustcd": "23120",
        "scmdept": "00",
        "id_env": "NWILL_DAECHEONG_UNCLEARED_ID",
        "pw_env": "NWILL_DAECHEONG_UNCLEARED_PW",
        "계정용도": "미통관",  # 참고용 라벨. 실제 통관상태는 테이블 컬럼값 사용.
    },
    {
        "창고명": "신우냉장",
        "base_url": "http://nwill.net:8080/swdst",
        "login_url": "http://nwill.net:8080/swdst/login.do?nav_num=00",
        "wms_cd": "104",
        "co_stel": "031-764-8107",
        # scustcd는 대청과 다를 수 있음 (미확인 - 로그인 후 페이지에서 확인 필요)
        "scustcd": "",
        "scmdept": "00",
        "id_env": "NWILL_SINWOO_UNCLEARED_ID",
        "pw_env": "NWILL_SINWOO_UNCLEARED_PW",
        "계정용도": "미통관(계육)",  # 실제로는 계육(닭) 관련 미통관 계정으로 확인됨
    },
    {
        "창고명": "한라냉장",
        "base_url": "http://211.239.173.91:8080/hlgdst",
        "login_url": "http://211.239.173.91:8080/hlgdst/login.do",
        "wms_cd": "176",
        "co_stel": "031-8027-4716~7",
        # scustcd 미확인 - 로그인 후 페이지에서 확인 필요
        "scustcd": "",
        "scmdept": "00",
        "id_env": "NWILL_HALLA_CLEARED_ID",
        "pw_env": "NWILL_HALLA_CLEARED_PW",
        "계정용도": "통관",
    },
    {
        "창고명": "한라냉장",
        "base_url": "http://211.239.173.91:8080/hlgdst",
        "login_url": "http://211.239.173.91:8080/hlgdst/login.do",
        "wms_cd": "176",
        "co_stel": "031-8027-4716~7",
        "scustcd": "",
        "scmdept": "00",
        "id_env": "NWILL_HALLA_UNCLEARED_ID",
        "pw_env": "NWILL_HALLA_UNCLEARED_PW",
        "계정용도": "미통관",
    },
    {
        "창고명": "대청냉장",
        "base_url": "http://211.239.173.91:8080/dchdst",
        "login_url": "http://211.239.173.91:8080/dchdst/login.do",
        "wms_cd": "1B6",
        "co_stel": "031-761-3002",
        "scustcd": "23120",
        "scmdept": "00",
        "id_env": "NWILL_DAECHEONG_CLEARED_ID",
        "pw_env": "NWILL_DAECHEONG_CLEARED_PW",
        "계정용도": "통관",
    },
    {
        "창고명": "신우냉장",
        "base_url": "http://nwill.net:8080/swdst",
        "login_url": "http://nwill.net:8080/swdst/login.do?nav_num=00",
        "wms_cd": "104",
        "co_stel": "031-764-8107",
        "scustcd": "",
        "scmdept": "00",
        "id_env": "NWILL_SINWOO_LIVESTOCK_CLEARED_ID",
        "pw_env": "NWILL_SINWOO_LIVESTOCK_CLEARED_PW",
        "계정용도": "통관(축산물)",
    },
    {
        "창고명": "신우냉장",
        "base_url": "http://nwill.net:8080/swdst",
        "login_url": "http://nwill.net:8080/swdst/login.do?nav_num=00",
        "wms_cd": "104",
        "co_stel": "031-764-8107",
        "scustcd": "",
        "scmdept": "00",
        "id_env": "NWILL_SINWOO_POULTRY_CLEARED_ID",
        "pw_env": "NWILL_SINWOO_POULTRY_CLEARED_PW",
        "계정용도": "통관(계육)",
    },
    {
        "창고명": "삼진1냉장",
        "base_url": "http://nwill.net:8080/sjn1dst",
        "login_url": "http://nwill.net:8080/sjn1dst/login.do",
        "wms_cd": "",  # playwright 방식은 사이트가 자동으로 채워주는 hidden 값을 그대로 씀 (불필요)
        "co_stel": "",
        "scustcd": "",
        "scmdept": "00",
        "id_env": "NWILL_SAMJIN1_ID",
        "pw_env": "NWILL_SAMJIN1_PW",
        "계정용도": "전체",  # 통관/미통관 구분 계정 없이 단일 계정
    },
    {
        "창고명": "삼진2냉장",
        "base_url": "http://nwill.net:8080/sjn2dst",
        "login_url": "http://nwill.net:8080/sjn2dst/login.do",
        "wms_cd": "",
        "co_stel": "",
        "scustcd": "",
        "scmdept": "00",
        "id_env": "NWILL_SAMJIN2_ID",
        "pw_env": "NWILL_SAMJIN2_PW",
        "계정용도": "전체",
    },
    {
        "창고명": "오로라씨에스",
        "base_url": "http://211.239.173.90:8080/aurdst",
        "login_url": "http://211.239.173.90:8080/aurdst/login.do",
        "wms_cd": "",
        "co_stel": "",
        "scustcd": "",
        "scmdept": "00",
        "id_env": "NWILL_AURORA_ID",
        "pw_env": "NWILL_AURORA_PW",
        "계정용도": "전체",
    },
    # 강동냉장: 점검중이라 보류
]


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def login(session: requests.Session, cfg: dict) -> None:
    """로그인 수행. 실패 시 예외 발생."""
    login_id = os.environ.get(cfg["id_env"])
    login_pw = os.environ.get(cfg["pw_env"])
    if not login_id or not login_pw:
        raise RuntimeError(
            f"[{cfg['창고명']}/{cfg['계정용도']}] 환경변수 {cfg['id_env']} / {cfg['pw_env']} 가 설정되지 않았습니다. "
            "GitHub Secrets 등록 여부를 확인하세요."
        )

    # 세션 없이 바로 login.do 를 호출하면 404가 나는 서버가 있어서,
    # 브라우저처럼 먼저 메인 페이지를 한 번 방문해 세션 쿠키를 확보한다.
    session.headers.update(HEADERS)
    base = cfg["base_url"].rstrip("/")
    warmup_resp = session.get(f"{base}/", timeout=30, headers={"Referer": base + "/"})
    warmup_resp.raise_for_status()

    payload = {
        "id": login_id,
        "pw": login_pw,
        "wms_cd": cfg["wms_cd"],
        "co_stel": cfg["co_stel"],
    }
    # Referer는 "로그인 폼이 실제로 렌더링된 그 URL"이어야 한다 (루트 경로가 아님).
    # 브라우저 devtools로 캡처한 실제 요청 기준으로 맞춤.
    resp = session.post(
        cfg["login_url"], data=payload, timeout=30,
        headers={
            "Referer": cfg["login_url"],
            "Origin": base,
            "Cache-Control": "max-age=0",
            "Upgrade-Insecure-Requests": "1",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.7"
            ),
        },
    )
    resp.raise_for_status()

    # 로그인 성공 시 메인/메뉴 화면에는 반드시 "logout.do" 링크가 존재한다.
    # (로그인 실패 시엔 로그인 폼이 다시 뜨거나 alert 스크립트만 내려옴)
    if "logout.do" not in resp.text:
        raise RuntimeError(
            f"[{cfg['창고명']}/{cfg['계정용도']}] 로그인 실패로 추정됩니다 (logout.do 링크 없음). "
            "id/pw 또는 wms_cd/co_stel 값을 확인하세요."
        )


def get_hidden_search_fields(session: requests.Session, cfg: dict) -> dict:
    """
    재고조회(셀분리) 검색폼을 GET으로 먼저 받아서, 서버가 로그인 계정에 맞춰
    자동으로 채워놓은 hidden 필드(scustcd, scmdept, swms_cd, nav_num)를 그대로 읽어온다.
    창고마다 계정 고유값이 달라서 하드코딩하지 않기 위함.
    """
    resp = session.get(f"{cfg['base_url']}/rtv_stock02.do?nav_num=0107", timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    form = soup.select_one("form[action='rtv_stock02.do']")
    hidden = {}
    if form:
        for inp in form.select("input[type=hidden]"):
            name = inp.get("name")
            if name:
                hidden[name] = inp.get("value", "")

    # 혹시 폼을 못 찾으면 설정에 있는 값으로 폴백 (구조가 다를 가능성 대비)
    hidden.setdefault("scustcd", cfg.get("scustcd", ""))
    hidden.setdefault("scmdept", cfg.get("scmdept", "00"))
    hidden.setdefault("swms_cd", "")
    hidden.setdefault("nav_num", "0107")
    return hidden


def fetch_stock_html(session: requests.Session, cfg: dict) -> str:
    """재고조회(셀분리) 조회 실행, 원본 HTML 반환."""
    hidden_fields = get_hidden_search_fields(session, cfg)

    today = datetime.now().strftime("%Y%m%d")
    payload = {
        **hidden_fields,
        "won_pmcode": "",
        "pmname": "",
        "blno": "",
        "dt": today,
        "pass_fg": "*",  # 전체 조회 후 실제 통관구분 컬럼값을 신뢰
    }
    resp = session.post(
        f"{cfg['base_url']}/rtv_stock02.do?nav_num=0107", data=payload, timeout=30
    )
    resp.raise_for_status()
    return resp.text


def parse_stock_table(html: str, 창고명: str) -> list:
    """
    재고조회(셀분리) 결과 테이블 파싱.

    창고마다 컬럼 개수/순서/이름이 다르다 (예: 신우는 19개, 대청/한라는 23~24개,
    유통기한 컬럼명도 신우는 "유통기한", 대청/한라는 "소비기한"). 그래서 고정된
    컬럼 순서를 가정하지 않고, 매번 <thead>에서 실제 헤더 텍스트를 읽어와
    그 이름 그대로 딕셔너리 키로 사용한 뒤 공통 스키마로 매핑한다.
    """
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

        # 헤더 개수와 셀 개수가 다르면 짧은 쪽 기준으로 zip (일부 셀 누락 방지용 안전장치)
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


def fetch_one(cfg: dict) -> list:
    session = requests.Session()
    login(session, cfg)
    html = fetch_stock_html(session, cfg)
    rows = parse_stock_table(html, cfg["창고명"])
    apply_default_customs_status(rows, cfg)
    print(f"[{cfg['창고명']}/{cfg['계정용도']}] {len(rows)}건 수집")
    return rows


def load_existing() -> dict:
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"수집시각": None, "총건수": 0, "데이터": []}


def main():
    existing = load_existing()
    existing_rows = existing.get("데이터", [])

    all_new_rows = []
    had_error = False

    for cfg in WAREHOUSE_CONFIGS:
        try:
            all_new_rows.extend(fetch_one(cfg))
        except Exception as e:  # noqa: BLE001
            had_error = True
            print(f"[오류] {cfg['창고명']}/{cfg['계정용도']} 수집 실패: {e}", file=sys.stderr)

    if not all_new_rows and had_error:
        # 전부 실패하면 기존 파일을 덮어쓰지 않고 종료 (데이터 유실 방지)
        print("모든 신규 창고 수집이 실패하여 기존 데이터를 유지합니다.", file=sys.stderr)
        sys.exit(1)

    # 버그 수정: "창고명"만 기준으로 지우면, 같은 창고의 다른 통관상태(예: 대청냉장/통관)까지
    # 통째로 사라진다. 이번에 실제로 수집된 (창고명, 통관상태) 조합만 정확히 교체한다.
    replace_keys = {(r.get("창고명"), r.get("통관상태")) for r in all_new_rows}
    kept_rows = [
        r for r in existing_rows
        if (r.get("창고명"), r.get("통관상태")) not in replace_keys
    ]

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
