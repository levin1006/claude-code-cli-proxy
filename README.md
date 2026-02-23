# claude-code-cli-proxy

Windows PowerShell에서 `cli-proxy-api.exe`를 provider별로 분리 실행하고, Claude Code를 로컬 프록시로 연결하기 위한 운영용 저장소입니다.

## 핵심 개념

- 이 저장소는 **CLIProxyAPI 소스코드 저장소가 아니라 운영/설정 저장소**입니다.
- `powershell/cc-proxy.ps1`가 진입점이며, provider별 포트/환경변수/프로세스 관리를 담당합니다.
- provider 분리는 `configs/<provider>/` + `auth-dir: "./"` 구조로 강제됩니다.

## 구성 요소

- `cli-proxy-api.exe` (binary, `CLIProxyAPI_6.8.24_windows_amd64`)
- `powershell/cc-proxy.ps1` (PowerShell helper functions)
- `configs/<provider>/config.yaml` (+ credential JSON)
- `docs/claude-code-cliproxy-windows-guide.md` (운영 가이드)

## 빠른 시작

### 1) 1회 로드

```powershell
. "D:\OneDrive\Tool\Productivity\claude-code-cli-proxy\powershell\cc-proxy.ps1"
```

최초 실행 시 프로필 등록 여부를 Y/N으로 묻습니다.

### 2) 프로필 등록(자동 로드)

수동으로 실행하려면:

```powershell
Install-CCProxyProfile
```

등록 후 현재 세션에도 즉시 반영됩니다.

### 3) 실행 명령

```powershell
cc                 # Native Claude Code (proxy env 제거)
cc-claude          # Claude provider proxy 경유
cc-gemini          # Gemini provider proxy 경유
cc-codex           # Codex provider proxy 경유
cc-ag              # Antigravity provider proxy 경유

cc-proxy-status    # proxy 상태 확인
cc-proxy-stop      # proxy 중지
```

## 포트 매핑

`powershell/cc-proxy.ps1` 기준:

- claude: `18417`
- gemini: `18418`
- codex: `18419`
- antigravity: `18420`

헬스/모델 확인 예시:

```powershell
curl.exe -fsS http://127.0.0.1:18417/
curl.exe http://127.0.0.1:18417/v1/models
```

## 참고 링크

- CLIProxyAPI repository: https://github.com/router-for-me/CLIProxyAPI
- API guide: https://help.router-for.me/

## 주의 사항

- `configs/*/*.json`은 credential/token 정보를 포함할 수 있습니다.
- 공개 저장소로 push하기 전에는 credential 유출 여부를 반드시 점검하세요.
- `configs/*/logs/`는 `.gitignore`로 제외되어 있습니다.
