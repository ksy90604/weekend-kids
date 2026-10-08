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
import urllib.error
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
BAD_CATEGORY = re.compile(r"술집|유흥|주점|호프|바\b|클럽|모텔|호텔|숙박|성인|카지노|노래방|PC방|당구|사우나|찜질|부동산|아파트|주거|오피스텔")
MIN_SIMILARITY = 0.6
DUP_RADIUS_KM = 0.5


class KakaoError(RuntimeError):
    """키·권한 문제처럼 재시도해도 소용없는 오류. 실행을 멈추고 Actions 를 실패로 표시한다."""


class Client:
    def __init__(self, key: str):
        self.key = key

    def search(self, query: str, size: int = 10) -> list[dict]:
        q = urllib.parse.urlencode({"query": query, "size": size})
        req = urllib.request.Request(f"{KAKAO_URL}?{q}", headers={"Authorization": f"KakaoAK {self.key}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8")).get("documents", [])
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            hint = {
                401: "REST API 키가 잘못됐어요. 카카오 디벨로퍼스 → 앱 키 → 'REST API 키'를 GitHub Secrets KAKAO_REST_KEY 에 넣었는지 확인하세요.",
                403: "앱에서 카카오맵이 꺼져 있어요. 카카오 디벨로퍼스 → 내 애플리케이션 → 제품 설정 → 카카오맵 → '활성화 설정' ON.",
            }.get(e.code, "")
            raise KakaoError(f"카카오 API HTTP {e.code}: {body}\n{hint}") from e


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


# '농원'·'체험장'처럼 업종을 나타내는 흔한 말. 제안자는 '한터 농원', 지도는 '한터조랑말농장'처럼 다르게 부르는 일이 많다.
GENERIC = re.compile(r"(키즈카페|테마파크|자연휴양림|체험농장|체험장|체험|농원|농장|목장|카페|놀이터|공원|박물관|과학관|미술관|"
                     r"수목원|식물원|동물원|랜드|파크|마을|센터|본점|지점|점)")


def core(s: str) -> str:
    return GENERIC.sub("", norm(s))


def similarity(a: str, b: str) -> float:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return 1.0
    score = difflib.SequenceMatcher(None, na, nb).ratio()
    ca, cb = core(a), core(b)
    if len(ca) >= 2 and len(cb) >= 2:
        if (ca in cb or cb in ca) and min(len(ca), len(cb)) >= 3:
            score = max(score, 0.9)
        else:
            score = max(score, difflib.SequenceMatcher(None, ca, cb).ratio())
    return score


ROAD = re.compile(r"([가-힣A-Za-z0-9]+(?:로|길))\s*(\d+(?:-\d+)?)")


def road_match(region: str, address: str) -> bool:
    """제안자가 '대대로 110'처럼 도로명+번호를 적었고 지도 주소에도 같은 게 있으면 같은 곳으로 본다."""
    m = ROAD.search(region or "")
    if not m:
        return False
    return (m.group(1) + m.group(2)) in (address or "").replace(" ", "")


def haversine(lat1, lon1, lat2, lon2) -> float:
    R, rad = 6371.0, math.pi / 180
    d = math.sin((lat2 - lat1) * rad / 2) ** 2 + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin((lon2 - lon1) * rad / 2) ** 2
    return 2 * R * math.asin(math.sqrt(d))


ADMIN_SUFFIX = re.compile(r"(특별시|광역시|특별자치시|특별자치도|도|시|군|구|읍|면|동|리)$")


def region_words(region: str) -> list[str]:
    """제안자가 적은 지역에서 행정구역 단어만 뽑는다. '경기 가평' → ['경기','가평'],
    '경기도 용인시 처인구 양지면 대대로 110 (대대리 96-1)' → ['경기','용인','처인','양지']"""
    text = re.sub(r"\([^)]*\)", " ", region)              # 괄호 안(지번 등) 제거
    words = []
    for w in re.split(r"[\s,/]+", text):
        if not w or re.search(r"\d", w):                   # 번지·숫자는 제외
            continue
        if words and not ADMIN_SUFFIX.search(w) and len(words) >= 2:
            break                                           # 행정구역 뒤의 도로명부터는 무시
        base = ADMIN_SUFFIX.sub("", w)
        if len(base) >= 1:
            words.append(base if len(base) >= 2 else w)
        if len(words) >= 3:
            break
    return words


def region_ok(region: str, *addresses: str) -> bool:
    """제안자가 적은 지역의 행정구역 단어가 지도 주소(도로명 또는 지번)에 모두 들어 있는지."""
    words = region_words(region) if region else []
    if not words:
        return True
    for addr in addresses:
        a = (addr or "").replace(" ", "")
        if a and all(w in a for w in words):
            return True
    return False


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
        if road_match(region, d.get("road_address_name", "")) and score >= 0.3:
            score = max(score, 0.95)  # 주소가 같으면 이름이 조금 달라도 같은 곳
        if score > best_score:
            best, best_score = d, score
    if best is None or best_score < MIN_SIMILARITY:
        return None, f"이름이 맞는 곳을 찾지 못했어요 (가장 비슷한 곳: {best['place_name'] if best else '-'})"
    addr = best.get("road_address_name") or best.get("address_name") or ""
    if not region_ok(region, best.get("road_address_name", ""), best.get("address_name", "")):
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
        if not name or done.get(key, {}).get("status") == "등록":
            continue
        done.pop(key, None)  # 반려였던 제안은 다시 검토 (규칙 개선 반영)
        if col(row, "숨김", "삭제"):
            continue
        region = col(row, "지역", "주소", "위치")
        stamp = re.search(r"(\d{4})[./-]\s*(\d{1,2})[./-]\s*(\d{1,2})", col(row, "타임", "시간", "날짜"))
        entry = {"key": key, "name": name, "nick": col(row, "닉네임", "작성자") or "익명",
                 "date": f"{stamp[1]}-{int(stamp[2]):02d}-{int(stamp[3]):02d}" if stamp else "", "checkedAt": today}
        try:
            doc, why = find_match(api, name, region)
        except KakaoError:
            raise
        except Exception as e:  # 일시적 네트워크 오류는 다음 실행 때 다시 시도
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
    try:
        run(Client(key), rows, dry_run=args.dry_run)
    except KakaoError as e:
        print(f"[실패] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
