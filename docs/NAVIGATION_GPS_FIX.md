# Pleos 기본 Navigation 현위치 고정: 수정이 필요한 지점

현재 앱의 대체 구현은 [TMAP 동행 기능 구현 및 검증](TMAP_IMPLEMENTATION.md)에 기록했다. 실제 GPS에서 TMAP 경로를 계산하고 앱 안에 표시하며, 이 문서의 기본 Navigation 내부 문제를 수정한 것은 아니다.

상태: **미해결**. 이 프로젝트 앱의 문제가 아니라 설치된 기본 Navigation 빌드의 위치 입력 처리 문제다. 아래는 읽기 전용으로 확인한 코드와 수정 지침이며, 적용·검증된 패치가 아니다.

## 확인한 내용

기본 APK: `ai.umos.maps.android.navigation.app`, `/system_ext/priv-app/Navi42/Navi42.apk`.
서명: `CN=42dot, O=42dot, C=KR`, SHA-256 `26baafc8e2eea52ae6cfa0eecc804037b88ee1bcdc2b5f7eb5558cd7cf6c7d44`.

ADB에서 APK 파일 읽기가 제한되어 있어 로컬 SDK의 원본 시스템 이미지에서 APK만 읽어 추출했다. 시스템 이미지와 APK를 수정하지 않았다. 분석 도구와 추출물은 `build/gps-investigation`에만 보관했다. 코드는 디컴파일 결과이므로 원본 소스와 대조해야 한다.

1. `GpsLocationSourceRepositoryImpl.onNmeaMessage`는 GGA/GSA를 파싱해 진단 정보와 GPS fix 상태를 저장한다. RMC는 위치 수신 경로가 아니다.
2. `LocationFixGate.canSetLocation`은 `hasAcquiredFix || nmeaData.gpsFixType.hasFix`가 참이어야 위치 전달을 허용한다. `GnssNmeaData`의 초기 fix 상태는 `UNKNOWN`이다.
3. `NavigationUseCase.initialize`의 위치 흐름은 위 gate를 통과한 경우에만 `mapMatchRepository.setLocation(location)`을 호출한다. 이 조건은 위치 소스 종류와 관계없이 적용된다.
4. `GpsManager.getLastLocation`은 `ro.hardware.type == automotive`이면 실제 GPS의 위도·경도를 SDK의 국가별 기본 좌표로 치환한다. 에뮬레이터도 이 조건에 들어간다.
5. 차량 위치는 별도의 PlaceSense/VNet 경로에서 받아 Android GPS보다 높은 우선순위로 등록된다. 차량 위치 흐름이 등록만 되고 데이터를 내보내지 않는 경우의 fallback도 확인해야 한다.

에뮬레이터의 공개 GPS 생성 코드에는 GGA/RMC에 고정 `*47`을 붙이는 부분이 있다. 다만 체크섬만 보정한다고 GSA fix 조건이나 차량 모드의 좌표 치환까지 해결되는 것은 아니다. 앞선 보고서의 ‘체크섬만이 원인’이라는 해석을 정정한다.

## 공급자 소스에서 적용할 수정

Pleos 에뮬레이터에 한정된 분기를 만들고 실제 차량의 위치 품질 검사는 유지해야 한다.

- `GpsManager.getLastLocation`: 에뮬레이터에서는 Android GPS의 실제 위도·경도를 보존한다. 차량 모드 기본 좌표 치환을 그대로 적용하지 않는다.
- `NavigationUseCase.startDefaultLocationSources`: 에뮬레이터에서 PlaceSense가 유효한 위치를 보내지 않으면 Android GPS로 fallback한다. 연결 성공 여부만으로 무응답 위치 흐름을 우선 선택하지 않는다.
- `LocationFixGate` 및 호출부: 에뮬레이터에서는 GSA 메시지 존재만을 필수 조건으로 삼지 않고, Android GPS의 유효 좌표·측정 시각·정확도와 갱신 여부를 검사해 위치를 허용한다. 실제 차량에서는 기존 GNSS fix 정책을 유지한다.

이 변경은 서명된 기본 Navigation 수정 빌드가 필요하다. 공개 NaviHelper 3.0.5에는 현위치를 강제로 덮어쓰는 API가 없고, 프로젝트 APK를 새로 빌드하는 것으로 기본 Navigation의 내부 코드를 교체할 수는 없다. 기존 패키지를 다른 키로 재서명하여 덮어쓰는 방식도 정상 업데이트로 설치되지 않는다.

## 수정 빌드 검증 기준

1. A는 서울, B는 대전 GPS를 설정하고 기본 내비 엔진의 실제 좌표가 각각 근처로 바뀌는지 확인한다.
2. 사용자가 만든 GPX를 재생하면서 최소 두 시점의 Android GPS와 내비 좌표가 함께 이동하는지 확인한다.
3. 정지·GPS 끄기·오래된 위치·재시작·PlaceSense 무응답에서도 동작을 확인한다.
4. 강릉 목적지 요청 후 목적지·경유지 응답을 별도로 확인한다. 위치가 움직이는 것과 경로 반영 성공을 구분한다.

읽기 전용 재현 검사:

```powershell
& "$env:LOCALAPPDATA/Programs/Python/Python313/python.exe" server/check_navigation_location.py --output docs/test-results/2026-11-10-navigation-fix/position-check.json
```

이 검사는 한 시점에서 GPS와 엔진 좌표가 1km 넘게 다르면 `mismatch`와 종료 코드 1을 반환한다. 일치에 가까운 한 번의 관측만으로 연속 주행 검증을 통과한 것으로 판정하지 않는다.

실제 실행에서 A 약 19.959km, B 약 120.904km 차이로 두 기기 모두 `mismatch`였다. 별도 계측 테스트로 공개 `NaviHelper.getCurrentLocationInfo()` 콜백도 수신했으며, 두 내비 모두 `(37.4127212, 127.094681)`을 반환했다. SDK 조회 기능은 동작하지만 현위치 문제는 해결되지 않았다. 원본 결과는 `docs/test-results/2026-11-10-navigation-fix`에 보관했다.

조사 중 B를 재시작해 `GnssGrpcV1` 비활성화와 외부 GPS 소켓을 시험했지만 해결되지 않았다. `-gps` 옵션은 현재 QEMU2에서 지원되지 않았다. 해당 실험 옵션은 제거하고 같은 AVD·데이터로 정상 실행을 복구했다. 저장 포인트·앱 데이터·기본 내비 APK·원본 시스템 이미지는 유지했다. B에서 진행하던 경로 재생은 재시작으로 중단되었다.
