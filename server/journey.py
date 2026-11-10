"""Authenticated journey calculations. Provider I/O never holds the room lock."""
import copy
import time

from tmap_service import Tmap, TmapError, route_point


class Journey:
    def __init__(self, convoy):
        self.convoy = convoy
        self.tmap = Tmap()

    def handle(self, code, token, body):
        from convoy_server import require, number, text
        store = self.convoy
        action = body.get("action", "overview")
        require(action in ("overview", "suggest", "apply", "config"), "지원하지 않는 여행 요청입니다.")
        with store.lock:
            live = store.rooms.get(code.upper())
            require(live is not None, "모임이 없습니다.", 404)
            me = store.member(live, token)["id"]
            room = store.snapshot(live)
        if action == "config":
            return {"map_key": self.tmap.map_key}
        drivers = {i: m for i, m in room["members"].items() if m.get("role", "driver") == "driver"}
        now = time.time()
        selected = {me: drivers[me]} if action == "apply" and me in drivers else drivers
        require(action != "apply" or me in drivers, "운전자만 경로를 반영할 수 있습니다.", 403)
        require(selected and all(m.get("location") and -5 <= now-m["location"]["measured_at"] <= 30 for m in selected.values()),
                "계산할 차량의 최근 30초 이내 위치 공유가 필요합니다.", 409)
        destination, vias = room["destination"], room.get("waypoints", [])
        if action == "apply":
            proposal = room.get("proposal")
            require(proposal and proposal["id"] == body.get("proposal_id") and proposal["status"] in ("approved", "completed"),
                    "전원 승인된 현재 제안만 반영할 수 있습니다.", 409)
            receipt = proposal["applications"].get(me, {})
            require(receipt.get("state") == "requested" and receipt.get("attempt_id") == body.get("attempt_id"),
                    "현재 경로 요청과 일치하지 않습니다.", 409)
        routes = {}
        for mid, member in selected.items():
            route = self.tmap.route(member["location"], destination, vias)
            routes[mid] = dict(route, name=member["name"], origin=member["location"],
                               arrival_at=route["computed_at"]+route["seconds"],
                               suggested_departure_at=room["arrival_at"]-route["seconds"] if room.get("arrival_at") else None)
        with store.lock:
            current = store.rooms.get(code.upper())
            require(current is not None and current.get("plan_version", 0) == room.get("plan_version", 0),
                    "계산 중 이동 계획이 변경되었습니다. 다시 계산하세요.", 409)
            store.member(current, token)
            if action == "apply":
                active = current.get("proposal")
                require(active and active["id"] == body["proposal_id"] and active["status"] in ("approved", "completed")
                        and active["applications"].get(me, {}).get("attempt_id") == body["attempt_id"],
                        "계산 중 경로 요청이 변경되었습니다.", 409)
        if action == "apply":
            return {"route": routes[me], "plan_version": room.get("plan_version", 0)}
        durations = [r["seconds"] for r in routes.values()]
        result = {"routes": routes, "arrival_spread_seconds": max(durations)-min(durations),
                  "computed_at": time.time(), "plan_version": room.get("plan_version", 0),
                  "basis": "TMAP 자동차 예상 경로·교통 소요 시간 / 실시간 회전별 음성 길안내 아님",
                  "charging_recommended": [mid for mid, m in drivers.items()
                      if m.get("battery_pct") is not None and (m["battery_pct"] <= 20 or
                          (m.get("range_km") is not None and m["range_km"] < routes[mid]["meters"]/1000+20))]}
        if action != "suggest":
            return result
        require(len(drivers) >= 2, "두 차량 이상 필요합니다.", 409)
        require(len(vias) < 5, "경유지 5개를 이미 사용 중입니다. 선두 차량이 계획을 정리하세요.", 409)
        category = body.get("category", "cafe")
        queries = {"cafe": "카페", "restaurant": "음식점", "rest_stop": "휴게소", "charging": "전기차충전소", "parking": "공영주차장"}
        require(category in queries, "검색 종류를 확인하세요.")
        mode = body.get("mode", "middle")
        require(mode in ("middle", "before_end"), "합류 방식을 확인하세요.")
        # ponytail: route progress samples approximate the join area; rank actual driving detours below.
        centers = [route_point(r, 0.5 if mode == "middle" else 0.85) for r in routes.values()]
        center = {k: sum(p[k] for p in centers)/len(centers) for k in ("latitude", "longitude")}
        query = text(body.get("query") or queries[category], 80)
        minimum = int(number(body.get("parking_cars", 0), 0, 8))
        candidates = self.tmap.search(query, center)
        ranked, last_error = [], None
        for candidate in candidates:
            estimates = []
            try:
                for mid, m in drivers.items():
                    to_meeting = self.tmap.route(m["location"], candidate, vias)
                    through_meeting = self.tmap.route(m["location"], destination, [*vias, candidate])
                    estimates.append({"member_id": mid, "seconds": to_meeting["seconds"],
                                      "detour_seconds": max(0, through_meeting["seconds"]-routes[mid]["seconds"])})
            except TmapError as error:
                last_error = error
                continue  # A non-drivable candidate must not become a zero-cost recommendation.
            wait = max(e["seconds"] for e in estimates)-min(e["seconds"] for e in estimates)
            candidate.update(estimates=estimates, wait_seconds=wait,
                             max_detour_seconds=max(e["detour_seconds"] for e in estimates),
                             parking_required=minimum, parking="주차 가능 대수 미확인 · 방문 전 확인 필요")
            ranked.append(candidate)
        if candidates and not ranked and last_error:
            raise last_error
        result.update(candidates=sorted(ranked, key=lambda c: c["max_detour_seconds"]+c["wait_seconds"]),
                      basis="차량별 실제 도로 우회 시간 + 먼저 도착한 차량의 예상 대기 시간 순",
                      attribution="TMAP 장소·자동차 경로 API", mode=mode,
                      notice="중간/후반 경로 지점 주변 후보입니다. 분기 지점·휴게소 진입 방향·주차 대수·충전 가용성 보장 아님")
        # Routes already supplied by overview; avoid repeating huge polylines for a candidate query.
        result.pop("routes")
        return result
