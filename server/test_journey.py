import time
import unittest
from unittest.mock import patch

from convoy_server import Convoy, ApiError
from tmap_service import Tmap, TmapError

DEST = {"name": "강릉", "latitude": 37.7519, "longitude": 128.8761}
STOP = {"name": "합류", "latitude": 37.4, "longitude": 128.1, "source": "tmap"}


class JourneyTest(unittest.TestCase):
    def setUp(self):
        self.store = Convoy()
        self.a = self.store.handle("POST", "/rooms", {"name": "A", "destination": DEST}, "")
        self.root = "/rooms/"+self.a["code"]
        self.b = self.call("join", {"name": "B"}, self.a)
        for who, lat, lon in ((self.a, 37.5665, 126.978), (self.b, 36.3504, 127.3845)):
            self.call("location", {"latitude": lat, "longitude": lon, "measured_at": time.time(), "source": "sdk"}, who)

    def call(self, op, body, who=None):
        return self.store.handle("POST", self.root+"/"+op, body, (who or self.a)["token"])

    @staticmethod
    def route(origin, dest, vias=()):
        seconds = (1000 if origin["latitude"] > 37 else 1600)+len(vias)*200
        return {"provider": "tmap", "path": [[origin["longitude"], origin["latitude"]], [dest["longitude"], dest["latitude"]]],
                "seconds": seconds, "meters": 100000, "computed_at": time.time(), "destination": dest, "waypoints": list(vias)}

    def test_authenticated_eta_departure_and_battery(self):
        with self.assertRaises(ApiError):
            self.store.handle("POST", self.root+"/journey", {"action": "overview"}, "bad")
        self.store.rooms[self.a["code"]]["arrival_at"] = time.time()+3000
        self.call("profile", {"battery_pct": 10, "range_km": 70})
        with patch.object(self.store.journey.tmap, "route", side_effect=self.route):
            r = self.call("journey", {"action": "overview"})
        self.assertEqual(r["arrival_spread_seconds"], 600)
        self.assertEqual(r["charging_recommended"], [self.a["member_id"]])
        self.assertIsNotNone(r["routes"][self.a["member_id"]]["suggested_departure_at"])

    def test_passenger_can_propose_but_not_approve_or_apply(self):
        phone = self.call("join", {"name": "passenger", "role": "passenger"})
        p = self.call("proposals", {"place": STOP}, phone)["proposal"]
        self.assertNotIn(phone["member_id"], p["votes"])
        with self.assertRaises(ApiError):
            self.call("decisions", {"proposal_id": p["id"], "approve": True}, phone)
        for who in (self.a, self.b):
            room = self.call("decisions", {"proposal_id": p["id"], "approve": True}, who)
        self.assertEqual(room["waypoints"][0]["name"], STOP["name"])
        self.assertEqual(room["waypoints"][0]["source"], "tmap")
        with self.assertRaises(ApiError):
            self.call("journey", {"action": "apply", "proposal_id": p["id"]}, phone)

    def test_plan_is_leader_only_and_waits_for_approval(self):
        with self.assertRaises(ApiError):
            self.call("proposals", {"kind": "plan", "place": STOP}, self.b)
        p = self.call("proposals", {"kind": "plan", "place": STOP, "waypoints": [DEST], "driving_mode": "same"})["proposal"]
        self.assertEqual(self.store.rooms[self.a["code"]]["destination"]["name"], DEST["name"])
        result = self.call("decisions", {"proposal_id": p["id"], "approve": True}, self.b)
        self.assertEqual(result["destination"]["name"], STOP["name"])
        self.assertEqual(result["driving_mode"], "same")
        with self.assertRaises(ApiError):
            self.call("journey", {"action": "apply", "proposal_id": p["id"], "attempt_id": "forged"})

    def test_old_locations_and_changed_plan_reject_results(self):
        def change(origin, dest, vias):
            self.store.rooms[self.a["code"]]["plan_version"] += 1
            return self.route(origin, dest, vias)
        with patch.object(self.store.journey.tmap, "route", side_effect=change), self.assertRaises(ApiError):
            self.call("journey", {"action": "overview"})
        self.store.rooms[self.a["code"]]["members"][self.b["member_id"]]["location"]["measured_at"] -= 31
        with self.assertRaises(ApiError):
            self.call("journey", {"action": "overview"})

    def test_candidate_uses_road_detour_and_preserves_unknown_parking(self):
        with patch.object(self.store.journey.tmap, "route", side_effect=self.route), \
             patch.object(self.store.journey.tmap, "search", return_value=[dict(STOP)]):
            r = self.call("journey", {"action": "suggest", "category": "cafe", "parking_cars": 3})
        p = r["candidates"][0]
        self.assertEqual(p["wait_seconds"], 600)
        self.assertEqual(p["max_detour_seconds"], 200)
        self.assertEqual(p["parking_required"], 3)
        self.assertIn("미확인", p["parking"])

    def test_search_sends_required_radius_and_does_not_forge_pleos_id(self):
        service = Tmap(key="test-only")
        response = {"searchPoiInfo": {"pois": {"poi": [{"name": "카페", "frontLat": "37.5", "frontLon": "127.2", "id": "123"}]}}}
        with patch.object(service, "request", return_value=response) as request:
            p = service.search("카페", STOP)[0]
        self.assertIn("radius=30", request.call_args.args[0])
        self.assertEqual(p["poi_id"], "")
        self.assertEqual(p["tmap_poi_id"], "123")
        service.budget = 0
        with self.assertRaises(TmapError):
            service.request("routes?version=1", {})

    def test_provider_failure_does_not_become_free_detour(self):
        original = self.route
        def failing(origin, dest, vias=()):
            if dest["name"] == STOP["name"]:
                raise TmapError("TMAP provider unavailable")
            return original(origin, dest, vias)
        with patch.object(self.store.journey.tmap, "route", side_effect=failing), \
             patch.object(self.store.journey.tmap, "search", return_value=[dict(STOP)]), self.assertRaises(TmapError):
            self.call("journey", {"action": "suggest", "category": "cafe"})


if __name__ == "__main__":
    unittest.main()
