# cc_proxy.py 모듈화 리팩터링 플랜

## Context
`core/cc_proxy.py`가 3,448줄, 113개 함수의 모놀리식 파일로, 백로그에 "코드가 너무 길어짐. 모듈화하여 접근성을 높여야 함"으로 등록되어 있음. 14개 논리 도메인을 10개 모듈로 분리하여 유지보수성과 가독성을 개선한다.

## Import 전략
- `python3 core/cc_proxy.py`로 실행 시 Python이 자동으로 `core/`를 `sys.path[0]`에 추가
- 따라서 모든 모듈은 단순 sibling import 사용: `from constants import ...`
- `__init__.py` 불필요 (패키지가 아닌 스크립트 실행 방식 유지)
- 기존 shell wrapper 호출 방식 (`python3 core/cc_proxy.py <args>`) 변경 없음

## 모듈 구조 (10개 모듈)

```
core/
  cc_proxy.py      # Entry point: docstring + main() CLI dispatcher (~300줄)
  constants.py     # 상수, ANSI 코드, 프로바이더 설정 (~70줄)
  paths.py         # 경로 해석, 토큰 디렉터리 (~140줄)
  process.py       # PID/프로세스 관리, 포트 해석, 헬스체크 (~130줄)
  config.py        # YAML config 수정, 토큰 파싱/검증 (~230줄)
  api.py           # Management API, 시크릿 읽기 (~80줄)
  quota.py         # Quota 조회 + 캐싱 (~170줄)
  usage.py         # Usage 추적 (스냅샷 + 누적) (~230줄)
  proxy.py         # Proxy 생명주기 (start/stop/status) + 대시보드 서버 (~370줄)
  display.py       # ANSI 포맷팅 + 박스 드로잉 + 상태 대시보드 렌더링 (~560줄)
  tui.py           # 터미널 UI (키 입력 + 메인 루프) (~680줄)
  commands.py      # Auth, invoke, profile install, token/secret 커맨드 (~350줄)
```

## 의존성 DAG (비순환)

```
constants          ← 의존 없음 (leaf)
  ↑
paths              ← constants
  ↑
process            ← constants, paths
  ↑
config             ← constants, paths
  ↑
api                ← constants, paths, config
  ↑
quota              ← constants, api
  ↑
usage              ← constants, paths, api
  ↑
proxy              ← constants, paths, process, config, api, usage
  ↑
display            ← constants, paths, api, quota, usage, proxy
  ↑
tui                ← constants, paths, process, proxy, api, display
  ↑
commands           ← constants, paths, process, proxy, config, api, usage
  ↑
cc_proxy           ← 모든 모듈 (fan-out dispatcher)
```

## 각 모듈 상세

### 1. `constants.py` (~70줄)
- `IS_WINDOWS`, `PROVIDERS`, `PORTS`, `HOST`, `PRESETS`, `LOGIN_FLAGS`
- `TOKEN_DIR_ENV`, `TOKEN_DIR_META_FILE`
- ANSI 색상 코드 (`_C_GREEN`, `_C_RED`, ...)
- `_PROVIDER_BRAND_COLORS`
- TUI 상수 (`_TUI_ALT_ON`, `_TUI_KEY_*`, ...)
- 스키마 버전 상수

### 2. `paths.py` (~140줄, 현재 71-208행)
- `get_base_dir`, `get_host_arch`, `get_repo_binary_path`, `get_binary_path`
- `get_provider_dir`, `get_token_dir`, `get_token_files`, `get_pid_file`, `get_config_file`
- `_token_prefixes_for_provider`, `_token_file_sort_key`, `_resolve_token_root`
- `_save_token_dir_metadata`, `_is_path_under`, `resolve_account_file_path`

### 3. `process.py` (~130줄, 현재 211-395행)
- `read_pid`, `write_pid`, `remove_pid`, `is_pid_alive`, `kill_pid`, `kill_all_proxies`
- `resolve_pid_by_port`, `_resolve_pid_ss`, `_resolve_pid_lsof`, `find_free_port`
- `check_health`, `is_ssh_session`, `try_copy_to_clipboard`

### 4. `config.py` (~230줄, 현재 745-1008행)
- `rewrite_port_in_config`, `rewrite_auth_dir_in_config`, `rewrite_secret_in_config`
- `_parse_iso`, `_parse_token_expiry`, `get_token_infos`, `ensure_tokens`

### 5. `api.py` (~80줄, 현재 1030-1100행)
- `_management_api_request`, `_management_api`, `_proxy_api`, `_read_secret_key`

### 6. `quota.py` (~170줄, 현재 1190-1350행)
- `_management_api_call`, `_fetch_quota_antigravity`, `_fetch_quota_claude`, `_fetch_quota_openai`
- `_QUOTA_FETCHERS` dict
- `_quota_cache_path`, `_quota_cache_load`, `_quota_cache_save`

### 7. `usage.py` (~230줄, 현재 1350-1558행)
- `_usage_snapshot_path`, `_usage_snapshot_save`, `_usage_snapshot_load`
- `_capture_usage_snapshot_before_stop`
- `_usage_cumulative_*` (path, load, save, clear, update_from_live, apply_to_usage_data)
- `_usage_totals_extract`

### 8. `proxy.py` (~370줄, 현재 830-941행 + 398-743행)
- **Proxy 생명주기**: `start_proxy`, `stop_proxy`, `get_status`
- **대시보드 서버**: `get_local_port_offset`, `get_management_port`, `get_management_url`
- `get_dashboard_*`, `stop_dashboard_server`, `_start_dashboard_server`
- `render_dashboard_html`, `ensure_dashboard_html`
- `should_open_auth_browser`, `print_management_links`, `cmd_links`

### 9. `display.py` (~560줄, 현재 1102-2163행)
- **포맷팅**: `_fmt_tokens`, `_time_ago`, `_fmt_local_dt`, `_fmt_reset_time`, `_fmt_quota_bar`, `_quota_window_rank`
- **ANSI/박스**: `_supports_truecolor`, `_provider_frame_color`, `_strip_ansi`, `_visible_len`, `_clip_visible`
- **박스 드로잉**: `_box_line`, `_box_top`, `_box_bottom`, `_box_sep`
- **계정 헬퍼**: `_acct_status_label`, `_account_identity`, `_dedupe_auth_files`
- **데이터 집계**: `_aggregate_per_account`, `_prefetch_provider_data`
- **대시보드 렌더**: `_print_status_dashboard`

### 10. `tui.py` (~680줄, 현재 2165-2843행)
- **화면 제어**: `_tui_write`, `_tui_flush`, `_tui_enter_screen`, `_tui_leave_screen`
- **입력**: `_tui_key_to_action`, `_read_key_timeout`, `_tui_clear_input_buffer`, `_tui_discard_pending_input`
- **로직**: `_tui_fetch_provider`, `_tui_fetch_provider_light`, `_tui_toggle_account`
- **렌더링**: `_tui_render`
- **메인 루프**: `_tui_main_loop`

### 11. `commands.py` (~350줄, 현재 2845-3170행)
- `run_auth`, `invoke_claude`
- `install_profile`, `_install_profile_linux`, `_install_profile_windows`
- `cmd_set_secret`, `_propagate_token_dir`, `cmd_token_dir`, `cmd_token_list`, `cmd_token_delete`

### 12. `cc_proxy.py` (~300줄, 현재 3172-3448행 + docstring)
- 모듈 docstring (usage 안내)
- `print_usage()`
- `main()` ? CLI 인수 파싱 + 각 모듈 함수 호출
- `if __name__ == "__main__": sys.exit(main())`
- `status` 커맨드의 threading + prefetch 로직 (현재 main() 내 인라인, display 함수 직접 호출)

## 마이그레이션 전략

### 순서: Bottom-up (의존성 없는 모듈부터)
1. `constants.py` 추출
2. `paths.py` 추출
3. `process.py` 추출
4. `config.py` 추출
5. `api.py` 추출
6. `quota.py` 추출
7. `usage.py` 추출
8. `proxy.py` 추출
9. `display.py` 추출
10. `tui.py` 추출
11. `commands.py` 추출
12. `cc_proxy.py`를 thin dispatcher로 축소

### 각 단계에서:
- 해당 함수들을 새 모듈로 이동
- 필요한 import 문 추가 (sibling import: `from constants import ...`)
- `cc_proxy.py`에서 해당 함수 제거, 새 모듈에서 import
- 단계마다 `python3 core/cc_proxy.py status` 등으로 동작 확인

### 주의사항
- `stop_proxy`가 `_capture_usage_snapshot_before_stop`를 호출 → `proxy.py`에서 `usage`를 import
- `_prefetch_provider_data`가 `get_status`, `_management_api`, quota/usage 함수 모두 사용 → `display.py`에서 여러 모듈 import
- 모듈 레벨 mutable state (`_BOX_EDGE_COLOR` 등)는 해당 모듈에 유지
- lazy import (urllib, webbrowser, fcntl 등)는 원래 위치의 모듈에 유지

## 검증

1. **기본 동작**: `CC_PROXY_ALLOW_REPO_RUN=1 python3 core/cc_proxy.py status`
2. **모든 서브커맨드**: `status`, `status --quota`, `status -s`, `start all`, `stop`, `ui`, `links`, `token-list`, `token-dir`, `usage-clear`, `install-profile --hint-only`
3. **Shell wrapper 호환**: `source shell/bash/cc-proxy.sh && cc-proxy-status`
4. **설치 후 검증**: `python3 installers/install.py --source local` → 설치 경로에서 실행 확인

## CLAUDE.md 업데이트
- "core/cc_proxy.py (~650 lines)" → 모듈 구조 설명으로 교체
- 편집 가이드 업데이트: 각 도메인별 수정 대상 모듈 안내
