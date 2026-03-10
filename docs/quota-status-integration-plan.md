# Quota + Status 통합 구현 계획

## 배경 및 문제 인식

현재 `cc-proxy-status`와 `cc-proxy-check` 두 커맨드가 존재하며, 두 함수
(`_print_status_dashboard`, `_print_check_panel`)가 헤더 렌더링 로직을 **완전히
중복**하고 있다. quota 기능을 별도 커맨드로 추가하면 세 번째 중복이 발생한다.

**결정: `cc-proxy-check`를 제거하고 `cc-proxy-status`에 통합한다.**

---

## 최종 UX 설계

### 커맨드 구조

```
cc-proxy-status              # 기존: 기본 상태 + 사용량 (빠름, ~1s)
cc-proxy-status --quota      # 신규: 기본 상태 + 사용량 + quota (느림, ~3-5s, upstream 호출)
cc-proxy-status --check      # 기존 cc-proxy-check 흡수: 계정별 모델 검증
cc-proxy-status <provider>   # 특정 provider만 (기존 동작 유지)
```

- `cc-proxy-check`는 `cc-proxy-status --check`로 대체 (shell alias 유지 가능)
- `cc-proxy-links`는 그대로 유지 (별도 목적)

### 출력 레이아웃 (`--quota` 옵션)

```
╔══════════════════════════════════════════════════════════════╗
║   cc-proxy status                        2026-03-04 13:00:00 ║
╠══════════════════════════════════════════════════════════════╣
║   antigravity  :18417   ● running  8 accounts                ║
║                                                              ║
║   Accounts                                                   ║
║   ────────────────────────────────────────────────────────── ║
║   appltarget@gmail.com        48m ago  active                ║
║   hy5297735@gmail.com          4m ago  ⚠ no models           ║
║                                                              ║
║   Quota  ── antigravity ──────────────────────────────────── ║
║     appltarget@gmail.com                                     ║
║       gemini-3.1-pro-high     ████████░░  80%  resets 2h14m  ║
║       claude-opus-4-6-think   ██████████ 100%  resets 5h02m  ║
║       gemini-3-flash          ██████████ 100%  resets 2h14m  ║
║     kimdh1st.india1@gmail.com                                ║
║       gemini-3.1-pro-high     ██████████ 100%  resets 2h14m  ║
║                                                              ║
║   Usage                                                      ║
║   ────────────────────────────────────────────────────────── ║
║   Total: 267 requests (264 ok, 3 fail)  ·  20.0M tokens      ║
║     ...                                                      ║
║   Per-account:                                               ║
║     kimdh1st.india3@gmail.co  40(40/0)  2026-03-04 12:42  ...║
╠══════════════════════════════════════════════════════════════╣
║   claude  :18418   ● running  3 accounts                     ║
║                                                              ║
║   Quota  ── claude ───────────────────────────────────────── ║
║     clarf2211@linkidmail.com                                 ║
║       5h window     ████████░░  82%  resets 3h22m            ║
║       7d window     ████░░░░░░  44%  resets 6d14h            ║
║       7d opus       ██░░░░░░░░  20%  resets 6d14h            ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║   openai  :18419   ● running  1 accounts                      ║
║                                                              ║
║   Quota  ── openai ────────────────────────────────────────── ║
║     kimdh1st@gmail.com  [pro]                                ║
║       5h window     ██████████ 100%  resets 4h58m            ║
║       7d window     █████████░  99%  resets 5d22h            ║
╚══════════════════════════════════════════════════════════════╝
```

**Quota 진행바 규칙:**
- `remainingFraction` (antigravity/gemini) 또는 `100 - used_percent` (claude/openai)
- ≥ 80% (충분): 기본색
- 40–79%: yellow (`\033[33m`)
- < 40% (부족): red (`\033[31m`)
- 진행바: `█` (채워짐) + `░` (빈칸), 10칸 고정
- `remainingFraction` 없거나 null → 표시 생략

---

## 구현 범위

### Provider별 Quota API

| Provider | API URL | 메서드 | 핵심 필드 |
|----------|---------|--------|----------|
| antigravity | `https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels` | POST `{"project":"$PROJECT$"}` | `models[id].quotaInfo.{remainingFraction,resetTime}` |
| claude | `https://api.anthropic.com/api/oauth/usage` | GET | `five_hour/seven_day/seven_day_opus.{utilization,resets_at}` |
| openai | `https://chatgpt.com/backend-api/wham/usage` | GET | `rate_limit.primary_window/secondary_window.{used_percent,reset_after_seconds}` |
| gemini | `https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota` | POST `{"project":"$PROJECT$"}` | `buckets[].{modelId,remainingFraction,resetTime}` — 이번 스코프 skip (project_id 파싱 필요) |

> **`$PROJECT$`**: 관리서버가 `auth_index`로 해당 계정 파일을 찾아 project_id를 주입한다
> (fetchAvailableModels는 `$PROJECT$` 플레이스홀더 없이 `{}` body로도 동작 확인됨 — 서버가 알아서 주입)

### `/v0/management/api-call` 호출 구조

```python
POST /v0/management/api-call
Authorization: Bearer <secret>
{
  "authIndex": "<auth_index>",   # 계정 식별자 (auth-files 응답에서 취득)
  "method": "GET" | "POST",
  "url": "<upstream_url>",
  "header": {"Authorization": "Bearer $TOKEN$", ...},
  "data": "{...}"                # POST body (JSON 문자열)
}
```

응답: `{"status_code": 200, "body": "...", "header": {...}}`

---

## 코드 변경 계획 (`core/cc_proxy.py`)

### 1. 신규 헬퍼 함수

```python
def _management_api_call(provider, secret, auth_index, method, url, headers, body=None):
    """POST /v0/management/api-call → (status_code, parsed_body_dict)"""

def _fetch_quota_antigravity(provider, secret, auth_index):
    """fetchAvailableModels → {model_id: {remaining_pct, reset_str}}"""

def _fetch_quota_claude(provider, secret, auth_index):
    """oauth/usage → {window_name: {remaining_pct, reset_str}}"""

def _fetch_quota_openai(provider, secret, auth_index):
    """/wham/usage → {window_name: {remaining_pct, reset_str}}"""

def _fmt_quota_bar(remaining_pct):
    """0-100 → '████████░░  80%' (색상 포함)"""

def _fmt_reset_time(seconds_or_iso):
    """reset_after_seconds or ISO string → '2h14m', '6d14h'"""
```

### 2. `_prefetch_provider_data()` 확장

```python
# 기존 result dict에 추가:
result["quota_data"] = {}   # {account_name: quota_dict}

# quota fetch는 --quota 플래그가 있을 때만 실행 (속도 분리)
if fetch_quota:
    for f in files:
        auth_index = f.get("auth_index", "")
        result["quota_data"][f["name"]] = _fetch_quota_for_provider(provider, secret, auth_index)
```

### 3. `_print_status_dashboard()` 확장

- 기존 `Accounts` / `Usage` 섹션 사이에 `Quota` 섹션 추가 (quota_data가 있을 때만)
- `--check` 모드일 때는 `_print_check_panel` 내용을 이 함수 내에서 인라인 렌더링
- `_print_check_panel` 함수는 삭제

### 4. `cmd_status()` / `cmd_check()` 통합

```python
def cmd_status(base_dir, provider=None, fetch_quota=False, show_check=False):
    # 기존 cmd_status + cmd_check 통합
    # fetch_quota=True → _prefetch_provider_data에 quota 요청 포함
    # show_check=True → 계정별 모델 검증 섹션 표시
```

- `cmd_check()` 함수 삭제
- `elif cmd == "check":` → `cmd_status(..., show_check=True)` 호출로 변경
- `elif cmd == "status":` → `--quota`, `--check` 플래그 파싱 추가

### 5. Shell 래퍼 업데이트

**bash (`shell/bash/cc-proxy.sh`)**:
```bash
cc-proxy-status() { _cc_proxy status "$@"; }
cc-proxy-check()  { _cc_proxy status --check "$@"; }  # alias 유지
# 신규:
# cc-proxy-quota()  { _cc_proxy status --quota "$@"; }  # 선택적 추가
```

**powershell**: 동일하게 alias 유지

---

## 파일 변경 목록

| 파일 | 변경 내용 |
|------|----------|
| `core/cc_proxy.py` | 신규 헬퍼 함수들, `_prefetch_provider_data` 확장, `_print_status_dashboard` 확장, `_print_check_panel` 삭제, `cmd_check` 삭제 |
| `shell/bash/cc-proxy.sh` | `cc-proxy-check` → `status --check` alias로 변경 |
| `shell/powershell/cc-proxy.ps1` | 동일 |
| `docs/backlog.md` | quota 항목 완료 처리 |

---

## 구현 순서

1. `_management_api_call()` 헬퍼 + provider별 quota fetch 함수 구현 및 단위 테스트
2. `_prefetch_provider_data()`에 `fetch_quota` 파라미터 추가
3. `_fmt_quota_bar()`, `_fmt_reset_time()` 렌더링 헬퍼 구현
4. `_print_status_dashboard()`에 Quota 섹션 추가
5. `_print_check_panel()` 로직을 `_print_status_dashboard()`에 흡수 후 삭제
6. `cmd_status` / `cmd_check` 통합
7. shell 래퍼 업데이트
8. 설치 동기화 + 검증

---

## 검증 체크리스트

- [ ] `cc-proxy-status` — 기존 동작 그대로 (quota 없음, 빠름)
- [ ] `cc-proxy-status --quota` — Quota 섹션 추가 표시 (3-5초)
- [ ] `cc-proxy-status --check` — 기존 `cc-proxy-check`와 동일 출력
- [ ] `cc-proxy-check` — 위와 동일 (alias)
- [ ] provider 인수 조합: `cc-proxy-status antigravity --quota`
- [ ] proxy 미실행 상태에서 graceful 처리
- [ ] quota API 실패(timeout/401) 시 해당 계정만 `(unavailable)` 표시

---

## 보류 항목

- **gemini provider quota**: `retrieveUserQuota`는 `project_id`를 account 필드 파싱으로
  추출해야 하는데 현재 auth-files 응답에서 쉽게 접근 불가. 추후 별도 이슈로 처리.
- **quota 캐싱**: 현재는 매 호출마다 fresh fetch. 향후 TTL 캐시 추가 검토.
