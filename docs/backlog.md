# cc-proxy-status 대시보드 백로그

완료된 항목은 [x], 미완료는 [ ]로 표시.

## 완료

- [x] box-drawing CLI 대시보드 (accounts, usage, models, daily, per-account)
- [x] ANSI 색상 (running=초록, stopped=회색, active=초록, disabled/fail=빨강)
- [x] "refreshed Xm ago" 삭제 (만료 시간이 실제 사용 가능 여부를 반영하지 않음)
- [x] ~/.local/bin/ shim 스크립트 (watch, cron 등 비대화형 셸 지원)
- [x] per-account usage 통계 (계정별 요청 수, 토큰 소비)
- [x] bcrypt 해시 감지 + CC_PROXY_SECRET 환경변수 지원

## 미완료

### 우선순위 높음

- [ ] 토큰/계정 유효성 검증 (cc-proxy-check)
  - 현재: 직접 claude "hello"로 수동 확인 → 토큰 낭비, 번거로움
  - 목표: /v1/models GET 또는 최소 completion으로 자동 검증
  - management API disable/enable 활용한 개별 계정 검증 가능성

- [ ] 상단 시간 초 단위까지 표시 (watch -n 1 용도)

### 우선순위 중간

- [ ] 병렬 API 호출 (threading)
  - 현재 4개 provider 순차 fetch → 동시 호출 시 4배 빨라짐
  - watch -n 1에서 체감

- [ ] --short / -s 압축 뷰
  - 헤더 한 줄만 표시 (usage 세부 없이)

- [ ] 401 실패 시 힌트 메시지
  - (auth failed — set CC_PROXY_SECRET)

- [ ] quota 표시 추가

### 우선순위 낮음 / 보류

- [ ] use interface (provider → account/usage/quota 브라우징)
  - 각 기능별 출력량이 크지 않아 현재로선 보류

- [ ] cc-proxy-stop 시 usage 데이터 손실 문제
  - CLIProxyAPI 바이너리 수준 이슈, hot-reload 불가
  - 가능한 우회: stop 전 usage 스냅샷 저장?

- [ ] 파일(토큰) 열람 및 삭제 기능

- [ ] usage에 계정별 실패 통계 추가
