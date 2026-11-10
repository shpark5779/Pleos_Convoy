"""Visible Daejeon emulator demo. Prepare: python server/demo_city_drive.py
Replay at 36 km/h: python server/demo_city_drive.py --replay
Requires the local server, installed debug APK and two running emulators.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from tmap_service import km

ROOT = Path(__file__).resolve().parent.parent
ADB = str(Path(os.environ["LOCALAPPDATA"])/"Android/Sdk/platform-tools/adb.exe")
PACKAGE = "com.example.pleosprojectv01.convoy"
PRIVATE = ROOT/"build/city-drive-session.json"
OUTPUT = ROOT/"docs/test-results/2026-11-10-city-driving"
DEVICES = ["emulator-5554", "emulator-5556"]
ORIGINS = [{"name": "대전시청", "latitude": 36.35062946, "longitude": 127.38599016},
           {"name": "타임월드", "latitude": 36.35215692, "longitude": 127.37824081}]
MEETING = {"name": "정부청사역 부근 테스트 경유점", "latitude": 36.35768412, "longitude": 127.38104596}
DESTINATION = {"name": "한밭수목원 주차장1", "latitude": 36.36548894, "longitude": 127.39029492}


def api(path, body=None, session=None):
    request = Request("http://127.0.0.1:8765"+path,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={"Content-Type": "application/json", **({"Authorization": "Bearer "+session["token"]} if session else {})})
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def adb(device, *args, data=None):
    result = subprocess.run([ADB, "-s", device, *args], input=data, capture_output=True, timeout=20)
    if result.returncode:
        raise RuntimeError(f"{device}: "+result.stderr.decode("utf-8", "replace")[:150])
    return result.stdout


def ui(device):
    adb(device, "shell", "uiautomator", "dump", "/sdcard/city-demo.xml")
    return ET.fromstring(adb(device, "exec-out", "cat", "/sdcard/city-demo.xml"))


def tap(device, text, scroll=False):
    for _ in range(5):
        for item in ui(device).iter("node"):
            if text in item.get("text", "") and item.get("clickable") == "true":
                x1,y1,x2,y2 = map(int, re.findall(r"\d+", item.get("bounds", "")))
                if x2>x1 and y2>y1:
                    adb(device,"shell","input","tap",str((x1+x2)//2),str((y1+y2)//2))
                    return
        if not scroll:
            break
        adb(device,"shell","input","swipe","1400","900","1400","300","400")
    raise RuntimeError(f"{device}: button missing: {text}")


def prepare():
    owner = api("/rooms", {"name": "1번 · 대전시청", "destination": DESTINATION})
    root = "/rooms/"+owner["code"]
    peer = api(root+"/join", {"name": "2번 · 타임월드"})
    proposal = api(root+"/proposals", {"kind": "plan", "place": DESTINATION, "waypoints": [MEETING]}, owner)["proposal"]
    api(root+"/decisions", {"proposal_id": proposal["id"], "approve": True}, peer)
    def launch(config):
        device,session,origin = config
        adb(device,"shell","am","force-stop",PACKAGE)
        adb(device,"emu","geo","fix",str(origin["longitude"]),str(origin["latitude"]))
        adb(device,"shell","pm","grant","--user","current",PACKAGE,"pleos.car.permission.FUSED_LOCATION")
        user = adb(device,"shell","am","get-current-user").decode().strip()
        prefs = ET.Element("map")
        for key,value in {"server":"http://10.0.2.2:8765","code":session["code"],"member_id":session["member_id"],"token":session["token"]}.items():
            ET.SubElement(prefs,"string",name=key).text=value
        adb(device,"exec-in","run-as",PACKAGE,"--user",user,"tee","shared_prefs/convoy.xml",data=ET.tostring(prefs,encoding="utf-8",xml_declaration=True))
        adb(device,"shell","am","start","-n",PACKAGE+"/com.example.pleosprojectv01.MainActivity")
        time.sleep(2)
        tap(device,"실제 차량 위치 공유",True)
        time.sleep(3)
        tap(device,"TMAP 동행 지도",True)
        time.sleep(4)
        tap(device,"경로·ETA 갱신")
        time.sleep(3)
        tap(device,"테스트 주행 화면")
        print(device+" driving view opened",flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(launch,zip(DEVICES,[owner,peer],ORIGINS)))
    room = api(root,session=owner)
    assert all(m["location"] and m["location"]["source"]=="sdk" for m in room["members"].values())
    result = api(root+"/journey",{"action":"overview"},owner)
    routes = [result["routes"][s["member_id"]] for s in (owner,peer)]
    assert all(0<r["meters"]<6000 for r in routes)
    PRIVATE.parent.mkdir(exist_ok=True)
    PRIVATE.write_text(json.dumps({"sessions":[owner,peer],"routes":routes},ensure_ascii=False),encoding="utf-8")
    OUTPUT.mkdir(parents=True,exist_ok=True)
    report = {"code":owner["code"],"origins":ORIGINS,"meeting":MEETING,"destination":DESTINATION,
              "routes":[{"name":r["name"],"meters":r["meters"],"seconds":r["seconds"]} for r in routes],
              "note":"TMAP REST road geometry / custom test guidance / emulator GPS replay, not TMAP navigation SDK"}
    (OUTPUT/"scenario.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False),flush=True)


def edges(route):
    result,total = [],0.0
    for segment in route["segments"]:
        for a,b in zip(segment,segment[1:]):
            length=km({"longitude":a[0],"latitude":a[1]},{"longitude":b[0],"latitude":b[1]})*1000
            if length:
                result.append((total,total+length,a,b));total+=length
    return result,total


def at(route_edges, distance):
    for start,end,a,b in route_edges:
        if distance<=end:
            t=max(0,(distance-start)/(end-start))
            return [a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t]
    return route_edges[-1][3]


def replay():
    state=json.loads(PRIVATE.read_text("utf-8"));sessions=state["sessions"]
    paths=[edges(route) for route in state["routes"]]
    meeting_distances=[min(((km({"longitude":a[0],"latitude":a[1]},MEETING),start) for start,_,a,_ in path),key=lambda x:x[0])[1] for path,_ in paths]
    speed=10.0  # 36 km/h, wall-clock replay. No simulated traffic signal stops.
    depart_together=max(meeting_distances)/speed+10
    duration=max(depart_together+(total-meet)/speed for (_,total),meet in zip(paths,meeting_distances))
    print(f"Replay starts: 36 km/h, wait at shared waypoint, about {duration/60:.1f} minutes.",flush=True)
    start_time=time.monotonic();last_report=-30;samples=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        while True:
            elapsed=time.monotonic()-start_time
            positions=[]
            for (path,total),meet in zip(paths,meeting_distances):
                distance=min(speed*elapsed,meet) if elapsed<depart_together else min(total,meet+speed*(elapsed-depart_together))
                positions.append(at(path,distance))
            list(pool.map(lambda c:adb(c[0],"emu","geo","fix",str(c[1][0]),str(c[1][1])),zip(DEVICES,positions)))
            if elapsed-last_report>=30:
                room=api("/rooms/"+sessions[0]["code"],session=sessions[0])
                locations=[room["members"][s["member_id"]]["location"] for s in sessions]
                assert all(p and p["source"]=="sdk" and time.time()-p["measured_at"]<15 for p in locations)
                samples.append({"elapsed":round(elapsed,1),"locations":locations})
                print(f"t={elapsed:.0f}s GPS SDK confirmed on both vehicles; phase="+("joining" if elapsed<depart_together else "shared final leg"),flush=True)
                if len(samples) in (1,3,6):
                    for device in DEVICES:(OUTPUT/f"{device}-t{int(elapsed)}.png").write_bytes(adb(device,"exec-out","screencap","-p"))
                last_report=elapsed
            if elapsed>=duration+10:
                break
            time.sleep(2)
    arrived=[]
    for device in DEVICES:
        text=" ".join(n.get("text","") for n in ui(device).iter("node"))
        arrived.append("목적지에 도착했습니다" in text)
        (OUTPUT/f"{device}-arrival.png").write_bytes(adb(device,"exec-out","screencap","-p"))
    (OUTPUT/"replay-result.json").write_text(json.dumps({"samples":samples,"arrival_ui":arrived,"duration_seconds":duration,"speed_kph":36},ensure_ascii=False,indent=2),encoding="utf-8")
    assert all(arrived),"Arrival must be visible on both driving screens"
    print("PASS: both live SDK tracks reached the destination; both driving screens show arrival.",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay",action="store_true")
    args=parser.parse_args()
    replay() if args.replay else prepare()
