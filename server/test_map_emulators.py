"""Explicit live map-only emulator test: fixed destination, four starts, three added stops.

Run manually: python server/test_map_emulators.py
Uses TMAP REST and map APIs. Never launches NativeTmapActivity or navigation SDK.
Results/screenshots/session tokens are kept in ignored build/map-only-test-20261111.
"""
import argparse
import json
import re
import subprocess
import sys
import threading
import time

from demo_city_drive import ROOT, DESTINATION, ORIGINS, MEETING, api, adb
from demo_mixed_drive import launch, paths_from, publish, positive, RendezvousReplay
from tmap_service import km
from virtual_console import VirtualConsole


OUTPUT = ROOT / "build/map-only-test-20261111"
DEVICES = ["emulator-5554", "emulator-5556"]
STARTS = [
    ORIGINS,
    [{"name": "둔산동 남쪽", "latitude": 36.3478, "longitude": 127.3865},
     {"name": "갈마동 동쪽", "latitude": 36.3485, "longitude": 127.3755}],
    [{"name": "갈마역 부근", "latitude": 36.3530, "longitude": 127.3720},
     {"name": "월평동", "latitude": 36.3565, "longitude": 127.3655}],
    [{"name": "정부청사 서쪽", "latitude": 36.3590, "longitude": 127.3750},
     {"name": "둔산동 동쪽", "latitude": 36.3520, "longitude": 127.3940}],
]
STOPS = [dict(MEETING, source="demo"),
         {"name": "가상 경유점 2 · 문화예술단지 남쪽", "latitude": 36.3607, "longitude": 127.3899, "source": "demo"},
         {"name": "가상 경유점 3 · 수목원 남쪽 도로", "latitude": 36.362209289472084, "longitude": 127.38847295455385, "source": "demo"}]


def inspect(device, index):
    result = subprocess.run(["node", str(ROOT / "server/inspect_map.cjs"), device, str(9222 + index)],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    if result.returncode:
        raise RuntimeError(f"{device}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def check_views(version, waypoint_count):
    views = [inspect(device, i) for i, device in enumerate(DEVICES)]
    for view in views:
        assert "JourneyActivity" in (view["activity"] or ""), view["activity"]
        assert view["plan_version"] == view["route_version"] == version, "Map has an old route version"
        assert view["waypoint_count"] == waypoint_count, "Map waypoint list differs from the approved plan"
        assert view["map_ready"] and "실패" not in view["map_status"], view["map_status"]
        assert len(view["routes"]) == 2 and all(r["point_count"] > 1 for r in view["routes"])
        assert all(r["waypoint_count"] == waypoint_count for r in view["routes"])
        assert all(m["location"] and m["location"]["source"] == "demo" for m in view["members"])
        assert next(v["label"] for v in view["vehicle_labels"] if v["own"]) == "A"
        assert all(v["label"] == "B" for v in view["vehicle_labels"] if not v["own"])
    return views


def screenshot(case_dir, label):
    for device in DEVICES:
        (case_dir / f"{device}-{label}.png").write_bytes(adb(device, "exec-out", "screencap", "-p"))


def check_visible_maps(case_dir):
    for device in DEVICES:
        adb(device, "shell", "uiautomator", "dump", "/sdcard/convoy-console-ui.xml")
        xml = adb(device, "exec-out", "cat", "/sdcard/convoy-console-ui.xml")
        (case_dir / f"{device}-moving-ui.xml").write_bytes(xml)
        text = xml.decode("utf-8")
        assert "주행 중에는 사용할 수 없습니다" not in text, "Automotive is blocking the map while driving"
        assert "TMAP 지도" in text, "The visible screen does not contain the convoy map"


def calculate(sessions):
    result = api("/rooms/" + sessions[0]["code"] + "/journey", {"action": "overview"}, sessions[0])
    return result, paths_from(result, sessions)


def gps_check(device, expected):
    dump = adb(device, "shell", "dumpsys", "location").decode("utf-8", "replace")
    fixes = re.findall(r"(?:last location=|lastLocation=)?Location\[gps ([+-]?[\d.]+),([+-]?[\d.]+)", dump)
    if not fixes:
        raise AssertionError(f"{device}: Android GPS fix missing")
    distances = [km({"latitude": float(lat), "longitude": float(lon)},
                    {"latitude": expected[1], "longitude": expected[0]}) * 1000 for lat, lon in fixes]
    assert min(distances) < 15, f"{device}: Android GPS does not match replay coordinates"
    return round(min(distances), 2)


def run_case(number, origins, args):
    case_dir = OUTPUT / f"case-{number}"
    case_dir.mkdir(parents=True, exist_ok=True)
    owner = api("/rooms", {"name": "1번 지도 · " + origins[0]["name"], "destination": DESTINATION})
    root = "/rooms/" + owner["code"]
    peer = api(root + "/join", {"name": "2번 지도 · " + origins[1]["name"]})
    sessions = [owner, peer]
    (case_dir / "private-session.json").write_text(json.dumps(sessions), encoding="utf-8")
    positions = [[p["longitude"], p["latitude"]] for p in origins]
    lock, stop = threading.Lock(), threading.Event()
    heartbeat_errors = []
    consoles = []
    speeds = [0.0, 0.0]
    parked = True
    paused = True
    replay = None
    started = last_tick = time.monotonic()

    def publish_tick():
        # Caller holds the same lock used to change GPS and motion state.
        for console, speed in zip(consoles, speeds):
            console.motion(speed, parked=parked)
        publish(DEVICES, sessions, positions)

    def console_snapshot(label):
        if not consoles:
            return []
        with lock:
            publish_tick()
            states = [c.snapshot() for c in consoles]
            for state, expected in zip(states, speeds):
                assert state["dds_ready"] and state["emulator_active"]
                assert state["speed_kph"] == round(expected), "Dashboard speed differs from GPS replay"
                assert state["gear"] == ("Park" if parked else "Drive")
            result["console_samples"].append({"label": label, "at": time.monotonic(),
                                              "positions": [p[:] for p in positions], "states": states})
        return states

    def heartbeat():
        nonlocal last_tick
        try:
            while not stop.is_set():
                with lock:
                    now = time.monotonic()
                    if replay is not None and not paused:
                        positions[:] = replay.advance(now-last_tick, now-started)
                        speeds[:] = replay.speeds_kph()
                    last_tick = now
                    publish_tick()
                stop.wait(args.interval)
        except Exception as error:
            heartbeat_errors.append(str(error))
            stop.set()
            for console in consoles:
                try:
                    console.motion(0, parked=True)
                except Exception:
                    pass  # Main thread records the error and verifies restoration in finally.

    publish(DEVICES, sessions, positions)
    worker = threading.Thread(target=heartbeat, daemon=True)
    result = {"case": number, "origins": origins, "destination": DESTINATION, "speed_kph": args.speed_kph,
              "phases": [], "samples": [], "status": "running"}
    result["console_samples"] = []
    print(f"CASE {number}: {origins[0]['name']} / {origins[1]['name']} -> {DESTINATION['name']}", flush=True)
    try:
        if args.console:
            for i, device in enumerate(DEVICES):
                console = VirtualConsole(device, 18088 + i*10000)
                consoles.append(console)
                console.start()
            console_snapshot("initial_park")
        worker.start()
        data, paths = calculate(sessions)
        for device, session in zip(DEVICES, sessions):
            launch(device, session, "map")
            adb(device, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
        # First paint + map tiles. Keep coordinates fresh without consuming additional REST routes.
        time.sleep(8)
        views = check_views(0, 0)
        screenshot(case_dir, "initial")
        result["phases"].append({"version": 0, "views": views, "road_meters": [r["meters"] for r in data["routes"].values()]})
        next_stop, last_sample = 0, -10
        speed = args.speed_kph / 3.6
        with lock:
            started = last_tick = time.monotonic()
            replay = RendezvousReplay(paths, [], speed, args.hold_seconds)
            parked, paused = False, False
        result["rendezvous_events"] = []
        moving_captured = waiting_captured = False
        while True:
            if heartbeat_errors:
                raise RuntimeError(heartbeat_errors[0])
            elapsed = time.monotonic() - started
            assert elapsed < args.max_seconds, "Replay timed out"
            with lock:
                events = replay.events[:]
                replay.events.clear()
                finished = replay.finished()
            for event in events:
                result["rendezvous_events"].append(event)
                if event["kind"] == "arrived" and event["waypoint"] == 1 and len(replay.arrivals) == 1 and not waiting_captured:
                    states = console_snapshot("early_arrival_wait")
                    if states:
                        assert states[event["vehicle"]]["speed_kph"] == 0
                        assert any(s["speed_kph"] > 0 for s in states)
                        time.sleep(1)
                        screenshot(case_dir, "early-wait-dashboard")
                    waiting_captured = True
                if event["kind"] == "joined":
                    states = console_snapshot("joined_" + str(event["waypoint"]))
                    assert all(s["speed_kph"] == 0 for s in states)
                    a, b = event["positions"]
                    gap = km({"longitude": a[0], "latitude": a[1]}, {"longitude": b[0], "latitude": b[1]})*1000
                    assert gap < 60, "Vehicles are too far apart to count as joined"
                    event["gap_m"] = round(gap, 2)
                    print(f"CASE {number}: waypoint {event['waypoint']} joined; early vehicle waited {event['wait_seconds']:.1f}s, gap {gap:.1f}m", flush=True)
                    if event["waypoint"] == 1:
                        time.sleep(3)
                        screenshot(case_dir, "joined-1")
                elif event["kind"] == "departed_together":
                    states = console_snapshot("departed_" + str(event["waypoint"]))
                    assert all(s["speed_kph"] > 0 for s in states)
                    print(f"CASE {number}: both vehicles departed waypoint {event['waypoint']} together", flush=True)
            if next_stop < len(STOPS) and elapsed >= (next_stop + 1) * args.stop_every:
                # Freeze at current coordinates for approval/routing/map checks.
                with lock:
                    paused = True
                    frozen = [p[:] for p in positions]
                    speeds[:] = [0.0, 0.0]
                    publish_tick()
                console_snapshot("rerouting_" + str(next_stop+1))
                proposal = api(root + "/proposals", {"place": STOPS[next_stop]}, owner)["proposal"]
                unchanged = api(root, session=owner)
                assert unchanged["plan_version"] == next_stop, "Pending proposal changed the route"
                assert unchanged["destination"]["latitude"] == DESTINATION["latitude"]
                approved = api(root + "/decisions", {"proposal_id": proposal["id"], "approve": True}, peer)
                next_stop += 1
                assert approved["plan_version"] == next_stop
                data, paths = calculate(sessions)
                assert all(len(r["waypoints"]) == next_stop for r in data["routes"].values())
                assert all(km(r["origin"], {"longitude": p[0], "latitude": p[1]}) < .001
                           for r, p in zip((data["routes"][s["member_id"]] for s in sessions), frozen))
                deadline = time.monotonic() + 35
                while True:
                    room = api(root, session=owner)
                    if room["proposal"]["status"] == "completed":
                        assert all(a["state"] == "succeeded" for a in room["proposal"]["applications"].values())
                        break
                    if time.monotonic() > deadline:
                        raise AssertionError("Map applications did not complete; next waypoint would be blocked")
                    time.sleep(1)
                views = check_views(next_stop, next_stop)
                screenshot(case_dir, f"waypoint-{next_stop}")
                result["phases"].append({"version": next_stop, "waypoint": STOPS[next_stop - 1], "views": views,
                                         "road_meters": [r["meters"] for r in data["routes"].values()],
                                         "receipt_states": [a["state"] for a in room["proposal"]["applications"].values()]})
                with lock:
                    replay = RendezvousReplay(paths, STOPS[:next_stop], speed, args.hold_seconds)
                    last_tick = time.monotonic()
                    paused = False
                print(f"CASE {number}: waypoint {next_stop}/3 approved, both maps updated; GPS resumes from current location", flush=True)
            elif finished:
                assert next_stop == len(STOPS), "Arrived before all waypoint tests"
                break
            if consoles and not moving_captured and elapsed >= 3:
                console_snapshot("moving")
                check_views(next_stop, next_stop)
                time.sleep(1)
                screenshot(case_dir, "moving-dashboard")
                check_visible_maps(case_dir)
                moving_captured = True
            if elapsed - last_sample >= 10:
                console_snapshot("periodic")
                room = api(root, session=owner)
                locations = [room["members"][s["member_id"]]["location"] for s in sessions]
                assert all(p["source"] == "demo" and time.time() - p["measured_at"] < 5 for p in locations)
                result["samples"].append({"elapsed": round(elapsed, 1), "locations": locations})
                last_sample = elapsed
            time.sleep(args.interval)
        time.sleep(4)
        console_snapshot("destination_stop")
        result["final_views"] = check_views(3, 3)
        joined = [e for e in result["rendezvous_events"] if e["kind"] == "joined"]
        departed = [e for e in result["rendezvous_events"] if e["kind"] == "departed_together"]
        assert len(joined) == len(departed) == 3, "All three waypoints must be visited and departed together"
        with lock:
            final_positions = [p[:] for p in positions]
        result["android_gps_error_m"] = [gps_check(d, p) for d, p in zip(DEVICES, final_positions)]
        result["arrival_distance_m"] = [round(km({"longitude": p[0], "latitude": p[1]}, DESTINATION) * 1000, 2)
                                          for p in final_positions]
        assert all(d < 60 for d in result["arrival_distance_m"]), "Road endpoint is too far from fixed destination"
        assert all(km(result["samples"][0]["locations"][i], result["samples"][-1]["locations"][i]) > .1 for i in (0, 1)), "GPS did not move"
        screenshot(case_dir, "arrival")
        result["duration_seconds"] = round(time.monotonic() - started, 1)
        result["status"] = "passed"
        print(f"CASE {number}: PASS, GPS arrived on both devices, {result['duration_seconds']}s", flush=True)
    except Exception as error:
        result["status"], result["error"] = "failed", str(error)
        screenshot(case_dir, "failure")
        raise
    finally:
        stop.set()
        if worker.ident is not None:
            worker.join(timeout=25)
        result["console_restored"] = []
        for console in consoles:
            try:
                result["console_restored"].append(console.close())
            except Exception as error:
                result["status"] = "failed"
                result.setdefault("cleanup_errors", []).append(str(error))
        (case_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert result["status"] == "passed", result.get("cleanup_errors")
    return result


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, choices=(1, 2, 3, 4), default=4)
    parser.add_argument("--console", action="store_true", help="Link Virtual Console gear/speed to GPS and rendezvous waits")
    parser.add_argument("--speed-kph", type=positive, default=72)
    parser.add_argument("--stop-every", type=positive, default=10)
    parser.add_argument("--hold-seconds", type=positive, default=6)
    parser.add_argument("--interval", type=positive, default=1)
    parser.add_argument("--max-seconds", type=positive, default=600)
    args = parser.parse_args()
    if args.console:
        OUTPUT = ROOT / "build/console-gps-test-20261111"
    report = {"destination": DESTINATION, "native_navigation_launched": False, "cases": []}
    try:
        for i, origins in enumerate(STARTS[:args.cases], 1):
            report["cases"].append(run_case(i, origins, args))
    finally:
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
