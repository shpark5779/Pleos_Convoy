"""Official native navigation + companion marker, variable per-car GPS/console speeds, MP4 capture.

One explicit native route request on A (no mid-run waypoint changes). Uses local server :8768.
Videos and private sessions stay under ignored build/native-variable-20261112/.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import math
import sys
from pathlib import Path
import subprocess
import threading
import time
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from convoy_server import make_server
from demo_city_drive import ROOT, PACKAGE, ADB, adb, edges, at, DESTINATION, ORIGINS
from virtual_console import VirtualConsole

OUT=ROOT/'build/native-variable-20261112'
SUMMARY=ROOT/'docs/test-results/2026-11-12-native-variable'
DEVICES=['emulator-5554','emulator-5556']
OVERVIEW='--overview' in sys.argv
DURATION=60 if OVERVIEW else 82
if OVERVIEW:
    OUT=OUT/'overview';SUMMARY=SUMMARY/'overview'


def speed_kph(vehicle,seconds):
    """Smooth acceleration/deceleration and different short stops; deliberately below 72."""
    phase=(seconds+vehicle*17)%70
    if 30<=phase<35:return 0.0
    base,amplitude,period=(32,9,9) if vehicle==0 else (47,11,13)
    speed=(base+amplitude*math.sin(seconds/period+vehicle))*min(1,max(0,seconds)/6)
    # Approach and leave the scheduled stop gradually, limiting sudden speed jumps.
    if 25<=phase<30:speed*=max(0,(30-phase)/5)
    if 35<=phase<40:speed*=min(1,(phase-35)/5)
    return speed


def api(path,body=None,session=None):
    req=Request('http://127.0.0.1:8768'+path,data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+session['token']} if session else {})})
    with urlopen(req,timeout=30) as response:return json.load(response)


def diagnostics():
    data=adb(DEVICES[0],'exec-out','run-as',PACKAGE,'--user','10','cat','shared_prefs/native_tmap_result.xml')
    try:return {x.get('name'):x.text if x.tag=='string' else x.get('value') for x in ET.fromstring(data)}
    except ET.ParseError:return {}


def publish(sessions,positions):
    for device,session,p in zip(DEVICES,sessions,positions):
        adb(device,'emu','geo','fix',str(p[0]),str(p[1]))
        api('/rooms/'+session['code']+'/location',{'longitude':p[0],'latitude':p[1],
            'measured_at':time.time(),'source':'demo'},session)


def launch(device,session,native):
    adb(device,'shell','am','force-stop',PACKAGE)
    adb(device,'install','-r',str(ROOT/'automotive/build/outputs/apk/debug/automotive-debug.apk'))
    for permission in ['pleos.car.permission.FUSED_LOCATION','android.permission.ACCESS_FINE_LOCATION','android.permission.ACCESS_COARSE_LOCATION']:
        adb(device,'shell','pm','grant','--user','current',PACKAGE,permission)
    user=adb(device,'shell','am','get-current-user').decode().strip()
    prefs=ET.Element('map')
    for key,value in {'server':'http://10.0.2.2:8768','code':session['code'],'member_id':session['member_id'],'token':session['token']}.items():
        ET.SubElement(prefs,'string',name=key).text=value
    adb(device,'exec-in','run-as',PACKAGE,'--user',user,'mkdir','-p','shared_prefs')
    adb(device,'exec-in','run-as',PACKAGE,'--user',user,'tee','shared_prefs/convoy.xml',data=ET.tostring(prefs,encoding='utf-8'))
    adb(device,'logcat','-c')
    adb(device,'shell','am','start','-n',PACKAGE+'/com.example.pleosprojectv01.MainActivity','--es','demo_screen',
        ('native-map' if OVERVIEW else 'native') if native else 'map')


def run():
    OUT.mkdir(parents=True,exist_ok=True);SUMMARY.mkdir(parents=True,exist_ok=True)
    a=api('/rooms',{'name':'A - variable 23-41 kph','destination':DESTINATION})
    b=api('/rooms/'+a['code']+'/join',{'name':'B - variable 36-58 kph'})
    sessions=[a,b]
    (OUT/'private-session.json').write_text(json.dumps(sessions),encoding='utf-8')
    # Start B 65 road metres ahead so its custom icon is in the actual native camera view.
    for session in sessions:
        api('/rooms/'+a['code']+'/location',dict(ORIGINS[0],measured_at=time.time(),source='demo'),session)
    initial=api('/rooms/'+a['code']+'/journey',{'action':'overview'},a)
    first=edges(initial['routes'][a['member_id']])
    positions=[at(first[0],0),at(first[0],65)]
    publish(sessions,positions)
    route_data=api('/rooms/'+a['code']+'/journey',{'action':'overview'},a)
    paths=[edges(route_data['routes'][s['member_id']]) for s in sessions]
    for device,session,native in zip(DEVICES,sessions,[True,False]):launch(device,session,native)
    # Keep timestamps fresh during SDK authentication; B is a map client, not another native SDK.
    for _ in range(15):
        publish(sessions,positions)
        time.sleep(1)
        d=diagnostics()
        if d.get('phase') in ['NAVIGATION_RUNNING','ROUTE_READY','ROUTE_FAILED','SDK_AUTH_FAILED','SDK_READY'] and d.get('companion_count')=='1':break
    d=diagnostics();initial_native=d.copy();print('Native state before driving:',d.get('phase'),d.get('error_code'),flush=True)
    records=[];consoles=[];samples=[];restored=[]
    try:
        for device,label in zip(DEVICES,['A','B']):
            log=(OUT/f'{label}-screenrecord.log').open('wb')
            proc=subprocess.Popen([ADB,'-s',device,'shell','screenrecord','--size','1280x720','--bit-rate','3000000',
                '--time-limit',str(DURATION+12),f'/sdcard/convoy-variable-{label}.mp4'],stdout=log,stderr=log)
            records.append((device,label,proc,log))
        for i,device in enumerate(DEVICES):consoles.append(VirtualConsole(device,19088+i*10000).start())
        progress=[0.,0.];last=time.monotonic();start=last;next_sample=0;shot_index=0
        with ThreadPoolExecutor(max_workers=2) as pool:
            while time.monotonic()-start<DURATION:
                now=time.monotonic();elapsed=now-start;dt=min(2,now-last);last=now
                speeds=[speed_kph(i,elapsed) for i in range(2)]
                progress=[min(total,p+speed/3.6*dt) for p,speed,(_,total) in zip(progress,speeds,paths)]
                positions=[at(path,p) for (path,_),p in zip(paths,progress)]
                list(pool.map(lambda x:x[0].motion(x[1]),zip(consoles,speeds)))
                publish(sessions,positions)
                if elapsed>=next_sample:
                    states=[c.snapshot() for c in consoles];d=diagnostics()
                    assert all(state['speed_kph']==round(speed) for state,speed in zip(states,speeds))
                    samples.append({'seconds':round(elapsed,2),'speeds_kph':speeds,'console':states,
                        'positions':positions,'progress_m':progress[:],'companion_count':d.get('companion_count'),
                        'companion_positions':d.get('companion_positions'),'native_phase':d.get('phase')})
                    print('t=%.0fs speeds=%.1f / %.1f km/h marker=%s'%(elapsed,*speeds,d.get('companion_count')),flush=True)
                    next_sample+=8
                    if shot_index<4:
                        for device,label in zip(DEVICES,['A','B']):
                            (SUMMARY/f'{label}-moving-{shot_index}.png').write_bytes(adb(device,'exec-out','screencap','-p'))
                        shot_index+=1
                time.sleep(.7)
        for console in consoles:restored.append(console.close())
        consoles=[]
        for device,label,proc,log in records:
            proc.wait(timeout=110);log.close()
            assert proc.returncode==0,(OUT/f'{label}-screenrecord.log').read_text(errors='replace')
            adb(device,'pull',f'/sdcard/convoy-variable-{label}.mp4',str(OUT/f'{label}-driving.mp4'))
            video=(OUT/f'{label}-driving.mp4').read_bytes()
            assert len(video)>100000 and b'ftyp' in video[:32] and b'moov' in video,'MP4 was not finalized'
        logs=adb(DEVICES[1],'logcat','-d','-s','NativeTmapCheck:I').decode('utf-8','replace')
        assert 'SDK_READY' not in logs
        assert all(max(s['speeds_kph'][i] for s in samples)>30 for i in range(2))
        assert len({round(s['speeds_kph'][0]) for s in samples})>4
        result={'samples':samples,'initial_native':{k:initial_native.get(k) for k in ['phase','error_code','sdk_plan_version']},
            'final_native':diagnostics(),'restored_consoles':restored,'B_native_sdk_initialized':False,
            'recordings':[str((OUT/f'{label}-driving.mp4').relative_to(ROOT)) for label in ['A','B']],
            'native_route_requested':not OVERVIEW,
            'note':'A official native SDK, B map, variable per-car emulator GPS and console speeds; no physical driving'}
        (SUMMARY/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('PASS: variable GPS/console speeds, MP4s finalized. Native:',result['final_native'].get('phase'),flush=True)
    finally:
        for console in consoles:
            try:console.close()
            except Exception:pass
        for _,_,proc,log in records:
            if proc.poll() is not None:log.close()


if __name__=='__main__':
    server=make_server(port=8768);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        run()
        while True:time.sleep(1)
    finally:server.shutdown();server.server_close()
