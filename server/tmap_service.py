"""TMAP road routing and POI search. Standard library; keys stay in local config."""
import copy
import json
import math
import os
from pathlib import Path
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen


class TmapError(Exception):
    pass


def settings():
    values = {}
    path = Path(__file__).resolve().parent.parent / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    for key in ("TMAP_APP_KEY", "TMAP_MAP_KEY", "TMAP_DAILY_BUDGET"):
        if key in os.environ:
            values[key] = os.environ[key].strip()
    return values


def km(a, b):
    lat1, lat2 = math.radians(a["latitude"]), math.radians(b["latitude"])
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(math.radians(b["longitude"]-a["longitude"])/2)**2
    return 12742 * math.asin(math.sqrt(min(1, max(0, h))))


class Tmap:
    def __init__(self, key=None):
        config = settings()
        self.key = config.get("TMAP_APP_KEY", "") if key is None else key
        self.map_key = config.get("TMAP_MAP_KEY") or self.key
        self.budget = int(config.get("TMAP_DAILY_BUDGET", "600"))
        self.cache = {}
        self.lock = threading.RLock()
        self.day, self.requests = "", 0

    def request(self, path, body=None):
        if not self.key:
            raise TmapError("서버 .env에 TMAP_APP_KEY를 설정하세요.")
        with self.lock:
            day = time.strftime("%Y-%m-%d")
            if day != self.day:
                self.day, self.requests = day, 0
            if self.requests >= self.budget:
                raise TmapError("이 서버의 일일 TMAP 호출 예산을 소진했습니다. 대시보드 사용량을 확인하세요.")
            self.requests += 1
        request = Request("https://apis.openapi.sk.com/tmap/" + path,
                          data=None if body is None else json.dumps(body).encode(),
                          headers={"appKey": self.key, "Accept": "application/json", "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise TmapError("TMAP 응답 크기 제한을 초과했습니다.")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise TmapError("TMAP 응답 형식을 확인할 수 없습니다.")
            return data
        except HTTPError as error:
            # Do not return provider request bodies, URLs or app keys to clients.
            message = {401: "TMAP 인증 키 또는 상품 연결을 확인하세요.", 403: "TMAP 상품 권한 또는 호출 제한을 확인하세요.",
                       429: "TMAP 호출 한도에 도달했습니다. 잠시 후 다시 시도하세요."}.get(error.code, "TMAP 요청을 처리하지 못했습니다.")
            raise TmapError(f"{message} (HTTP {error.code})") from None
        except (URLError, TimeoutError, ValueError) as error:
            raise TmapError("TMAP 연결 또는 응답 처리에 실패했습니다.") from None

    def cached(self, key, seconds, work):
        # ponytail: in-memory cache for this local prototype; shared quotas need durable accounting in production.
        with self.lock:
            value = self.cache.get(key)
            if value and time.time() - value[0] < seconds:
                return copy.deepcopy(value[1])
        result = work()
        with self.lock:
            if len(self.cache) >= 256:
                del self.cache[next(iter(self.cache))]
            self.cache[key] = (time.time(), copy.deepcopy(result))
        return result

    def route(self, origin, destination, waypoints=()):
        if len(waypoints) > 5:
            raise TmapError("자동차 경로 API는 경유지를 최대 5개까지 지원합니다.")
        points = [origin, *waypoints, destination]
        key = ("route", tuple((round(p["longitude"], 4), round(p["latitude"], 4)) for p in points))
        def work():
            body = {"startX": origin["longitude"], "startY": origin["latitude"],
                    "endX": destination["longitude"], "endY": destination["latitude"],
                    "startName": quote(origin.get("name", "출발")), "endName": quote(destination.get("name", "목적지")),
                    "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO", "searchOption": 0, "trafficInfo": "Y"}
            if waypoints:
                body["passList"] = "_".join(f'{p["longitude"]},{p["latitude"]}' for p in waypoints)
            data = self.request("routes?version=1", body)
            features = data.get("features", [])
            summary = next((f.get("properties", {}) for f in features if "totalTime" in f.get("properties", {})), None)
            if summary is None:
                raise TmapError("TMAP 경로를 찾지 못했습니다.")
            path, segments, turns = [], [], []
            for feature in features:
                geom, props = feature.get("geometry", {}), feature.get("properties", {})
                if geom.get("type") == "LineString":
                    # TMAP also appends unindexed virtual waypoint connectors. They are not road links.
                    if "lineIndex" not in props:
                        continue
                    segment = [[float(c[0]), float(c[1])] for c in geom.get("coordinates", [])]
                    if len(segment) < 2:
                        continue
                    segments.append(segment)
                    path.extend(segment)
                elif geom.get("type") == "Point" and props.get("description"):
                    turns.append({"point": geom.get("coordinates", [])[:2], "description": props["description"],
                                  "turn_type": props.get("turnType")})
            seconds, meters = float(summary["totalTime"]), float(summary["totalDistance"])
            if not path or not math.isfinite(seconds) or not math.isfinite(meters) or seconds < 0 or meters < 0:
                raise TmapError("TMAP 경로 데이터가 유효하지 않습니다.")
            return {"provider": "tmap", "path": path, "segments": segments, "turns": turns, "seconds": seconds, "meters": meters,
                    "computed_at": time.time(), "destination": destination, "waypoints": list(waypoints),
                    "notice": "TMAP 예상 경로·교통 시간 / 실시간 회전별 음성 길안내 아님"}
        return self.cached(key, 30, work)

    def search(self, query, center, count=3):
        key = ("poi", query, round(center["latitude"], 3), round(center["longitude"], 3), count)
        def work():
            params = {"version": 1, "searchKeyword": query, "centerLat": center["latitude"],
                      "centerLon": center["longitude"], "searchtypCd": "R", "radius": 30, "count": count,
                      "resCoordType": "WGS84GEO", "reqCoordType": "WGS84GEO"}
            data = self.request("pois?" + urlencode(params))
            items = data.get("searchPoiInfo", {}).get("pois", {}).get("poi", [])
            if isinstance(items, dict):
                items = [items]
            result = []
            for item in items:
                try:
                    lat = float(item.get("frontLat") or item.get("noorLat"))
                    lon = float(item.get("frontLon") or item.get("noorLon"))
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        continue
                    road = item.get("newAddressList", {}).get("newAddress", [])
                    address = road[0].get("fullAddressRoad", "") if isinstance(road, list) and road else ""
                    result.append({"name": str(item["name"])[:100], "latitude": lat, "longitude": lon,
                                   "poi_id": "", "tmap_poi_id": str(item.get("id", "")), "source": "tmap",
                                   "address": address[:200], "parking": "주차 가능 여부 미확인", "phone": item.get("telNo", ""),
                                   "charging_status": "충전기 가용 상태·커넥터·운영 시간 미확인"})
                except (KeyError, ValueError, TypeError):
                    continue
            return result
        return self.cached(key, 300, work)


def route_point(route, fraction):
    segments = route.get("segments", [route["path"]])
    edges = []
    for segment in segments:
        points = [{"latitude": p[1], "longitude": p[0]} for p in segment]
        edges.extend((a, b, km(a, b)) for a, b in zip(points, points[1:]))
    target, walked = sum(length for _, _, length in edges) * fraction, 0.0
    for a, b, length in edges:
        if walked + length >= target:
            ratio = 0 if length == 0 else (target-walked)/length
            return {key: a[key] + (b[key]-a[key])*ratio for key in ("latitude", "longitude")}
        walked += length
    last = segments[-1][-1]
    return {"latitude": last[1], "longitude": last[0]}
