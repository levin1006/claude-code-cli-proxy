# claude-code-cli-proxy

Windows PowerShell 및 Linux Bash에서 CLIProxyAPI를 provider별로 분리 실행하고, Claude Code를 로컬 프록시로 연결하기 위한 운영용 저장소입니다.

## 핵심 개념

- 이 저장소는 **CLIProxyAPI 소스코드 저장소가 아니라 운영/설정 저장소**입니다.
- `shell/powershell/cc-proxy.ps1` (Windows) 또는 `shell/bash/cc-proxy.sh` (Linux)가 진입점이며, provider별 포트/환경변수/프로세스 관리를 담당합니다.
- provider 분리는 `configs/<provider>/` + `auth-dir: "./"` 구조로 강제됩니다.

## 구성 요소

저장소 내부 바이너리는 아키텍처별 경로로 관리합니다:

- `CLIProxyAPI/windows/amd64/cli-proxy-api.exe`
- `CLIProxyAPI/linux/amd64/cli-proxy-api`
- `CLIProxyAPI/linux/arm64/cli-proxy-api`

단일 명령어 설치를 완료하면 `~/.cli-proxy/` 디렉토리 아래에 다음 파일들이 자동으로 구성됩니다:

- canonical 실행파일명 바이너리: `cli-proxy-api.exe` (Windows) 또는 `cli-proxy-api` (Linux/macOS)
- `shell/powershell/cc-proxy.ps1` (Windows helper functions)
- `shell/bash/cc-proxy.sh` (Linux/macOS helper functions)
- `core/cc_proxy.py` (핵심 로직을 처리하는 공통 파이썬 스크립트)
- `configs/<provider>/config.yaml` (+ credential JSON)
- `docs/claude-code-cliproxy-windows-guide.md` (Windows 운영 가이드)
- `docs/claude-code-cliproxy-linux-guide.md` (Linux 운영 가이드)
- `config.yaml` (루트 샘플/운영용 기본 설정)

## 배포용 설치 (one-liner, `~/.cli-proxy`에 설치)

이 섹션은 **배포/최종 사용자 설치용**입니다. 저장소를 클론할 필요 없이 터미널에 명령어 한 줄을 복사하여 붙여넣으면 설치가 완료되며, `~/.cli-proxy` 디렉토리에 필요한 모든 파일과 바이너리가 구성됩니다.
저장소를 이미 clone해서 그 안의 파일을 직접 사용하려면 아래 **"저장소에서 직접 실행 (개발/검증)"** 섹션을 사용하세요.

> 호환성 정책: 기존 루트 one-liner URL(`.../install.sh`, `.../install.ps1`)은 더 이상 지원하지 않습니다. 반드시 `.../installers/install.sh`, `.../installers/install.ps1` 경로를 사용하세요.

### Windows (PowerShell)

관리자 권한 없이 일반 PowerShell에서 실행 가능합니다.

```powershell
irm https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/main/installers/install.ps1 | iex
```

특정 태그로 고정 설치하려면:

```powershell
$script = irm https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/main/installers/install.ps1
[ScriptBlock]::Create($script).InvokeReturnAsIs('--tag','vX.Y.Z')
```

설치 후 안내되는 명령어(`Install-CCProxyProfile`)를 실행하면 `$PROFILE`에 자동 등록되어 다음 세션부터 바로 사용할 수 있습니다.

### Linux / macOS (Bash)

```bash
curl -fsSL https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/main/installers/install.sh | bash
```

특정 태그로 고정 설치하려면:

```bash
curl -fsSL https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/main/installers/install.sh | bash -s -- --tag vX.Y.Z
```

설치 시 `~/.bashrc` 및 `~/.zshrc`에 자동으로 `source` 구문이 추가되므로, 터미널을 재시작하거나 `source ~/.cli-proxy/shell/bash/cc-proxy.sh`를 실행하면 즉시 적용됩니다.

---

## 저장소에서 직접 실행 (개발/검증)

> 이 방법은 **이미 clone한 repository의 파일을 직접 source**합니다.
> 즉, `~/.cli-proxy`에 재설치하지 않고 현재 작업 중인 저장소 내용을 그대로 사용합니다.

### Windows (PowerShell, repo root에서)

```powershell
. .\shell\powershell\cc-proxy.ps1
```

### Linux / macOS (Bash, repo root에서)

```bash
source shell/bash/cc-proxy.sh
```

---

## one-liner 설치 사용자용: `~/.cli-proxy` 수동 로드 (선택)

> 이 섹션은 one-liner로 이미 `~/.cli-proxy`에 설치된 경우에만 해당합니다.
> repository에서 직접 `source shell/...` 방식으로 실행 중이라면 이 섹션은 건너뛰세요.

### Windows (PowerShell)

#### 1) 1회 로드

```powershell
. "~\.cli-proxy\shell\powershell\cc-proxy.ps1"
```

최초 실행 시 프로필 등록 여부를 Y/N으로 묻습니다.

#### 2) 프로필 등록(자동 로드)

수동으로 실행하려면:

```powershell
Install-CCProxyProfile
```

등록 후 현재 세션에도 즉시 반영됩니다.

### Linux / macOS (Bash)

#### 1) 1회 로드

```bash
source ~/.cli-proxy/shell/bash/cc-proxy.sh
```

처음 source 시 프로필 등록 여부를 Y/N으로 묻습니다.

#### 2) 프로필 등록(자동 로드)

```bash
cc_proxy_install_profile
```

`~/.bashrc` 및 `~/.zshrc`(존재 시)에 source 라인을 추가합니다.

### 실행 명령 (양 플랫폼 공통)

```
cc                 # Native Claude Code (proxy env 제거)
cc-ag-claude       # Antigravity provider proxy 경유 (Claude 계열 모델 세트)
cc-claude          # Claude provider proxy 경유 (기동 필요 시 시작, 실행 중이면 재사용)
cc-codex           # Codex provider proxy 경유 (기동 필요 시 시작, 실행 중이면 재사용)
cc-gemini          # Gemini provider proxy 경유 (기동 필요 시 시작, 실행 중이면 재사용)
cc-ag-gemini       # Antigravity provider proxy 경유 (Gemini 계열 모델 세트)

cc-proxy-status    # proxy 상태 확인
cc-proxy-stop      # proxy 중지(명시적으로 종료할 때만 사용)
```

## 포트 매핑

`shell/powershell/cc-proxy.ps1` 및 `shell/bash/cc-proxy.sh` 기준:

- antigravity: `18417`
- claude: `18418`
- codex: `18419`
- gemini: `18420`

헬스/모델 확인 예시 (Linux에서는 `curl`, Windows에서는 `curl.exe`):

```
curl -fsS http://127.0.0.1:18418/
curl http://127.0.0.1:18418/v1/models
```

## 태그 기반 설치 아키텍처 요약

- 설치기는 저장소의 `raw` 경로를 사용하되, **`main` 고정이 아니라 `--tag vX.Y.Z`로 ref를 고정**할 수 있습니다.
- `installers/install.py`는 `CLIProxyAPI/<os>/<arch>/` 경로에서 플랫폼별 바이너리를 선택해 canonical 실행파일명으로 설치합니다.
- 설치 후 `~/.cli-proxy/.installed-tag`와 `~/.cli-proxy/.install-meta.json`에 설치 tag/repo/platform 정보를 기록해 역추적할 수 있습니다.
- release asset 없이도 태그 기준으로 재현 가능한 설치가 가능합니다.

## 참고 링크

- CLIProxyAPI repository: https://github.com/router-for-me/CLIProxyAPI
- API guide: https://help.router-for.me/

## 주의 사항

- `configs/*/*.json`은 credential/token 정보를 포함할 수 있습니다.
- 공개 저장소로 push하기 전에는 credential 유출 여부를 반드시 점검하세요.
- `configs/*/logs/`는 `.gitignore`로 제외되어 있습니다.
- `configs/*/.config.runtime.yaml` 및 `**/main.log`는 실행 중 생성/갱신되는 파일이므로 `.gitignore`로 추적 제외합니다.
- 루트 `config.yaml`은 저장소 루트에 유지하고 신규 인증 토큰 발급/초기 설정 시작점으로 사용합니다.
- provider별 `config.yaml`은 dashboard가 직접 갱신하는 운영 파일로 사용하며 Git 추적에서 제외합니다.
- 신규 provider는 루트 `config.yaml`을 템플릿으로 복사한 뒤 provider 포트(예: 18417~18420)를 설정해 사용합니다.
