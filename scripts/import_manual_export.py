# -*- coding: utf-8 -*-
"""
창고 사이트에서 사람이 직접 로그인 → "재고조회(셀분리)" 화면에서
통관구분을 "전체"로 놓고 조회 → 표 우측 상단 "출력" 버튼 옆
DataTables 내보내기(CSV) 버튼으로 받은 CSV 파일을 warehouse_stock.json에 병합한다.

로그인 자동화(scripts/fetch_all_warehouses.py)가 이 사이트들에서 아직
막혀 있어서(원인 미해결), 당분간은 이 수작업+변환 방식을 사용한다.

사용 예:
  python scripts/import_manual_export.py --warehouse 대청냉장 data/raw/daecheong.csv
  python scripts/import_manual_export.py --warehouse 신우냉장 data/raw/sinwoo.csv
  python scripts/import_manual_export.py --warehouse 한라냉장 data/raw/halla.csv

한 번에 여러 창고를 같이 갱신하려면 --warehouse/파일 쌍을 반복해서 넘기면 된다:
  python scripts/import_manual_export.py \
      --warehouse 대청냉장 data/raw/daecheong.csv \
      --warehouse 신우냉장 data/raw/sinwoo.csv

동작 방식:
  - 지정한 창고명(들)에 대해서만 기존 데이터를 새 CSV 내용으로 통째로 교체한다.
  - 지정하지 않은 다른 창고(예: 지금 갱신 안 하는 쪽)의 기존 데이터는 그대로 둔다.
  - CSV 헤더는 사이트의 재고조회(셀분리) 표 헤더와 동일해야 한다:
    사업부,관리번호,품목코드,수탁품,위탁자품목코드,규격,단위중량,단위,
    LOT-NO,B/L NO,식별번호,브랜드,저장구역,재고수량,중량,허용수량,
    적재수량,PLT수량,소비기한,제조일자,통관구분,통관일자,상태,비고
"""

import argparse
import csv
import json
import os
from datetime import datetime

OUTPUT_PATH = "data/warehouse_stock.json"

# CSV 헤더 -> 내부 스키마 필드명 매핑
COLUMN_MAP = {
    "수탁품": "품목명",
    "브랜드": "공급사",
    "저장구역": "저장위치",
    "중량": "중량_kg",
    "소비기한": "유통기한",
    "통관구분": "통관상태",
}

# 최종적으로 남길 필드 (기존 warehouse_stock.json 스키마와 맞춤)
KEEP_FIELDS = [
    "창고명", "품목명", "공급사", "통관상태", "재고수량", "중량_kg",
    "저장위치", "유통기한", "제조일자", "통관일자", "LOT-NO", "B/L NO",
    "규격", "비고", "사업부", "관리번호", "품목코드", "위탁자품목코드",
    "단위중량", "단위", "식별번호", "허용수량", "적재수량", "PLT수량", "상태",
]


def read_csv_rows(path: str, 창고명: str) -> list:
    rows = []
    # 사이트가 EUC-KR 인코딩을 쓰므로 우선 EUC-KR로 시도하고, 실패하면 UTF-8로 재시도
    for enc in ("euc-kr", "utf-8-sig", "utf-8"):
        try:
            with open(path, encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                for raw in reader:
                    record = {}
                    for k, v in raw.items():
                        if k is None:
                            continue
                        key = k.strip()
                        mapped_key = COLUMN_MAP.get(key, key)
                        record[mapped_key] = (v or "").strip()
                    record["창고명"] = 창고명
                    rows.append(record)
            print(f"[{path}] 인코딩 {enc} 로 읽음, {len(rows)}건")
            return rows
        except UnicodeDecodeError:
            rows = []
            continue
    raise RuntimeError(f"{path} 파일 인코딩을 인식하지 못했습니다 (euc-kr/utf-8 둘 다 실패).")


def load_existing() -> dict:
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"수집시각": None, "총건수": 0, "데이터": []}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--warehouse", action="append", required=True,
        help="이 옵션 뒤에 오는 파일이 속한 창고명 (여러 쌍 반복 가능)",
    )
    parser.add_argument("files", nargs="+", help="--warehouse 순서와 1:1 대응하는 CSV 파일 경로들")
    args = parser.parse_args()

    if len(args.warehouse) != len(args.files):
        raise SystemExit(
            f"--warehouse 개수({len(args.warehouse)})와 파일 개수({len(args.files)})가 다릅니다. "
            "쌍을 맞춰서 넘겨주세요."
        )

    existing = load_existing()
    existing_rows = existing.get("데이터", [])

    new_rows_by_warehouse = {}
    for wh, path in zip(args.warehouse, args.files):
        rows = read_csv_rows(path, wh)
        new_rows_by_warehouse.setdefault(wh, []).extend(rows)

    updated_warehouses = set(new_rows_by_warehouse.keys())
    kept_rows = [r for r in existing_rows if r.get("창고명") not in updated_warehouses]

    all_new_rows = []
    for wh, rows in new_rows_by_warehouse.items():
        # 불필요한 필드 제거하고 스키마 정리
        cleaned = []
        for r in rows:
            cleaned.append({k: r.get(k, "") for k in KEEP_FIELDS if k in r or k == "창고명"})
        all_new_rows.extend(cleaned)
        print(f"{wh}: {len(cleaned)}건 갱신")

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
