"""Drive the CURRENT native guidance session; no app restart or SDK route request.

Reads the existing :8768 session and current SDK route exported to build/active-sdk-route.json.
Updates Android test GPS/Virtual Consoles and records both displays without restarting A.
Requires compiled/pushed server/TestGps.java and configured shell test GPS providers.
--restore-gps removes those test providers and restores shell mock-location permissions.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from demo_city_drive import ROOT, ADB, PACKAGE, adb, edges, at, ui
from demo_native_variable import api, diagnostics, publish, speed_kph, DEVICES
from virtual_console import VirtualConsole
from road_speed import RoadSpeedPlan

OUT=ROOT/'build/active-guidance-drive-20261112/sdk-route'
EVIDENCE=ROOT/'docs/test-results/2026-11-12-active-guidance/sdk-route'
PREVIOUS={}
OBEY_LIMITS='--obey-limits' in sys.argv
if OBEY_LIMITS:
    OUT=ROOT/'build/active-guidance-drive-20261112/speed-limits'
    EVIDENCE=ROOT/'docs/test-results/2026-11-12-active-guidance/speed-limits'


def publish_drive(sessions,positions,speeds):
    for device,session,p,speed in zip(DEVICES,sessions,positions,speeds):
        previous=PREVIOUS.get(device,p)
        dy=p[1]-previous[1];dx=(p[0]-previous[0])*math.cos(math.radians(p[1]))
        bearing=(math.degrees(math.atan2(dx,dy))+360)%360 if dx or dy else 0
        adb(device,'shell',f'CLASSPATH=/data/local/tmp/convoy-test-gps.dex app_process /system/bin TestGps {p[1]} {p[0]} {speed/3.6} {bearing}')
        PREVIOUS[device]=p[:]
        api('/rooms/'+session['code']+'/location',{'longitude':p[0],'latitude':p[1],
            'measured_at':time.time(),'source':'demo'},session)


def run():
    OUT.mkdir(parents=True,exist_ok=True);EVIDENCE.mkdir(parents=True,exist_ok=True)
    initial=diagnostics()
    initial_texts=[n.get('text') for n in ui(DEVICES[0]).iter('node') if n.get('text')]
    assert int(initial.get('distance_m','0'))>0 and 'm' in initial_texts,'Existing native guidance UI is required'
    pid=adb(DEVICES[0],'shell','pidof',PACKAGE).decode().strip()
    sessions=json.loads((ROOT/'build/native-variable-20261112/overview/private-session.json').read_text('utf-8'))
    room=api('/rooms/'+sessions[0]['code'],session=sessions[0])
    route=json.loads((ROOT/'build/active-sdk-route.json').read_text('utf-8'))
    path=edges(route);paths=[path,path]
    initial_progress=[min(700,path[1]*.3),min(820,path[1]*.3+120)]
    speed_plan=RoadSpeedPlan(route) if OBEY_LIMITS else None
    if speed_plan:
        if any(s['limit_kph'] is None for s in speed_plan.sections):
            raise ValueError('Speed limit unknown: stopped before replay, not assuming a default')
        reductions=[s['start_m'] for i,s in enumerate(speed_plan.sections) if i and s['limit_kph']<speed_plan.sections[i-1]['limit_kph']]
        if reductions:
            initial_progress=[max(0,reductions[0]-220),max(0,reductions[0]-120)]
    positions=[at(p[0],distance) for p,distance in zip(paths,initial_progress)]
    publish_drive(sessions,positions,[0,0])
    time.sleep(5)
    records=[];consoles=[];samples=[];restored=[]
    try:
        for device,label in zip(DEVICES,['A','B']):
            log=(OUT/f'{label}-record.log').open('wb')
            proc=subprocess.Popen([ADB,'-s',device,'shell','screenrecord','--size','1280x720','--bit-rate','3000000',
                '--time-limit','75',f'/sdcard/active-guidance-{label}.mp4'],stdout=log,stderr=log)
            records.append((device,label,proc,log))
        for i,device in enumerate(DEVICES):consoles.append(VirtualConsole(device,19088+i*10000).start())
        progress=initial_progress[:];started=last=time.monotonic();next_sample=0;speeds=[0.,0.];control_samples=[]
        with ThreadPoolExecutor(max_workers=2) as pool:
            while time.monotonic()-started<60:
                now=time.monotonic();elapsed=now-started;dt=min(2,now-last);last=now
                if speed_plan:
                    states=[speed_plan.advance(p,v,dt,i,elapsed) for i,(p,v) in enumerate(zip(progress,speeds))]
                    progress=[p for p,_ in states];speeds=[v for _,v in states]
                    limits=[speed_plan.limit_at(p) for p in progress]
                    assert all(limit is not None and speed<=limit+1e-6 for speed,limit in zip(speeds,limits))
                    control_samples.append({'seconds':elapsed,'progress_m':progress[:],'speeds_kph':speeds[:],'limits_kph':limits})
                else:
                    speeds=[speed_kph(i,elapsed) for i in range(2)]
                    speeds=[0 if p>=total else speed for p,speed,(_,total) in zip(progress,speeds,paths)]
                    progress=[min(total,p+speed/3.6*dt) for p,speed,(_,total) in zip(progress,speeds,paths)]
                positions=[at(path,p) for (path,_),p in zip(paths,progress)]
                list(pool.map(lambda item:item[0].motion(item[1]),zip(consoles,speeds)))
                publish_drive(sessions,positions,speeds)
                if elapsed>=next_sample:
                    d=diagnostics();states=[c.snapshot() for c in consoles]
                    texts=[n.get('text') for n in ui(DEVICES[0]).iter('node') if n.get('text')]
                    assert 'm' in texts,'Actual native guidance UI must remain visible'
                    assert d.get('companion_count')=='1','Peer marker must stay registered'
                    assert all(s['speed_kph']==round(v) for s,v in zip(states,speeds))
                    assert adb(DEVICES[0],'shell','pidof',PACKAGE).decode().strip()==pid,'Native app restarted'
                    samples.append({'seconds':round(elapsed,2),'speeds_kph':speeds,'progress_m':progress[:],
                        'limits_kph':[speed_plan.limit_at(p) for p in progress] if speed_plan else None,
                        'positions':positions,'native_phase':d['phase'],'companion_positions':d.get('companion_positions'),
                        'companion_count':d.get('companion_count'),'console_states':states,'guidance_ui_texts':texts})
                    label=str(int(elapsed))
                    for device,name in zip(DEVICES,['A','B']):
                        (EVIDENCE/f'{name}-drive-{label}.png').write_bytes(adb(device,'exec-out','screencap','-p'))
                    print('DRIVING %.0fs: A %.1f / B %.1f km/h; A %.0f / B %.0fm; actual native guidance + peer marker'%(elapsed,*speeds,*progress),flush=True)
                    next_sample+=15
                time.sleep(.7)
        for console in consoles:restored.append(console.close())
        consoles=[]
        publish_drive(sessions,positions,[0,0])
        for device,name,proc,log in records:
            proc.wait(timeout=40);log.close();assert proc.returncode==0
            adb(device,'pull',f'/sdcard/active-guidance-{name}.mp4',str(OUT/f'{name}-active-driving.mp4'))
        if speed_plan:
            assert all(p-start>5 for p,start in zip(progress,initial_progress))
            if reductions:
                lower_limit=speed_plan.limit_at(reductions[0]+1e-4)
                assert all(any(sample['limits_kph'][i]==lower_limit for sample in control_samples) for i in range(2)), 'Both cars must enter the lower-limit section'
        else:
            assert all(p-start>150 for p,start in zip(progress,initial_progress))
        metrics=lambda texts:[(texts[i-1],v) for i,v in enumerate(texts) if i and v in ['m','km']]
        assert metrics(samples[0]['guidance_ui_texts'])!=metrics(samples[-1]['guidance_ui_texts']),'Native guidance distances stayed frozen'
        result={'native_diagnostic_phase_before':initial['phase'],'native_guidance_ui_visible_before':True,'app_pid_unchanged':True,'explicit_sdk_route_requests':0,
            'road_speed_sections':speed_plan.sections if speed_plan else None,'raw_sdk_road_info':route.get('roads'),
            'control_samples':control_samples,'speeding_samples':0 if speed_plan else None,
            'sessions_reused':True,'samples':samples,'final_progress_m':progress,'final_native':diagnostics(),
            'initial_progress_m':initial_progress,'travelled_m':[p-start for p,start in zip(progress,initial_progress)],
            'geometry_source':'running native SDK observableRouteData (42 points), not REST geometry',
            'restored_consoles':restored,'recordings':[str((OUT/f'{n}-active-driving.mp4').relative_to(ROOT)) for n in ['A','B']],
            'note':'Continued the already successful real native guidance. Emulator GPS replay; not a full arrival test.'}
        (EVIDENCE/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('PASS: actual guidance distances changed during two-car driving; both videos saved.',flush=True)
    finally:
        for console in consoles:
            try:console.close()
            except Exception:pass


if __name__=='__main__':
    if '--restore-gps' in sys.argv:
        for device in DEVICES:
            adb(device,'shell','cmd','location','providers','remove-test-provider','gps')
            adb(device,'shell','appops','set','2000','android:mock_location','default')
            adb(device,'shell','appops','set','com.android.shell','android:mock_location','default')
        print('Original GPS providers and shell app-ops restored.')
    else:run()
