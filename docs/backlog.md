# cc-proxy-status 대시보드 백로그

완료된 항목은 [x], 미완료는 [ ]로 표시.

## 완료

- [x] box-drawing CLI 대시보드 (accounts, usage, models, daily, per-account)
- [x] ANSI 색상 (running=초록, stopped=회색, active=초록, disabled/fail=빨강)
- [x] "refreshed Xm ago" 삭제 (만료 시간이 실제 사용 가능 여부를 반영하지 않음)
- [x] ~/.local/bin/ shim 스크립트 (watch, cron 등 비대화형 셸 지원)
- [x] per-account usage 통계 (계정별 요청 수, 토큰 소비)
- [x] bcrypt 해시 감지 + CC_PROXY_SECRET 환경변수 지원
- [x] 상단 시간 초 단위까지 표시 (watch -n 1 용도)
- [x] 401 실패 시 힌트 메시지 (auth failed — set CC_PROXY_SECRET)
- [x] auth-files 풍부한 필드 활용 (status, unavailable, last_refresh time_ago, plan_type)
- [x] 병렬 API 호출 (threading으로 4개 provider 동시 fetch)
- [x] cc-proxy-check 커맨드 구현 → cc-proxy-status --check 로 통합
  - per-credential 검증: auth-files/models?name=<name> API로 계정별 모델 접근 확인
  - 계정별 모델 수, last_refresh, status 표시
  - 전체 verdict (All OK / Some degraded)
  - Available Models 목록 표시

- [x] Usage -> per-account에서 req, fail, last request time, total tokens 표시
  - 요청 수: total / ok(초록) / fail(빨강) 오른쪽 정렬 컬럼
  - 토큰: dim(last_req_tok) / total_tok · dim(datetime) 포맷

- [x] quota 표시 추가 (cc-proxy-status --quota)
  - /v0/management/api-call 엔드포인트로 upstream provider API 프록시 호출
  - antigravity: fetchAvailableModels → quotaInfo.remainingFraction
  - claude: oauth/usage → five_hour / seven_day / seven_day_opus utilization
  - codex: wham/usage → primary_window / secondary_window used_percent
  - 진행바 (10칸) + 리셋 시간 표시, 색상 구분 (≥80% 기본 / 40-79% 노랑 / <40% 빨강)
  - cc-proxy-check alias → cc-proxy-status --check, 신규 cc-proxy-quota alias 추가

- [x] quota에서 위가 5h 아래가 7d로 통일 (일부 7d가 5h 위에 있는 경우가 있음)

- [x] use interface (provider 브라우징)
  - `cc-proxy-ui` 인터랙티브 화면 추가 (provider/account 브라우징)
  - status의 quota + account validation + available model을 한 화면에서 확인 가능

- [x] cli ui를 통해 방향키로 이동하여 계정 on/off 시키는 기능
  - 키맵: ←/→ provider, ↑/↓ account, space toggle, r refresh, 1-4 jump, q quit
  - 토글 안정화: 선택된 account의 path JSON 직접 수정 + atomic write(tmp→replace)
  - 토글 반영: provider 재시작으로 확정 반영 (quiet 모드)
  - UI 안정화: 토글 진행 로그를 박스 하단 메시지바로 통합 (외부 로그 출력 억제)
  - 렌더링 안정화: ANSI/CJK 폭 기준 박스 정렬 보정으로 메시지 변경 시 깨짐 방지

- [ ] cc-proxy-stop 시 usage 데이터 손실 문제
  - CLIProxyAPI 바이너리 수준 이슈, hot-reload 불가
  - 가능한 우회: stop 전 usage 스냅샷 저장?

- [x] accounts와 accounts validation 탭이 거의 중복되므로 account validation 정보를 accounts로 옮기기 (accounts validation 정보가 이모지도 있고 모델 개수도 있고 더 풍부함)

- [ ] cc-proxy.py 코드가 너무 길어짐. 모듈화하여 접근성을 높여야 함

- [ ] 토큰 관리 위치 일원화 및 auth files 로드 기능 추가
  - 기존 provider별 config 디렉토리에 보관하던 auth file을 한 디렉토리 안에서 관리하고 file 명의 prefix로 구분
  - 설치 위치에서 민감 정보인 토큰을 관리하는 것은 위험하기 때문.
  - cc-proxy-auth를 실행시 별도 설정이 없으면 실행하는 위치에 파일 생성하여 사용자가 따로 관리할 수 있게 함
  - cc-proxy에서는 지정한 위치에서 auth files를 불러오는 것을 시도하고 로드할 파일 경로를 설정하는 기능을 추가

- [ ] 파일(토큰) 열람 및 삭제 기능

- [x] quota 캐싱 (TTL 30초)
  - `/tmp/cc-proxy-quota-{provider}-{md5(auth_index)[:12]}.json` 계정별 캐시 파일
  - 30초 이내 재호출 시 upstream API 생략 → rate limit 방지
  - `watch -n 10 cc-proxy-quota` 수준의 polling 안전하게 사용 가능

- [x] --short / -s 압축 뷰
  - provider당 1행: 이름 · 포트 · running/stopped · accts · req · tok
  - `cc-proxy-short` alias 추가 (bash/powershell)
  - `watch -n 1 cc-proxy-short` 으로 빠른 전체 모니터링 가능

- [ ] provider 선택 출력: 현재 전체 provider를 출력하거나 단일 출력만 가능한데 두개 이상도 선택한 것만 출력 가능하도록
- [ ] provider 마다 박스 색깔 다르게 적용
