"""API 키 없이 파싱 규칙과 전체 흐름을 확인하는 테스트. 실행: python scripts/test_fetch_places.py"""
import json
import tempfile
import unittest
from pathlib import Path

import fetch_places as fp


class ParseTest(unittest.TestCase):
    def test_closed_days(self):
        self.assertEqual(fp.parse_closed_days("매주 월요일 휴관 (공휴일인 경우 다음날)"), [1])
        self.assertEqual(fp.parse_closed_days("매주 일·월요일"), [0, 1])
        self.assertEqual(fp.parse_closed_days("연중무휴"), [])
        self.assertEqual(fp.parse_closed_days("매월 첫째 주 월요일"), [])
        self.assertEqual(fp.parse_closed_days("1월 1일, 설날 및 추석 당일"), [])
        # 실제 TourAPI 문구에서 나온 사례
        self.assertEqual(fp.parse_closed_days("매주 토요일~월요일 / 법정공휴일"), [0, 1, 6])
        self.assertEqual(fp.parse_closed_days("매주 월요일~목요일※ 연휴 시 운영"), [1, 2, 3, 4])
        self.assertEqual(fp.parse_closed_days("매달 둘째 화요일 (3월 / 6월~8월 / 11월)"), [])
        self.assertEqual(fp.parse_closed_days("매주 월요일 (공휴일인 경우 다음의 첫번째 평일)/ 1월 1일"), [1])
        self.assertEqual(fp.parse_closed_days("매주 월요일~일요일 / 법정공휴일"), [])  # 7일 전부면 입력 오류

    def test_closed_dates(self):
        self.assertEqual(fp.parse_closed_dates("매주 월요일, 1월 1일, 12월 25일"), ["01-01", "12-25"])

    def test_months(self):
        self.assertEqual(fp.parse_months("7월~8월"), [7, 8])
        self.assertEqual(fp.parse_months("4~10월 운영"), [4, 5, 6, 7, 8, 9, 10])
        self.assertEqual(fp.parse_months("12월~2월"), [12, 1, 2])
        self.assertIsNone(fp.parse_months("연중"))

    def test_fee(self):
        self.assertEqual(fp.parse_fee("어른 4,000원<br>어린이 2,000원"), {"adult": 4000, "child": 2000})
        self.assertEqual(fp.parse_fee("무료"), {"adult": 0, "child": 0})
        self.assertEqual(fp.parse_fee("입장료 5,000원"), {"adult": 5000, "child": 5000})
        self.assertIsNone(fp.parse_fee("홈페이지 참조"))

    def test_hours_parking_homepage(self):
        self.assertEqual(fp.parse_hours("09:30~17:30 (입장마감 16:30)"), "09:30~17:30")
        self.assertEqual(fp.parse_hours("10시~18시"), "10:00~18:00")
        self.assertEqual(fp.parse_parking("무료"), 0)
        self.assertEqual(fp.parse_parking("소형 3,000원"), 3000)
        self.assertEqual(fp.homepage('<a href="https://www.sciencecenter.go.kr" target="_blank">누리집</a>'),
                         "https://www.sciencecenter.go.kr")

    def test_filter(self):
        self.assertTrue(fp.is_kid_friendly({"title": "국립과천과학관"}))
        self.assertFalse(fp.is_kid_friendly({"title": "OO 골프클럽"}))
        self.assertFalse(fp.is_kid_friendly({"title": "OO 시장"}))
        for name in ["수주근린공원", "평화강변수목캠핑장", "화도낚시공원", "율암온천숯가마 테마파크", "동덕여자대학교 박물관"]:
            self.assertFalse(fp.is_kid_friendly({"title": name}), name)
        for name in ["서울대공원", "광명동굴", "인천대공원 목재문화체험장", "썬밸리워터파크"]:
            self.assertTrue(fp.is_kid_friendly({"title": name}), name)


class ClassifyTest(unittest.TestCase):
    def test_tags(self):
        _, tags, _, _ = fp.classify("한터농원(한터조랑말농장)", "아이들이 농작물을 심어보고 동물을 만져보고 타보며", "12")
        self.assertIn("feeding", tags)
        self.assertIn("animals", tags)
        _, tags, _, _ = fp.classify("양수리딸기체험농장", "딸기 수확 체험", "12")
        self.assertNotIn("animals", tags)
        self.assertIn("craft", tags)


class FakeClient(fp.Client):
    """정해진 응답을 돌려주는 가짜 API."""

    def __init__(self):
        super().__init__("dummy", budget=100)

    def get(self, op, **p):
        self.calls += 1
        if op == "areaBasedList2":
            items = []
            if p["lDongRegnCd"] == "11" and p["contentTypeId"] == "14":
                items = [
                    {"contentid": "1", "contenttypeid": "14", "title": "OO 어린이박물관", "addr1": "서울특별시 종로구 어딘가",
                     "mapx": "126.98", "mapy": "37.57", "modifiedtime": "20260901120000"},
                    {"contentid": "2", "contenttypeid": "14", "title": "OO 와인바", "addr1": "서울", "mapx": "127", "mapy": "37.5"},
                ]
            self.last_total = len(items)
            return items
        if op == "searchFestival2":
            items = []
            if p["lDongRegnCd"] == "41":
                items = [{"contentid": "9", "contenttypeid": "15", "title": "OO 가을 꽃 축제", "addr1": "경기도 가평군",
                          "mapx": "127.35", "mapy": "37.74", "eventstartdate": "20261001", "eventenddate": "20261020",
                          "modifiedtime": "20260920000000"}]
            self.last_total = len(items)
            return items
        if op == "detailCommon2":
            return [{"overview": "아이들이 몸으로 체험하는 실내 전시가 많아요.", "homepage": '<a href="https://example.org">홈</a>'}]
        if op == "detailIntro2":
            if p["contentTypeId"] == "15":
                return [{"playtime": "10:00~18:00", "usetimefestival": "무료"}]
            return [{"restdateculture": "매주 월요일, 1월 1일", "usetimeculture": "10:00~18:00",
                     "usefee": "어른 4,000원 / 어린이 2,000원", "parkingfee": "무료"}]
        raise AssertionError(op)


class FlowTest(unittest.TestCase):
    def test_run(self):
        with tempfile.TemporaryDirectory() as d:
            fp.OUT = Path(d) / "places.json"
            data = fp.run(FakeClient())
        names = [p["name"] for p in data["items"]]
        self.assertEqual(names, ["OO 가을 꽃 축제", "OO 어린이박물관"])
        museum = next(p for p in data["items"] if p["id"] == "1")
        self.assertEqual(museum["closedDays"], [1])
        self.assertEqual(museum["closedDates"], ["01-01"])
        self.assertEqual(museum["price"], {"adult": 4000, "child": 2000})
        self.assertEqual(museum["setting"], "indoor")
        fest = next(p for p in data["items"] if p["id"] == "9")
        self.assertEqual(fest["period"], {"start": "2026-10-01", "end": "2026-10-20"})
        self.assertEqual(fest["price"], {"adult": 0, "child": 0})
        json.dumps(data, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main(verbosity=1)
