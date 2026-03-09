# claude-code-cli-proxy

Windows PowerShell 및 Linux Bash에서 CLIProxyAPI를 provider별로 분리 실행하고, Claude Code를 로컬 프록시로 연결하기 위한 운영용 저장소입니다.

## 핵심 개념

- 이 저장소는 **CLIProxyAPI 소스코드 저장소가 아니라 운영/설정 저장소**입니다.
- `shell/powershell/cc-proxy.ps1` (Windows) 또는 `shell/bash/cc-proxy.sh` (Linux)가 진입점이며, provider별 포트/환경변수/프로세스 관리를 담당합니다.
- provider 격리는 **파일명 prefix** (`claude-*`, `antigravity-*`, `codex-*`, `gemini-*`) 기반으로 수행됩니다. 토큰 파일은 공용 디렉터리(`configs/tokens/`)에 모아두고, 각 provider binary는 동일 경로를 바라보며 prefix로 자신의 계정을 구분합니다.
- **실행은 반드시 `~/.cli-proxy`에 설치된 경로에서만 가능합니다.** 저장소에서 직접 실행하는 방식(`CC_PROXY_ALLOW_REPO_RUN=1` bypass 포함)은 지원하지 않습니다.

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
설치 과정에서 알아서 쉘 프로필(`$PROFILE`, `~/.bashrc`, `~/.zshrc`)을 찾아 래퍼 스크립트를 로드하는 구문을 자동 등록해 주므로, 설치가 끝나면 터미널 창을 껐다 켜기만 하면 바로 사용할 수 있습니다.

> 호환성 정책: 기존 루트 one-liner URL(`.../install.sh`, `.../install.ps1`)은 더 이상 지원하지 않습니다. 반드시 `.../installers/install.sh`, `.../installers/install.ps1` 경로를 사용하세요.

### Windows (PowerShell)

관리자 권한 없이 일반 PowerShell에서 실행 가능합니다.

```powershell
irm https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/main/installers/install.ps1 | iex
```

배포/검증용으로 특정 태그를 완전히 고정하려면(권장):

```powershell
irm https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/vX.Y.Z/installers/install.ps1 | iex
```

### Linux / macOS (Bash)

```bash
curl -fsSL https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/main/installers/install.sh | bash
```

배포/검증용으로 특정 태그를 완전히 고정하려면(권장):

```bash
curl -fsSL https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/vX.Y.Z/installers/install.sh | bash
```

원격/컨테이너 환경에서 management 링크 포트를 분리하려면(선택):

```bash
curl -fsSL https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/vX.Y.Z/installers/install.sh | bash -s -- --remote
```

---

## 개발 반영 설치 (로컬 소스 동기화)

> 권장 개발 플로우: 이곳 저장소(`claude-code-cli-proxy`) 폴더에서 코드를 수정한 뒤, 아래 명령어로 `~/.cli-proxy` 실행 환경에 동기화(덮어쓰기)합니다.
> **로컬 동기화 시에는 쉘 래퍼를 우회하여 아래처럼 Python 코어 스크립트(`install.py`)를 직접 실행하는 것을 공식 방법으로 권장합니다.**

### Windows (repo root에서)

```powershell
python installers\install.py --source local
```
> 참고: `.\installers\install.ps1 --source local` 로도 동일하게 동작합니다.

### Linux / macOS (repo root에서)

```bash
python3 installers/install.py --source local
```

---

## `~/.cli-proxy` 수동 로드 (선택)

> 기본적으로 설치 과정에서 쉘 프로필에 자동 등록되므로 아래 과정은 첫 설치 직후 터미널을 재시작하지 않고 현재 창에서 바로 사용하고 싶을 때만 1회 입력합니다.

### Windows (PowerShell)

```powershell
. "~\.cli-proxy\shell\powershell\cc-proxy.ps1"
```

### Linux / macOS (Bash)

```bash
source ~/.cli-proxy/shell/bash/cc-proxy.sh
```

### 실행 명령 (양 플랫폼 공통)

```
cc                 # Native Claude Code (proxy env 제거)
cc-ag-claude       # Antigravity provider proxy 경유 (Claude 계열 모델 세트)
cc-claude          # Claude provider proxy 경유 (기동 필요 시 시작, 실행 중이면 재사용)
cc-codex           # Codex provider proxy 경유 (기동 필요 시 시작, 실행 중이면 재사용)
cc-gemini          # Gemini provider proxy 경유 (기동 필요 시 시작, 실행 중이면 재사용)
cc-ag-gemini       # Antigravity provider proxy 경유 (Gemini 계열 모델 세트)

cc-proxy-start-all # 모든 provider proxy를 백그라운드로 한번에 기동
cc-proxy-status    # proxy 상태 확인
cc-proxy-links     # management URL 및 통합 대시보드 URL 출력 (URL 클립보드 자동 복사)
cc-proxy-stop      # proxy 중지(명시적으로 종료할 때만 사용)
cc-proxy-ui        # 인터랙티브 TUI (계정 on/off, quota, 상태 통합 확인)
```

### 토큰(인증) 관리

```
cc-proxy-auth <provider>                         # OAuth 재인증 (새 토큰 발급, 공용 디렉터리 저장)
cc-proxy-token-dir                               # 현재 공용 토큰 디렉터리 경로 확인
cc-proxy-token-dir <path>                        # 공용 토큰 디렉터리 변경 (영구 저장)
cc-proxy-token-list                              # 전체 provider 토큰 목록
cc-proxy-token-list <provider>                   # 특정 provider 토큰만 조회
cc-proxy-token-delete <provider> <token> --yes   # 토큰 파일 삭제 (안전장치 적용)
```

> `<token>`에는 파일명 (`claude-abc@mail.com.json`), 확장자 없는 이름, 이메일 주소, 전체 경로 모두 사용 가능합니다.

## 포트 매핑

`core/cc_proxy.py` 기준 (단일 진실 공급원):

- antigravity: `18417`
- claude: `18418`
- codex: `18419`
- gemini: `18420`
- 통합 대시보드 서버: `18500`

헬스/모델 확인 예시 (Linux에서는 `curl`, Windows에서는 `curl.exe`):

```
curl -fsS http://127.0.0.1:18418/
curl http://127.0.0.1:18418/v1/models
```

---

## 대시보드 접속 (SSH 원격 서버에서 실행 시)

> 로컬 머신에서 직접 실행하는 경우에는 이 섹션이 불필요합니다. 포트 포워딩 없이 `http://127.0.0.1:<port>/management.html`로 바로 접속할 수 있습니다.

SSH 원격 서버에서 proxy를 실행하는 경우, **브라우저는 로컬 머신에서 실행**되므로 원격 포트를 로컬로 포워딩해야 합니다.

### 왜 포트 포워딩이 필요한가

통합 대시보드(`cc_proxy_management_dashboard.html`)는 각 provider의 management 페이지를 `<iframe>`으로 임베드합니다. 브라우저는 iframe URL을 **server-side가 아닌 client-side 기준**으로 해석합니다. 즉, 통합 대시보드가 provider 포트를 참조할 때 로컬에서 해당 포트로 연결을 시도합니다. 따라서 provider 포트와 대시보드 서버 포트 모두 로컬로 포워딩해야 합니다.

### SSH 포트 포워딩 설정

`CC_PROXY_LOCAL_PORT_OFFSET=10000`을 설정한 경우 (기본 SSH 설정), 원격 포트에 10000을 더한 로컬 포트로 포워딩합니다:

```bash
ssh -L 28417:localhost:18417 \
    -L 28418:localhost:18418 \
    -L 28419:localhost:18419 \
    -L 28420:localhost:18420 \
    -L 28500:localhost:18500 \
    user@remote-host
```

또는 `~/.ssh/config`에 영구 설정:

```
Host myserver
    HostName remote-host
    LocalForward 28417 localhost:18417
    LocalForward 28418 localhost:18418
    LocalForward 28419 localhost:18419
    LocalForward 28420 localhost:18420
    LocalForward 28500 localhost:18500
```

### CC_PROXY_LOCAL_PORT_OFFSET 설정

`CC_PROXY_LOCAL_PORT_OFFSET`은 대시보드 및 management URL에 표시되는 포트를 오프셋만큼 이동시킵니다. SSH 포워딩 시 `=10000`으로 설정하면 원격 포트(18417~18420, 18500)가 로컬 포트(28417~28420, 28500)로 표시됩니다.

**자동 설정 (권장)**: `cc_proxy_install_profile` 또는 설치 시 프로필 등록을 수행하면, SSH 세션에서만 자동으로 `CC_PROXY_LOCAL_PORT_OFFSET=10000`이 적용됩니다:

```bash
# ~/.bashrc / ~/.zshrc에 자동 추가되는 내용
[ -n "${SSH_CONNECTION}" ] && export CC_PROXY_LOCAL_PORT_OFFSET=10000
```

로컬 실행 시에는 `SSH_CONNECTION`이 설정되지 않으므로 오프셋이 적용되지 않습니다. 양쪽 환경 모두 자동 호환됩니다.

**수동 설정**: 특정 값을 직접 지정하려면:

```bash
export CC_PROXY_LOCAL_PORT_OFFSET=10000   # SSH 세션
export CC_PROXY_LOCAL_PORT_OFFSET=0       # 로컬 실행 (기본값, 설정 불필요)
```

### 접속 URL (CC_PROXY_LOCAL_PORT_OFFSET=10000 기준)

```
통합 대시보드:          http://localhost:28500/cc_proxy_management_dashboard.html
antigravity 대시보드:   http://localhost:28417/management.html
claude 대시보드:        http://localhost:28418/management.html
codex 대시보드:         http://localhost:28419/management.html
gemini 대시보드:        http://localhost:28420/management.html
```

`cc-proxy-links` 명령 실행 시 위 URL들이 현재 오프셋 기준으로 출력되며, 통합 대시보드 URL은 클립보드에 자동 복사됩니다.

## 태그 기반 설치 아키텍처 요약

- installer는 source 모드를 지원합니다: `--source remote`(GitHub tag 기준), `--source local`(현재 로컬 트리 복사), `--source auto`(로컬 추론 우선).
- `installers/install.py`는 `CLIProxyAPI/<os>/<arch>/` 경로에서 플랫폼별 바이너리를 선택해 canonical 실행파일명으로 설치합니다.
- 설치 후 `~/.cli-proxy/.installed-tag`와 `~/.cli-proxy/.install-meta.json`에 설치 tag/repo/platform/source_mode 정보를 기록해 역추적할 수 있습니다.
- 실행은 `~/.cli-proxy` wrapper에서 수행하고, 개발 반영은 local source install로 동기화하는 방식을 권장합니다.

## 참고 링크

- CLIProxyAPI repository: https://github.com/router-for-me/CLIProxyAPI
- API guide: https://help.router-for.me/

## 주의 사항

- `configs/tokens/*.json`은 credential/token 정보를 포함합니다. 공용 토큰 디렉터리(`configs/tokens/`)는 `.gitignore`로 반드시 추적 제외하세요.
- 공개 저장소로 push하기 전에는 credential 유출 여부를 반드시 점검하세요.
- `configs/*/logs/`는 `.gitignore`로 제외되어 있습니다.
- `configs/*/.config.runtime.yaml` 및 `**/main.log`는 실행 중 생성/갱신되는 파일이므로 `.gitignore`로 추적 제외합니다.
- 루트 `config.yaml`은 저장소 루트에 유지하고 신규 인증 토큰 발급/초기 설정 시작점으로 사용합니다.
- provider별 `config.yaml`은 dashboard가 직접 갱신하는 운영 파일로 사용하며 Git 추적에서 제외합니다.
- 신규 provider는 루트 `config.yaml`을 템플릿으로 복사한 뒤 provider 포트(예: 18417~18420)를 설정해 사용합니다.
