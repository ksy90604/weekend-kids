"""카카오 API 없이 제안 검증 흐름을 확인하는 테스트. 실행: python scripts/test_verify_proposals.py"""
import json
import tempfile
import unittest
from pathlib import Path

import verify_proposals as vp


def doc(id_, name, addr, x, y, cat="여행 > 관광,명소 > 테마파크", phone="031-000-0000"):
    return {"id": id_, "place_name": name, "road_address_name": addr, "address_name": addr,
            "x": str(x), "y": str(y), "category_name": cat, "phone": phone,
            "place_url": f"http://place.map.kakao.com/{id_}"}


class FakeClient(vp.Client):
    def __init__(self):
        super().__init__("dummy")

    def search(self, query, size=10):
        if "푸른들" in query:
            return [doc("111", "푸른들동물농장", "경기 가평군 가평읍 어딘가 1", 127.51, 37.83),
                    doc("112", "푸른들 호프", "경기 가평군 가평읍 어딘가 2", 127.52, 37.84, cat="음식점 > 술집 > 호프,요리주점")]
        if "양떼" in query:
            return [doc("222", "늘솔길공원양떼목장", "인천 남동구 논현동 1", 126.72, 37.44)]
        if "달빛" in query:
            return [doc("333", "달빛 바", "서울 마포구 1", 126.92, 37.55, cat="음식점 > 술집 > 바")]
        if "별빛" in query:
            return [doc("444", "별빛키즈카페", "서울 송파구 1", 127.10, 37.51, cat="문화,예술 > 키즈카페")]
        return []


def row(name, region="", nick="", when="2026/10/08 오전 10:00:00", **extra):
    r = {"타임스탬프": when, "장소 이름": name, "지역 (시/군/구)": region, "추천 이유": "아이가 좋아해요",
         "쉬는 날 (선택)": "매주 월요일", "이용 시간 (선택)": "10:00~18:00", "요금 (선택)": "어른 10,000원 / 어린이 8,000원",
         "닉네임 (선택)": nick}
    r.update(extra)
    return r


class UnitTest(unittest.TestCase):
    def test_similarity(self):
        self.assertEqual(vp.similarity("푸른들 동물농장", "푸른들동물농장"), 1.0)
        self.assertGreater(vp.similarity("푸른들 동물 농장", "푸른들동물농장 가평점"), 0.9)
        self.assertLess(vp.similarity("푸른들 동물농장", "달빛 바"), 0.3)

    def test_region(self):
        self.assertTrue(vp.region_ok("경기 가평", "경기 가평군 가평읍 1"))
        self.assertTrue(vp.region_ok("서울 송파구", "서울 송파구 올림픽로 1"))
        self.assertFalse(vp.region_ok("강원 춘천", "경기 가평군 1"))
        self.assertTrue(vp.region_ok("", "아무 주소"))

    def test_col(self):
        self.assertEqual(vp.col(row("x", nick="감자"), "닉네임"), "감자")
        self.assertEqual(vp.col(row("x"), "쉬는", "휴무"), "매주 월요일")


class FlowTest(unittest.TestCase):
    def run_flow(self, rows, existing_custom=None, existing_places=None):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            vp.PLACES, vp.CUSTOM, vp.STATUS = d / "p.json", d / "c.json", d / "s.json"
            vp.PLACES.write_text(json.dumps({"items": existing_places or []}), encoding="utf-8")
            vp.CUSTOM.write_text(json.dumps({"items": existing_custom or []}), encoding="utf-8")
            status = vp.run(FakeClient(), rows)
            custom = json.loads(vp.CUSTOM.read_text(encoding="utf-8"))
            return status, custom

    def test_register_and_reject(self):
        rows = [
            row("푸른들 동물농장", "경기 가평", nick="감자"),
            row("달빛 바", "서울 마포", when="2026/10/08 오전 11:00:00"),
            row("없는곳12345", "서울", when="2026/10/08 오전 12:00:00"),
            row("푸른들 동물농장", "강원 춘천", when="2026/10/08 오후 1:00:00"),
        ]
        status, custom = self.run_flow(rows)
        by = {s["name"] + s["date"]: s for s in status["items"]}
        self.assertEqual(len(custom["items"]), 1)
        p = custom["items"][0]
        self.assertEqual(p["id"], "custom-k111")
        self.assertEqual(p["name"], "푸른들동물농장")
        self.assertEqual(p["closedDays"], [1])
        self.assertEqual(p["price"], {"adult": 10000, "child": 8000})
        self.assertEqual(p["proposedBy"], "감자")
        self.assertEqual(p["area"], "경기 가평군")
        statuses = [s["status"] for s in status["items"]]
        self.assertEqual(statuses, ["등록", "반려", "반려", "반려"])
        self.assertIn("아이와 가는 곳이 아닌", status["items"][1]["reason"])
        self.assertIn("찾을 수 없", status["items"][2]["reason"])
        self.assertIn("지역이 달라요", status["items"][3]["reason"])

    def test_duplicate_and_idempotent(self):
        existing = [{"id": "3", "name": "늘솔길공원양떼목장", "lat": 37.44, "lon": 126.72}]
        rows = [row("늘솔길 양떼목장", "인천")]
        status, custom = self.run_flow(rows, existing_places=existing)
        self.assertEqual(status["items"][0]["status"], "반려")
        self.assertIn("이미 등록", status["items"][0]["reason"])
        self.assertEqual(custom["items"], [])
        # 같은 제안을 다시 돌려도 중복 처리하지 않는다
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            vp.PLACES, vp.CUSTOM, vp.STATUS = d / "p.json", d / "c.json", d / "s.json"
            vp.PLACES.write_text(json.dumps({"items": existing}), encoding="utf-8")
            vp.CUSTOM.write_text(json.dumps({"items": []}), encoding="utf-8")
            vp.STATUS.write_text(json.dumps(status), encoding="utf-8")
            again = vp.run(FakeClient(), rows)
            self.assertEqual(len(again["items"]), 1)

    def test_kids_cafe_registers(self):
        status, custom = self.run_flow([row("별빛 키즈카페", "서울 송파")])
        self.assertEqual(status["items"][0]["status"], "등록")
        self.assertIn("play", custom["items"][0]["tags"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
