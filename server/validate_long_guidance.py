"""Decode the long recordings and summarize the recorded SDK speed-limit evidence."""
import json
from pathlib import Path
import cv2
import argparse

root=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--evidence', default='docs/test-results/2026-11-12-active-guidance/long-sign')
folder=root/parser.parse_args().evidence
result=json.loads((folder/'result.json').read_text('utf-8'))
movies=[]
for relative in result['recordings']:
    cap=cv2.VideoCapture(str(root/relative))
    assert cap.isOpened(),relative
    fps=cap.get(cv2.CAP_PROP_FPS);count=cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration=count/fps
    assert duration>=result['duration_target_s'],(relative,duration)
    captures=[]
    for seconds in (30,120,240,295,result['duration_target_s']-2):
        cap.set(cv2.CAP_PROP_POS_MSEC,seconds*1000)
        ok,frame=cap.read()
        assert ok,(relative,seconds)
        destination=folder/(Path(relative).stem+f'-frame-{seconds}s.png')
        cv2.imwrite(str(destination),frame)
        captures.append({'seconds':seconds,'file':str(destination.relative_to(root))})
    movies.append({'file':relative,'duration_s':duration,'fps':fps,'frames':count,'decoded_frames':captures})
    cap.release()
limits=[]
for vehicle in (0,1):
    groups=[]
    for limit in sorted({s['limit_kph'] for s in result['road_speed_sections']},reverse=True):
        values=[t['speeds_kph'][vehicle] for t in result['control_samples'] if t['limits_kph'][vehicle]==limit]
        assert values and max(values)<=limit+1e-6
        groups.append({'limit_kph':limit,'samples':len(values),'min_kph':min(values),'max_kph':max(values)})
    limits.append({'vehicle':'AB'[vehicle],'sections':groups})
validation={'videos':movies,'speed_statistics':limits,'speeding_samples':0,
            'control_ticks':len(result['control_samples']),
            'ui_badges':[{'seconds':s['seconds'],'badges':s['badges']} for s in result['samples']]}
(folder/'validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'videos':[{k:v for k,v in m.items() if k!='decoded_frames'} for m in movies],
                  'speed_statistics':limits,'control_ticks':len(result['control_samples'])},indent=2))
