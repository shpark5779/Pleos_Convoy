"""An explicitly simulated second vehicle, never a real Navigation client."""
import argparse
import json
import time
from urllib.request import Request, urlopen


def call(base, path, body, token=""):
    request = Request(base + path, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + token})
    with urlopen(request, timeout=5) as response:
        return json.load(response)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--room", required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8765")
    parser.add_argument("--approve", action="store_true", help="Explicitly auto-approve for this simulated vehicle only")
    args = parser.parse_args()
    root = "/rooms/" + args.room.upper()
    session = call(args.server, root + "/join", {"name": "Python 테스트 차량"})
    print("Simulated vehicle joined. Ctrl+C to leave. Auto-approve:", args.approve, flush=True)
    try:
        while True:
            room = call(args.server, root + "/location", {"latitude": 37.52, "longitude": 127.06,
                        "measured_at": time.time(), "source": "demo"}, session["token"])
            proposal = room.get("proposal")
            if proposal and proposal["status"] == "pending" and args.approve:
                call(args.server, root + "/decisions", {"proposal_id": proposal["id"], "approve": True}, session["token"])
                print("Simulated approval:", proposal["place"]["name"], flush=True)
            if proposal and proposal["status"] == "approved" and proposal["applications"][session["member_id"]]["state"] == "not_requested":
                room = call(args.server, root + "/applications", {"proposal_id": proposal["id"], "state": "requested"}, session["token"])
                attempt = room["proposal"]["applications"][session["member_id"]]["attempt_id"]
                call(args.server, root + "/applications", {"proposal_id": proposal["id"], "attempt_id": attempt,
                     "state": "failed", "detail": "Python 테스트 차량: 실제 내비게이션이 없어 반영하지 않음"}, session["token"])
            time.sleep(3)
    except KeyboardInterrupt:
        try:
            call(args.server, root + "/leave", {}, session["token"])
        except Exception:
            pass
