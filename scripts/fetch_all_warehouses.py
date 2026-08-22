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
        "wms_cd": "1B6",
        "co_stel": "031-761-3002",
        "scustcd": "23120",
        "scmdept": "00",
        "id_env": "NWILL_DAECHEONG_UNCLEARED_ID",
        "pw_env": "NWILL_DAECHEONG_UNCLEARED_PW",
        "계정용도": "미통관",  # 참고용 라벨. 실제 통관상태는 테이블 컬럼값 사용.
    },
    # 아래는 준비되는 대로 추가 (동일 스키마, base_url/wms_cd/co_stel/scustcd만 교체)
    # {
    #     "창고명": "대청냉장",
    #     "base_url": "http://211.239.173.91:8080/dchdst",
    #     "wms_cd": "1B6",
    #     "co_stel": "031-761-3002",
    #     "scustcd": "23120",
    #     "scmdept": "00",
    #     "id_env": "NWILL_DAECHEONG_CLEARED_ID",
    #     "pw_env": "NWILL_DAECHEONG_CLEARED_PW",
    #     "계정용도": "통관",
    # },
]


def login(session: requests.Session, cfg: dict) -> None:
    """로그인 수행. 실패 시 예외 발생."""
    login_id = os.environ.get(cfg["id_env"])
    login_pw = os.environ.get(cfg["pw_env"])
    if not login_id or not login_pw:
        raise RuntimeError(
            f"[{cfg['창고명']}/{cfg['계정용도']}] 환경변수 {cfg['id_env']} / {cfg['pw_env']} 가 설정되지 않았습니다. "
            "GitHub Secrets 등록 여부를 확인하세요."
        )

    payload = {
        "id": login_id,
        "pw": login_pw,
        "wms_cd": cfg["wms_cd"],
        "co_stel": cfg["co_stel"],
    }
    resp = session.post(f"{cfg['base_url']}/login.do", data=payload, timeout=30)
    resp.raise_for_status()

    # 로그인 성공 시 메인/메뉴 화면에는 반드시 "logout.do" 링크가 존재한다.
    # (로그인 실패 시엔 로그인 폼이 다시 뜨거나 alert 스크립트만 내려옴)
    if "logout.do" not in resp.text:
        raise RuntimeError(
            f"[{cfg['창고명']}/{cfg['계정용도']}] 로그인 실패로 추정됩니다 (logout.do 링크 없음). "
            "id/pw 또는 wms_cd/co_stel 값을 확인하세요."
        )


def fetch_stock_html(session: requests.Session, cfg: dict) -> str:
    """재고조회(셀분리) 조회 실행, 원본 HTML 반환."""
    today = datetime.now().strftime("%Y%m%d")
    payload = {
        "scustcd": cfg["scustcd"],
        "scmdept": cfg["scmdept"],
        "swms_cd": "",
        "nav_num": "0107",
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
    """재고조회(셀분리) 결과 테이블 파싱."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.dataTables-example")
    if table is None:
        raise RuntimeError("재고조회 결과 테이블을 찾지 못했습니다 (페이지 구조 변경 가능성).")

    rows = []
    tbody = table.find("tbody")
    if tbody is None:
        return rows

    for tr in tbody.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]

        # "조회된 결과가 없습니다" 같은 안내행 (colspan 한 칸짜리) 스킵
        if len(cells) < len(TABLE_COLUMNS):
            continue

        record = dict(zip(TABLE_COLUMNS, cells))

        # 통관구분 정규화: "통관" / "미통관" / "분할통관" 텍스트 그대로 두되
        # 값이 비어있으면 이 계정의 용도를 기본값으로 사용
        pass_raw = record.pop("통관상태_원본").strip()
        record["통관상태"] = pass_raw if pass_raw else None  # 후처리 단계에서 계정 기본값 적용

        record["창고명"] = 창고명
        record["품목명"] = record.pop("수탁품")
        record["공급사"] = record.pop("브랜드") or "기타/미상"

        rows.append(record)

    return rows


def apply_default_customs_status(rows: list, cfg: dict) -> None:
    """통관구분 값이 비어있는 행에 한해 계정 기본값 적용."""
    for r in rows:
        if not r.get("통관상태"):
            r["통관상태"] = cfg["계정용도"]


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

    # 이번에 새로 수집한 창고/계정 조합의 기존 레코드는 제거 후 교체
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
