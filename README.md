# claude-code-cli-proxy

Windows PowerShell 및 Linux Bash에서 CLIProxyAPI를 provider별로 분리 실행하고, Claude Code를 로컬 프록시로 연결하기 위한 운영용 저장소입니다.

## 핵심 개념

- 이 저장소는 **CLIProxyAPI 소스코드 저장소가 아니라 운영/설정 저장소**입니다.
- `powershell/cc-proxy.ps1` (Windows) 또는 `bash/cc-proxy.sh` (Linux)가 진입점이며, provider별 포트/환경변수/프로세스 관리를 담당합니다.
- provider 분리는 `configs/<provider>/` + `auth-dir: "./"` 구조로 강제됩니다.

## 구성 요소

- `cli-proxy-api.exe` (Windows binary, `CLIProxyAPI_6.8.24_windows_amd64`)
- `cli-proxy-api` (Linux binary, 별도 다운로드)
- `powershell/cc-proxy.ps1` (Windows helper functions)
- `bash/cc-proxy.sh` (Linux helper functions)
- `configs/<provider>/config.yaml` (+ credential JSON)
- `docs/claude-code-cliproxy-windows-guide.md` (Windows 운영 가이드)
- `docs/claude-code-cliproxy-linux-guide.md` (Linux 운영 가이드)
- `config.yaml` (루트 샘플/운영용 기본 설정: 신규 인증 토큰 발급 및 초기 설정 부트스트랩 용도)

## 빠른 시작

### Windows (PowerShell)

#### 1) 1회 로드

```powershell
. "D:\OneDrive\Tool\Productivity\claude-code-cli-proxy\powershell\cc-proxy.ps1"
```

최초 실행 시 프로필 등록 여부를 Y/N으로 묻습니다.

#### 2) 프로필 등록(자동 로드)

수동으로 실행하려면:

```powershell
Install-CCProxyProfile
```

등록 후 현재 세션에도 즉시 반영됩니다.

### Linux (Ubuntu)

#### 1) 바이너리 다운로드

```bash
cd ~/claude-code-cli-proxy
wget -qO- "https://github.com/router-for-me/CLIProxyAPI/releases/download/v6.8.26/CLIProxyAPI_6.8.26_linux_amd64.tar.gz" \
  | tar xz
chmod +x cli-proxy-api
```

> 새 버전이 나오면 [GitHub Releases](https://github.com/router-for-me/CLIProxyAPI/releases) 페이지에서 최신 URL을 확인합니다.

#### 2) 1회 로드

```bash
source ~/claude-code-cli-proxy/bash/cc-proxy.sh
```

처음 source 시 프로필 등록 여부를 Y/N으로 묻습니다.

#### 3) 프로필 등록(자동 로드)

```bash
cc_proxy_install_profile
```

`~/.bashrc` 및 `~/.zshrc`(존재 시)에 source 라인을 추가합니다.

### 실행 명령 (양 플랫폼 공통)

```
cc                 # Native Claude Code (proxy env 제거)
cc-claude          # Claude provider proxy 경유 (기동 필요 시 시작, 실행 중이면 재사용)
cc-gemini          # Gemini provider proxy 경유 (기동 필요 시 시작, 실행 중이면 재사용)
cc-codex           # Codex provider proxy 경유 (기동 필요 시 시작, 실행 중이면 재사용)
cc-ag-claude       # Antigravity provider proxy 경유 (Claude 계열 모델 세트)
cc-ag-gemini       # Antigravity provider proxy 경유 (Gemini 계열 모델 세트)

cc-proxy-status    # proxy 상태 확인
cc-proxy-stop      # proxy 중지(명시적으로 종료할 때만 사용)
```

## 포트 매핑

`powershell/cc-proxy.ps1` 및 `bash/cc-proxy.sh` 기준:

- claude: `18417`
- gemini: `18418`
- codex: `18419`
- antigravity: `18420`

헬스/모델 확인 예시 (Linux에서는 `curl`, Windows에서는 `curl.exe`):

```
curl -fsS http://127.0.0.1:18417/
curl http://127.0.0.1:18417/v1/models
```

## 참고 링크

- CLIProxyAPI repository: https://github.com/router-for-me/CLIProxyAPI
- API guide: https://help.router-for.me/

## 주의 사항

- `configs/*/*.json`은 credential/token 정보를 포함할 수 있습니다.
- 공개 저장소로 push하기 전에는 credential 유출 여부를 반드시 점검하세요.
- `configs/*/logs/`는 `.gitignore`로 제외되어 있습니다.
- `configs/*/.config.runtime.yaml` 및 `**/main.log`는 실행 중 생성/갱신되는 파일이므로 `.gitignore`로 추적 제외합니다.
- 루트 `config.yaml`은 `cli-proxy-api.exe`와 같은 경로에 두고 신규 인증 토큰 발급/초기 설정 시작점으로 사용합니다.
- provider별 `config.yaml`은 dashboard가 직접 갱신하는 운영 파일로 사용하며 Git 추적에서 제외합니다.
- 신규 provider는 루트 `config.yaml`을 템플릿으로 복사한 뒤 provider 포트(예: 18417~18420)를 설정해 사용합니다.
