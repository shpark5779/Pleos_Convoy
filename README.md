# 같이 가요 — Pleos 동행 주행 시제품

최신 검증: [확대·축소 수정 후 5분 30초 주행·SDK 도착 확인](docs/CAMERA_FIXED_DRIVING.md). [주행 영상 13개 모음](docs/videos/README.md)은 Git LFS로 관리하며 새 PC에서는 `git lfs pull`로 받습니다.

최신 구현: [오피넷 주유소별 휘발유·경유 가격 지도](docs/OPINET_FUEL_PRICES.md). [한 대의 정식 내비에 동행 차량 GPS 표시](docs/SINGLE_NAVIGATION_CONVOY.md)도 지원하며, 다른 차량은 **GPS만 공유 · 내비 미사용** 화면에서 좌표만 전송합니다.

두 대 이상 차량의 모임·위치 공유·공동 경유지 제안·전원 승인·내비게이션 반영 상태를 연결한 개발용 시제품입니다.

- Android 앱: `automotive` 모듈. 앱 이름 **같이 가요**, 패키지 `com.example.pleosprojectv01.convoy`.
- 서버: 기본 기능은 Python 표준 라이브러리 사용. 오피넷 좌표 변환은 `pip install -r server/requirements-opinet.txt`가 필요합니다. 프로젝트 루트에서 `python server/convoy_server.py` 실행.
- 에뮬레이터 앱의 기본 서버 주소: `http://10.0.2.2:8765`.
- 실행 방법, 구현 과정, 검증 결과와 제한: [구현 보고서](docs/IMPLEMENTATION_REPORT.md).
- 1번 TMAP 내비 / 2번 지도, 가상 GPS와 중간 경유지 변경: [혼합 디바이스 시연](docs/MIXED_DEVICE_DEMO.md).
- 두 기기 지도 전용, 출발 4조합과 경유지 합류·공동 출발: [실행 검증 기록](docs/MAP_ONLY_TEST.md).
- 가상 GPS와 Virtual Console 기어·속도 동기화: [지도·계기판 통합 주행](docs/CONSOLE_GPS_TEST.md).

TMAP 도로 경로·ETA·합류 후보와 공동 경유지 승인 기능을 추가했습니다. [REST 기반 동행 기능](docs/TMAP_IMPLEMENTATION.md), [두 에뮬레이터 시내 GPS 재생](docs/CITY_DRIVING_DEMO.md), [건양대병원·고려대 세종 → 울산 시연](docs/ULSAN_DEMO.md)을 확인할 수 있습니다.

정식 TMAP 내비 SDK도 별도 화면에 연결했습니다. 두 에뮬레이터의 초기화와 공식 길안내 UI 표시를 확인했으나 후속 경로 요청이 429로 제한돼 SDK 내부 모의주행·최종 도착은 아직 미검증입니다. [SDK 연결 결과와 제한](docs/NATIVE_TMAP_SDK.md)에 실제 화면과 테스트 결과를 기록했습니다.

새 PC에서는 `.env.example`을 `.env`로 복사해 발급받은 `TMAP_APP_KEY`를 설정하고 Android SDK 경로를 로컬에 지정한 다음 앱을 빌드합니다. `TMAP_CLIENT_ID`는 발급받은 경우에 설정합니다. 키를 변경하면 앱도 다시 빌드해야 합니다. 기본 서버 기능은 별도 Python 패키지 없이 실행할 수 있으며, 오피넷을 사용하려면 해당 Python 환경에 `server/requirements-opinet.txt`를 설치합니다.

```powershell
Copy-Item .env.example .env
# .env의 TMAP_APP_KEY 설정 후
.\gradlew.bat :automotive:assembleDebug :automotive:testDebugUnitTest
python server/convoy_server.py
```

실제 `.env`, 로컬 모임 인증 토큰, IDE·빌드 캐시와 APK는 Git에 포함하지 않습니다. 기능별 스크린샷과 검증 기록은 `docs/test-results/`에 있습니다.

서버는 이 PC의 루프백 주소에서만 실행되고 데이터는 메모리에 보관합니다. 실제 차량에 배포하는 서비스가 아닙니다.
