"""Additional boundary, concurrency and retry checks (no external services)."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import unittest
from unittest.mock import patch

from convoy_server import ApiError, osm_places
import test_convoy as existing
from test_convoy import MEETING


class BoundaryTest(unittest.TestCase):
    setUp = existing.ConvoyTest.setUp
    call = existing.ConvoyTest.call
    propose = existing.ConvoyTest.propose

    def assert_status(self, status, operation):
        with self.assertRaises(ApiError) as error:
            operation()
        self.assertEqual(error.exception.status, status)

    def approve(self):
        proposal = self.propose()
        self.call("POST", self.root + "/decisions", {"proposal_id": proposal["id"], "approve": True}, self.peer)
        return proposal["id"]

    def location(self, session, measured_at):
        return self.call("POST", self.root + "/location",
                         dict(MEETING, measured_at=measured_at, source="demo"), session)

    def test_eight_vehicle_limit_is_atomic_under_concurrent_joins(self):
        def join(index):
            try:
                self.call("POST", self.root + "/join", {"name": f"vehicle {index}"})
                return 200
            except ApiError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=12) as pool:
            statuses = list(pool.map(join, range(12)))
        self.assertEqual(statuses.count(200), 6)
        self.assertEqual(statuses.count(409), 6)
        self.assertEqual(len(self.call("GET", self.root, session=self.owner)["members"]), 8)

    def test_concurrent_proposals_allow_exactly_one_winner(self):
        barrier = threading.Barrier(2)
        def propose(session):
            barrier.wait(timeout=3)
            try:
                self.call("POST", self.root + "/proposals", {"place": MEETING}, session)
                return 200
            except ApiError as error:
                return error.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(propose, (self.owner, self.peer))), [200, 409])

    def test_cross_room_token_and_departed_token_are_rejected(self):
        other = self.call("POST", "/rooms", {"name": "other", "destination": MEETING})
        self.assert_status(403, lambda: self.call("GET", self.root, session=other))
        self.call("POST", self.root + "/leave", session=self.peer)
        self.assert_status(403, lambda: self.call("GET", self.root, session=self.peer))

    def test_only_proposer_can_cancel_and_cancelled_cannot_apply(self):
        proposal = self.propose()
        body = {"proposal_id": proposal["id"]}
        self.assert_status(409, lambda: self.call("POST", self.root + "/cancel", body, self.peer))
        room = self.call("POST", self.root + "/cancel", body, self.owner)
        self.assertEqual(room["proposal"]["status"], "cancelled")
        self.assert_status(409, lambda: self.call("POST", self.root + "/applications", dict(body, state="requested"), self.owner))

    def test_three_vehicles_require_every_vote_and_boolean_input(self):
        third = self.call("POST", self.root + "/join", {"name": "C"})
        proposal = self.propose()
        body = {"proposal_id": proposal["id"], "approve": True}
        room = self.call("POST", self.root + "/decisions", body, self.peer)
        self.assertEqual(room["proposal"]["status"], "pending")
        for value in (1, "true", None):
            self.assert_status(400, lambda: self.call("POST", self.root + "/decisions", dict(body, approve=value), third))
        room = self.call("POST", self.root + "/decisions", body, third)
        self.assertEqual(room["proposal"]["status"], "approved")

    def test_retry_rotates_attempt_and_rejects_previous_receipt(self):
        body = {"proposal_id": self.approve(), "state": "requested"}
        def request():
            room = self.call("POST", self.root + "/applications", body, self.owner)
            return room["proposal"]["applications"][self.owner["member_id"]]["attempt_id"]
        first = request()
        self.call("POST", self.root + "/applications", dict(body, state="failed", attempt_id=first), self.owner)
        second = request()
        self.assertNotEqual(first, second)
        self.assert_status(409, lambda: self.call("POST", self.root + "/applications", dict(body, state="succeeded", attempt_id=first), self.owner))
        self.call("POST", self.root + "/applications", dict(body, state="succeeded", attempt_id=second), self.owner)
        self.assert_status(409, request)

    def test_approved_proposal_blocks_membership_changes(self):
        self.approve()
        self.assert_status(409, lambda: self.call("POST", self.root + "/join", {"name": "C"}))
        self.assert_status(409, lambda: self.call("POST", self.root + "/leave", session=self.peer))

    def test_room_expiry_and_last_member_cleanup(self):
        self.call("POST", self.root + "/leave", session=self.peer)
        self.call("POST", self.root + "/leave", session=self.owner)
        self.assertNotIn(self.owner["code"], self.store.rooms)
        self.setUp()
        self.store.rooms[self.owner["code"]]["created_at"] -= 21601
        self.assert_status(404, lambda: self.call("GET", self.root, session=self.owner))

    def test_future_and_stale_locations_are_rejected(self):
        for offset in (-31, 6):
            self.assert_status(400, lambda: self.location(self.owner, time.time() + offset))

    def test_delayed_location_does_not_replace_newer_measurement(self):
        now = time.time()
        self.location(self.owner, now)
        self.location(self.owner, now - 10)
        room = self.call("GET", self.root, session=self.owner)
        self.assertEqual(room["members"][self.owner["member_id"]]["location"]["measured_at"], now,
                         "Delayed packets must not move the shared location backwards in time")

    def test_real_search_rate_limit_is_global_but_demo_is_available(self):
        for session in (self.owner, self.peer):
            self.location(session, time.time())
        body = {"category": "restaurant", "source": "osm"}
        self.assertIn("osm_query", self.call("POST", self.root + "/candidates", body, self.owner))
        self.assert_status(429, lambda: self.call("POST", self.root + "/candidates", body, self.peer))
        self.assertEqual(len(self.call("POST", self.root + "/candidates", dict(body, source="demo"), self.peer)["candidates"]), 3)

    @patch("convoy_server.urlopen")
    def test_overpass_incomplete_response_is_not_reported_as_empty_success(self, request):
        request.return_value.__enter__.return_value.read.return_value = b'{"remark":"runtime error: timeout","elements":[]}'
        self.assert_status(502, lambda: osm_places("restaurant", 37.5, 127))


if __name__ == "__main__":
    unittest.main(verbosity=2)
