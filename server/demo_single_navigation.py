"""Two-emulator check: A native navigation + B GPS-only. --navigate sends ONE SDK route request.

Runs a separate local server on port 8766. Keep this command running to keep the demo room alive.
Session tokens stay only in ignored build/single-navigation-session.json.
"""
import argparse
import json
from pathlib import Path
import threading
import subprocess
import time
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from convoy_server import make_server
from demo_city_drive import ROOT, PACKAGE, adb, tap

OUT = ROOT / 'docs/test-results/2026-11-11-single-navigation'
DEVICES = ['emulator-5554', 'emulator-5556']


def api(path, body=None, session=None):
    request = Request('http://127.0.0.1:8766'+path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json', **({'Authorization':'Bearer '+session['token']} if session else {})})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def diagnostics():
    try:
        data = adb(DEVICES[0], 'exec-out','run-as',PACKAGE,'--user',USER,'cat','shared_prefs/native_tmap_result.xml')
        return {e.get('name'): e.text if e.tag=='string' else e.get('value') for e in ET.fromstring(data)}
    except (ET.ParseError, RuntimeError, subprocess.TimeoutExpired):
        return {}


def wait_for(check, seconds=50):
    end = time.time()+seconds
    while time.time()<end:
        value = check()
        if value:
            return value
        time.sleep(1)
    raise AssertionError('Timed out waiting for emulator state')


def prepare(navigate):
    OUT.mkdir(parents=True, exist_ok=True)
    a = api('/rooms', {'name':'A · 내비 표시','destination':{'name':'한밭수목원 주차장1','latitude':36.36548894,'longitude':127.39029492}})
    b = api('/rooms/'+a['code']+'/join', {'name':'B · GPS 전용'})
    private = ROOT/'build/single-navigation-session.json'
    private.parent.mkdir(exist_ok=True)
    private.write_text(json.dumps({'sessions':[a,b],'port':8766}), encoding='utf-8')
    for device in DEVICES:
        adb(device,'shell','am','force-stop',PACKAGE)
        adb(device,'install','-r',str(ROOT/'automotive/build/outputs/apk/debug/automotive-debug.apk'))
        for permission in ['pleos.car.permission.FUSED_LOCATION','android.permission.ACCESS_FINE_LOCATION','android.permission.ACCESS_COARSE_LOCATION']:
            adb(device,'shell','pm','grant','--user','current',PACKAGE,permission)
        adb(device,'logcat','-c')
    adb(DEVICES[0],'install','-r',str(ROOT/'automotive/build/outputs/apk/androidTest/debug/automotive-debug-androidTest.apk'))
    tests = adb(DEVICES[0],'shell','am','instrument','-w','-r','-e','class',
        'com.example.pleosprojectv01.CompanionVehiclesTest',PACKAGE+'.test/androidx.test.runner.AndroidJUnitRunner').decode('utf-8','replace')
    (OUT/'marker-filter-tests.txt').write_text(tests,encoding='utf-8')
    assert 'OK (3 tests)' in tests
    for device, session, lon, lat in [(DEVICES[0],a,127.38599,36.35063),(DEVICES[1],b,127.3865,36.3509)]:
        adb(device,'shell','am','force-stop',PACKAGE)
        user=adb(device,'shell','am','get-current-user').decode().strip()
        prefs=ET.Element('map')
        for key,value in {'server':'http://10.0.2.2:8766','code':session['code'],'member_id':session['member_id'],'token':session['token']}.items():
            ET.SubElement(prefs,'string',name=key).text=value
        adb(device,'exec-in','run-as',PACKAGE,'--user',user,'tee','shared_prefs/convoy.xml',data=ET.tostring(prefs,encoding='utf-8'))
        adb(device,'emu','geo','fix',str(lon),str(lat))
        adb(device,'shell','am','start','-n',PACKAGE+'/com.example.pleosprojectv01.MainActivity')
        time.sleep(2)
        tap(device,'정식 TMAP 내비 SDK' if device==DEVICES[0] else 'GPS만 공유',True)
    wait_for(lambda: diagnostics().get('phase')=='SDK_READY')
    wait_for(lambda: diagnostics().get('companion_count')=='1')
    print('A: official SDK ready, B: GPS-only, companion marker registered',flush=True)
    route={'attempted':navigate}
    if navigate:
        tap(DEVICES[0],'승인 계획 · 실제 안내')
        wait_for(lambda: diagnostics().get('phase') in ('NAVIGATION_RUNNING','ROUTE_READY','ROUTE_FAILED','PLAN_FAILED') or int(diagnostics().get('distance_m','0'))>0,70)
        d=diagnostics()
        route.update(phase=d.get('phase'),error_code=d.get('error_code'),distance_m=d.get('distance_m'))
        print('Single native route request:',route,flush=True)
    measure(a,b,route)


def measure(a,b,route):
    samples=[]
    for index,(lat,lon) in enumerate([(36.3509,127.3865),(36.3513,127.3865),(36.3517,127.3865)]):
        adb(DEVICES[1],'emu','geo','fix',str(lon),str(lat))
        def moved():
            room=api('/rooms/'+a['code'],session=a)
            point=room['members'][b['member_id']].get('location')
            d=diagnostics()
            entries=d.get('companion_positions','').split(',')
            marker_lat=float(entries[0].split(':')[-1]) if len(entries)==2 else None
            return (point,d) if point and d.get('companion_count')=='1' and abs(point['latitude']-lat)<0.00004 and marker_lat is not None and abs(marker_lat-lat)<0.00004 else None
        point,d=wait_for(moved)
        samples.append({'latitude':point['latitude'],'longitude':point['longitude'],'source':point['source'],
            'companion_count':d['companion_count'],'positions':d['companion_positions']})
        time.sleep(2)
        (OUT/f'A-marker-{index}.png').write_bytes(adb(DEVICES[0],'exec-out','screencap','-p'))
        print('GPS + marker movement sample',index,'passed',flush=True)
    (OUT/'B-gps-only.png').write_bytes(adb(DEVICES[1],'exec-out','screencap','-p'))
    logs=adb(DEVICES[1],'logcat','-d','-s','NativeTmapCheck:I').decode('utf-8','replace')
    assert not any(state in logs for state in ('INITIALIZING','SDK_READY','ROUTE_REQUESTED'))
    adb(DEVICES[1],'shell','input','keyevent','KEYCODE_BACK')
    wait_for(lambda: diagnostics().get('companion_count')=='0',45)
    (OUT/'A-stale-hidden.png').write_bytes(adb(DEVICES[0],'exec-out','screencap','-p'))
    result={'marker_filter_tests':3,'native_sdk_devices':1,'gps_only_devices':1,'route':route,
        'movement_samples':samples,'stale_hidden':True,'gps_sender_native_sdk_initialized':False}
    (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    tap(DEVICES[1],'GPS만 공유',True)
    wait_for(lambda: diagnostics().get('companion_count')=='1')
    print('PASS: movement, stale expiry and recovery. Demo left running on port 8766.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--navigate',action='store_true',help='Request native guidance once on A only')
    parser.add_argument('--resume',action='store_true',help='Restore last local room and check existing screens without initializing SDK or requesting another route')
    args=parser.parse_args()
    server=make_server(port=8766)
    USER=adb(DEVICES[0],'shell','am','get-current-user').decode().strip()
    if args.resume:
        sessions=json.loads((ROOT/'build/single-navigation-session.json').read_text('utf-8'))['sessions']
        a,b=sessions
        room=b['room']; room['created_at']=time.time()
        for session in sessions:
            room['members'][session['member_id']]['token']=session['token']
        server.convoy.rooms[a['code']]=room
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        if args.resume:
            d=diagnostics()
            measure(a,b,{'attempted':d.get('phase') not in (None,'SDK_READY','CONFIGURED','INITIALIZING'),
                'phase':d.get('phase'),'distance_m':d.get('distance_m'),'resumed_without_new_request':True})
        else:
            prepare(args.navigate)
        while True:
            time.sleep(1)
    finally:
        server.shutdown(); server.server_close()
