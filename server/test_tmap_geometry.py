import unittest
from unittest.mock import patch

from tmap_service import Tmap, TmapError, route_point


class RouteGeometryTest(unittest.TestCase):
    def test_virtual_waypoint_connectors_do_not_extend_the_road_route(self):
        def line(points, properties):
            return {"geometry": {"type": "LineString", "coordinates": points}, "properties": properties}
        roads = [[[127.3, 36.3], [128.7, 36.0]], [[128.7, 36.0], [129.31, 35.54]]]
        features = [{"geometry": {"type": "Point", "coordinates": roads[0][0]},
                     "properties": {"totalTime": 1000, "totalDistance": 250000}}]
        features += [line(points, {"lineIndex": i}) for i, points in enumerate(roads)]
        # Auxiliary geometry comes AFTER arrival, as in the actual TMAP response.
        features += [line([[128.7, 36.0], [128.7001, 36.0001]],
                          {"description": "경유지와 연결된 가상의 라인입니다"}),
                     line([[129.1, 35.8], [129.1001, 35.8001]], {"name": ""})]
        service = Tmap(key="test-only")
        with patch.object(service, "request", return_value={"features": features}):
            route = service.route({"latitude": 36.3, "longitude": 127.3},
                                  {"latitude": 35.54, "longitude": 129.31},
                                  [{"latitude": 36.0, "longitude": 128.7}])
        self.assertEqual(route["segments"], roads)
        self.assertEqual(route["path"][-1], roads[-1][-1])
        self.assertEqual(len(route["path"]), 4)
        self.assertEqual((route["seconds"], route["meters"]), (1000, 250000))

    def test_progress_uses_road_segments_without_crossing_a_geometry_gap(self):
        segments = [[[0, 0], [1, 0]], [[10, 0], [11, 0]]]
        route = {"segments": segments, "path": [p for s in segments for p in s]}
        self.assertAlmostEqual(route_point(route, .5)["longitude"], 1)
        self.assertAlmostEqual(route_point(route, .75)["longitude"], 10.5)

    def test_auxiliary_geometry_alone_is_not_a_valid_driving_route(self):
        response = {"features": [
            {"geometry": {"type": "Point"}, "properties": {"totalTime": 10, "totalDistance": 100}},
            {"geometry": {"type": "LineString", "coordinates": [[127, 36], [128, 35]]},
             "properties": {"description": "경유지와 연결된 가상의 라인입니다"}}]}
        with patch.object(Tmap, "request", return_value=response), self.assertRaises(TmapError):
            Tmap(key="test-only").route({"latitude": 36, "longitude": 127}, {"latitude": 35, "longitude": 128})


if __name__ == "__main__":
    unittest.main()
