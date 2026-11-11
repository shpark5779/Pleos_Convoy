# 1번 TMAP 내비 + 2번 지도 · 가상 GPS 시연

## 동작

- 1번(`emulator-5554`): 정식 TMAP 내비 SDK의 **실제 안내 모드**입니다. 이동 좌표만 에뮬레이터 가상 GPS이고 SDK 내부 모의주행은 사용하지 않습니다.
- 2번(`emulator-5556`): 기존 동행 지도에 두 차량과 도로 경로를 표시합니다. 정식 내비 SDK를 열지 않습니다.
- 대전시청 / 타임월드에서 한밭수목원 주차장으로 출발합니다. 기본 속도 36km/h, GPS 입력 간격 1초입니다.
- 출발 45초 뒤 정부청사역 부근의 **가상 경유점**을 제안하고 두 테스트 차량이 자동 승인합니다. 실제 사용자 모임의 승인을 자동화하지 않습니다.
- 전원 승인 후 현재 좌표에서 TMAP REST 도로 경로를 다시 계산합니다. 계산 중 GPS를 유지하고, 새 경로에서 이동 거리를 0으로 시작해 출발점으로 되돌아가지 않습니다.
- 1번은 승인된 계획 버전마다 SDK 경로를 한 번 요청합니다. 2번 지도는 첫 연결과 계획 변경 시 REST 경로를 자동 갱신합니다. 수동 갱신도 가능합니다.
- 공유 좌표는 `source=demo`입니다. GPS 재생이 완료돼도 SDK 안내/도착 성공으로 기록하지 않습니다.
- 먼저 도착한 차량은 공동 경유지의 도로 지점에서 기다립니다. 두 차량이 모두 합류하면 6초간 정차한 뒤 함께 출발합니다.
- 어느 디바이스에서나 내 차량은 파란색 A, 상대 차량은 주황색 B입니다. 경유지는 보라색 번호, 목적지는 D로 표시합니다.

## 나중에 실행할 때

혼합 모드의 정식 내비 SDK는 아직 실행 검증하지 않았습니다. 아래 명령은 **나중에 혼합 모드를 시연할 때** 사용합니다. 실행 시 SDK 인증·경로 요청과 REST 호출이 발생합니다. 지도만 사용하는 실제 에뮬레이터 검증은 `server/test_map_emulators.py`로 별도 수행합니다.

1. `.env`의 `TMAP_APP_KEY`를 설정한 뒤 앱을 다시 빌드합니다. 키는 앱 빌드 시 반영됩니다.
2. 두 Pleos 에뮬레이터를 실행합니다. `adb devices`로 식별자를 확인하고 내비가 필요한 차량을 `--device1`로 지정합니다.
3. debug APK를 두 기기의 현재 사용자에 설치합니다. Python 3가 필요합니다.

```powershell
.\gradlew.bat :automotive:assembleDebug
$adb = "$env:LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe"
& $adb -s emulator-5554 install -r automotive/build/outputs/apk/debug/automotive-debug.apk
& $adb -s emulator-5556 install -r automotive/build/outputs/apk/debug/automotive-debug.apk
python server/convoy_server.py
```

별도 터미널:

```powershell
python server/demo_mixed_drive.py --device1 emulator-5554 --device2 emulator-5556
# 시각/속도 변경:
python server/demo_mixed_drive.py --waypoint-after 30 --speed-kph 36
```

스크립트는 두 기기의 앱을 종료하고 저장된 모임을 새 테스트 모임으로 교체합니다. debug 빌드의 명시적 실행 인자(`demo_screen=native/map`)로만 화면을 분기하며, 평소 실행은 기존 홈 화면을 엽니다. 세션 토큰은 Git에서 제외되는 `build/mixed-drive-session.json`에만 저장합니다.

## 한도와 검증 범위

SDK가 429를 반환하면 해당 내비 화면에서 자동 재요청을 중단합니다. 한도 복구 후 화면을 다시 여세요. 다른 SDK 경로 오류도 같은 계획으로 자동 재시도하지 않습니다. REST 호출이 실패하면 스크립트는 오류로 중단하며 직선 경로를 대신 주입하지 않습니다. 배경 지도 로딩도 TMAP 지도 키/권한에 따릅니다.

GPS는 REST 도로 좌표를 사용하므로 SDK의 탐색 경로와 완전히 같다고 보장하지 않습니다. SDK GPS 추적, 경유지 재탐색, 회전 안내와 도착은 한도 복구 후 기기에서 확인해야 합니다. 지도 전용 검증은 앱 설치/실행, TMAP REST와 지도 호출, 에뮬레이터 GPS 주입을 포함하며 정식 내비 SDK는 열지 않습니다.

Ctrl+C로 재생을 중단합니다. 중단/완료 후 마지막 가상 좌표는 에뮬레이터에 남습니다. 15분이 지나면 스크립트가 중단됩니다(`--max-seconds`로 조정).
