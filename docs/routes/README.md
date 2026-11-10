# 에뮬레이터 이동 재생용 경로

2026-11-10 공개 OSRM driving API로 조회한 도로 경로를 GPX와 KML로 변환했다. 실제 차량 주행 기록이 아니라 OpenStreetMap 도로망에 기반한 합성 테스트 데이터다.

| 기기 | 출발 → 도착 | 거리 | 예상 이동 시간 | 좌표 수 | GPX | KML |
|---|---|---:|---:|---:|---|---|
| A | 서울시청 → 강릉시청 | 216.46km | 178.5분 | 3,066 | [A GPX](A-seoul-to-gangneung.gpx) | [A KML](A-seoul-to-gangneung.kml) |
| B | 대전시청 → 강릉시청 | 277.67km | 216.6분 | 3,220 | [B GPX](B-daejeon-to-gangneung.gpx) | [B KML](B-daejeon-to-gangneung.kml) |

## 사용

1. 각 에뮬레이터의 **Extended controls → Location → Load/Import GPX/KML**을 연다.
2. A에는 A GPX, B에는 B GPX 파일을 선택한다.
3. **Run / Play**를 눌러 이동을 재생한다. 임포트만으로 재생이 시작된다고 가정하지 않는다.
4. 처음에는 1X로 위치 변화를 확인하고 필요하면 배속을 올린다. 경로 전체 재생은 오래 걸리므로 몇 분만 실행해도 위치 갱신 여부를 확인할 수 있다.
5. ‘같이 가요’ 앱에서는 **실제 차량 위치 공유**를 켠다. 테스트 좌표 공유는 꺼둔다.

GPX의 시간은 OSRM 구간별 예상 소요 시간으로 생성했다. 실제 관측 시간·실시간 교통 정보가 아니다. KML은 같은 도로 좌표를 담은 LineString이며 시간 정보가 없다. 고도는 미측정으로 0을 넣었다. 시작·도착은 경로 서비스에서 인접 도로로 보정되어 요청 좌표와 조금 다를 수 있다.

검증 범위: XML 재파싱, 좌표 범위, 경로 좌표와 구간 시간 개수 일치, GPX 시간 증가 및 GPX/KML 좌표 일치. **실제 에뮬레이터 UI 임포트·재생은 아직 검증하지 않았다.** 기존 Saved points와 현재 기기 GPS는 변경하지 않았다.

이 파일을 재생해도 기본 Navigation 앱의 기존 NMEA 체크섬 오류가 해결되는지는 별도 검증이 필요하다. 임포트는 에뮬레이터 위치 재생 기능이며 Navigation 앱에 목적지·경유지를 등록하는 기능이 아니다.

## 출처와 재생성

- 도로 데이터: © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright)
- 경로 계산: [OSRM API](https://project-osrm.org/docs/v26.5.0/http), [공개 데모 사용 지침](https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server)
- 원본 요청 URL, 생성 시각, 도로로 보정된 시작·도착 좌표: [routes-source.json](routes-source.json)
- 임포트·재생 방법: [Android 공식 문서](https://developer.android.com/studio/run/emulator-extended-controls)

프로젝트 루트에서 `python server/generate_route_files.py`를 실행하면 두 경로를 다시 조회하고 이 디렉터리의 파일을 갱신한다. 공개 데모는 요청 속도 제한이 있으며 조회 시점에 따라 경로가 달라질 수 있다.
