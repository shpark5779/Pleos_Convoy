# 오피넷 주유소별 가격 지도

2026-11-13. 사용자가 발급받은 일반 API 키로 실제 주유소 판매가격을 연동했다. 키는 로컬 `.env`의 `OPINET_API_KEY`에만 저장했고 앱·브라우저 응답·Git에 넣지 않았다.

## 사용 방법

- 정식 내비: **주유소 가격 → 휘발유 또는 경유**. 가격순 최대 12곳을 표시한다. 목록에서 주유소를 선택하면 주소·두 유종 가격·가격 기준일자/시간을 확인한다. **지도에서 보기**를 눌렀을 때만 주변 가격이 보이도록 카메라를 한 번 이동한다. 숨기기도 지원한다. 네비 지도 마커는 가격 표시용이며 상세 선택은 목록에서 한다.
- 동행 지도: **주변 주유소 가격** 버튼으로 선택 유종을 조회한다. 가격 마커를 터치하거나 목록을 선택하면 상세 창이 열린다. WebView 터치와 데스크톱 클릭을 모두 처리한다. 유종을 바꾸면 이전 유종 마커를 지운다.
- 중심은 화면 중앙이 아니라 모임에 공유된 내 차량 위치다. 최근 120초 이내 위치가 필요하다. 직선 반경 5km이며 경로상 우회 시간이 적거나 영업 중인 주유소를 추천한다는 의미는 아니다.

조회 시각과 가격 보고 기준시각을 구분한다. 반경 조회는 서버 조회 시각을 보여주고 상세 조회는 오피넷 `TRADE_DT/TRADE_TM`을 표시한다. 0·누락·비정상 가격은 실제 0원으로 표시하지 않는다. 실제 판매가격·영업 여부는 현장 확인이 필요하다. 출처는 한국석유공사 오피넷으로 표시한다.

## 실제 확인

대전시청 주변 휘발유·경유 주유소 12곳씩을 조회했다. 신대전셀프주유소 응답에는 휘발유 1,798원/L·경유 1,788원/L와 각 가격 기준시각이 들어 있었다. 지도 마커를 실제 터치해 우리하나셀프주유소 상세 팝업도 확인했다. 이 가격은 테스트 당시 응답이며 현재 가격을 보장하지 않는다.

- [정식 SDK 지도 가격 표시](test-results/2026-11-13-opinet/A-price-map.png)
- [정식 SDK 지도 경유 가격](test-results/2026-11-13-opinet/A-diesel-map.png)
- [주유소 상세 가격·기준시각](test-results/2026-11-13-opinet/A-price-detail.png)
- [동행 지도 가격 표시](test-results/2026-11-13-opinet/B-price-map.png)
- [동행 지도 마커 터치 상세 창](test-results/2026-11-13-opinet/B-price-detail.png)
- [실제 API 정규화 응답](test-results/2026-11-13-opinet/live-api.json), [검증 요약](test-results/2026-11-13-opinet/result.json)

서버 테스트 **46개**, 앱 단위 테스트 **7개**, APK 빌드가 통과했다. 두 기기에 APK를 적용했다. 정지 상태 SDK 지도와 WebView에서 확인했으며 추가 SDK 길안내 요청은 0회다. 길안내 주행 중 가격 마커 표시·조작은 이번에 재검증하지 않았다.

## API와 한도

[반경 내 주유소 API](https://www.opinet.co.kr/user/custapi/openApiInfoDtl.do?apiId=3)의 `aroundAll.do`와 [주유소 상세정보 API](https://www.opinet.co.kr/user/custapi/openApiInfoDtl.do?apiId=1)의 `detailById.do`를 사용한다. 공식 페이지의 인증 파라미터 표기는 `certkey`이지만 이번 발급 키의 실제 응답은 `code`에서 정상 데이터가 반환됐다. 이를 실제 조회로 확인해 `code`를 사용했다. 인증 파라미터를 자동으로 번갈아 재시도하지 않는다.

KATEC와 WGS84는 `pyproj`로 변환한다. 공식 예제 좌표의 서울 강남 위치와 왕복 변환을 테스트하고, 중심에서 5.2km를 벗어난 응답 좌표는 제거한다. 주변 조회는 약 100m 격자별 10분 캐시, 상세는 30분 캐시다. SQLite에 일일 호출 예약 수와 캐시를 저장하므로 이 프로젝트에서 서버를 재시작해도 유지되고 다른 포트의 프로세스도 같은 로컬 예산을 공유한다. 실패한 API 요청도 예산에 포함한다.

화면의 300회 한도보다 낮은 **하루 280회**를 로컬 기본 상한으로 삼는다. 이 카운터는 한국 시각 기준이며 다른 PC·서비스에서 같은 키를 쓴 호출이나 제공자의 실제 잔여 한도까지 파악하는 것은 아니다. 자동 위치 폴링은 오피넷을 호출하지 않고 사용자가 가격 버튼을 눌러 조회한다.

## 설정

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r server/requirements-opinet.txt
# .env에 OPINET_API_KEY 및 선택적으로 OPINET_DAILY_BUDGET 설정
.venv\Scripts\python server/convoy_server.py
.venv\Scripts\python -m unittest discover -s server -p 'test_*.py'
```

이번 에뮬레이터 검증 서버는 포트 8770이며 두 앱도 해당 주소로 설정했다. 캐시·호출 예산 DB는 Git 제외 경로 `build/opinet-cache.sqlite`다. 기본 모임 서버는 기존처럼 8765를 사용할 수 있다. 오피넷을 쓰지 않는 기존 기능은 추가 패키지 없이도 동작한다.
