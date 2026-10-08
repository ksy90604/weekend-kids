"""카카오 수집 스크립트의 필터·중복 처리 테스트. 실행: python scripts/test_fetch_kakao.py"""
import unittest

import fetch_kakao as fk
import verify_proposals as vp


def doc(id_, name, cat, addr="서울 송파구 잠실동 1", x=127.10, y=37.51):
    return {"id": id_, "place_name": name, "category_name": cat, "road_address_name": addr, "address_name": addr,
            "x": str(x), "y": str(y), "phone": "02-000-0000", "place_url": f"http://place.map.kakao.com/{id_}"}


class FakeClient(vp.Client):
    def __init__(self):
        super().__init__("dummy")
        self.calls = []

    def search_page(self, query, page=1, size=15):
        self.calls.append((query, page))
        if page > 1:
            return []
        if "키즈카페" in query:
            return [doc("1", "별빛키즈카페", "문화,예술 > 키즈카페"),
                    doc("2", "달빛 호프", "음식점 > 술집 > 호프,요리주점"),
                    doc("3", "키즈카페 옆 오피스텔", "부동산 > 주거시설 > 오피스텔")]
        if "체험농장" in query:
            return [doc("4", "늘솔길공원양떼목장", "여행 > 관광,명소 > 목장", "인천 남동구 논현동 1", 126.72, 37.44),
                    doc("5", "행복체험농장", "여행 > 관광,명소 > 농장", "경기 용인시 처인구 1", 127.20, 37.20)]
        return []


class KakaoTest(unittest.TestCase):
    def test_run(self):
        regions = {"서울": {"name": "서울특별시", "areas": {"송파구": [37.51, 127.10]}}}
        fk.PLACES = fk.ROOT / "nonexistent.json"
        fk.CUSTOM = fk.ROOT / "nonexistent.json"
        existing_backup = vp.load_json
        try:
            vp.load_json = lambda path, default: {"items": [{"id": "3", "name": "늘솔길공원양떼목장", "lat": 37.44, "lon": 126.72}]}
            fk.load_json = vp.load_json
            data = fk.run(FakeClient(), regions, ["키즈카페", "체험농장"])
        finally:
            vp.load_json = existing_backup
            fk.load_json = existing_backup
        names = [p["name"] for p in data["items"]]
        self.assertEqual(sorted(names), ["별빛키즈카페", "행복체험농장"])
        cafe = next(p for p in data["items"] if p["name"] == "별빛키즈카페")
        self.assertEqual(cafe["id"], "kakao-1")
        self.assertEqual(cafe["setting"], "indoor")
        self.assertIn("play", cafe["tags"])
        self.assertTrue(cafe["unknownHours"])
        self.assertEqual(cafe["source"], "kakao")

    def test_acceptable(self):
        self.assertTrue(fk.acceptable(doc("9", "포니목장", "여행 > 관광,명소 > 목장")))
        self.assertFalse(fk.acceptable(doc("9", "포니 골프", "스포츠,레저 > 골프장")))
        self.assertFalse(fk.acceptable(doc("9", "아이사랑 모텔", "숙박 > 모텔")))


if __name__ == "__main__":
    unittest.main(verbosity=1)
