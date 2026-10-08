"""카카오 지도 키워드 검색으로 키즈카페·체험농장 같은 사설 장소를 모아 data/kakao-places.json 을 만든다.

- 지역(data/regions.json 의 시/군/구) × 키워드 조합으로 검색한다.
- 업종이 아이와 맞지 않거나(술집·숙박·주거 등) 이름에 제외어가 있으면 뺀다.
- 관광공사 데이터·직접 등록·제안 등록과 겹치는 곳은 뺀다 (이름이 비슷하고 500m 안).
- 매번 전체를 다시 만들기 때문에 지도에서 사라진 곳은 자동으로 빠진다.
- 쉬는 날·요금 정보는 없다. 사이트는 이런 곳을 "운영시간·요금 확인 필요"로 표시한다.

사용법:
  KAKAO_REST_KEY=키 python scripts/fetch_kakao.py
  KAKAO_REST_KEY=키 python scripts/fetch_kakao.py --sido 서울 --keyword 키즈카페   # 일부만
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_places import EXCLUDE_WORDS, classify  # noqa: E402
from verify_proposals import BAD_CATEGORY, Client, KakaoError, duplicate_of, load_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REGIONS = ROOT / "data" / "regions.json"
PLACES = ROOT / "data" / "places.json"
CUSTOM = ROOT / "data" / "custom-places.json"
OUT = ROOT / "data" / "kakao-places.json"
KST = dt.timezone(dt.timedelta(hours=9))

KEYWORDS = ["키즈카페", "실내놀이터", "체험농장", "동물농장", "눈썰매장"]
# 검색 결과의 업종(category_name)이 이 중 하나와 맞아야 한다
GOOD_CATEGORY = re.compile(r"키즈카페|놀이|농장|목장|체험|테마파크|썰매|동물원|수족관|아쿠아리움|과학관|박물관|관광|여행|문화")
PAGES = 2  # 지역·키워드당 최대 2쪽(30곳)


def search_all(api: Client, query: str) -> list[dict]:
    out: list[dict] = []
    for page in range(1, PAGES + 1):
        docs = api.search_page(query, page=page, size=15)
        out += docs
        if len(docs) < 15:
            break
    return out


def acceptable(doc: dict) -> bool:
    name, cat = doc.get("place_name", ""), doc.get("category_name", "")
    if EXCLUDE_WORDS.search(name) or BAD_CATEGORY.search(cat):
        return False
    return bool(GOOD_CATEGORY.search(cat) or GOOD_CATEGORY.search(name))


def to_place(doc: dict, keyword: str, today: str) -> dict:
    name = doc["place_name"]
    addr = doc.get("road_address_name") or doc.get("address_name") or ""
    cat = doc.get("category_name", "")
    setting, tags, emoji, ages = classify(name, f"{cat} {keyword}", "12")
    if keyword in ("키즈카페", "실내놀이터"):
        setting, ages = "indoor", ["baby", "kid"]
        tags = sorted(set(tags) | {"play"})
        emoji = "🎠"
    return {
        "id": f"kakao-{doc['id']}",
        "name": name,
        "area": " ".join(addr.split()[:2]),
        "lat": round(float(doc["y"]), 5), "lon": round(float(doc["x"]), 5),
        "emoji": emoji, "setting": setting, "tags": tags, "ages": ages,
        "price": None, "parking": None, "closedDays": [], "closedDates": [],
        "hours": "운영시간 확인 필요", "unknownHours": True,
        "tel": doc.get("phone") or None, "homepage": doc.get("place_url") or None,
        "address": addr, "category": cat.split(" > ")[-1],
        "tip": f"카카오 지도 '{keyword}' 검색으로 찾은 곳이에요. 업종: {cat.split(' > ')[-1] or '-'}",
        "verifiedAt": today, "source": "kakao",
    }


def run(api: Client, regions: dict, keywords: list[str], sidos: list[str] | None = None) -> dict:
    today = dt.datetime.now(KST).strftime("%Y-%m-%d")
    existing = load_json(PLACES, {"items": []}).get("items", []) + load_json(CUSTOM, {"items": []}).get("items", [])
    found: dict[str, dict] = {}
    skipped = {"업종": 0, "중복": 0}
    calls = 0
    for sido, info in regions.items():
        if sidos and sido not in sidos:
            continue
        for gu in info["areas"]:
            for kw in keywords:
                docs = search_all(api, f"{info['name']} {gu} {kw}")
                calls += 1
                for d in docs:
                    if d["id"] in found:
                        continue
                    if not acceptable(d):
                        skipped["업종"] += 1
                        continue
                    if duplicate_of(float(d["y"]), float(d["x"]), d["place_name"], existing):
                        skipped["중복"] += 1
                        continue
                    found[d["id"]] = to_place(d, kw, today)
        print(f"[{sido}] 누적 {len(found)}곳")
    items = sorted(found.values(), key=lambda p: (p["area"], p["name"]))
    print(f"[결과] {len(items)}곳, 업종 제외 {skipped['업종']}, 기존과 중복 {skipped['중복']}, 검색 호출 약 {calls}회")
    return {"updatedAt": dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "source": "카카오 지도 검색",
            "keywords": keywords, "items": items}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sido", action="append", help="특정 시/도만 (여러 번 가능)")
    ap.add_argument("--keyword", action="append", help="특정 키워드만 (여러 번 가능)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    key = os.environ.get("KAKAO_REST_KEY", "").strip()
    if not key:
        print("KAKAO_REST_KEY 환경변수가 없습니다.", file=sys.stderr)
        return 1
    regions = json.loads(REGIONS.read_text(encoding="utf-8"))
    try:
        data = run(Client(key), regions, args.keyword or KEYWORDS, args.sido)
    except KakaoError as e:
        print(f"[실패] {e}", file=sys.stderr)
        return 1
    if not data["items"]:
        print("[실패] 받은 장소가 0곳이라 기존 파일을 유지합니다.", file=sys.stderr)
        return 1
    if not args.dry_run:
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
