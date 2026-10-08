"""방문자가 구글 폼으로 제안한 장소를 카카오 지도 검색으로 검증하고, 통과하면 data/custom-places.json 에 등록한다.

흐름
  1. reviews-config.js 의 PROPOSALS.csvUrl (공개 구글 시트) 에서 제안 목록을 읽는다.
  2. 아직 처리하지 않은 제안마다 카카오 로컬 API(키워드 검색)로 실제 존재하는 장소인지 확인한다.
     - 이름이 충분히 비슷하고, 적은 지역이 주소에 들어 있어야 통과
     - 이미 등록된 곳(관광공사 데이터·직접 등록)과 겹치면 반려
     - 유흥·성인 업소 등은 반려
  3. 통과한 곳은 좌표·주소·전화를 받아 custom-places.json 에 추가하고,
     결과(등록/반려/사유)를 data/proposals-status.json 에 남긴다. 사이트가 이 파일로 상태를 보여 준다.

사용법:
  KAKAO_REST_KEY=키 python scripts/verify_proposals.py
  python scripts/verify_proposals.py --dry-run   # 파일을 바꾸지 않고 결과만 출력
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import difflib
import io
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_places import EXCLUDE_WORDS, classify, clean, parse_closed_days, parse_closed_dates, parse_fee, parse_months  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "reviews-config.js"
PLACES = ROOT / "data" / "places.json"
CUSTOM = ROOT / "data" / "custom-places.json"
STATUS = ROOT / "data" / "proposals-status.json"
KST = dt.timezone(dt.timedelta(hours=9))

KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
BAD_CATEGORY = re.compile(r"술집|유흥|주점|호프|바\b|클럽|모텔|호텔|숙박|성인|카지노|노래방|PC방|당구|사우나|찜질")
MIN_SIMILARITY = 0.6
DUP_RADIUS_KM = 0.5


class Client:
    def __init__(self, key: str):
        self.key = key

    def search(self, query: str, size: int = 10) -> list[dict]:
        q = urllib.parse.urlencode({"query": query, "size": size})
        req = urllib.request.Request(f"{KAKAO_URL}?{q}", headers={"Authorization": f"KakaoAK {self.key}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8")).get("documents", [])


# ── 입력 읽기 ───────────────────────────────────────
def config_url(name: str) -> str:
    m = re.search(rf"window\.{name}\s*=\s*\{{(.*?)\}};", CONFIG.read_text(encoding="utf-8"), re.S)
    if not m:
        return ""
    u = re.search(r'csvUrl:\s*"([^"]*)"', m.group(1))
    return u.group(1) if u else ""


def fetch_csv(url: str) -> list[dict]:
    with urllib.request.urlopen(url, timeout=30) as r:
        text = r.read().decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return []
    header = [h.strip() for h in rows[0]]
    return [dict(zip(header, r)) for r in rows[1:] if any(c.strip() for c in r)]


def col(row: dict, *words: str) -> str:
    """헤더에 키워드가 들어 있는 열의 값 (질문 제목이 조금 달라도 찾는다)."""
    for k, v in row.items():
        key = re.sub(r"\s", "", k)
        if any(w in key for w in words):
            return (v or "").strip()
    return ""


def proposal_key(row: dict) -> str:
    return f"{col(row, '타임', '시간', '날짜')}|{col(row, '장소이름', '이름', '장소명')}"


# ── 검증 ───────────────────────────────────────────
def norm(s: str) -> str:
    return re.sub(r"[\s\(\)\[\]\-_.,·'\"‘’]|점$", "", s).lower()


def similarity(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def haversine(lat1, lon1, lat2, lon2) -> float:
    R, rad = 6371.0, math.pi / 180
    d = math.sin((lat2 - lat1) * rad / 2) ** 2 + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin((lon2 - lon1) * rad / 2) ** 2
    return 2 * R * math.asin(math.sqrt(d))


def region_ok(region: str, address: str) -> bool:
    """제안자가 적은 지역(예: '경기 가평', '서울 송파구')의 단어가 주소에 들어 있는지."""
    if not region:
        return True
    words = [w for w in re.split(r"[\s,/]+", region) if len(w) >= 2]
    words = [re.sub(r"(특별시|광역시|특별자치도|도|시|군|구)$", "", w) or w for w in words]
    addr = address.replace(" ", "")
    return all(w.replace(" ", "") in addr for w in words)


def find_match(api: Client, name: str, region: str) -> tuple[dict | None, str]:
    """카카오에서 찾아 (장소, 사유) 반환. 못 찾으면 (None, 사유)."""
    queries = [f"{region} {name}".strip(), name] if region else [name]
    seen: list[dict] = []
    for q in queries:
        for d in api.search(q):
            if d not in seen:
                seen.append(d)
    if not seen:
        return None, "지도에서 찾을 수 없어요"
    best, best_score = None, 0.0
    for d in seen:
        score = similarity(name, d.get("place_name", ""))
        if score > best_score:
            best, best_score = d, score
    if best is None or best_score < MIN_SIMILARITY:
        return None, f"이름이 맞는 곳을 찾지 못했어요 (가장 비슷한 곳: {best['place_name'] if best else '-'})"
    addr = best.get("road_address_name") or best.get("address_name") or ""
    if not region_ok(region, addr):
        return None, f"지역이 달라요 (지도 주소: {addr})"
    cat = best.get("category_name", "")
    if BAD_CATEGORY.search(cat) or EXCLUDE_WORDS.search(best.get("place_name", "")):
        return None, f"아이와 가는 곳이 아닌 것 같아요 ({cat.split(' > ')[-1]})"
    return best, ""


def duplicate_of(lat: float, lon: float, name: str, existing: list[dict]) -> dict | None:
    for p in existing:
        try:
            dist = haversine(lat, lon, float(p["lat"]), float(p["lon"]))
        except (KeyError, TypeError, ValueError):
            continue
        if dist <= DUP_RADIUS_KM and similarity(name, p.get("name", "")) >= MIN_SIMILARITY:
            return p
    return None


def build_place(doc: dict, row: dict, today: str) -> dict:
    name = doc["place_name"]
    addr = doc.get("road_address_name") or doc.get("address_name") or ""
    tip = col(row, "이유", "소개", "설명", "추천")
    rest, hours, fee = col(row, "쉬는", "휴무"), col(row, "이용시간", "운영시간", "시간"), col(row, "요금", "입장료", "가격")
    setting, tags, emoji, ages = classify(name, f"{tip} {doc.get('category_name', '')}", "12")
    place = {
        "id": f"custom-k{doc['id']}",
        "name": name,
        "area": " ".join(addr.split()[:2]) or col(row, "지역", "주소"),
        "lat": round(float(doc["y"]), 5),
        "lon": round(float(doc["x"]), 5),
        "emoji": emoji, "setting": setting, "tags": tags, "ages": ages,
        "price": parse_fee(fee) if fee else None,
        "parking": None,
        "closedDays": parse_closed_days(rest), "closedDates": parse_closed_dates(rest),
        "restText": clean(rest) or None,
        "hours": clean(hours) or "이용시간 확인 필요",
        "tel": doc.get("phone") or None,
        "homepage": doc.get("place_url") or None,
        "address": addr,
        "tip": clean(tip),
        "proposedBy": col(row, "닉네임", "작성자") or "익명",
        "verifiedAt": today,
        "source": "proposal",
    }
    months = parse_months(hours) or parse_months(rest)
    if months:
        place["months"] = months
    return place


# ── 실행 ───────────────────────────────────────────
def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def run(api: Client, rows: list[dict], dry_run: bool = False) -> dict:
    today = dt.datetime.now(KST).strftime("%Y-%m-%d")
    places = load_json(PLACES, {"items": []}).get("items", [])
    custom = load_json(CUSTOM, {"items": []})
    custom.setdefault("items", [])
    status = load_json(STATUS, {"items": []})
    done = {s["key"]: s for s in status.get("items", [])}
    existing = places + custom["items"]

    new_status, added = [], 0
    for row in rows:
        key = proposal_key(row)
        name = col(row, "장소이름", "이름", "장소명")
        if not name or key in done:
            continue
        if col(row, "숨김", "삭제"):
            continue
        region = col(row, "지역", "주소", "위치")
        entry = {"key": key, "name": name, "nick": col(row, "닉네임", "작성자") or "익명",
                 "date": col(row, "타임", "시간", "날짜")[:13], "checkedAt": today}
        try:
            doc, why = find_match(api, name, region)
        except Exception as e:  # 네트워크 오류 등은 다음 실행 때 다시 시도
            print(f"[보류] {name}: {e}", file=sys.stderr)
            continue
        if doc is None:
            entry.update(status="반려", reason=why)
        else:
            lat, lon = float(doc["y"]), float(doc["x"])
            dup = duplicate_of(lat, lon, doc["place_name"], existing)
            if dup:
                entry.update(status="반려", reason=f"이미 등록된 곳이에요 ({dup['name']})", placeId=dup.get("id"))
            else:
                place = build_place(doc, row, today)
                custom["items"].append(place)
                existing.append(place)
                entry.update(status="등록", placeId=place["id"], matched=doc["place_name"], address=place["address"])
                added += 1
        new_status.append(entry)
        print(f"[{entry['status']}] {name} → {entry.get('matched') or entry.get('reason')}")

    status["items"] = list(done.values()) + new_status
    status["updatedAt"] = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    print(f"[결과] 새로 검토 {len(new_status)}건, 등록 {added}곳")
    if not dry_run and new_status:
        CUSTOM.write_text(json.dumps(custom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    key = os.environ.get("KAKAO_REST_KEY", "").strip()
    if not key:
        print("KAKAO_REST_KEY 환경변수가 없습니다 (카카오 디벨로퍼스 REST API 키).", file=sys.stderr)
        return 1
    url = config_url("PROPOSALS")
    if not url:
        print("reviews-config.js 의 PROPOSALS.csvUrl 이 비어 있어요.", file=sys.stderr)
        return 1
    rows = fetch_csv(url)
    print(f"[제안] {len(rows)}건 읽음")
    run(Client(key), rows, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
