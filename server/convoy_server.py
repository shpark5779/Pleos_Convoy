"""Local convoy prototype. Python standard library only; rooms live in memory."""
import argparse
import copy
import json
import math
import secrets
import threading
import time
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from journey import Journey
from tmap_service import TmapError
from opinet_service import Opinet, OpinetError

sys.modules.setdefault("convoy_server", sys.modules[__name__])


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def require(condition, message, status=400):
    if not condition:
        raise ApiError(status, message)


def text(value, limit=100):
    require(isinstance(value, str) and 0 < len(value.strip()) <= limit, "문자열 입력을 확인하세요.")
    return value.strip()


def number(value, low, high):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
            "좌표 또는 숫자 범위를 확인하세요.")
    return float(value)


def place(value):
    require(isinstance(value, dict), "장소 정보가 필요합니다.")
    return {"name": text(value.get("name")),
            "latitude": number(value.get("latitude"), -90, 90),
            "longitude": number(value.get("longitude"), -180, 180),
            "poi_id": str(value.get("poi_id", ""))[:120],
            "address": str(value.get("address", ""))[:200],
            "source": value.get("source") if value.get("source") in ("demo", "osm", "tmap") else "manual"}


def distance_km(a, b):
    lat1, lat2 = map(math.radians, (a["latitude"], b["latitude"]))
    dlat = lat2 - lat1
    dlon = math.radians(b["longitude"] - a["longitude"])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def osm_places(category, lat, lon):
    selector = '["highway"="services"]' if category == "rest_stop" else '["amenity"="restaurant"]'
    query = f'[out:json][timeout:20][maxsize:8388608];nwr(around:15000,{lat:.5f},{lon:.5f}){selector};out center tags 80;'
    request = Request("https://overpass-api.de/api/interpreter",
                      data=urlencode({"data": query}).encode(),
                      headers={"User-Agent": "PleosConvoyPrototype/0.1 (local development)"})
    try:
        with urlopen(request, timeout=25) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        require(len(raw) <= 8 * 1024 * 1024, "장소 검색 응답이 너무 큽니다.", 502)
        result = json.loads(raw)
        require(not result.get("remark"), "장소 검색 서버가 조회를 완료하지 못했습니다.", 502)
    except (URLError, TimeoutError, ValueError) as error:
        raise ApiError(502, "장소 검색 서버 연결 실패. 테스트 후보 또는 좌표 입력을 사용하세요.") from error
    candidates = []
    for item in result.get("elements", []):
        tags = item.get("tags", {})
        center = item.get("center", item)
        if not tags.get("name") or "lat" not in center or "lon" not in center:
            continue
        candidates.append(place({"name": tags["name"], "latitude": center["lat"],
                                 "longitude": center["lon"], "source": "osm",
                                 "address": tags.get("addr:full", "")}))
    return candidates


class Convoy:
    def __init__(self):
        self.rooms = {}
        # ponytail: one lock for at most 100 local test rooms; use durable transactions before deployment.
        self.lock = threading.RLock()
        self.last_osm_search = 0.0
        self.journey = Journey(self)
        self.opinet = Opinet()

    def member(self, room, token):
        require(token.isascii(), "잘못된 인증 토큰입니다.", 403)
        for member in room["members"].values():
            if secrets.compare_digest(member["token"], token):
                return member
        raise ApiError(403, "참가 인증이 만료되었거나 잘못되었습니다.")

    def add_member(self, room, name, role="driver"):
        require(role in ("driver", "passenger"), "참가 역할을 확인하세요.")
        require(len(room["members"]) < 8, "이 시제품은 최대 8대까지 참가할 수 있습니다.", 409)
        member = {"id": secrets.token_hex(6), "name": text(name, 30),
                  "token": secrets.token_urlsafe(32), "location": None, "last_seen": time.time(), "role": role}
        room["members"][member["id"]] = member
        return member

    def snapshot(self, room):
        result = copy.deepcopy(room)
        result.pop("created_at")
        for member in result["members"].values():
            member.pop("token")
        return result

    def proposal(self, room, body):
        proposal = room.get("proposal")
        require(proposal and proposal["id"] == body.get("proposal_id"), "이미 바뀐 제안입니다. 새로 확인하세요.", 409)
        return proposal

    def finish(self, proposal):
        if proposal and proposal["status"] == "approved":
            for application in proposal["applications"].values():
                if application["state"] == "requested" and time.time() - application["updated_at"] > 90:
                    application.update(state="unconfirmed", detail="응답 기한 초과. 실제 내비를 확인하세요.")
            if all(a["state"] in ("succeeded", "failed", "unconfirmed") for a in proposal["applications"].values()):
                proposal["status"] = "completed"

    def handle(self, method, path, body, token):
        parts = path.strip("/").split("/")
        if method == "POST" and len(parts) == 3 and parts[0] == "rooms" and parts[2] == "fuel":
            with self.lock:
                room = self.rooms.get(parts[1].upper())
                require(room is not None, "모임을 찾지 못했습니다.", 404)
                member = self.member(room, token)
                location = copy.deepcopy(member.get("location"))
            if body.get("action") == "detail":
                return self.opinet.detail(body.get("id"))
            require(location is not None, "주유소를 찾으려면 차량 위치가 필요합니다.", 409)
            require(time.time()-location['measured_at'] <= 120, "차량 위치가 오래됐습니다. GPS 위치를 갱신하세요.", 409)
            return self.opinet.nearby(location['latitude'], location['longitude'], body.get('product', 'B027'))
        if method == "POST" and len(parts) == 3 and parts[0] == "rooms" and parts[2] == "journey":
            return self.journey.handle(parts[1], token, body)
        with self.lock:
            now = time.time()
            for code in list(self.rooms):
                if now - self.rooms[code]["created_at"] > 6 * 3600:
                    del self.rooms[code]
            if method == "GET" and path == "/health":
                return {"status": "ok", "version": "0.1"}
            if method == "POST" and path == "/rooms":
                require(len(self.rooms) < 100, "테스트 모임 개수 제한입니다.", 429)
                destination = place(body.get("destination"))
                code = secrets.token_hex(4).upper()
                while code in self.rooms:
                    code = secrets.token_hex(4).upper()
                room = {"code": code, "destination": destination, "members": {}, "proposal": None, "created_at": now, "revision": 1}
                member = self.add_member(room, body.get("name"))
                room.update(leader_id=member["id"], waypoints=[], plan_version=0, arrival_at=None, driving_mode="individual")
                self.rooms[code] = room
                return {"code": code, "member_id": member["id"], "token": member["token"], "room": self.snapshot(room)}
            parts = path.strip("/").split("/")
            require(len(parts) in (2, 3) and parts[0] == "rooms", "없는 API 주소입니다.", 404)
            room = self.rooms.get(parts[1].upper())
            require(room is not None, "모임을 찾지 못했습니다. 서버 재시작 시 새 모임을 만드세요.", 404)
            self.finish(room["proposal"])
            operation = parts[2] if len(parts) == 3 else ""
            if method == "POST" and operation == "join":
                require(not room["proposal"] or room["proposal"]["status"] not in ("pending", "approved"),
                        "제안 처리 중에는 참가할 수 없습니다.", 409)
                member = self.add_member(room, body.get("name"), body.get("role", "driver"))
                room["revision"] += 1
                return {"code": room["code"], "member_id": member["id"], "token": member["token"], "room": self.snapshot(room)}
            member = self.member(room, token)
            member["last_seen"] = now
            room["revision"] += 1
            if method == "GET" and operation == "":
                return self.snapshot(room)
            require(method == "POST", "지원하지 않는 메서드입니다.", 405)
            if operation == "location":
                latitude = number(body.get("latitude"), -90, 90)
                longitude = number(body.get("longitude"), -180, 180)
                measured_at = number(body.get("measured_at"), now - 30, now + 5)
                require(body.get("source") in ("sdk", "demo", "phone"), "위치 출처가 필요합니다.")
                if member["location"] and measured_at < member["location"]["measured_at"]:
                    return self.snapshot(room)
                member["location"] = {"latitude": latitude, "longitude": longitude,
                                      "measured_at": measured_at, "source": body["source"]}
            elif operation == "proposals":
                drivers = {mid: m for mid, m in room["members"].items() if m["role"] == "driver"}
                require(len(drivers) >= 2, "최소 두 대가 참가해야 합니다.", 409)
                previous = room["proposal"]
                require(not previous or previous["status"] in ("rejected", "cancelled", "completed"),
                        "진행 중인 제안을 먼저 완료하거나 취소하세요.", 409)
                kind = body.get("kind", "stop")
                require(kind in ("stop", "plan"), "제안 종류를 확인하세요.")
                require(kind != "plan" or room["leader_id"] == member["id"], "선두 차량만 이동 계획을 제안할 수 있습니다.", 403)
                target = place(body.get("place"))
                if kind == "plan":
                    raw_vias = body.get("waypoints", [])
                    require(isinstance(raw_vias, list) and len(raw_vias) <= 5, "경유지는 최대 5개입니다.")
                    new_vias = [place(p) for p in raw_vias]
                    mode = body.get("driving_mode", "individual")
                    require(mode in ("same", "individual"), "주행 모드를 확인하세요.")
                    arrival = body.get("arrival_at")
                    if arrival is not None:
                        arrival = number(arrival, now, now+7*86400)
                else:
                    require(len(room["waypoints"]) < 5, "경유지는 최대 5개입니다. 선두 차량이 계획을 정리하세요.", 409)
                    new_vias, mode, arrival = [*room["waypoints"], target], room["driving_mode"], room["arrival_at"]
                room["proposal"] = {"id": secrets.token_hex(8), "place": target, "kind": kind,
                                    "plan": {"destination": target if kind == "plan" else room["destination"],
                                             "waypoints": new_vias, "driving_mode": mode, "arrival_at": arrival},
                                    "created_at": now, "proposer_id": member["id"], "status": "pending",
                                    "votes": {mid: (True if mid == member["id"] else None) for mid in drivers},
                                    "applications": {mid: {"state": "not_requested", "detail": "", "updated_at": now}
                                                     for mid in drivers}}
            elif operation == "decisions":
                proposal = self.proposal(room, body)
                require(member["id"] in proposal["votes"], "동승자는 제안만 할 수 있습니다. 운전자가 승인하세요.", 403)
                require(proposal["status"] == "pending", "이미 결정된 제안입니다.", 409)
                require(type(body.get("approve")) is bool, "승인 여부가 필요합니다.")
                proposal["votes"][member["id"]] = body["approve"]
                if not body["approve"]:
                    proposal["status"] = "rejected"
                elif all(v is True for v in proposal["votes"].values()):
                    proposal["status"] = "approved"
                    room.update(copy.deepcopy(proposal["plan"]))
                    room["plan_version"] += 1
            elif operation == "applications":
                proposal = self.proposal(room, body)
                require(proposal["status"] in ("approved", "completed"), "전원 승인 전에는 경로를 바꿀 수 없습니다.", 409)
                require(proposal["votes"].get(member["id"]) is True, "이 차량의 승인이 필요합니다.", 403)
                application = proposal["applications"][member["id"]]
                state = body.get("state")
                if state == "requested":
                    require(application["state"] in ("not_requested", "failed", "unconfirmed"), "이미 요청했거나 반영된 경로입니다.", 409)
                    application.update(state=state, attempt_id=secrets.token_hex(8), detail="내비게이션 응답 대기", updated_at=now)
                    proposal["status"] = "approved"
                else:
                    require(state in ("succeeded", "failed", "unconfirmed"), "잘못된 반영 상태입니다.")
                    require(application["state"] == "requested" and body.get("attempt_id") == application.get("attempt_id"),
                            "현재 요청과 맞지 않는 응답입니다.", 409)
                    application.update(state=state, detail=str(body.get("detail", ""))[:200], updated_at=now)
                self.finish(proposal)
            elif operation == "cancel":
                proposal = self.proposal(room, body)
                require(proposal["proposer_id"] == member["id"] and proposal["status"] == "pending", "제안자는 대기 중인 제안만 취소할 수 있습니다.", 409)
                proposal["status"] = "cancelled"
            elif operation == "leave":
                proposal = room["proposal"]
                require(not proposal or proposal["status"] != "approved", "경로 반영 처리 중에는 모임을 나갈 수 없습니다.", 409)
                if proposal and proposal["status"] == "pending":
                    proposal["status"] = "cancelled"
                del room["members"][member["id"]]
                if room["leader_id"] == member["id"]:
                    room["leader_id"] = next((mid for mid, m in room["members"].items() if m["role"] == "driver"), "")
                if not room["members"]:
                    del self.rooms[room["code"]]
                return {"left": True}
            elif operation == "profile":
                require(member["role"] == "driver", "운전자 차량의 배터리 정보만 설정하세요.", 403)
                member["battery_pct"] = None if body.get("battery_pct") is None else number(body["battery_pct"], 0, 100)
                member["range_km"] = None if body.get("range_km") is None else number(body["range_km"], 0, 1500)
                member["battery_source"] = "user_input"
            elif operation == "candidates":
                category, source = body.get("category"), body.get("source")
                require(category in ("rest_stop", "restaurant") and source in ("demo", "osm"), "검색 종류를 확인하세요.")
                locations = [m["location"] for m in room["members"].values()]
                require(len(locations) >= 2 and all(loc and now - loc["measured_at"] <= 30 for loc in locations),
                        "두 대 이상 모든 차량의 최근 30초 이내 위치가 필요합니다.", 409)
                lat = sum(loc["latitude"] for loc in locations) / len(locations)
                lon = sum(loc["longitude"] for loc in locations) / len(locations)
                if source == "demo":
                    candidates = [place({"name": f"{'휴게소' if category == 'rest_stop' else '식사 장소'} 테스트 {i + 1}",
                                        "latitude": max(-90, min(90, lat + offset)), "longitude": lon,
                                        "source": "demo"}) for i, offset in enumerate((0.01, -0.02, 0.04))]
                else:
                    require(now - self.last_osm_search >= 60, "실제 장소 검색은 서버 전체에서 1분에 한 번 가능합니다.", 429)
                    self.last_osm_search = now
                    # Network work runs outside the room lock so other vehicles can continue polling.
                    return {"osm_query": (category, lat, lon), "locations": copy.deepcopy(locations)}
                return self.rank(candidates, locations)
            else:
                raise ApiError(404, "없는 API 주소입니다.")
            return self.snapshot(room)

    @staticmethod
    def rank(candidates, locations, source=None):
        for candidate in candidates:
            candidate["max_straight_km"] = round(max(distance_km(loc, candidate) for loc in locations), 2)
        return {"candidates": sorted(candidates, key=lambda p: p["max_straight_km"])[:10],
                "basis": "최대 직선거리순 · 도로 방향/우회 시간/영업 여부 미확인",
                "attribution": "© OpenStreetMap contributors · https://www.openstreetmap.org/copyright"
                if source == "osm" or (candidates and candidates[0]["source"] == "osm") else "테스트 좌표 · 실제 장소가 아닙니다."}


class Handler(BaseHTTPRequestHandler):
    server_version = "ConvoyPrototype/0.1"

    def do_GET(self):
        self.respond("GET")

    def do_POST(self):
        self.respond("POST")

    def respond(self, method):
        try:
            self.connection.settimeout(5)
            if method == "GET" and self.path in ("/", "/journey", "/driving.js"):
                script = self.path == "/driving.js"
                data = Path(__file__).with_name("driving.js" if script else "journey.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ("application/javascript" if script else "text/html")+"; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(data)
                return
            size = int(self.headers.get("Content-Length", "0"))
            require(0 <= size <= 16384, "요청 크기 제한입니다.", 413)
            body = json.loads(self.rfile.read(size)) if size else {}
            require(isinstance(body, dict), "JSON 객체가 필요합니다.")
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            result = self.server.convoy.handle(method, self.path, body, token)
            if "osm_query" in result:
                result = self.server.convoy.rank(osm_places(*result["osm_query"]), result["locations"], source="osm")
            self.send_json(200, result)
        except ApiError as error:
            self.send_json(error.status, {"error": error.message})
        except (TmapError, OpinetError) as error:
            self.send_json(502, {"error": str(error)})
        except (ValueError, UnicodeError):
            self.send_json(400, {"error": "올바른 JSON 요청이 필요합니다."})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            self.log_error("unexpected server error")
            self.send_json(500, {"error": "서버 내부 오류입니다."})

    def send_json(self, status, body):
        data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def make_server(host="127.0.0.1", port=8765):
    server = ThreadingHTTPServer((host, port), Handler)
    server.convoy = Convoy()
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = make_server(host=args.host, port=args.port)
    print(f"Convoy development server: http://{args.host}:{server.server_port} (memory only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
