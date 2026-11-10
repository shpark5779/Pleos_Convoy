"""Explicit opt-in two-device test. Requires built APKs and localhost server.

Run: python server/test_two_emulators.py
This replaces the convoy app's saved test session on both emulators.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
from urllib.request import Request, urlopen


def main():
    root = Path(__file__).resolve().parent.parent
    adb = str(Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/platform-tools/adb.exe")
    output = root / "docs/test-results/2026-11-10-seoul-daejeon-gangneung"
    output.mkdir(parents=True, exist_ok=True)
    devices = [line.split()[0] for line in subprocess.check_output([adb, "devices"], text=True).splitlines()
               if line.startswith("emulator-") and "\tdevice" in line]
    if len(devices) != 2:
        raise RuntimeError(f"Expected exactly two ready emulators, got {devices}")

    def post(path, body):
        request = Request("http://127.0.0.1:8765" + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    owner = post("/rooms", {"name": "Emulator A", "destination": {
        "name": "Gangneung City Hall", "latitude": 37.7521, "longitude": 128.8759}})
    peer = post(f'/rooms/{owner["code"]}/join', {"name": "Emulator B"})

    def run(config):
        device, role, session = config
        lat, lon = (37.5665, 126.9780) if role == "owner" else (36.3504, 127.3845)
        subprocess.run([adb, "-s", device, "emu", "geo", "fix", str(lon), str(lat)], check=True, capture_output=True)
        for apk in ("automotive/build/outputs/apk/debug/automotive-debug.apk",
                    "automotive/build/outputs/apk/androidTest/debug/automotive-debug-androidTest.apk"):
            subprocess.run([adb, "-s", device, "install", "-r", str(root / apk)], check=True, capture_output=True, timeout=60)
        subprocess.run([adb, "-s", device, "shell", "am", "force-stop", "com.example.pleosprojectv01.convoy"], check=True)
        subprocess.run([adb, "-s", device, "shell", "pm", "grant", "--user", "current",
                        "com.example.pleosprojectv01.convoy", "pleos.car.permission.FUSED_LOCATION"], check=True, capture_output=True)
        command = [adb, "-s", device, "shell", "am", "instrument", "-w", "-r",
                   "-e", "class", "com.example.pleosprojectv01.TwoEmulatorFlowTest",
                   "-e", "convoy_role", role, "-e", "convoy_code", session["code"],
                   "-e", "convoy_member", session["member_id"], "-e", "convoy_token", session["token"],
                   "com.example.pleosprojectv01.convoy.test/androidx.test.runner.AndroidJUnitRunner"]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=210)
        (output / f"{role}-instrumentation.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
        location = subprocess.check_output([adb, "-s", device, "shell", "dumpsys", "location"])
        (output / f"{role}-location.txt").write_bytes(location)
        log = subprocess.check_output([adb, "-s", device, "logcat", "-d", "-t", "2000",
                                       "-s", "navi_engine:I", "GpsLocationSource:W"])
        (output / f"{role}-navigation-log.txt").write_bytes(log)
        screenshot = subprocess.check_output([adb, "-s", device, "exec-out", "screencap", "-p"])
        (output / f"{role}-navigation.png").write_bytes(screenshot)
        print(f'{device} {role}: {result.stdout.strip()}', flush=True)
        return result.returncode == 0 and "OK (1 test)" in result.stdout

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [(devices[0], "owner", owner), (devices[1], "peer", peer)]))
    request = Request(f'http://127.0.0.1:8765/rooms/{owner["code"]}', headers={"Authorization": "Bearer " + owner["token"]})
    with urlopen(request, timeout=5) as response:
        room = json.load(response)
    (output / "room-result.json").write_text(json.dumps(room, ensure_ascii=False, indent=2), encoding="utf-8")
    for session, expected in ((owner, (37.5665, 126.9780)), (peer, (36.3504, 127.3845))):
        location = room["members"][session["member_id"]]["location"]
        assert location is not None and location["source"] == "sdk", location
        assert abs(location["latitude"] - expected[0]) < 0.00001, location
        assert abs(location["longitude"] - expected[1]) < 0.00001, location
    for member_id, receipt in (room.get("proposal") or {}).get("applications", {}).items():
        print(f'{room["members"][member_id]["name"]}: {receipt["state"]} / {receipt["detail"]}', flush=True)
    if not all(results) or room.get("proposal", {}).get("status") != "completed":
        raise SystemExit("Two-device flow failed; inspect instrumentation reports")
    print("Both emulator UI flows passed; navigation receipts above are separate from test success.", flush=True)


if __name__ == "__main__":
    main()
