"""Read-only check: Android GPS vs Pleos Navigation engine position."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    adb = str(Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/platform-tools/adb.exe")
    def run(*command):
        return subprocess.check_output([adb, *command], timeout=10).decode("utf-8", errors="replace")
    devices = [line.split()[0] for line in run("devices").splitlines()
               if line.startswith("emulator-") and "\tdevice" in line]
    results = []
    for device in devices:
        location = run("-s", device, "shell", "dumpsys", "location")
        log = run("-s", device, "logcat", "-d", "-t", "1500", "-s", "navi_engine:I", "GpsLocationSource:W")
        gps = re.findall(r"last location=Location\[gps ([+-]?[\d.]+),([+-]?[\d.]+)", location)
        engine = re.findall(r"org\(([+-]?[\d.]+),([+-]?[\d.]+):", log)
        result = {"device": device, "status": "unverified",
                  "nmea_checksum_errors_in_log": log.count("NMEA checksum mismatch")}
        if gps and engine:
            lat, lon = map(float, gps[-1])
            nav_lon, nav_lat = map(float, engine[-1])
            a, b = map(math.radians, (lat, nav_lat))
            h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(nav_lon-lon)/2)**2
            km = 12742 * math.asin(math.sqrt(min(1, max(0, h))))
            result.update(gps_lat_lon=[lat, lon], navigation_lat_lon=[nav_lat, nav_lon],
                          distance_km=round(km, 3), status="mismatch" if km > 1 else "nearby")
        results.append(result)
    report = {"note": "nearby is a sampled position comparison, not proof of continuous tracking or route success", "devices": results}
    raw = json.dumps(report, ensure_ascii=False, indent=2)
    print(raw)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw, encoding="utf-8")
    return 0 if results and all(r["status"] == "nearby" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
