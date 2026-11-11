# 가상 GPS와 Virtual Console 동기화

두 Pleos 에뮬레이터에서 TMAP REST 도로 경로를 따라 GPS를 입력하면서 Virtual Console의 기어·속도를 함께 갱신합니다. 두 앱은 지도 화면을 사용하며 정식 TMAP 네비 SDK를 열지 않습니다.

| 상태 | 지도·GPS | 기어·계기판 |
|---|---|---|
| 주행 | 각자 도로 경로를 따라 이동 | D · 72km/h |
| 경유지에 먼저 도착 | 그 지점에서 상대를 기다림 | D · 0km/h · 브레이크 유지 |
| 전원 합류 | 최소 6초 함께 정차 후 공동 출발 | 모두 D · 0 → 72km/h |
| 경로 재계산 | 현재 좌표 유지 | D · 0km/h |
| 완료·중단 | 마지막 좌표 유지 | P · 0km/h, 제어 연결 종료 |

브라우저 창 대신 스크립트가 기기별 Virtual Console 세션을 유지합니다. GPS와 콘솔 제어는 같은 주행 상태에서 갱신하며, 화면 검사·캡처 중에도 주행 갱신이 계속됩니다. 각 기기의 내 차량은 A, 상대 차량은 B입니다.

## 재실행

로컬 모임 서버와 두 에뮬레이터, 새 debug APK가 필요합니다. 앱 키는 기존 로컬 `.env`를 사용합니다.

```powershell
.\gradlew.bat :automotive:assembleDebug
$adb = "$env:LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe"
& $adb -s emulator-5554 install -r automotive/build/outputs/apk/debug/automotive-debug.apk
& $adb -s emulator-5556 install -r automotive/build/outputs/apk/debug/automotive-debug.apk
# 서버가 실행 중이 아닐 때 별도 터미널에서:
python server/convoy_server.py
python server/test_map_emulators.py --cases 1 --console
```

이 PC의 임시 Python 런타임으로 실행하려면 프로젝트 루트에서:

```powershell
$python = Join-Path $env:TEMP 'codex-python-3.13.0/python.exe'
& $python -u -c "import sys,runpy;sys.path.insert(0,'server');sys.argv=['server/test_map_emulators.py','--cases','1','--console'];runpy.run_path('server/test_map_emulators.py',run_name='__main__')"
```

기존 저장 모임은 새 테스트 모임으로 교체됩니다. 자동으로 기기별 ADB 포트를 연결하며, `--cases 4`를 주면 이전의 출발 조합 4개로 반복합니다. 테스트가 제어하는 동안 Virtual Console 브라우저에서 페달·기어를 별도로 조작하면 입력이 충돌할 수 있습니다.

## 표시 설정과 기록

실제 차속 입력 시 지도 화면이 OS에 의해 가려지는 현상을 확인해, `automotive/src/debug/AndroidManifest.xml`의 `JourneyActivity`에 테스트용 `distractionOptimized` 메타데이터를 추가했습니다. release manifest에는 이 설정을 추가하지 않았습니다. 주행 중 실제 UI 트리에 지도 텍스트가 존재하고 차단 문구가 없는지도 검사합니다. 메타데이터의 의미는 [Android Automotive 공식 문서](https://developer.android.com/training/cars/platforms/automotive-os#distraction-optimization)를 참고하세요.

2026-11-11, 1번 대전시청 / 2번 타임월드에서 고정 목적지 한밭수목원 주차장까지 **두 디바이스 모두 통과**했습니다. 주행은 261.4초였고, 주행 중 경유지를 3번 추가했습니다.

- 먼저 도착한 2번은 첫 경유지에서 40.3초 기다렸습니다. 이때 계기판은 1번 72km/h, 2번 0km/h였습니다.
- 경유지 3곳 모두 두 차량의 D·0km/h 정차와 D·72km/h 공동 출발을 확인했습니다. 콘솔 상태 표본은 38개입니다.
- 목적지의 도로 끝까지 거리 4.16m, 최종 Android GPS와 입력 좌표 차이는 두 기기 각각 0.11m였습니다.
- 완료 후 두 기기의 P·0km/h 복귀를 읽어 확인했습니다. 정식 네비 SDK 실행 로그는 각각 0건입니다.
- debug APK 빌드와 Android 단위 테스트, Python 테스트 36개, 지도 JavaScript 검사도 통과했습니다.

- [상세 결과 JSON](../build/console-gps-test-20261111/case-1/result.json)
- [검증 요약 JSON](test-results/2026-11-11-convoy-gps-console/console-gps-summary.json)
- [먼저 도착한 2번 · 0km/h 대기](../build/console-gps-test-20261111/case-1/emulator-5556-early-wait-dashboard.png)
- [접근 중인 1번 · 72km/h](../build/console-gps-test-20261111/case-1/emulator-5554-early-wait-dashboard.png)
- [지도·계기판 주행 영상](../build/console-gps-test-20261111/case-1/driving-and-dashboard.mp4)

검증 요약 JSON은 레포지토리에 포함합니다. 상세 결과·캡처·영상과 테스트 세션 인증 정보는 Git에서 제외되는 `build/console-gps-test-20261111/`에 보관합니다.
