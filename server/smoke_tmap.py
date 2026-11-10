"""Explicit paid/quota-consuming live API check: python server/smoke_tmap.py.

Creates only in-process test rooms; never writes tokens or keys to the report.
"""
import json
from pathlib import Path
import time

from convoy_server import Convoy


def main():
    store = Convoy()
    destination = {"name": "강릉시청", "latitude": 37.7519, "longitude": 128.8761}
    owner = store.handle("POST", "/rooms", {"name": "서울 A", "destination": destination}, "")
    root = "/rooms/"+owner["code"]
    def call(op, data, who=owner):
        return store.handle("POST", root+"/"+op, data, who["token"])
    peer = call("join", {"name": "대전 B"})
    def locations():
        for who, lat, lon in ((owner, 37.5665, 126.978), (peer, 36.3504, 127.3845)):
            call("location", {"latitude": lat, "longitude": lon, "source": "demo", "measured_at": time.time()}, who)
    locations()
    proposal = call("proposals", {"kind": "plan", "place": destination, "arrival_at": time.time()+5*3600,
                                   "driving_mode": "same", "waypoints": []})["proposal"]
    call("decisions", {"proposal_id": proposal["id"], "approve": True}, peer)
    call("profile", {"battery_pct": 15, "range_km": 70})
    overview = call("journey", {"action": "overview"})
    assert len(overview["routes"]) == 2 and owner["member_id"] in overview["charging_recommended"]
    report = {"location_source": "demo / 서울·대전 시뮬레이션 좌표", "provider": "TMAP live",
              "routes": [{"name": r["name"], "km": round(r["meters"]/1000, 1), "minutes": round(r["seconds"]/60),
                          "points": len(r["path"]), "suggested_departure_at": r["suggested_departure_at"]}
                         for r in overview["routes"].values()],
              "arrival_spread_minutes": round(overview["arrival_spread_seconds"]/60), "charging_recommended": True}
    for category, mode in (("cafe", "before_end"), ("charging", "middle")):
        locations()
        candidates = call("journey", {"action": "suggest", "category": category, "mode": mode, "parking_cars": 3})["candidates"]
        assert candidates, f"No candidates: {category}"
        report[category] = [{"name": p["name"], "max_detour_minutes": round(p["max_detour_seconds"]/60),
                             "wait_minutes": round(p["wait_seconds"]/60), "parking": p["parking"],
                             "charging_status": p["charging_status"]} for p in candidates]
    report["outbound_requests"] = store.journey.tmap.requests
    output = Path(__file__).resolve().parent.parent/"docs/test-results/2026-11-10-tmap-two-emulators/live-api.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("PASS: live routes, departure times, EV warning, late-route cafes, charging POIs; no availability claims.")
    print(f"Provider requests: {report['outbound_requests']}; report: {output.name}")


if __name__ == "__main__":
    main()
