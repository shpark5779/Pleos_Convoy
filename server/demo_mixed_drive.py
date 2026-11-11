"""Device 1: native TMAP guidance. Device 2: convoy map. GPS replay + mid-drive waypoint.

Explicit emulator demo, not run by tests. Requires local server, debug APK and two
running emulators. TMAP REST supplies road geometry; native SDK quota is separate.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import time
from xml.etree import ElementTree as ET

from demo_city_drive import ROOT, PACKAGE, ORIGINS, DESTINATION, MEETING, api, adb, edges, at
from tmap_service import km


class RendezvousReplay:
    """Follow road geometry; hold early arrivals and release all vehicles together at each via."""
    def __init__(self, paths, waypoints, speed, hold_seconds=6):
        self.paths, self.speed, self.hold_seconds = paths, speed, hold_seconds
        self.progress = [0.0] * len(paths)
        self.checkpoint = 0
        self.release_at = None
        self.events = []
        self.arrivals = {}
        self.stops = []
        for path, total in paths:
            distances, previous = [], 0.0
            for waypoint in waypoints:
                candidates = []
                scale = math.cos(math.radians(waypoint["latitude"]))
                for start, end, a, b in path:
                    if end < previous:
                        continue
                    x, y = (b[0]-a[0])*scale, b[1]-a[1]
                    t = ((waypoint["longitude"]-a[0])*scale*x+(waypoint["latitude"]-a[1])*y)/(x*x+y*y or 1)
                    t = max(0, min(1, max(t, (previous-start)/(end-start))))
                    point = {"longitude": a[0]+(b[0]-a[0])*t, "latitude": a[1]+(b[1]-a[1])*t}
                    candidates.append((km(point, waypoint)*1000, start+(end-start)*t))
                error, distance = min(candidates)
                if error > 60:
                    raise ValueError(f"{waypoint.get('name', '경유지')}: 도로 경로와 {error:.0f}m 떨어져 합류를 확인할 수 없습니다.")
                distances.append(distance)
                previous = distance
            self.stops.append(distances)
        self.waypoints = waypoints

    def advance(self, seconds, now):
        if self.release_at is not None:
            if now < self.release_at:
                return self.positions()
            seconds = min(seconds, max(0, now-self.release_at))
            self.events.append({"kind": "departed_together", "waypoint": self.checkpoint+1,
                                "at": now, "positions": self.positions()})
            self.checkpoint += 1
            self.release_at, self.arrivals = None, {}
        for i, (_, total) in enumerate(self.paths):
            limit = self.stops[i][self.checkpoint] if self.checkpoint < len(self.waypoints) else total
            self.progress[i] = min(limit, self.progress[i] + max(0, seconds)*self.speed)
            if self.checkpoint < len(self.waypoints) and self.progress[i] >= limit and i not in self.arrivals:
                self.arrivals[i] = now
                self.events.append({"kind": "arrived", "waypoint": self.checkpoint+1, "vehicle": i,
                                    "at": now, "position": self.positions()[i]})
        if self.checkpoint < len(self.waypoints) and len(self.arrivals) == len(self.paths):
            self.release_at = now + self.hold_seconds
            self.events.append({"kind": "joined", "waypoint": self.checkpoint+1, "at": now,
                                "wait_seconds": max(self.arrivals.values())-min(self.arrivals.values()),
                                "positions": self.positions()})
        return self.positions()

    def positions(self):
        return [at(path, distance) for (path, _), distance in zip(self.paths, self.progress)]

    def finished(self):
        return self.checkpoint == len(self.waypoints) and all(d >= total for d, (_, total) in zip(self.progress, self.paths))

    def speeds_kph(self):
        speeds = []
        for i, (_, total) in enumerate(self.paths):
            limit = self.stops[i][self.checkpoint] if self.checkpoint < len(self.waypoints) else total
            speeds.append(0.0 if self.progress[i] >= limit else self.speed*3.6)
        return speeds


def paths_from(result, sessions):
    paths = [edges(result["routes"][s["member_id"]]) for s in sessions]
    if any(not path or total <= 0 for path, total in paths):
        raise ValueError("GPS 재생에 필요한 도로 경로가 비어 있습니다.")
    return paths


def positions_at(paths, elapsed, speed):
    return [at(path, min(total, max(0, elapsed) * speed)) for path, total in paths]


def publish(devices, sessions, positions):
    for device, session, (lon, lat) in zip(devices, sessions, positions):
        adb(device, "emu", "geo", "fix", str(lon), str(lat))
        api("/rooms/" + session["code"] + "/location", {
            "longitude": lon, "latitude": lat, "measured_at": time.time(), "source": "demo"}, session)


def launch(device, session, screen):
    adb(device, "shell", "am", "force-stop", PACKAGE)
    for permission in ("android.permission.ACCESS_COARSE_LOCATION", "android.permission.ACCESS_FINE_LOCATION",
                       "pleos.car.permission.FUSED_LOCATION"):
        adb(device, "shell", "pm", "grant", "--user", "current", PACKAGE, permission)
    user = adb(device, "shell", "am", "get-current-user").decode().strip()
    prefs = ET.Element("map")
    for key, value in {"server": "http://10.0.2.2:8765", "code": session["code"],
                       "member_id": session["member_id"], "token": session["token"]}.items():
        ET.SubElement(prefs, "string", name=key).text = value
    adb(device, "exec-in", "run-as", PACKAGE, "--user", user, "mkdir", "-p", "shared_prefs")
    adb(device, "exec-in", "run-as", PACKAGE, "--user", user, "tee", "shared_prefs/convoy.xml",
        data=ET.tostring(prefs, encoding="utf-8", xml_declaration=True))
    adb(device, "shell", "am", "start", "-n", PACKAGE + "/com.example.pleosprojectv01.MainActivity",
        "--es", "demo_screen", screen)


def add_waypoint(sessions):
    """Auto-vote only for these two explicitly simulated vehicles. No SDK success receipt."""
    owner, peer = sessions
    root = "/rooms/" + owner["code"]
    proposal = api(root + "/proposals", {"place": dict(MEETING, source="demo")}, owner)["proposal"]
    room = api(root + "/decisions", {"proposal_id": proposal["id"], "approve": True}, peer)
    if room["proposal"]["status"] != "approved":
        raise RuntimeError("가상 경유지가 전원 승인되지 않았습니다.")
    return room["plan_version"]


def calculate(devices, sessions, positions, interval):
    # Hold both GPS positions while REST is working. Do not jump forward after a slow response.
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(api, "/rooms/" + sessions[0]["code"] + "/journey",
                             {"action": "overview"}, sessions[0])
        while not future.done():
            publish(devices, sessions, positions)
            time.sleep(interval)
        return paths_from(future.result(), sessions)


def run(args):
    devices = [args.device1, args.device2]
    if devices[0] == devices[1] or any(not d.startswith("emulator-") for d in devices):
        raise ValueError("서로 다른 에뮬레이터 두 대를 지정하세요.")
    for device in devices:
        if adb(device, "get-state").decode().strip() != "device":
            raise RuntimeError(f"에뮬레이터 연결을 확인하세요: {device}")
    owner = api("/rooms", {"name": "1번 · TMAP 내비 (가상 GPS)", "destination": DESTINATION})
    peer = api("/rooms/" + owner["code"] + "/join", {"name": "2번 · 지도 (가상 GPS)"})
    sessions = [owner, peer]
    positions = [[p["longitude"], p["latitude"]] for p in ORIGINS]
    publish(devices, sessions, positions)
    paths = calculate(devices, sessions, positions, args.interval)
    state = ROOT / "build/mixed-drive-session.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"sessions": sessions, "devices": devices}, ensure_ascii=False), encoding="utf-8")
    for device, session, screen in zip(devices, sessions, ("native", "map")):
        launch(device, session, screen)
    print("1번: TMAP 실제 안내 + 가상 GPS / 2번: 동행 지도 + 가상 GPS", flush=True)
    print("SDK가 429이면 자동 재요청 중단. 지도/GPS 재생 성공과 SDK 안내 성공은 별개입니다.", flush=True)
    start = last_tick = time.monotonic()
    changed = False
    speed = args.speed_kph / 3.6
    replay = RendezvousReplay(paths, [], speed)
    while True:
        now = time.monotonic()
        if now - start > args.max_seconds:
            raise TimeoutError("시연 시간 제한에 도달했습니다. GPS 재생을 중단합니다.")
        positions = replay.advance(now - last_tick, now-start)
        last_tick = now
        publish(devices, sessions, positions)
        if not changed and now - start >= args.waypoint_after:
            version = add_waypoint(sessions)
            print(f"가상 경유지 승인: {MEETING['name']} / 계획 {version}. 현재 위치에서 재탐색.", flush=True)
            paths = calculate(devices, sessions, positions, args.interval)
            replay = RendezvousReplay(paths, [MEETING], speed)
            last_tick = time.monotonic()
            changed = True
        elif replay.finished():
            if not changed:
                raise RuntimeError("경유지 추가 전에 도착했습니다. --waypoint-after를 줄이세요.")
            print("두 차량의 가상 GPS가 수정 경로의 끝에 도착했습니다. SDK 도착 검증은 미수행.", flush=True)
            return
        time.sleep(args.interval)


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("0보다 큰 유한수를 입력하세요.")
    return number


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device1", default="emulator-5554")
    parser.add_argument("--device2", default="emulator-5556")
    parser.add_argument("--speed-kph", type=positive, default=36)
    parser.add_argument("--interval", type=positive, default=1)
    parser.add_argument("--waypoint-after", type=positive, default=45, help="경유지를 추가할 주행 시작 후 초")
    parser.add_argument("--max-seconds", type=positive, default=900)
    try:
        run(parser.parse_args())
    except KeyboardInterrupt:
        print("GPS 재생 중단. 마지막 가상 위치는 에뮬레이터에 남습니다.")
