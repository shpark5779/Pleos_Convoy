import json
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from convoy_server import ApiError, Convoy, make_server, osm_places


DESTINATION = {"name": "테스트 목적지", "latitude": 37.48544722, "longitude": 127.03636666}
MEETING = {"name": "테스트 경유지", "latitude": 37.51, "longitude": 127.05, "source": "demo"}


class ConvoyTest(unittest.TestCase):
    def setUp(self):
        self.store = Convoy()
        self.owner = self.call("POST", "/rooms", {"name": "차량 A", "destination": DESTINATION})
        self.root = "/rooms/" + self.owner["code"]
        self.peer = self.call("POST", self.root + "/join", {"name": "차량 B"})

    def call(self, method, path, body=None, session=None):
        return self.store.handle(method, path, body or {}, (session or {}).get("token", ""))

    def propose(self):
        return self.call("POST", self.root + "/proposals", {"place": MEETING}, self.owner)["proposal"]

    def test_only_authenticated_members_can_see_locations(self):
        with self.assertRaises(ApiError) as error:
            self.call("GET", self.root)
        self.assertEqual(error.exception.status, 403)
        room = self.call("GET", self.root, session=self.peer)
        self.assertTrue(all("token" not in member for member in room["members"].values()))

    def test_all_approve_then_independent_route_receipts(self):
        proposal = self.propose()
        application = {"proposal_id": proposal["id"], "state": "requested"}
        with self.assertRaises(ApiError):
            self.call("POST", self.root + "/applications", application, self.owner)
        approved = self.call("POST", self.root + "/decisions", {"proposal_id": proposal["id"], "approve": True}, self.peer)
        self.assertEqual(approved["proposal"]["status"], "approved")
        for session, final in ((self.owner, "succeeded"), (self.peer, "failed")):
            room = self.call("POST", self.root + "/applications", application, session)
            attempt = room["proposal"]["applications"][session["member_id"]]["attempt_id"]
            with self.assertRaises(ApiError):
                self.call("POST", self.root + "/applications", application, session)
            with self.assertRaises(ApiError):
                self.call("POST", self.root + "/applications", dict(application, state=final, attempt_id="stale"), session)
            room = self.call("POST", self.root + "/applications", dict(application, state=final, attempt_id=attempt), session)
        self.assertEqual(room["proposal"]["status"], "completed")
        self.assertEqual(room["proposal"]["applications"][self.peer["member_id"]]["state"], "failed")

    def test_rejection_and_old_proposal_cannot_apply(self):
        old = self.propose()
        self.call("POST", self.root + "/decisions", {"proposal_id": old["id"], "approve": False}, self.peer)
        new = self.propose()
        self.assertNotEqual(new["id"], old["id"])
        with self.assertRaises(ApiError):
            self.call("POST", self.root + "/decisions", {"proposal_id": old["id"], "approve": True}, self.peer)

    def test_membership_change_does_not_silently_bypass_votes(self):
        self.propose()
        with self.assertRaises(ApiError):
            self.call("POST", self.root + "/join", {"name": "차량 C"})
        self.call("POST", self.root + "/leave", session=self.peer)
        room = self.call("GET", self.root, session=self.owner)
        self.assertEqual(room["proposal"]["status"], "cancelled")

    def test_locations_expire_and_candidates_are_ranked(self):
        payload = dict(MEETING, measured_at=time.time(), source="demo")
        for session in (self.owner, self.peer):
            self.call("POST", self.root + "/location", payload, session)
        result = self.call("POST", self.root + "/candidates", {"category": "restaurant", "source": "demo"}, self.owner)
        distances = [p["max_straight_km"] for p in result["candidates"]]
        self.assertEqual(distances, sorted(distances))
        self.assertTrue(all(p["source"] == "demo" for p in result["candidates"]))
        self.store.rooms[self.owner["code"]]["members"][self.peer["member_id"]]["location"]["measured_at"] -= 31
        with self.assertRaises(ApiError):
            self.call("POST", self.root + "/candidates", {"category": "restaurant", "source": "demo"}, self.owner)
        for bad in (float("nan"), True, 1000):
            with self.assertRaises(ApiError):
                self.call("POST", self.root + "/location", dict(payload, latitude=bad), self.owner)

    def test_timed_out_route_is_unconfirmed_not_success(self):
        proposal = self.propose()
        self.call("POST", self.root + "/decisions", {"proposal_id": proposal["id"], "approve": True}, self.peer)
        self.call("POST", self.root + "/applications", {"proposal_id": proposal["id"], "state": "requested"}, self.owner)
        application = self.store.rooms[self.owner["code"]]["proposal"]["applications"][self.owner["member_id"]]
        application["updated_at"] -= 91
        room = self.call("GET", self.root, session=self.peer)
        self.assertEqual(room["proposal"]["applications"][self.owner["member_id"]]["state"], "unconfirmed")

    @patch("convoy_server.urlopen")
    def test_osm_parser_does_not_invent_poi_ids(self, request):
        request.return_value.__enter__.return_value.read.return_value = json.dumps({"elements": [
            {"type": "node", "id": 1, "lat": 37.5, "lon": 127.0, "tags": {"name": "식당"}},
            {"type": "way", "id": 2, "center": {"lat": 37.6, "lon": 127.1}, "tags": {"name": "휴게소"}},
            {"type": "node", "id": 3, "lat": 37.5, "lon": 127.0, "tags": {}}
        ]}).encode()
        places = osm_places("restaurant", 37.5, 127)
        self.assertEqual(len(places), 2)
        self.assertTrue(all(p["source"] == "osm" and p["poi_id"] == "" for p in places))


class HttpTest(unittest.TestCase):
    def test_two_clients_and_bad_json_over_real_http(self):
        server = make_server(port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            def send(path, body):
                request = Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
                with urlopen(request, timeout=3) as response:
                    return json.load(response)
            owner = send("/rooms", {"name": "A", "destination": DESTINATION})
            peer = send("/rooms/" + owner["code"] + "/join", {"name": "B"})
            self.assertEqual(len(peer["room"]["members"]), 2)
            self.assertNotEqual(peer["token"], owner["token"])
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base + "/rooms", data=b"[1,2]"), timeout=3)
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main(verbosity=2)
