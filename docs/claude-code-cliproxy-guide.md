# Claude Code + CLIProxyAPI 통합 멀티-프로바이더 운영 가이드

> **지원 환경**: Windows (PowerShell) / Linux (Bash)
> **공통 목표**: Claude Code에서 OpenAI OpenAI, Google Gemini, Antigravity, Anthropic Claude 등 다양한 모델을 **로컬 프록시(CLIProxyAPI)** 를 경유하여 사용합니다. Provider별로 **자격증명(토큰)을 분리**해 원치 않는 호출 혼입을 방지하고 분산 환경을 손쉽게 모니터링합니다.

---

## 1. 아키텍처 개요

기존에는 쉘 스크립트(PowerShell, Bash)가 복잡한 프로세스 관리 로직을 모두 가지고 있었으나, 현재는 **Python 코어 스크립트(`core/cc_proxy.py`)** 가 모든 논리를 담당하고 OS 쉘 스크립트는 단순 래퍼(Thin wrapper) 역할만 수행합니다.

| 환경 | 스크립트 위치 | 스크립트 로드 방식 | 프로필 등록 명령 | 바이너리 |
|---|---|---|---|---|
| **Windows** | `shell/powershell/cc-proxy.ps1` | `. .\shell\powershell\cc-proxy.ps1` | `Install-CCProxyProfile` | `CLIProxyAPI/windows/amd64/cli-proxy-api.exe` |
| **Linux** | `shell/bash/cc-proxy.sh` | `source shell/bash/cc-proxy.sh` | `cc_proxy_install_profile` | `CLIProxyAPI/linux/<arch>/cli-proxy-api` |

**핵심 원리 (공통)**:
1. **Provider별 고정 포트**: (Antigravity: 18417, Claude: 18418, OpenAI: 18419, Gemini: 18420)
2. **Provider 격리**: 토큰 파일명 prefix(`claude-*`, `gemini-*`, `openai-*`, `antigravity-*`)로 provider를 구분합니다.
3. **토큰 디렉터리 일원화**: 기본 `configs/tokens`를 사용하며, `CC_PROXY_TOKEN_DIR`(환경변수) 또는 `cc-proxy-token-dir <path>`로 변경할 수 있습니다.
4. **상태 관리**: 메모리가 아닌 `configs/<provider>/.proxy.pid` 파일로 추적해 쉘 세션과 무관하게 생명주기를 관리합니다.

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

기본 토큰 저장 위치는 `configs/tokens/` 입니다. 파일명 prefix로 provider를 구분합니다.
(예: `claude-account1.json`, `gemini-work.json`, `openai-main.json`, `antigravity-team.json`)

```text
claude-code-cli-proxy/
  CLIProxyAPI/
    windows/amd64/cli-proxy-api.exe
    linux/amd64/cli-proxy-api
    linux/arm64/cli-proxy-api
  configs/
    tokens/
      claude-account1.json
      gemini-account1.json
      openai-account1.json
      antigravity-account1.json
    claude/
      config.yaml
    gemini/
      config.yaml
    openai/
      config.yaml
    antigravity/
      config.yaml
```

> 전환 호환성: 기존 `configs/<provider>/` 아래 토큰 파일도 병행 탐색합니다(점진 이전 지원). 실행 시 legacy 경로의 최신 파일이 공용 token-dir로 자동 동기화됩니다.

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
cc-openai           # OpenAI OpenAI
cc-gemini          # Google Gemini
cc-ag-gemini       # Antigravity (Gemini 모델 계열 매핑)
```

### 3.2 프로세스 모니터링 및 전체 제어
4개의 프록시를 일괄로 켜고, cc-proxy-ui를 통해 모니터링할 수 있습니다.

```bash
cc-proxy-start-all        # 4개의 프록시를 모두 백그라운드에서 구동
cc-proxy-status           # 각 프록시의 PID, 구동 및 Health 상태, 토큰 상태 출력
cc-proxy-ui               # 인터랙티브 TUI (계정 on/off, quota, 상태 통합 확인)
cc-proxy-stop             # 구동 중인 모든 프록시 프로세스 일괄 종료
cc-proxy-auth gemini      # 특정 Provider 재인증 (OAuth 브라우저 오픈)
cc-proxy-token-dir        # 현재 토큰 디렉터리 조회
cc-proxy-token-dir ~/secure-tokens  # 토큰 디렉터리 변경(저장)
cc-proxy-token-list       # 전체 provider 토큰 목록
cc-proxy-token-list claude # 특정 provider 토큰 목록
cc-proxy-token-delete claude claude-account1.json --yes  # 토큰 삭제
```


## 4. 토큰 관리 전략

### 6.1 공용 토큰 디렉터리 구조

모든 provider의 인증 토큰은 하나의 공용 디렉터리에서 관리합니다.

```
~/.cli-proxy/configs/tokens/         ← 공용 토큰 루트 (기본값)
  antigravity-account1.json          ← antigravity provider 토큰
  antigravity-account2.json
  claude-work.json                   ← claude provider 토큰
  claude-personal.json
  openai-main.json                    ← openai provider 토큰
  gemini-team.json                   ← gemini provider 토큰
```

**파일명 규칙** — `<provider>-<식별자>.json`
- `antigravity-` 또는 `ag-`: Antigravity provider
- `claude-`: Claude provider
- `openai-`: OpenAI provider
- `gemini-`: Gemini provider

인증(`cc-proxy-auth`)으로 발급된 토큰은 자동으로 이 규칙에 맞는 이름으로 저장됩니다.

---

### 6.2 토큰 디렉터리 변경

기본 위치를 유지해도 충분하지만, 보안 요건이나 외부 볼륨 마운트 등의 이유로 위치를 바꿀 수 있습니다.

```bash
# 현재 위치 확인
cc-proxy-token-dir

# 영구 변경 (설정 파일에 저장됨)
cc-proxy-token-dir ~/secure-tokens

# 이번 세션에서만 임시 변경
export CC_PROXY_TOKEN_DIR=~/secure-tokens
```

변경 후 첫 proxy 시작 시 legacy 위치의 파일이 새 위치로 자동 동기화됩니다.

**우선순위** (높을수록 우선):
1. `CC_PROXY_TOKEN_DIR` 환경변수
2. `~/.cli-proxy/.token-dir` 파일에 저장된 경로
3. `~/.cli-proxy/configs/tokens/` (기본값)

---

### 6.3 토큰 상태 확인

```bash
# 전체 provider 토큰 일람 (이메일, 상태, 경로)
cc-proxy-token-list

# 특정 provider만 조회
cc-proxy-token-list claude
```

출력 예시:
```
[cc-proxy] token-list claude (3):
[cc-proxy]    1. work@company.com        ok      /configs/tokens/claude-work@company.com.json
[cc-proxy]    2. personal@gmail.com      expired /configs/tokens/claude-personal@gmail.com.json
[cc-proxy]    3. team@company.com        ok      /configs/tokens/claude-team@company.com.json
```

상태 의미:
| 상태 | 설명 |
|------|------|
| `ok` | 유효한 토큰 |
| `expired` | 만료됨 → `cc-proxy-auth <provider>`로 재발급 필요 |
| `disabled` | 수동으로 비활성화됨 (`cc-proxy-ui`에서 space 키로 토글) |
| `unknown` | 토큰 파일은 있지만 형식을 파싱할 수 없음 |

---

### 6.4 토큰 삭제

```bash
# 이메일 주소로 지정
cc-proxy-token-delete claude work@company.com --yes

# 파일명으로 지정 (확장자 있어도/없어도 가능)
cc-proxy-token-delete claude claude-work@company.com.json --yes
cc-proxy-token-delete claude claude-work@company.com --yes

# --yes 없이 실행하면 대상 경로만 출력하고 취소
cc-proxy-token-delete claude work@company.com
```

**안전장치** — 다음 조건 중 하나라도 위반하면 삭제가 차단됩니다:
- `--yes` 플래그 없음
- 파일명이 provider prefix로 시작하지 않음 (`claude-work.json`이 아닌 `work.json` 등)
- 파일 경로가 허용 디렉터리 범위(`configs/tokens/` 또는 `configs/<provider>/`) 밖

---

### 6.5 권장 토큰 관리 워크플로우

#### 신규 계정 추가
```bash
cc-proxy-auth claude        # OAuth 인증 → configs/tokens/에 자동 저장
cc-proxy-token-list claude  # 저장 확인
cc-proxy-start-all          # proxy 재시작으로 새 토큰 반영
```

#### 만료된 토큰 갱신
```bash
cc-proxy-token-list         # expired 상태 계정 확인
cc-proxy-auth <provider>    # 해당 provider 재인증 (기존 파일 덮어쓰기)
```

#### 불필요한 토큰 정리
```bash
cc-proxy-token-list                              # 전체 목록 확인
cc-proxy-token-delete claude old@mail.com --yes  # 오래된 토큰 삭제
cc-proxy-stop && cc-proxy-start-all              # 반영을 위한 proxy 재시작
```

#### 토큰 디렉터리 이전/백업
```bash
# 새 위치로 이전
cc-proxy-token-dir ~/new-token-dir
# 기존 파일을 수동으로 복사 (또는 proxy 재시작 시 자동 sync)
cp ~/.cli-proxy/configs/tokens/*.json ~/new-token-dir/
```

---

### 6.6 보안 제안

1. **`.gitignore` 확인** — `configs/tokens/` 및 `configs/*/*.json`이 반드시 포함되어 있어야 합니다.
2. **파일 권한** — 토큰 파일은 소유자만 읽을 수 있도록 설정합니다.
   ```bash
   chmod 600 ~/.cli-proxy/configs/tokens/*.json
   ```
3. **토큰 디렉터리를 암호화 볼륨에** — 보안 민감 환경에서는 `cc-proxy-token-dir`로 경로를 암호화 볼륨 마운트 포인트로 변경하세요.
4. **정기적인 만료 확인** — `watch -n 3600 cc-proxy-token-list`로 만료 상태를 주기적으로 모니터링할 수 있습니다.

---

## 6. FAQ 및 트러블슈팅

### Q1. Provider 간 모델 요청이 섞입니다.
A1. cc-proxy는 파일명 prefix로 provider를 구분합니다. 토큰 파일명이 `claude-`, `antigravity-`, `openai-`, `gemini-`로 시작하는지 확인하세요. `cc-proxy-token-list`로 현재 목록을 조회할 수 있습니다. 잘못된 이름의 파일이 있다면 삭제 후 `cc-proxy-auth <provider>`로 재발급받으세요.

### Q2. cc-claude 등을 실행했는데 `curl` 오류가 발생하거나 헬스체크를 통과 못합니다. (Windows)
A2. PowerShell 5.x의 `curl`이 기본 내장 `Invoke-WebRequest` 알리어스일 때 발생합니다. `curl.exe`가 설치되어 동작 가능한지 확인하세요. (최신 스크립트는 내부적으로 `curl.exe`를 우선 찾도록 개선되었습니다)

### Q3. GUI가 없는 헤드리스(Headless) Linux 서버에서 사용할 수 있나요?
A3. 네, 구동 시 브라우저를 강제 오픈하지 않고 링크만 터미널에 출력하는 방식으로 개편되었습니다. 포트 포워딩이나 SSH 터널링을 맺은 뒤 클라이언트 브라우저에서 제공된 `http://` 링크에 접속하시면 대시보드를 사용할 수 있습니다.

### Q4. 토큰 인증(새 로그인)은 어떻게 하나요?
A4. 아래 커맨드를 통해 Provider별 인증을 다시 진행할 수 있습니다. (OAuth 브라우저가 열립니다)
```bash
cc-proxy-auth gemini
```
인증에 성공하면 프록시가 자동으로 재시작되어 최신 토큰을 반영합니다. 토큰은 현재 설정된 token-dir(기본 `configs/tokens`)에 저장됩니다.

### Q5. 토큰 저장 위치를 바꾸고 싶습니다.
A5. 아래 명령으로 변경할 수 있습니다.
```bash
cc-proxy-token-dir ~/secure-tokens
```
한 세션에서만 임시로 바꾸려면 환경변수(`CC_PROXY_TOKEN_DIR`)를 사용하세요.

### Q6. 토큰 목록 확인/삭제는 어떻게 하나요?
A6. 목록과 삭제 명령을 사용할 수 있습니다.
```bash
cc-proxy-token-list
cc-proxy-token-list claude
cc-proxy-token-delete claude claude-account1.json --yes
```
삭제는 provider prefix와 허용 경로 범위를 검증하므로, 범위 밖 파일은 거부됩니다.

### Q7. "Permission denied" 오류가 발생합니다. (Linux)
A7. 다운로드 받은 바이너리에 실행 권한이 없는 경우입니다. `chmod +x CLIProxyAPI/linux/<arch>/cli-proxy-api` 명령으로 실행 권한을 부여하세요.

### Q8. 프록시 프로세스가 비정상 종료되어 시작이 안 됩니다.
A8. `cc-proxy-stop` 명령을 실행하면 남아있는 `.proxy.pid` 파일들이 모두 자동 정리됩니다. 포트 충돌이 의심될 경우 Windows는 `netstat -ano -p TCP`, Linux는 `ss -tlnp` 명령으로 직접 확인할 수 있습니다.

---

> 기타 문의사항이나 세부 코드는 본 저장소의 `core/cc_proxy.py` 모듈과 `CLAUDE.md`를 참고하세요.
