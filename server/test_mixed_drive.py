"""Offline approval/rerouting checks; no devices or provider calls."""
import argparse
import time
import unittest
from unittest.mock import patch

from convoy_server import Convoy
from demo_mixed_drive import (DESTINATION, ORIGINS, MEETING, add_waypoint, calculate,
                              paths_from, positions_at, positive, RendezvousReplay, edges)


class MixedDriveTest(unittest.TestCase):
    def setUp(self):
        self.store = Convoy()
        owner = self.store.handle("POST", "/rooms", {"name": "A", "destination": DESTINATION}, "")
        self.root = "/rooms/" + owner["code"]
        peer = self.store.handle("POST", self.root + "/join", {"name": "B"}, "")
        self.sessions = [owner, peer]
        for session, origin in zip(self.sessions, ORIGINS):
            self.call(self.root + "/location", dict(origin, measured_at=time.time(), source="demo"), session)

    def call(self, path, body=None, session=None):
        return self.store.handle("GET" if body is None else "POST", path, body or {}, (session or self.sessions[0])["token"])

    @staticmethod
    def route(origin, destination, vias):
        points = [[p["longitude"], p["latitude"]] for p in [origin, *vias, destination]]
        return {"segments": [points], "meters": 2000, "seconds": 200, "computed_at": time.time()}

    def test_waypoint_changes_paths_only_after_approval_from_current_positions(self):
        with patch.object(self.store.journey.tmap, "route", side_effect=self.route):
            before = paths_from(self.call(self.root + "/journey", {"action": "overview"}), self.sessions)
            positions = positions_at(before, elapsed=20, speed=10)
            for session, (lon, lat) in zip(self.sessions, positions):
                self.call(self.root + "/location", {"longitude": lon, "latitude": lat,
                          "measured_at": time.time(), "source": "demo"}, session)
            proposal = self.call(self.root + "/proposals", {"place": dict(MEETING, source="demo")})["proposal"]
            self.assertEqual(self.call(self.root)["waypoints"], [])
            self.call(self.root + "/cancel", {"proposal_id": proposal["id"]})
            with patch("demo_mixed_drive.api", side_effect=self.call):
                self.assertEqual(add_waypoint(self.sessions), 1)
                with patch("demo_mixed_drive.adb"):
                    after = calculate(["emulator-a", "emulator-b"], self.sessions, positions, .001)
        for position, (path, total) in zip(positions, after):
            self.assertEqual(path[0][2], position)
            self.assertIn([MEETING["longitude"], MEETING["latitude"]], [edge[3] for edge in path])
            self.assertEqual(positions_at([(path, total)], 0, 10)[0], position)
        room = self.call(self.root)
        self.assertEqual(room["proposal"]["status"], "approved")
        self.assertTrue(all(m["location"]["source"] == "demo" for m in room["members"].values()))
        self.assertTrue(all(a["state"] == "not_requested" for a in room["proposal"]["applications"].values()))

    def test_gps_interpolation_speed_and_arrival_clamp(self):
        path = [(0, 100, [127., 36.], [127.001, 36.])]
        self.assertEqual(positions_at([(path, 100)], 5, 10), [[127.0005, 36.]])
        self.assertEqual(positions_at([(path, 100)], 100, 10), [[127.001, 36.]])
        self.assertEqual(positions_at([(path, 100)], -1, 10), [[127., 36.]])

    def test_invalid_replay_settings_and_empty_geometry(self):
        for value in ("0", "-1", "nan", "inf"):
            with self.assertRaises(argparse.ArgumentTypeError):
                positive(value)
        with self.assertRaises(ValueError):
            paths_from({"routes": {"a": {"segments": [[]]}}}, [{"member_id": "a"}])
        road = edges({"segments": [[[127., 36.], [127.001, 36.]]]})
        with self.assertRaises(ValueError):
            RendezvousReplay([road, road], [{"latitude": 36.01, "longitude": 127.001}], speed=10)

    def test_early_arrival_waits_then_both_depart_each_waypoint(self):
        via = {"latitude": 36., "longitude": 127.001}
        second = {"latitude": 36., "longitude": 127.0015}
        paths = [edges({"segments": [[[start, 36.], [127.001, 36.], [127.0015, 36.], [127.002, 36.]]]})
                 for start in (127., 127.0005)]
        replay = RendezvousReplay(paths, [via, second], speed=10, hold_seconds=6)
        positions = replay.advance(5, 5)
        self.assertEqual(replay.speeds_kph(), [36, 0])
        early_position = positions[1]
        positions = replay.advance(1, 6)
        self.assertEqual(positions[1], early_position, "early vehicle must stay at the waypoint")
        replay.advance(4, 10)
        self.assertEqual(replay.release_at, 16)
        self.assertEqual(replay.speeds_kph(), [0, 0])
        joined_positions = replay.positions()
        self.assertEqual(replay.advance(5, 15), joined_positions)
        replay.advance(1, 16)
        moved = replay.advance(1, 17)
        self.assertNotEqual(moved[0], joined_positions[0])
        self.assertNotEqual(moved[1], joined_positions[1])
        self.assertAlmostEqual(moved[0][0], moved[1][0])
        self.assertEqual(replay.speeds_kph(), [36, 36])
        for now in range(18, 45):
            replay.advance(1, now)
        self.assertTrue(replay.finished())
        self.assertEqual(replay.speeds_kph(), [0, 0])
        self.assertEqual(len([e for e in replay.events if e["kind"] == "joined"]), 2)
        self.assertEqual(len([e for e in replay.events if e["kind"] == "departed_together"]), 2)


if __name__ == "__main__":
    unittest.main()
