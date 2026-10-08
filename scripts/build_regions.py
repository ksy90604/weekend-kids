"""출발지 선택용 시/도 → 시/군/구 좌표 목록(data/regions.json)을 만든다.

좌표는 OpenStreetMap Nominatim(무료, 키 없음)에서 한 번만 받아 파일로 저장한다.
사용법: python scripts/build_regions.py   (약 1분, 1초에 1건씩 요청)
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "regions.json"

REGIONS: dict[str, list[str]] = {
    "서울": ["강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구", "노원구", "도봉구", "동대문구", "동작구",
           "마포구", "서대문구", "서초구", "성동구", "성북구", "송파구", "양천구", "영등포구", "용산구", "은평구", "종로구", "중구", "중랑구"],
    "인천": ["강화군", "계양구", "남동구", "동구", "미추홀구", "부평구", "서구", "연수구", "옹진군", "중구"],
    "경기": ["가평군", "고양시", "과천시", "광명시", "광주시", "구리시", "군포시", "김포시", "남양주시", "동두천시", "부천시", "성남시",
           "수원시", "시흥시", "안산시", "안성시", "안양시", "양주시", "양평군", "여주시", "연천군", "오산시", "용인시", "의왕시",
           "의정부시", "이천시", "파주시", "평택시", "포천시", "하남시", "화성시"],
    "강원": ["춘천시", "원주시", "강릉시", "속초시", "홍천군", "횡성군", "평창군", "양양군"],
    "충남": ["천안시", "아산시", "공주시", "보령시", "서산시", "태안군"],
    "충북": ["청주시", "충주시", "제천시", "단양군"],
    "세종": ["세종시"],
    "대전": ["대전광역시"],
}
FULL = {"서울": "서울특별시", "인천": "인천광역시", "경기": "경기도", "강원": "강원특별자치도", "충남": "충청남도",
        "충북": "충청북도", "세종": "세종특별자치시", "대전": "대전광역시"}


def geocode(q: str) -> tuple[float, float] | None:
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "jsonv2", "countrycodes": "kr", "limit": 1, "accept-language": "ko"})
    req = urllib.request.Request(url, headers={"User-Agent": "weekend-kids/1.0 (github.com/ksy90604/weekend-kids)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not data:
        return None
    return round(float(data[0]["lat"]), 4), round(float(data[0]["lon"]), 4)


def main() -> int:
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    out: dict[str, dict] = {}
    for sido, guns in REGIONS.items():
        out[sido] = {"name": FULL[sido], "areas": {}}
        for g in guns:
            prev = old.get(sido, {}).get("areas", {}).get(g)
            if prev:
                out[sido]["areas"][g] = prev
                continue
            q = FULL[sido] if g == FULL[sido].replace("특별자치시", "시") or g == FULL[sido] else f"{FULL[sido]} {g}"
            try:
                pt = geocode(q)
            except Exception as e:  # noqa: BLE001
                print(f"[실패] {q}: {e}", file=sys.stderr)
                pt = None
            if pt:
                out[sido]["areas"][g] = list(pt)
                print(f"{q} → {pt}")
            else:
                print(f"[없음] {q}", file=sys.stderr)
            time.sleep(1.1)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    total = sum(len(v["areas"]) for v in out.values())
    print(f"[결과] {total}곳 저장 → {OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
