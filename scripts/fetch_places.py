"""한국관광공사 TourAPI(KorService2)에서 아이와 갈 만한 장소·축제를 받아 data/places.json 을 만든다.

- 목록에서 사라진 곳(폐업·삭제)은 자동으로 빠진다.
- 상세 정보(쉬는 날·이용시간·요금)는 수정일이 바뀐 곳만 다시 받아 호출 수를 아낀다.
- 표준 라이브러리만 사용 (pip 설치 불필요).

사용법:
  TOUR_API_KEY=발급키 python scripts/fetch_places.py            # 전체 갱신
  TOUR_API_KEY=발급키 python scripts/fetch_places.py --check    # 키·응답 형식만 확인
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://apis.data.go.kr/B551011/KorService2"
OUT = Path(__file__).resolve().parent.parent / "data" / "places.json"
KST = dt.timezone(dt.timedelta(hours=9))

# 법정동 시도 코드: 서울 11, 인천 28, 경기 41
REGIONS = {"11": "서울", "28": "인천", "41": "경기"}
# 12 관광지, 14 문화시설, 28 레포츠
CONTENT_TYPES = ["12", "14", "28"]
FESTIVAL_TYPE = "15"
FESTIVAL_DAYS_AHEAD = 21

KID_WORDS = re.compile(
    r"어린이|아이|키즈|유아|체험|과학관|박물관|동물원|동물|아쿠아리움|수족관|수목원|식물원|농장|목장|"
    r"놀이|테마파크|에버랜드|롯데월드|서울랜드|대공원|테마공원|생태공원|숲|썰매|물놀이|워터|갯벌|천문|"
    r"동굴|생태|자연휴양림|딸기"
)
EXCLUDE_WORDS = re.compile(
    r"골프|카지노|나이트|주점|와인|와이너리|양조|맥주|바비큐|스파|온천|숯가마|사우나|찜질|요트|사격|번지|"
    r"클럽|성인|묘역|납골|낚시|캠핑|글램핑|오토캠|근린공원|체육공원|대학교|학교 박물관|승마|서바이벌|ATV|"
    r"전통술|금융|문화원"
)
# 축제는 이름에 아이 관련 말이 없어도 받되, 어른·전문가 대상 행사는 뺀다.
FESTIVAL_EXCLUDE = re.compile(
    r"소극장|연극|어워즈|디자인|옥토버|빈티지|마켓|건축|비엔날레|청년|콘서트|뮤직|음악|발레|영화|OST|AI|"
    r"살롱|야간|야행|밤의|걷기|주간|위크|페스타.*웰니스|문화제$"
)

INDOOR_WORDS = re.compile(r"박물관|과학관|미술관|전시관|체험관|기념관|아쿠아리움|수족관|키즈카페|도서관|천문|동굴|실내")
TAG_RULES = [
    ("feeding", r"먹이\s*주기|먹이\s*체험|먹이를\s*주|목장|양떼|팜랜드|동물농장|동물\s*체험|동물을\s*만|조랑말|승마|염소|토끼|알파카|당나귀|사슴|젖소|송아지"),
    ("craft", r"만들기|공방|체험|클래스|워크숍|원데이"),
    ("water", r"물놀이|수영장|워터|해수욕장|계곡"),
    ("snow", r"눈썰매|스키|썰매"),
    ("bloom", r"수목원|식물원|꽃|정원"),
    ("foliage", r"수목원|숲|자연휴양림|산림"),
    ("animals", r"동물|목장|아쿠아리움|수족관|사파리|조랑말|염소|토끼|알파카|사슴|곤충|새|나비"),
    ("science", r"과학|천문|우주"),
    ("museum", r"박물관|미술관|전시관|기념관"),
    ("tide", r"갯벌"),
    ("nature", r"공원|숲|생태|자연|수목원|계곡"),
    ("play", r"놀이|테마파크|랜드|키즈"),
]
EMOJI = {"feeding": "🐑", "water": "🏊", "snow": "🛷", "animals": "🐾", "science": "🔭", "museum": "🏛️", "tide": "🦀",
         "bloom": "🌷", "foliage": "🍁", "play": "🎠", "nature": "🌳"}
WEEKDAYS = {"일": 0, "월": 1, "화": 2, "수": 3, "목": 4, "금": 5, "토": 6}

# 상세(intro) 응답의 필드명은 콘텐츠 타입마다 접미사가 다르다.
INTRO_FIELDS = {
    "12": {"rest": "restdate", "time": "usetime", "fee": None, "parking": "parking", "parkingText": "parking", "season": "useseason", "baby": "chkbabycarriage", "tel": "infocenter"},
    "14": {"rest": "restdateculture", "time": "usetimeculture", "fee": "usefee", "parking": "parkingfee", "parkingText": "parkingculture", "season": None, "baby": "chkbabycarriageculture", "tel": "infocenterculture"},
    "28": {"rest": "restdateleports", "time": "usetimeleports", "fee": "usefeeleports", "parking": "parkingfeeleports", "parkingText": "parkingleports", "season": "openperiod", "baby": "chkbabycarriageleports", "tel": "infocenterleports"},
    "15": {"rest": None, "time": "playtime", "fee": "usetimefestival", "parking": None, "parkingText": None, "season": None, "baby": None, "tel": "sponsor1tel"},
}


class ApiError(RuntimeError):
    pass


class Client:
    def __init__(self, key: str, budget: int):
        # 공공데이터포털 키는 '인코딩'/'디코딩' 두 가지가 있다. 이미 인코딩된 키면 그대로 쓴다.
        self.key = key if "%" in key else urllib.parse.quote(key, safe="")
        self.budget = budget
        self.calls = 0

    def get(self, op: str, **params) -> list[dict]:
        if self.calls >= self.budget:
            raise ApiError("budget")
        q = {"MobileOS": "ETC", "MobileApp": "WeekendKids", "_type": "json", **params}
        url = f"{BASE}/{op}?serviceKey={self.key}&" + urllib.parse.urlencode(q)
        self.calls += 1
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    raw = r.read().decode("utf-8", "replace")
                break
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise ApiError(f"{op} 인증 실패 (HTTP {e.code}). 키가 잘못 입력됐거나 아직 활성화되지 않았어요. "
                                   "--check 로 다시 확인해 보세요.") from e
                if attempt == 2:
                    raise ApiError(f"{op} 요청 실패: {e}") from e
                time.sleep(2 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == 2:
                    raise ApiError(f"{op} 요청 실패: {e}") from e
                time.sleep(2 * (attempt + 1))
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # 키 오류 등은 _type=json 이어도 XML 로 온다.
            raise ApiError(f"{op} 응답이 JSON 이 아닙니다: {raw[:300]}")
        resp = data.get("response", data)
        header = resp.get("header", {})
        if header.get("resultCode") not in (None, "0000"):
            raise ApiError(f"{op} 오류 {header.get('resultCode')}: {header.get('resultMsg')}")
        body = resp.get("body", {})
        self.last_total = int(body.get("totalCount") or 0)
        items = body.get("items") or {}
        item = items.get("item", []) if isinstance(items, dict) else []
        return item if isinstance(item, list) else [item]

    def get_all(self, op: str, rows: int = 500, **params) -> list[dict]:
        out, page = [], 1
        while True:
            chunk = self.get(op, numOfRows=rows, pageNo=page, **params)
            out += chunk
            if len(out) >= self.last_total or not chunk:
                return out
            page += 1


# ── 텍스트 파싱 ─────────────────────────────────────
def clean(s) -> str:
    s = re.sub(r"<br\s*/?>", " / ", str(s or ""), flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_closed_days(text: str) -> list[int]:
    """'매주 월요일 휴관' → [1]. '첫째 주 월요일'처럼 격주·특정 주 휴무는 매주가 아니므로 제외."""
    if not text or re.search(r"연중\s*무휴|없음", text):
        return []
    days = set()
    order = "일월화수목금토"
    # '/', '※', '(' 와 요일 나열이 아닌 쉼표에서 문장을 나눈다 ("일, 월요일"은 한 덩어리)
    for seg in re.split(r"[/\n]|※|\(|,(?!\s*[일월화수목금토]\s*(?:요일|[,·]))", text):
        if re.search(r"(첫|둘|셋|넷|다섯|마지막|[1-5])\s*(째|번째)|격주|매월|매달", seg):
            continue
        for m in re.finditer(r"([일월화수목금토])\s*요일?\s*[~\-]\s*([일월화수목금토])\s*요일", seg):
            a, b = order.index(m.group(1)), order.index(m.group(2))
            span = range(a, b + 1) if a <= b else list(range(a, 7)) + list(range(0, b + 1))
            days.update(span)
        seg = re.sub(r"[일월화수목금토]\s*요일?\s*[~\-]\s*[일월화수목금토]\s*요일", "", seg)
        for m in re.finditer(r"([일월화수목금토](?:\s*[,·및]\s*[일월화수목금토])*)\s*요일", seg):
            for ch in re.findall(r"[일월화수목금토]", m.group(1)):
                days.add(WEEKDAYS[ch])
    # "매주 월요일~일요일"처럼 7일 모두 휴무로 읽히면 입력 오류다. 모르는 것으로 두고 원문만 보여 준다.
    return sorted(days) if len(days) < 7 else []


def parse_closed_dates(text: str) -> list[str]:
    """'1월 1일' → ['01-01']. 설·추석처럼 음력 명절은 날짜가 매년 달라 제외."""
    return sorted({f"{int(m):02d}-{int(d):02d}" for m, d in re.findall(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", text or "")})


def parse_months(text: str) -> list[int] | None:
    """'7월~8월', '4~10월' → 운영 월 목록. 못 찾으면 None(연중)."""
    m = re.search(r"(\d{1,2})\s*월?\s*[~\-]\s*(\d{1,2})\s*월", text or "")
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if not (1 <= a <= 12 and 1 <= b <= 12):
        return None
    return list(range(a, b + 1)) if a <= b else list(range(a, 13)) + list(range(1, b + 1))


def parse_hours(text: str) -> str:
    m = re.search(r"(\d{1,2})\s*[:시]\s*(\d{2})?\s*분?\s*[~\-]\s*(\d{1,2})\s*[:시]\s*(\d{2})?", text or "")
    if not m:
        return clean(text)[:40] or "이용시간 정보 없음"
    return f"{int(m.group(1)):02d}:{m.group(2) or '00'}~{int(m.group(3)):02d}:{m.group(4) or '00'}"


def _won(s: str) -> int:
    return int(s.replace(",", ""))


def parse_fee(text: str) -> dict | None:
    """'어른 4,000원 / 어린이 2,000원' → {'adult': 4000, 'child': 2000}. 해석 못 하면 None."""
    t = clean(text)
    if not t:
        return None
    if "무료" in t and not re.search(r"\d[\d,]*\s*원", t):
        return {"adult": 0, "child": 0}
    adult = re.search(r"(?:어른|성인|대인|일반)[^\d]{0,10}(\d[\d,]*)\s*원", t)
    child = re.search(r"(?:어린이|소인|아동|유아|초등)[^\d]{0,10}(\d[\d,]*)\s*원", t)
    if adult or child:
        a = _won(adult.group(1)) if adult else _won(child.group(1))
        c = _won(child.group(1)) if child else a
        return {"adult": a, "child": c}
    one = re.findall(r"(\d[\d,]*)\s*원", t)
    if len(one) == 1:
        v = _won(one[0])
        return {"adult": v, "child": v}
    return None


def parse_parking(text: str) -> int | None:
    t = clean(text)
    if not t:
        return None
    if "무료" in t and not re.search(r"\d[\d,]*\s*원", t):
        return 0
    m = re.search(r"(\d[\d,]*)\s*원", t)
    return _won(m.group(1)) if m else None


def homepage(html: str) -> str | None:
    m = re.search(r'href=["\']([^"\']+)', html or "")
    return m.group(1) if m else (html.strip() if (html or "").startswith("http") else None)


def classify(title: str, overview: str, ctype: str) -> tuple[str, list[str], str, list[str]]:
    text = f"{title} {overview}"
    tags = [t for t, rx in TAG_RULES if re.search(rx, text)]
    if ctype == "14" or INDOOR_WORDS.search(title):
        setting = "indoor"
    elif re.search(r"실내", overview or ""):
        setting = "mixed"
    else:
        setting = "outdoor"
    emoji = next((EMOJI[t] for t in tags if t in EMOJI), "📍")
    ages = ["kid", "school"] if ("science" in tags or "museum" in tags) else ["baby", "kid", "school"]
    return setting, tags, emoji, ages


def fmt_date(s: str) -> str | None:
    s = re.sub(r"\D", "", str(s or ""))
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else None


# ── 수집 ───────────────────────────────────────────
def is_kid_friendly(item: dict) -> bool:
    title = item.get("title", "")
    return bool(KID_WORDS.search(title)) and not EXCLUDE_WORDS.search(title)


def base_place(item: dict, region: str) -> dict | None:
    try:
        lat, lon = float(item["mapy"]), float(item["mapx"])
    except (KeyError, ValueError, TypeError):
        return None
    if not lat or not lon:
        return None
    addr = clean(item.get("addr1"))
    return {
        "id": str(item["contentid"]),
        "contentTypeId": str(item.get("contenttypeid") or ""),
        "name": clean(item.get("title")),
        "area": " ".join(addr.split()[:2]) or region,
        "lat": round(lat, 5), "lon": round(lon, 5),
        "image": item.get("firstimage") or None,
        "tel": clean(item.get("tel")) or None,
        "modified": fmt_date(item.get("modifiedtime")),
    }


def fetch_detail(api: Client, place: dict) -> dict:
    ctype = place["contentTypeId"]
    common = (api.get("detailCommon2", contentId=place["id"]) or [{}])[0]
    intro = (api.get("detailIntro2", contentId=place["id"], contentTypeId=ctype) or [{}])[0]
    f = INTRO_FIELDS.get(ctype, INTRO_FIELDS["12"])
    pick = lambda k: clean(intro.get(f[k])) if f.get(k) else ""
    overview = clean(common.get("overview"))
    rest, season = pick("rest"), pick("season")
    setting, tags, emoji, ages = classify(place["name"], overview, ctype)
    fee = parse_fee(pick("fee")) if f["fee"] else None
    if fee is None and ctype == "12" and re.search(r"무료", overview[:200]):
        fee = {"adult": 0, "child": 0}
    return {
        "setting": setting, "tags": tags, "emoji": emoji, "ages": ages,
        "price": fee, "parking": parse_parking(pick("parking")),
        # 주차 가능 여부 글 ("가능", "없음", "소형 50대" 등). 요금 글과 합쳐 둔다.
        "parkingText": " / ".join(t for t in (pick("parkingText"), pick("parking") if f.get("parking") != f.get("parkingText") else "") if t) or None,
        "closedDays": parse_closed_days(rest), "closedDates": parse_closed_dates(rest),
        "months": parse_months(season), "restText": rest or None, "seasonText": season or None,
        "hours": parse_hours(pick("time")),
        "babyCarriage": pick("baby") or None,
        "tel": place.get("tel") or pick("tel") or None,
        "homepage": homepage(common.get("homepage", "")),
        "tip": (overview[:110] + "…") if len(overview) > 110 else overview,
        "detailFetched": dt.datetime.now(KST).strftime("%Y-%m-%d"),
    }


def load_cache() -> dict[str, dict]:
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if old.get("isSample"):
        return {}
    return {p["id"]: p for p in old.get("items", [])}


def run(api: Client) -> dict:
    today = dt.datetime.now(KST).date()
    cache = load_cache()
    candidates: dict[str, dict] = {}

    for code, region in REGIONS.items():
        for ctype in CONTENT_TYPES:
            items = api.get_all("areaBasedList2", lDongRegnCd=code, contentTypeId=ctype, arrange="C")
            kept = [p for it in items if is_kid_friendly(it) and (p := base_place(it, region))]
            print(f"[목록] {region} 타입{ctype}: {len(items)}곳 중 {len(kept)}곳 후보")
            for p in kept:
                candidates[p["id"]] = p

        # 이미 시작해서 진행 중인 축제도 잡도록 90일 전부터 조회
        fests = api.get_all("searchFestival2", lDongRegnCd=code,
                            eventStartDate=(today - dt.timedelta(days=90)).strftime("%Y%m%d"))
        horizon = today + dt.timedelta(days=FESTIVAL_DAYS_AHEAD)
        n = 0
        for it in fests:
            start, end = fmt_date(it.get("eventstartdate")), fmt_date(it.get("eventenddate"))
            if not start or not end or end < today.isoformat() or start > horizon.isoformat():
                continue
            if EXCLUDE_WORDS.search(it.get("title", "")) or FESTIVAL_EXCLUDE.search(it.get("title", "")):
                continue
            p = base_place(it, region)
            if p:
                p["contentTypeId"] = FESTIVAL_TYPE
                p["period"] = {"start": start, "end": end}
                candidates[p["id"]] = p
                n += 1
        print(f"[축제] {region}: 앞으로 {FESTIVAL_DAYS_AHEAD}일 안에 열리는 {n}건")

    # 수정일이 그대로인 곳은 캐시 재사용, 바뀐 곳·새 곳만 상세 조회 (최근 수정순)
    places, pending = [], []
    for p in candidates.values():
        old = cache.get(p["id"])
        if old and old.get("modified") == p["modified"] and old.get("detailFetched") and "parkingText" in old:
            places.append({**old, **p})
        else:
            pending.append(p)
    pending.sort(key=lambda p: p["modified"] or "", reverse=True)

    skipped = 0
    for i, p in enumerate(pending):
        try:
            places.append({**p, **fetch_detail(api, p)})
        except ApiError as e:
            if str(e) == "budget":
                skipped = len(pending) - i
                break
            print(f"[경고] {p['name']} 상세 실패: {e}", file=sys.stderr)
    if skipped:
        print(f"[알림] 호출 한도로 {skipped}곳은 다음 실행 때 받아요.")

    dropped = len(set(cache) - set(candidates))
    print(f"[결과] {len(places)}곳 저장, 목록에서 사라져 뺀 곳 {dropped}곳, API 호출 {api.calls}회")
    places.sort(key=lambda p: p["name"])
    return {
        "updatedAt": dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "isSample": False,
        "source": "한국관광공사 TourAPI",
        "items": places,
    }


def reprocess() -> int:
    data = json.loads(OUT.read_text(encoding="utf-8"))
    if data.get("isSample"):
        print("샘플 데이터라 재처리할 게 없어요.", file=sys.stderr)
        return 1
    before = len(data["items"])
    kept = []
    for p in data["items"]:
        festival = p.get("contentTypeId") == FESTIVAL_TYPE
        if EXCLUDE_WORDS.search(p["name"]) or (festival and FESTIVAL_EXCLUDE.search(p["name"]))                 or (not festival and not KID_WORDS.search(p["name"])):
            continue
        rest = p.get("restText") or ""
        p["closedDays"], p["closedDates"] = parse_closed_days(rest), parse_closed_dates(rest)
        # 주제 태그는 규칙이 늘어날 수 있으니 이름·소개글로 다시 매긴다 (기존 태그는 유지)
        _, tags, emoji, _ = classify(p["name"], p.get("tip") or "", p.get("contentTypeId", "12"))
        # 'animals'는 예전 규칙이 '농장'만 보고도 붙였으므로 새 규칙으로 다시 판단한다
        p["tags"] = sorted((set(p.get("tags") or []) - {"animals"}) | set(tags))
        if p.get("emoji", "📍") == "📍":
            p["emoji"] = emoji
        if p.get("seasonText"):
            p["months"] = parse_months(p["seasonText"])
        kept.append(p)
    data["items"] = kept
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[재처리] {before}곳 → {len(kept)}곳")
    return 0


def check(api: Client) -> None:
    items = api.get("areaBasedList2", numOfRows=3, pageNo=1, lDongRegnCd="11", contentTypeId="14", arrange="C")
    print(f"[확인] 키 정상. 서울 문화시설 전체 {api.last_total}곳. 첫 항목 필드:")
    if items:
        print(json.dumps(items[0], ensure_ascii=False, indent=2))
        intro = api.get("detailIntro2", contentId=items[0]["contentid"], contentTypeId="14")
        print("[확인] 상세(intro) 필드:")
        print(json.dumps(intro[0] if intro else {}, ensure_ascii=False, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="키와 응답 형식만 확인")
    ap.add_argument("--reprocess", action="store_true", help="API 호출 없이 저장된 데이터에 규칙만 다시 적용")
    ap.add_argument("--max-calls", type=int, default=int(os.environ.get("TOUR_MAX_CALLS", 900)),
                    help="하루 API 호출 상한 (개발계정 기본 한도 1,000회)")
    args = ap.parse_args()
    if args.reprocess:
        return reprocess()

    key = os.environ.get("TOUR_API_KEY", "").strip()
    if not key and sys.stdin.isatty():
        import getpass
        key = getpass.getpass("TourAPI 인증키를 붙여 넣고 Enter (화면에는 안 보여요): ")
        # 붙여넣기 때 섞여 들어온 보이지 않는 문자 제거
        key = "".join(ch for ch in key if ch.isprintable()).strip()
        print(f"키 {len(key)}자 입력됨 (보통 64자 이상이에요)")
    if not key:
        print("TOUR_API_KEY 환경변수가 없습니다. 공공데이터포털에서 발급받은 키를 넣어 주세요.", file=sys.stderr)
        return 1
    api = Client(key, args.max_calls)
    try:
        if args.check:
            check(api)
            return 0
        data = run(api)
    except ApiError as e:
        print(f"[실패] {e}", file=sys.stderr)
        return 1
    if not data["items"]:
        print("[실패] 받은 장소가 0곳이라 기존 파일을 유지합니다.", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
