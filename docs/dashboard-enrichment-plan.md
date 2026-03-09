# CLI 대시보드 강화 + cc-proxy-check 구현 계획

## Context

백로그 우선순위 높음 항목(토큰/계정 유효성 검증, 상단 시간 초 표시)과 중간 항목(병렬 API,
401 힌트, quota)을 구현한다. CLIProxyAPI 웹 대시보드 수준의 풍부한 정보를
CLI 대시보드에도 반영한다.

### API 탐사 결과 (2026-03-04)

| 엔드포인트 | 상태 | 용도 |
|---|---|---|
| `GET /v0/management/auth-files` | 사용중 | 계정 목록 (status, status_message, unavailable, last_refresh, id_token 등 풍부) |
| `GET /v0/management/usage` | 사용중 | 사용량 통계 |
| `GET /v0/management/auth-files/models?name=<name>` | **미사용, 200 OK** | per-credential 모델 목록 → 계정 검증에 활용 |
| `GET /v1/models` | 미사용 | 프록시 집계 모델 목록 |
| `GET /v0/management/config` | 미사용 | 전체 설정 (routing.strategy 등) |
| `GET /v0/management/quota` | **404** | 전용 quota 엔드포인트 없음 |

- openai `auth-files` 응답에 `id_token.plan_type` (pro/plus 등), 구독 기간 포함
- quota 데이터는 management API에 없음 → 웹 대시보드는 upstream provider API를 직접 호출하는 것으로 추정. CLI에서는 `status`/`status_message` 필드로 간접 표시

## 수정 파일

- **`core/cc_proxy.py`** — 모든 로직 변경 (single source of truth)
- **`shell/bash/cc-proxy.sh`** — `cc-proxy-check` 함수 1줄 추가
- **`shell/powershell/cc-proxy.ps1`** — `cc-proxy-check` 함수 1줄 추가
- **`docs/backlog.md`** — 완료 항목 체크

## 구현 순서

### Step 1: 상단 시간 초 단위 표시 (1줄 변경)

**파일**: `core/cc_proxy.py` — `main()` 내 `cmd == "status"` 블록 (line ~1368)
- `"%Y-%m-%d %H:%M"` → `"%Y-%m-%d %H:%M:%S"`
- `watch -n 1 cc-proxy-status` 시 초 단위 갱신 확인 가능

### Step 2: 401 auth 실패 힌트 메시지

**파일**: `core/cc_proxy.py` — `_print_status_dashboard()` 내 management API 호출 except 블록
- `urllib.error.HTTPError` 401 감지 시:
  `auth failed — set CC_PROXY_SECRET env var` 힌트 출력 (빨강)
- 현재 bare `except Exception: pass`를 세분화

### Step 3: auth-files 응답 풍부한 필드 활용

**파일**: `core/cc_proxy.py` — `_print_status_dashboard()` 계정 섹션 (lines ~1040-1049)

현재 `email`, `name`, `disabled`만 사용. 추가 활용:
- `status` / `status_message`: runtime 상태 표시 (active 대신 실제 상태)
- `unavailable`: 사용 불가 계정 표시
- `last_refresh`: 마지막 갱신 시각 (`_time_ago()` 활용)
- `id_token.plan_type` (openai): 구독 유형 표시

계정 행 포맷 변경:
```
현재: user@example.com                              active
변경: user@example.com                  3m ago  active
      user@openai.com                    pro     5m ago  active
```

### Step 4: 병렬 API 호출 (threading)

**파일**: `core/cc_proxy.py`

현재 4개 provider 순차 fetch → threading으로 동시 호출.

1. 새 함수 `_prefetch_provider_data(base_dir, provider)` 추가:
   - `get_status()` + `_management_api("auth-files")` + `_management_api("usage")` 한 묶음
   - 결과를 dict로 반환

2. `main()` cmd=="status" 블록에서:
   - `threading.Thread`로 각 provider 데이터 동시 fetch
   - `join(timeout=10)` 후 순차 렌더링

3. `_print_status_dashboard()` 시그니처 변경:
   - 기존: `(base_dir, provider, status, W)` — 내부에서 API 호출
   - 변경: `(base_dir, provider, status, W, auth_data=None, usage_data=None, auth_error=False)` — 외부 주입

### Step 5: `_proxy_api()` 헬퍼 함수

**파일**: `core/cc_proxy.py` — `_management_api()` 뒤에 추가

```python
def _proxy_api(provider, path, timeout=5):
    """GET arbitrary path from a running provider proxy (no auth)."""
    port = PORTS[provider]
    url = "http://{}:{}/{}".format(HOST, port, path.lstrip("/"))
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
```

`/v1/models` 호출에 사용 (cc-proxy-check에서).

### Step 6: `cc-proxy-check` 서브커맨드 구현

**파일**: `core/cc_proxy.py`

#### 6a. `cmd_check(base_dir, provider=None)` 함수 추가

메인 진입점. 대시보드와 동일한 box-drawing 스타일.

#### 6b. `_print_check_panel(base_dir, provider, W, prefetched_data)` 함수 추가

Provider별 검증 패널:

```
╠══════════════════════════════════════════════════════════════════════╣
║  antigravity  :18417   ● running  4 accounts                       ║
║                                                                    ║
║  Account Validation                                                ║
║  ──────────────────────────────────────────────────────────────     ║
║  appltarget@gmail.com         12 models   3m ago   ● active        ║
║  hy5297735@gmail.com          12 models   8m ago   ● active        ║
║  disabled@gmail.com            0 models            ○ disabled      ║
║  broken@gmail.com              — (error)           ✕ unavail       ║
║                                                                    ║
║  Available Models (12)                                             ║
║  ──────────────────────────────────────────────────────────────     ║
║    claude-opus-4-6-thinking  claude-sonnet-4-6  gemini-3.1-pro-... ║
║    gemini-3-flash  gemini-2.5-flash  ...                           ║
╠══════════════════════════════════════════════════════════════════════╣
```

검증 로직:
1. `GET /v0/management/auth-files` → 계정 목록 + runtime status
2. 각 계정에 `GET /v0/management/auth-files/models?name=<name>` 호출
   → 모델 수로 유효성 판별 (0개 = 문제, N개 = 정상)
   → threading으로 병렬 호출 (계정이 여러 개일 수 있으므로)
3. `GET /v1/models` → 프록시 집계 모델 목록

#### 6c. `main()` 디스패처에 `check` 추가

`cmd == "check"` 분기 추가. usage docstring 업데이트.

### Step 7: Shell wrapper 업데이트

**`shell/bash/cc-proxy.sh`** (line 44 부근):
```bash
cc-proxy-check()      { _cc_proxy check      "$@"; }
```

**`shell/powershell/cc-proxy.ps1`** (line 47 부근):
```powershell
function cc-proxy-check     { _cc_proxy check     @args }
```

### Step 8: backlog.md 완료 항목 체크

완료된 항목 `[x]`로 업데이트.

## 구현하지 않는 항목 (이유)

| 항목 | 사유 |
|---|---|
| quota 수치 표시 | management API에 전용 엔드포인트 없음 (404). 웹 대시보드는 upstream API 직접 호출 추정. 향후 CLIProxyAPI에 quota 엔드포인트가 추가되면 재검토 |
| --short / -s 압축 뷰 | 이번 스코프 밖, 별도 작업으로 진행 |
| routing strategy 표시 | config 응답이 크고, 현재 round-robin 고정이므로 보류 |

## 검증 계획

1. `python3 installers/install.py --source local` (설치 경로 동기화)
2. 새 셸: `source ~/.cli-proxy/shell/bash/cc-proxy.sh`
3. `echo "$CC_PROXY_BASE_DIR"` → `~/.cli-proxy` 확인
4. `cc-proxy-status` → 초 단위 시간, 풍부한 계정 상태 확인
5. `watch -n 1 cc-proxy-status` → 초 갱신 + 병렬 fetch 속도 체감
6. `cc-proxy-check` → 전체 provider 검증 출력
7. `cc-proxy-check claude` → 단일 provider 검증
8. 401 테스트: `CC_PROXY_SECRET=wrong cc-proxy-status` → 힌트 메시지 확인
