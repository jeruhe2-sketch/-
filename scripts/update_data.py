"""
매일 GitHub Actions가 실행하는 자동 갱신 스크립트.

1. 공공데이터포털 API(ImportLivestInspStatsInfo)를 전량 호출
2. 합계/소계 행을 제거하고 냉동/냉장 상세행만 추출
3. 기존 data/master_flat.json을 읽어와서, "올해" 데이터만 최신값으로 교체
   (과거 연도 히스토리는 그대로 보존)
4. 다시 같은 포맷(meta + flat 압축배열)으로 저장

인증키는 GitHub Actions Secret(OPEN_API_KEY)에서 읽어옵니다.
로컬에서 테스트할 때는 환경변수로 넣어서 실행하세요:
    OPEN_API_KEY="발급받은 Encoding키" python scripts/update_data.py
"""

import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

BASE_URL = "https://apis.data.go.kr/1471000/ImportLivestInspStatsInfo/getImportLivestInspStatsInfo"
DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "master_flat.json")
NUM_OF_ROWS = 100

SERVICE_KEY = os.environ.get("OPEN_API_KEY", "")
if not SERVICE_KEY:
    raise SystemExit("환경변수 OPEN_API_KEY가 설정되어 있지 않습니다. (GitHub Actions Secret 또는 로컬 환경변수로 지정하세요)")


def fetch_page(page_no: int) -> dict:
    url = (
        f"{BASE_URL}?serviceKey={SERVICE_KEY}"
        f"&pageNo={page_no}&numOfRows={NUM_OF_ROWS}&type=json"
    )
    with urllib.request.urlopen(url, timeout=20) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def fetch_all() -> list[dict]:
    all_items = []
    first = fetch_page(1)
    header = first.get("header", {})
    if header.get("resultCode") != "00":
        raise RuntimeError(f"API 오류: {header}")

    body = first["body"]
    total_count = body["totalCount"]
    all_items.extend([row["item"] for row in body.get("items", [])])

    total_pages = (total_count + NUM_OF_ROWS - 1) // NUM_OF_ROWS
    print(f"총 {total_count}건 / {total_pages}페이지")

    for page_no in range(2, total_pages + 1):
        time.sleep(0.2)
        page = fetch_page(page_no)
        all_items.extend([row["item"] for row in page["body"].get("items", [])])

    return all_items


DETAIL_ICE_VALUES = {"냉동", "냉장"}


def is_detail_row(item: dict) -> bool:
    if item.get("MNF_NTNCD") is None:
        return False
    regn = item.get("REGN_CD") or ""
    ice = item.get("ICE_YN") or ""
    if regn.endswith("합계"):
        return False
    if ice not in DETAIL_ICE_VALUES:
        return False
    return True


def main():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    current_year = now.year

    print(f"[{now.isoformat()}] 데이터 갱신 시작 (기준연도 {current_year})")

    raw_items = fetch_all()
    detail_items = [i for i in raw_items if is_detail_row(i)]
    print(f"상세행(합계 제외): {len(detail_items)} / 전체 {len(raw_items)}")

    # 기존 압축 데이터 로드 및 롱포맷으로 복원
    with open(DATA_PATH, encoding="utf-8") as f:
        payload = json.load(f)
    meta = payload["meta"]
    year_base = meta["yearBase"]
    flat = payload["flat"]

    records = {}  # (y, m, 품명, 구분, 부위, 국가) -> ton
    for idx in range(0, len(flat), 7):
        y = flat[idx] + year_base
        m = flat[idx + 1]
        p = meta["품명"][flat[idx + 2]]
        i = meta["구분"][flat[idx + 3]]
        r = meta["부위"][flat[idx + 4]]
        n = meta["국가"][flat[idx + 5]]
        ton = flat[idx + 6] / 10
        records[(y, m, p, i, r, n)] = ton

    # 올해분 기존 레코드 제거 (API가 최신 재계산값으로 완전히 대체)
    records = {k: v for k, v in records.items() if k[0] != current_year}

    added = 0
    for item in detail_items:
        p = item["KOREAN_NM"]
        i = item["ICE_YN"]
        r = item["REGN_CD"]
        n = item["MNF_NTNCD"]
        for month_idx in range(12):
            val = item.get(f"MON{month_idx + 1}")
            val = float(val) if val not in (None, "") else 0.0
            if val == 0:
                continue
            key = (current_year, month_idx + 1, p, i, r, n)
            records[key] = val / 1000  # kg -> 톤
            added += 1

    print(f"올해({current_year})분 갱신 레코드: {added}")

    # 다시 meta + flat 압축 포맷으로 인코딩
    품명s = sorted(set(k[2] for k in records))
    구분s = sorted(set(k[3] for k in records))
    부위s = sorted(set(k[4] for k in records))
    국가s = sorted(set(k[5] for k in records))
    p_idx = {v: i for i, v in enumerate(품명s)}
    i_idx = {v: i for i, v in enumerate(구분s)}
    r_idx = {v: i for i, v in enumerate(부위s)}
    n_idx = {v: i for i, v in enumerate(국가s)}

    min_year = min(k[0] for k in records)
    new_flat = []
    for (y, m, p, i, r, n), ton in records.items():
        new_flat.extend([y - min_year, m, p_idx[p], i_idx[i], r_idx[r], n_idx[n], round(ton * 10)])

    new_payload = {
        "meta": {"품명": 품명s, "구분": 구분s, "부위": 부위s, "국가": 국가s, "yearBase": min_year},
        "flat": new_flat,
        "updatedAt": now.isoformat(),
    }

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(new_payload, f, ensure_ascii=False, separators=(",", ":"))

    print(f"저장 완료: {DATA_PATH} (레코드 {len(records)}건)")


if __name__ == "__main__":
    main()
