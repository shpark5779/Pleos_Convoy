# 주행 영상 모음

2026-11-12 에뮬레이터 녹화 11개. 실제 차량 주행이 아니라 GPS 재생 시연이다. 1번만 정식 내비를 사용하고 2번은 GPS·동행 지도를 사용한다.

| 시나리오 | 1번 | 2번 |
| --- | --- | --- |
| 제한속도 표지 + 5분 주행 | [약 5분 7초](2026-11-12/long-sign/A-long-driving.mp4) | [약 5분 7초](2026-11-12/long-sign/B-long-driving.mp4) |
| SDK 실제 길안내·동행 아이콘 | [약 75초](2026-11-12/sdk-route/A-active-driving.mp4) | [약 75초](2026-11-12/sdk-route/B-active-driving.mp4) |
| 50→10km/h 감속 검증 | [약 75초](2026-11-12/speed-limits/A-active-driving.mp4) | [약 75초](2026-11-12/speed-limits/B-active-driving.mp4) |
| SDK 지도 미리보기·동행 아이콘 | [약 72초](2026-11-12/native-overview/A-driving.mp4) | [약 72초](2026-11-12/native-overview/B-driving.mp4) |
| 초기 요청 제한 상태·길안내 성공 영상 아님 | [초기 녹화](2026-11-12/initial-route-failure/A-driving.mp4) | [초기 녹화](2026-11-12/initial-route-failure/B-driving.mp4) |

[정식 길안내 요청 성공 장면](2026-11-12/guidance-request/guidance-request.mp4)도 포함한다.

**5분 영상은 반복 확대·축소 코드 수정 전이다.** 수정 APK 빌드·설치는 확인했으며 수정 후 길안내 주행 재녹화는 아직 하지 않았다. 전체 도착 검증 영상도 아니다. [상세 검증·카메라 수정 보고서](../LONG_GUIDANCE_SPEED_SIGN.md).

영상은 Git LFS로 관리한다. GitHub에서는 파일의 다운로드 버튼으로 원본을 받을 수 있다. 새 PC에서 복제할 때는 Git LFS를 설치한 뒤 다음 명령을 실행한다.

```powershell
git lfs install
git lfs pull
```

[manifest.json](2026-11-12/manifest.json)에 원본 경로·바이트 크기·SHA-256을 기록했다. 로컬 녹화 원본과 비공개 세션 파일은 `build/`에 남고 인증 토큰과 `.env`는 업로드하지 않는다. 상세 테스트 JSON의 `recordings`는 당시 로컬 생성 경로를 유지한다.
