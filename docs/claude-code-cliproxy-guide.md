# Claude Code + CLIProxyAPI 통합 멀티-프로바이더 운영 가이드

> **지원 환경**: Windows (PowerShell) / Linux (Bash)
> **공통 목표**: Claude Code에서 OpenAI Codex, Google Gemini, Antigravity, Anthropic Claude 등 다양한 모델을 **로컬 프록시(CLIProxyAPI)** 를 경유하여 사용합니다. Provider별로 **자격증명(토큰)을 분리**해 원치 않는 호출 혼입을 방지하고 분산 환경을 손쉽게 모니터링합니다.

---

## 1. 아키텍처 개요

기존에는 쉘 스크립트(PowerShell, Bash)가 복잡한 프로세스 관리 로직을 모두 가지고 있었으나, 현재는 **Python 코어 스크립트(`core/cc_proxy.py`)** 가 모든 논리를 담당하고 OS 쉘 스크립트는 단순 래퍼(Thin wrapper) 역할만 수행합니다.

| 환경 | 스크립트 위치 | 스크립트 로드 방식 | 프로필 등록 명령 | 바이너리 |
|---|---|---|---|---|
| **Windows** | `shell/powershell/cc-proxy.ps1` | `. .\shell\powershell\cc-proxy.ps1` | `Install-CCProxyProfile` | `CLIProxyAPI/windows/amd64/cli-proxy-api.exe` |
| **Linux** | `shell/bash/cc-proxy.sh` | `source shell/bash/cc-proxy.sh` | `cc_proxy_install_profile` | `CLIProxyAPI/linux/<arch>/cli-proxy-api` |

**핵심 원리 (공통)**:
1. **Provider별 고정 포트**: (Antigravity: 18417, Claude: 18418, Codex: 18419, Gemini: 18420)
2. **Provider 격리**: `configs/<provider>/` 디렉터리를 기준 경로로 삼고 `auth-dir: "./"` 설정을 통해 각 프록시는 자신의 폴더에 있는 토큰만 사용합니다.
3. **상태 관리**: 메모리가 아닌 `configs/<provider>/.proxy.pid` 파일로 추적해 쉘 세션과 무관하게 생명주기를 관리합니다.

---

## 2. 초기 설치 및 셋업

### 2.1 저장소 클론 및 바이너리 다운로드

1. 이 저장소를 로컬로 클론합니다.
   ```bash
   git clone <repo-url> claude-code-cli-proxy
   cd claude-code-cli-proxy
   ```

2. **운영체제/아키텍처에 맞는 바이너리**를 받아 아키텍처별 경로에 배치합니다.
   - **Windows amd64**: `CLIProxyAPI/windows/amd64/cli-proxy-api.exe`
   - **Linux amd64**: `CLIProxyAPI/linux/amd64/cli-proxy-api`
   - **Linux arm64**: `CLIProxyAPI/linux/arm64/cli-proxy-api`

   Linux 예시:
   ```bash
   mkdir -p CLIProxyAPI/linux/amd64
   wget -qO- "https://github.com/router-for-me/CLIProxyAPI/releases/latest/download/CLIProxyAPI_linux_amd64.tar.gz" | tar xz
   mv cli-proxy-api CLIProxyAPI/linux/amd64/cli-proxy-api
   chmod +x CLIProxyAPI/linux/amd64/cli-proxy-api
   ```

### 2.2 디렉터리 및 토큰 구조 세팅

아래와 같이 `configs/` 하위에 Provider별로 폴더를 만들고 JSON 형태의 인증(토큰) 파일들을 배치합니다.
(처음 셋업 시, `config.yaml`은 인증 명령어나 구동 시 자동 복사되므로 JSON 토큰들만 넣으면 됩니다)

```text
claude-code-cli-proxy/
  CLIProxyAPI/
    windows/amd64/cli-proxy-api.exe
    linux/amd64/cli-proxy-api
    linux/arm64/cli-proxy-api
  configs/
    claude/
      claude-account1.json
      ...
    gemini/
      gemini-account1.json
      ...
    codex/
    antigravity/
```

### 2.3 환경 스크립트 로드 및 프로필 등록

매번 스크립트를 로드하는 번거로움을 줄이려면 쉘 프로필(startup script)에 등록하세요.

**Windows (PowerShell)**:
```powershell
. .\shell\powershell\cc-proxy.ps1
Install-CCProxyProfile
```

**Linux (Bash)**:
```bash
source shell/bash/cc-proxy.sh
cc_proxy_install_profile
```
> 첫 로드 시 대화형(Y/N) 프롬프트로 자동 프로필 등록을 권장하기도 합니다.

---

## 3. 주요 명령어 가이드

### 3.1 모델 라우팅 실행
원하는 Provider에 따라 명령어를 입력하면, 프록시가 꺼져 있으면 자동 실행(start-if-needed)하고 헬스체크 후 Claude Code를 시작합니다.

```bash
cc                 # 순정 모드: 프록시 환경변수 제거 후 Claude Code 실행
cc-ag-claude       # Antigravity (Claude 모델 계열 매핑)
cc-claude          # Anthropic Claude
cc-codex           # OpenAI Codex
cc-gemini          # Google Gemini
cc-ag-gemini       # Antigravity (Gemini 모델 계열 매핑)
```

### 3.2 프로세스 모니터링 및 전체 제어
4개의 프록시를 일괄로 켜고, 링크를 통해 모니터링할 수 있습니다.

```bash
cc-proxy-start-all        # 4개의 프록시를 모두 백그라운드에서 구동
cc-proxy-status           # 각 프록시의 PID, 구동 및 Health 상태, 토큰 상태 출력
cc-proxy-links            # 전체 Provider Management 링크 및 통합 대시보드 링크 출력
cc-proxy-links claude     # 특정 Provider의 링크만 출력
cc-proxy-stop             # 구동 중인 모든 프록시 프로세스와 대시보드 서버 일괄 종료
cc-proxy-auth gemini      # 특정 Provider 재인증 (OAuth 브라우저 오픈)
```

---

## 4. 통합 대시보드 (Management UI)

`cc-proxy-links` 명령어를 사용하면 **http://127.0.0.1:<포트>/cc_proxy_management_dashboard.html** 형태의 **통합 대시보드 링크**가 출력됩니다. (터미널에서 `Ctrl+Click` 지원)

- 통합 대시보드는 4개의 Provider 화면을 2x2 그리드(iframe)로 보여주며, 곧바로 쿼터(Quota) 모니터링 화면으로 진입합니다.
- 특정 환경(CSP, X-Frame-Options)으로 인해 패널이 빈 화면으로 나오면, 상단의 `Open directly` 링크를 통해 개별 탭으로 직접 열어 관찰할 수 있습니다.
- 대시보드를 서빙하는 로컬 HTTP 서버는 프로세스에 독립적이며, `cc-proxy-stop` 시 깔끔하게 함께 정리됩니다.

### 확인 가능 지표:
- Model Name = 요청된 모델 ID
- Source = 요청 처리에 사용된 Auth 파일(토큰) 식별자
- Token usage = 컨텍스트 / 캐시 / 출력 사용량

---

## 5. FAQ 및 트러블슈팅

### Q1. Provider 간 모델 요청이 섞입니다.
A1. `configs/<provider>` 단위로 폴더를 나누고 `auth-dir: "./"`로 설정했는지 점검하세요. 이 구조를 지키면 다른 계정의 토큰이 읽힐 구조적 가능성이 차단됩니다.

### Q2. cc-claude 등을 실행했는데 `curl` 오류가 발생하거나 헬스체크를 통과 못합니다. (Windows)
A2. PowerShell 5.x의 `curl`이 기본 내장 `Invoke-WebRequest` 알리어스일 때 발생합니다. `curl.exe`가 설치되어 동작 가능한지 확인하세요. (최신 스크립트는 내부적으로 `curl.exe`를 우선 찾도록 개선되었습니다)

### Q3. GUI가 없는 헤드리스(Headless) Linux 서버에서 사용할 수 있나요?
A3. 네, 구동 시 브라우저를 강제 오픈하지 않고 링크만 터미널에 출력하는 방식으로 개편되었습니다. 포트 포워딩이나 SSH 터널링을 맺은 뒤 클라이언트 브라우저에서 제공된 `http://` 링크에 접속하시면 대시보드를 사용할 수 있습니다.

### Q4. 토큰 인증(새 로그인)은 어떻게 하나요?
A4. 아래 커맨드를 통해 Provider별 인증을 다시 진행할 수 있습니다. (OAuth 브라우저가 열립니다)
```bash
cc-proxy-auth gemini
```
인증에 성공하면 프록시가 자동으로 재시작되어 최신 토큰을 반영합니다.

### Q5. "Permission denied" 오류가 발생합니다. (Linux)
A5. 다운로드 받은 바이너리에 실행 권한이 없는 경우입니다. `chmod +x CLIProxyAPI/linux/<arch>/cli-proxy-api` 명령으로 실행 권한을 부여하세요.

### Q6. 프록시 프로세스가 비정상 종료되어 시작이 안 됩니다.
A6. `cc-proxy-stop` 명령을 실행하면 남아있는 `.proxy.pid` 파일들이 모두 자동 정리됩니다. 포트 충돌이 의심될 경우 Windows는 `netstat -ano -p TCP`, Linux는 `ss -tlnp` 명령으로 직접 확인할 수 있습니다.

---

> 기타 문의사항이나 세부 코드는 본 저장소의 `core/cc_proxy.py` 모듈과 `CLAUDE.md`를 참고하세요.
