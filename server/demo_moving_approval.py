"""A native map + B GPS-only, moving road replay with a real on-screen proposal/approval.

Uses separate port 8767. --native allows initial guidance and one changed-plan request on A.
Keeps the server running after checks. Session tokens are saved only under ignored build/.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import re
import threading
import time
from urllib.request import Request,urlopen
from xml.etree import ElementTree as ET

from convoy_server import make_server
from demo_city_drive import ROOT,PACKAGE,adb,tap,ui,edges,at
from demo_single_navigation import wait_for
from tmap_service import km

OUT=ROOT/'docs/test-results/2026-11-11-moving-approval'
DEVICES=['emulator-5554','emulator-5556']
ORIGINS=[{'name':'Daejeon City Hall','latitude':36.35063,'longitude':127.38599},
         {'name':'Daejeon Station','latitude':36.33223,'longitude':127.43417}]
DEST={'name':'Hanbat Arboretum Parking 1','latitude':36.36548894,'longitude':127.39029492}
VIA={'name':'Government_Station','latitude':36.35768412,'longitude':127.38104596}


def api(path,body=None,session=None):
    req=Request('http://127.0.0.1:8767'+path,data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+session['token']} if session else {})})
    with urlopen(req,timeout=45) as response:return json.load(response)


def diag():
    data=adb(DEVICES[0],'exec-out','run-as',PACKAGE,'--user','10','cat','shared_prefs/native_tmap_result.xml')
    try:return {e.get('name'):e.text if e.tag=='string' else e.get('value') for e in ET.fromstring(data)}
    except ET.ParseError:return {}


def shot(name):
    for label,device in zip(['A','B'],DEVICES):
        (OUT/f'{label}-{name}.png').write_bytes(adb(device,'exec-out','screencap','-p'))


def fill(description,value):
    item=next(n for n in ui(DEVICES[0]).iter('node') if n.get('content-desc')==description)
    x1,y1,x2,y2=map(int,re.findall(r'\d+',item.get('bounds')))
    adb(DEVICES[0],'shell','input','tap',str((x1+x2)//2),str((y1+y2)//2))
    adb(DEVICES[0],'shell','input','text',str(value))
    adb(DEVICES[0],'shell','input','keyevent','KEYCODE_BACK')


class Replay:
    def __init__(self,routes,sessions):
        self.lock=threading.Lock();self.paths=[edges(r) for r in routes]
        self.started=time.monotonic();self.hold=False;self.positions=None
        self.stop=threading.Event();self.error=None;self.samples=[];self.sessions=sessions
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def replace(self,routes):
        with self.lock:
            self.paths=[edges(r) for r in routes];self.started=time.monotonic();self.hold=False
    def run(self):
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                while not self.stop.is_set():
                    with self.lock:
                        if not self.hold or self.positions is None:
                            self.positions=[at(path,min(total,12*(time.monotonic()-self.started))) for path,total in self.paths]
                        positions=self.positions[:]
                    list(pool.map(lambda p:adb(p[0],'emu','geo','fix',str(p[1][0]),str(p[1][1])),zip(DEVICES,positions)))
                    self.stop.wait(2)
        except Exception as error:self.error=type(error).__name__
    def snapshot(self,room):
        assert self.error is None,self.error
        positions=[room['members'][s['member_id']]['location'] for s in self.sessions]
        assert all(p and p['source']=='sdk' and time.time()-p['measured_at']<15 for p in positions)
        self.samples.append(positions)
        return positions


def run(native):
    OUT.mkdir(parents=True,exist_ok=True)
    a=api('/rooms',{'name':'A - City Hall','destination':DEST})
    b=api('/rooms/'+a['code']+'/join',{'name':'B - Daejeon Station'})
    sessions=[a,b];root='/rooms/'+a['code']
    (ROOT/'build/moving-approval-session.json').write_text(json.dumps({'sessions':sessions,'port':8767}),encoding='utf-8')
    for device,session,origin in zip(DEVICES,sessions,ORIGINS):
        adb(device,'shell','am','force-stop',PACKAGE)
        adb(device,'install','-r',str(ROOT/'automotive/build/outputs/apk/debug/automotive-debug.apk'))
        for permission in ['pleos.car.permission.FUSED_LOCATION','android.permission.ACCESS_FINE_LOCATION','android.permission.ACCESS_COARSE_LOCATION']:
            adb(device,'shell','pm','grant','--user','current',PACKAGE,permission)
        user=adb(device,'shell','am','get-current-user').decode().strip();assert user=='10'
        prefs=ET.Element('map')
        for key,value in {'server':'http://10.0.2.2:8767','code':session['code'],'member_id':session['member_id'],'token':session['token']}.items():
            ET.SubElement(prefs,'string',name=key).text=value
        adb(device,'exec-in','run-as',PACKAGE,'--user',user,'tee','shared_prefs/convoy.xml',data=ET.tostring(prefs,encoding='utf-8'))
        adb(device,'emu','geo','fix',str(origin['longitude']),str(origin['latitude']))
        adb(device,'logcat','-c')
        adb(device,'shell','am','start','-n',PACKAGE+'/com.example.pleosprojectv01.MainActivity');time.sleep(2)
        tap(device,'정식 TMAP 내비 SDK' if device==DEVICES[0] else 'GPS만 공유',True)
    wait_for(lambda:diag().get('phase')=='SDK_READY')
    wait_for(lambda:all(m['location'] for m in api(root,session=a)['members'].values()))
    initial=api(root+'/journey',{'action':'overview'},a)
    routes=[initial['routes'][s['member_id']] for s in sessions]
    replay=Replay(routes,sessions)
    native_initial={'requested':native}
    if native:
        tap(DEVICES[0],'승인 계획 · 실제 안내')
        wait_for(lambda:diag().get('phase') in ['NAVIGATION_RUNNING','ROUTE_FAILED','ROUTE_READY'],65)
        d=diag();native_initial.update(phase=d.get('phase'),error_code=d.get('error_code'),sdk_plan_version=d.get('sdk_plan_version'))
        print('Native initial:',native_initial,flush=True)
    before=replay.snapshot(api(root,session=a));shot('moving-before')
    time.sleep(20)
    moving=replay.snapshot(api(root,session=a))
    assert all(km(p,q)*1000>60 for p,q in zip(before,moving)),'Both vehicles must move before proposal'
    tap(DEVICES[0],'공동 경유지 추가')
    fill('경유지 이름',VIA['name']);fill('위도',VIA['latitude']);fill('경도',VIA['longitude'])
    tap(DEVICES[0],'제안 보내기')
    pending=wait_for(lambda:(lambda r:r if (r.get('proposal') or {}).get('status')=='pending' else None)(api(root,session=a)))
    wait_for(lambda:any(n.get('text')=='공동 경유지 승인 요청' for n in ui(DEVICES[1]).iter('node')))
    assert pending['plan_version']==0 and not pending['waypoints']
    assert pending['proposal']['votes'][a['member_id']] is True and pending['proposal']['votes'][b['member_id']] is None
    shot('approval-pending')
    replay.hold=True
    # Compare old and new plans at the same held GPS coordinates, not just at different origins.
    time.sleep(4)
    pending_routes=api(root+'/journey',{'action':'overview'},a)
    assert pending_routes['plan_version']==0
    tap(DEVICES[1],'승인')
    approved=wait_for(lambda:(lambda r:r if r['plan_version']==1 else None)(api(root,session=a)))
    assert approved['waypoints'][0]['name']==VIA['name']
    changed=api(root+'/journey',{'action':'overview'},a)
    new_routes=[changed['routes'][s['member_id']] for s in sessions]
    assert changed['plan_version']==1
    assert all(pending_routes['routes'][s['member_id']]['segments']!=changed['routes'][s['member_id']]['segments'] for s in sessions)
    closest=[min(km({'longitude':p[0],'latitude':p[1]},VIA)*1000 for seg in r['segments'] for p in seg) for r in new_routes]
    assert all(d<80 for d in closest),closest
    replay.replace(new_routes)
    if native:
        wait_for(lambda:diag().get('sdk_requested_plan_version')=='1',65)
        wait_for(lambda:diag().get('phase') in ['NAVIGATION_RUNNING','ROUTE_FAILED','ROUTE_READY'],65)
    shot('approved')
    after=replay.snapshot(api(root,session=a))
    time.sleep(25)
    final=replay.snapshot(api(root,session=a))
    assert all(km(p,q)*1000>60 for p,q in zip(after,final)),'Both vehicles must move on changed routes'
    shot('moving-after')
    d=diag()
    b_logs=adb(DEVICES[1],'logcat','-d','-s','NativeTmapCheck:I').decode('utf-8','replace')
    assert not any(s in b_logs for s in ['SDK_READY','INITIALIZING','ROUTE_REQUESTED'])
    result={'origin_separation_m':km(*ORIGINS)*1000,'origins':ORIGINS,'destination':DEST,'waypoint':VIA,
        'speed_kph':43.2,'initial_route_m':[r['meters'] for r in routes],
        'pending_plan_version':pending['plan_version'],'pending_kept_old_routes':True,
        'approved_plan_version':changed['plan_version'],'approved_via_distance_m':closest,
        'changed_route_m':[r['meters'] for r in new_routes],'gps_samples':replay.samples,
        'native_initial':native_initial,'native_after':{k:d.get(k) for k in ['phase','error_code','sdk_requested_plan_version','sdk_plan_version','waypoint_count']},
        'B_native_sdk_initialized':False,'both_moving_before_and_after':True,'ui_proposal_and_approval':True}
    (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: two road replays, A UI proposal, B UI approval, REST plan 0 -> 1; native status:',result['native_after'],flush=True)
    return replay


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--native',action='store_true');args=parser.parse_args()
    server=make_server(port=8767)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    replay=None
    try:
        replay=run(args.native)
        # Leave screens and positions visible, continue refreshing GPS at the last test positions.
        replay.hold=True
        while True:time.sleep(1)
    finally:
        if replay:replay.stop.set()
        server.shutdown();server.server_close()
