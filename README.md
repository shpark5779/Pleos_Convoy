# 같이 가요 — Pleos 동행 주행 시제품

두 대 이상 차량의 모임·위치 공유·공동 경유지 제안·전원 승인·내비게이션 반영 상태를 연결한 개발용 시제품입니다.

- Android 앱: `automotive` 모듈. 앱 이름 **같이 가요**, 패키지 `com.example.pleosprojectv01.convoy`.
- 서버: Python 표준 라이브러리만 사용. 프로젝트 루트에서 `python server/convoy_server.py` 실행.
- 에뮬레이터 앱의 기본 서버 주소: `http://10.0.2.2:8765`.
- 실행 방법, 구현 과정, 검증 결과와 제한: [구현 보고서](docs/IMPLEMENTATION_REPORT.md).

서버는 이 PC의 루프백 주소에서만 실행되고 데이터는 메모리에 보관합니다. 실제 차량에 배포하는 서비스가 아닙니다.
