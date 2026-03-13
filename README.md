# claude-code-cli-proxy

Windows PowerShell 및 Linux Bash에서 CLIProxyAPI를 provider별로 분리 실행하고, Claude Code를 로컬 프록시로 연결하기 위한 운영용 저장소입니다.

## 핵심 개념

- 이 저장소는 **CLIProxyAPI 소스코드 저장소가 아니라 운영/설정 저장소**입니다.
- `shell/powershell/cc-proxy.ps1` (Windows) 또는 `shell/bash/cc-proxy.sh` (Linux)가 진입점이며, provider별 포트/환경변수/프로세스 관리를 담당합니다.
- provider 격리는 **파일명 prefix** (`claude-*`, `antigravity-*`, `openai-*`, `gemini-*`) 기반으로 수행됩니다. 토큰 파일은 공용 디렉터리(`configs/tokens/`)에 모아두고, 각 provider binary는 동일 경로를 바라보며 prefix로 자신의 계정을 구분합니다.
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

## 설치 방법

저장소 루트에 4개의 진입점 스크립트가 있습니다:

| 스크립트 | 용도 |
|---|---|
| `install-local.ps1` | Windows — 현재 로컬 소스 → `~/.cli-proxy` 동기화 |
| `install-local.sh` | Linux/macOS — 현재 로컬 소스 → `~/.cli-proxy` 동기화 |
| `install-remote.ps1` | Windows — GitHub main 최신본 다운로드 후 설치 |
| `install-remote.sh` | Linux/macOS — GitHub main 최신본 다운로드 후 설치 |

실제 설치 로직은 `shell/` 디렉터리 내부에 있으며, 루트 스크립트는 얇은 진입점입니다.

### 로컬 개발 동기화 (수정사항 반영)

> 저장소에서 코드를 수정한 뒤 `~/.cli-proxy/` 실행 환경에 동기화할 때 사용합니다.
> 설치 완료 후 모든 프록시가 자동으로 재시작됩니다.

**Windows (PowerShell):**
```powershell
.\install-local.ps1
```

**Linux / macOS:**
```bash
bash install-local.sh
```

### 원격 설치 (GitHub에서 최신본 다운로드)

> 저장소를 클론하지 않고 GitHub main 브랜치 최신 코드를 `~/.cli-proxy/`에 설치합니다.

**Windows (PowerShell):**
```powershell
.\install-remote.ps1
```

또는 저장소 클론 없이 직접 실행 (최초 설치):
```powershell
irm https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/main/install-remote.ps1 | iex
```

**Linux / macOS:**
```bash
bash install-remote.sh
```

또는 저장소 클론 없이 직접 실행 (최초 설치):
```bash
curl -fsSL https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/main/install-remote.sh | bash
```

> **주의:** `install-remote`는 GitHub main 브랜치에서 파일을 다운로드합니다. 로컬 변경사항이 덮어씌워지므로 개발 중에는 `install-local`을 사용하세요.

### 제거 (Uninstall)

`--uninstall` 플래그를 동일한 진입점 스크립트에 전달합니다. 프록시 정지 → shim 제거 → 프로필 라인 삭제 → `~/.cli-proxy/` 삭제 순서로 실행됩니다.

**Windows:**
```powershell
.\install-local.ps1 --uninstall
```

**Linux / macOS (로컬 저장소에서):**
```bash
bash install-local.sh --uninstall
```

**Linux / macOS (저장소 없이, curl):**
```bash
curl -fsSL https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/main/install-remote.sh | bash -s -- --uninstall
```


### 실행 명령 (양 플랫폼 공통)

```
cc                 # Native Claude Code (proxy env 제거)
cc-ag-claude       # Antigravity provider proxy 경유 (Claude 계열 모델 세트)
cc-claude          # Claude provider proxy 경유 (기동 필요 시 시작, 실행 중이면 재사용)
cc-openai           # OpenAI provider proxy 경유 (기동 필요 시 시작, 실행 중이면 재사용)
cc-gemini          # Gemini provider proxy 경유 (기동 필요 시 시작, 실행 중이면 재사용)
cc-ag-gemini       # Antigravity provider proxy 경유 (Gemini 계열 모델 세트)

cc-proxy-start-all # 모든 provider proxy를 백그라운드로 한번에 기동
cc-proxy-status    # proxy 상태 확인
cc-proxy-links     # management URL 및 통합 대시보드 URL 출력 (URL 클립보드 자동 복사)
cc-proxy-stop      # proxy 중지(명시적으로 종료할 때만 사용)
cc-proxy-ui        # 인터랙티브 TUI (계정 on/off, quota, 상태 통합 확인)
cc-proxy-update    # 최신 버전으로 업데이트
```

### 업데이트

```
cc-proxy-update           # 업데이트 확인 및 적용
cc-proxy-update --force   # 미커밋 변경이 있어도 강제 적용
```

GitHub `main` 브랜치 최신 commit SHA와 현재 설치된 commit SHA를 비교해 업데이트를 결정합니다.

| 모드 | 조건 | 동작 |
|------|------|------|
| **Local** | 로컬 저장소가 메타데이터에 등록된 경우 | `git pull --ff-only` → `install.py --source local` |
| **Remote** | 로컬 저장소 없음 (순수 다운로드 설치) | `install.py --source remote` (GitHub에서 직접 다운로드) |

> 현재 모드는 `~/.cli-proxy/.install-meta.json`의 `local_source_root` 필드로 구분됩니다.
> dirty working tree가 있을 경우 `--force` 없이는 중단됩니다.

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
- openai: `18419`
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
openai 대시보드:         http://localhost:28419/management.html
gemini 대시보드:        http://localhost:28420/management.html
```

`cc-proxy-links` 명령 실행 시 위 URL들이 현재 오프셋 기준으로 출력되며, 통합 대시보드 URL은 클립보드에 자동 복사됩니다.

## 태그 기반 설치 아키텍처 요약

- installer는 source 모드를 지원합니다: `--source remote`(GitHub tag 기준), `--source local`(현재 로컬 트리 복사), `--source auto`(로컬 추론 우선).
- `installers/install.py`는 `CLIProxyAPI/<os>/<arch>/` 경로에서 플랫폼별 바이너리를 선택해 canonical 실행파일명으로 설치합니다.
- 설치 후 `~/.cli-proxy/.install-meta.json`에 설치 tag/repo/platform/source_mode/**commit_sha** 정보를 기록합니다. `cc-proxy-update`는 이 SHA를 기준으로 GitHub와 버전을 비교합니다.
- 실행은 `~/.cli-proxy` wrapper에서 수행하고, 개발 반영은 local source install로 동기화하는 방식을 권장합니다.

## 테스트

`tests/` 디렉토리에 유닛/스모크 테스트가 구현되어 있으며, stdlib `unittest` 기반으로 외부 의존성 없이 실행 가능합니다.

```powershell
# 전체 테스트 (101개)
py tests\run_tests.py -v

# 유닛 테스트만 (바이너리 불필요)
py tests\run_tests.py --unit -v

# 스모크 테스트만 (바이너리 필요)
py tests\run_tests.py --smoke -v
```

바이너리 업데이트 또는 코드 변경 시 반드시 테스트를 실행하여 호환성을 검증합니다. 자세한 테스트 절차 및 배포 가이드는 [`docs/testing-and-deployment.md`](docs/testing-and-deployment.md)를 참고하세요.

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
