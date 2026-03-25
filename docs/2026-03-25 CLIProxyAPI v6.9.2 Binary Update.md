# CLIProxyAPI v6.9.2 바이너리 업데이트

## 현재 상태

- **현재 바이너리 버전**: v6.8.55
- **최신 릴리스 버전**: v6.9.2
- **영향 받는 버전**: v6.9.0, v6.9.1, v6.9.2

## 버전별 변경사항 분석

### v6.9.0 (v6.8.55 → v6.9.0)

| 구분 | 변경사항 | 호환성 영향 |
|------|---------|------------|
| feat | `-local-model` 플래그 추가 (remote model catalog fetching 건너뛰기) | 없음 (바이너리 내부) |
| fix(auth) | OAuth callback 대기 시 blocking 방지 | 없음 |
| fix(claude) | `disable_parallel_tool_use` 옵션 준수 | 없음 |
| fix | Gemini `function_declarations`에서 `uniqueItems` 제거 | 없음 |
| refactor(auth) | callback URL 처리를 `AsyncPrompt`로 변경 | 없음 |

### v6.9.1 (v6.9.0 → v6.9.1)

| 구분 | 변경사항 | 호환성 영향 |
|------|---------|------------|
| feat(claude) | device profile stabilization 스위치 추가 | 없음 |
| fix(antigravity) | thought parts에 text 필드 항상 포함 → Google 500 에러 방지 | 없음 (bugfix) |
| fix(auth) | auth file 처리 시 절대 경로 보장 | 없음 |
| fix(claude) | fingerprint 관련 다수 수정 (racy downgrade 방지, baseline 유지 등) | 없음 |
| fix(translator) | Gemini `function_declarations`용 tool name sanitization | 없음 |
| fix | codex web search alias 처리, model-support fallback 강화 | 없음 |
| perf(watcher) | auth cache 메모리 사용량 감소 | 없음 |

### v6.9.2 (v6.9.1 → v6.9.2)

| 구분 | 변경사항 | 호환성 영향 |
|------|---------|------------|
| feat(api) | batch auth file upload/delete 지원 | 없음 (Management API) |
| feat(codex) | codex client identity 헤더 통과 (passthrough) | 없음 |
| feat(openai-compat) | per-model thinking 지원 (parentheses 문법) | 없음 (이미 preset에서 사용 중) |
| fix | #2274 수정 | 없음 |

### 새 CLI 플래그 (바이너리 `-h` 출력에서 확인)

| 플래그 | 용도 | 래퍼 영향 |
|--------|------|----------|
| `-qwen-login` | Qwen OAuth 로그인 | **새 provider 추가 시 필요** |
| `-local-model` | remote model catalog 건너뛰기 | 래퍼 불필요 (사용자 직접 사용) |
| `-standalone` | TUI 모드에 embedded local server 포함 | 래퍼 불필요 |
| `-tui` | Terminal management UI 시작 | 래퍼 불필요 (이미 `cc-proxy-ui` 존재) |

## 호환성 분석 결론

> [!IMPORTANT]
> **Breaking change 없음**. 기존 래퍼 코드가 v6.9.2 바이너리와 100% 호환됩니다.

### 필수 작업 (바이너리 업데이트)

1. `binary_updater.py`로 3개 플랫폼 바이너리 다운로드 (Windows/amd64, Linux/amd64, Linux/arm64)
2. `binary-version.txt`를 `v6.9.2`로 업데이트
3. smoke test 실행 → 통과 확인

### 선택 작업 (Qwen provider 추가)

바이너리가 `-qwen-login` 플래그를 지원하며, `config.yaml`에는 이미 `qwen` 채널이 참조되어 있으나 (`oauth-model-alias`, `oauth-excluded-models`), 래퍼 코드에는 `qwen` provider가 등록되어 있지 않음.

추가 시 변경 대상:
- `core/constants.py` — `PROVIDERS`, `PORTS`, `PRESETS`, `LOGIN_FLAGS`에 qwen 추가
- `shell/powershell/cc-proxy.ps1` — `cc-qwen` 함수 추가
- `shell/bash/cc-proxy.sh` — `cc-qwen` 함수 추가
- `tests/test_smoke.py` — `-qwen-login` 플래그 검증 추가
- `tests/test_constants.py` — qwen provider 포함 테스트 (자동 통과)

> [!NOTE]
> Qwen provider 추가는 이번 업데이트 범위에 **포함하지 않습니다** (별도의 feature 작업).

## 실행 계획

### 1단계: 바이너리 업데이트
```powershell
python core/binary_updater.py
```

### 2단계: 버전 파일 업데이트
`binary-version.txt` → `v6.9.2`

### 3단계: Smoke 테스트에 `-qwen-login` 플래그 추가
기존 `test_smoke.py`의 `test_help_shows_login_flags`에 `-qwen-login` 플래그 추가

### 4단계: 테스트 실행
```powershell
python tests/run_tests.py -v
```

## Verification Plan

### Automated Tests
1. `python tests/run_tests.py --unit -v` — 기존 유닛 테스트 전체 통과 확인
2. `python tests/run_tests.py --smoke -v` — 바이너리 존재, 버전 출력, 로그인 플래그 확인
3. 전체: `python tests/run_tests.py -v`

### Binary Verification
```powershell
# 새 바이너리 버전 확인
d:\OneDrive\Tool\Productivity\claude-code-cli-proxy\CLIProxyAPI\windows\amd64\cli-proxy-api.exe -h
# "CLIProxyAPI Version: 6.9.2" 출력 확인
```
