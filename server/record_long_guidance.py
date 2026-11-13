"""Five-minute replay of the existing SDK guidance, including its live road-limit badge.

No activity restart, SDK route request, or APK installation. Requires the same
running sessions/test GPS setup as record_active_guidance.py.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import re
import subprocess
import time

from record_active_guidance import publish_drive
from demo_city_drive import ROOT, ADB, PACKAGE, DEVICES, adb, edges, at, ui
from demo_native_variable import diagnostics
from road_speed import RoadSpeedPlan
from virtual_console import VirtualConsole

OUT = ROOT/'build/active-guidance-drive-20261112/long-sign'
EVIDENCE = ROOT/'docs/test-results/2026-11-12-active-guidance/long-sign'
DURATION = 300
SESSION = ROOT/'build/native-variable-20261112/overview/private-session.json'


def capture(seconds):
    tree = ui(DEVICES[0])
    texts = [n.get('text') for n in tree.iter('node') if n.get('text')]
    badges = [n.get('content-desc') for n in tree.iter('node')
              if n.get('content-desc', '').startswith('SDK ')]
    for device, label in zip(DEVICES, ['A', 'B']):
        (EVIDENCE/f'{label}-{seconds}s.png').write_bytes(adb(device, 'exec-out', 'screencap', '-p'))
    return {'seconds': seconds, 'texts': texts, 'badges': badges, 'native': diagnostics()}


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    pid = adb(DEVICES[0], 'shell', 'pidof', PACKAGE).decode().strip()
    assert pid, 'Existing native guidance required'
    sessions = json.loads(SESSION.read_text('utf-8'))
    route = json.loads((ROOT/'build/active-sdk-route.json').read_text('utf-8'))
    plan = RoadSpeedPlan(route)
    assert all(s['limit_kph'] is not None for s in plan.sections)
    path, _ = edges(route)
    initial = [0., 120.]
    progress, speeds = initial[:], [0., 0.]
    positions = [at(path, p) for p in progress]
    records, consoles, ticks, futures, restored = [], [], [], [], []
    publish_drive(sessions, positions, speeds)
    time.sleep(4)
    try:
        for i, device in enumerate(DEVICES):
            consoles.append(VirtualConsole(device, 19088+i*10000).start())
        for device, label in zip(DEVICES, ['A', 'B']):
            existing = subprocess.run([ADB, '-s', device, 'shell', 'pidof', 'screenrecord'], capture_output=True)
            assert not existing.stdout.strip(), 'Another recording is active'
            log = (OUT/f'{label}-record.log').open('wb')
            remote = f'/sdcard/convoy-long-sign-{label}.mp4'
            proc = subprocess.Popen([ADB, '-s', device, 'shell', 'screenrecord', '--size', '1280x720',
                                     '--bit-rate', '3000000', '--time-limit', '0', remote], stdout=log, stderr=log)
            time.sleep(.5)
            recorder_pid = adb(device, 'shell', 'pidof', 'screenrecord').decode().strip()
            assert recorder_pid.isdigit()
            records.append((device, label, proc, log, remote, recorder_pid))
        started = last = time.monotonic()
        next_capture = 0
        with ThreadPoolExecutor(max_workers=1) as capture_pool:
            while time.monotonic()-started < DURATION:
                now = time.monotonic()
                elapsed = now-started
                remaining = now-last
                last = now
                # Account for actual wall time; no lost distance when ADB is slow.
                while remaining > 1e-6:
                    dt = min(1., remaining)
                    states = [plan.advance(p, v, dt, i, elapsed-remaining+dt)
                              for i, (p, v) in enumerate(zip(progress, speeds))]
                    progress = [p for p, _ in states]
                    speeds = [v for _, v in states]
                    remaining -= dt
                limits = [plan.limit_at(p) for p in progress]
                assert all(v <= limit+1e-6 for v, limit in zip(speeds, limits))
                for console, speed in zip(consoles, speeds):
                    console.motion(speed)
                positions = [at(path, p) for p in progress]
                publish_drive(sessions, positions, speeds)
                ticks.append({'seconds': elapsed, 'progress_m': progress[:],
                              'speeds_kph': speeds[:], 'limits_kph': limits})
                if elapsed >= next_capture:
                    futures.append(capture_pool.submit(capture, int(elapsed)))
                    print(f'DRIVING {elapsed:.0f}s / {DURATION}s: progress {progress}; speeds {speeds}; limits {limits}', flush=True)
                    next_capture += 45
                time.sleep(.35)
            futures.append(capture_pool.submit(capture, DURATION))
            samples = [future.result() for future in futures]
    finally:
        publish_drive(sessions, positions, [0., 0.])
        for console in consoles:
            restored.append(console.close())
        for device, label, proc, log, remote, recorder_pid in records:
            adb(device, 'shell', 'kill', '-2', recorder_pid)
            proc.wait(timeout=20)
            log.close()
            adb(device, 'pull', remote, str(OUT/f'{label}-long-driving.mp4'))
    assert adb(DEVICES[0], 'shell', 'pidof', PACKAGE).decode().strip() == pid
    assert all(p-start > 1900 for p, start in zip(progress, initial))
    expected_limits = {section['limit_kph'] for section in plan.sections}
    assert all(expected_limits <= {t['limits_kph'][i] for t in ticks} for i in range(2))
    visible_limits = {int(re.search(r'(\d+) km/h', b).group(1))
                      for sample in samples for b in sample['badges'] if re.search(r'(\d+) km/h', b)}
    assert expected_limits <= visible_limits, visible_limits
    assert sum(s['native'].get('companion_count') == '1' for s in samples) >= 3
    result = {'duration_target_s': DURATION, 'app_pid_unchanged': True, 'app_pid': pid,
              'explicit_sdk_route_requests': 0, 'apk_installed': False,
              'badge': 'Live app View using SDK RoadInfo and SDK current position',
              'road_speed_sections': plan.sections, 'control_samples': ticks, 'samples': samples,
              'speeding_samples': 0, 'visible_limits_kph': sorted(visible_limits),
              'travelled_m': [p-start for p, start in zip(progress, initial)],
              'restored_consoles': restored,
              'recordings': [str((OUT/f'{n}-long-driving.mp4').relative_to(ROOT)) for n in ['A', 'B']]}
    (EVIDENCE/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: long driving, visible SDK limit signs, moving companion; no SDK request/restart.', flush=True)


if __name__ == '__main__':
    run()
