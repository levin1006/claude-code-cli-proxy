# Claude Code + CLIProxyAPI (Linux Ubuntu) 멀티-프로바이더 연결/분산 운용 가이드

> **환경 기준**: Ubuntu 20.04+ / Bash 4.2+ / CLIProxyAPI (linux_amd64 또는 linux_arm64) + Claude Code(claude CLI)
> **목표**: Windows 가이드와 동일한 provider 분리 구조를 Linux에서 운용한다.

---

## 0. 아키텍처 개요

Windows 버전과 동일한 개념이지만 실행 환경이 다르다.

| 항목 | Windows | Linux |
|------|---------|-------|
| 스크립트 | `powershell/cc-proxy.ps1` | `bash/cc-proxy.sh` |
| 프로세스 상태 | `$script:` 인메모리 | PID 파일 (`configs/<provider>/.proxy.pid`) |
| 포트 확인 | `Get-NetTCPConnection` | `ss -tlnp` / `lsof` fallback |
| 백그라운드 실행 | `Start-Process -WindowStyle Hidden` | `nohup ... &` |
| 브라우저 열기 | `Start-Process $url` | `xdg-open` / `open` |
| 프로필 등록 | `$PROFILE` (PowerShell) | `~/.bashrc` / `~/.zshrc` |

**핵심 원리는 동일**:
1. provider별 고정 포트(18417~18420)
2. `configs/<provider>/` 작업 디렉터리 분리 + `auth-dir: "./"`
3. `cc-<provider>` 함수가 start-if-needed / healthy-reuse 후 `claude` 실행

---

## 1. 사전 요구 사항

- **OS**: Ubuntu 20.04+ (또는 Bash 4.2+ 지원 Linux 배포판)
- **Bash**: 4.2 이상 (`bash --version`으로 확인; Ubuntu 20.04는 Bash 5.0 기본 탑재)
- **curl**: HTTP 헬스체크에 사용 (`sudo apt install curl`)
- **ss**: 포트 리스닝 확인 (iproute2 패키지, 대부분 기본 설치됨)
- **claude CLI**: Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)

---

## 2. 설치

### 2.1 저장소 클론

```bash
git clone <repo-url> ~/claude-code-cli-proxy
cd ~/claude-code-cli-proxy
```

### 2.2 바이너리 다운로드

GitHub Releases에서 Linux 바이너리를 다운로드한다.

**amd64 (x86_64)**:
```bash
cd ~/claude-code-cli-proxy
wget -qO- "https://github.com/router-for-me/CLIProxyAPI/releases/download/v6.8.26/CLIProxyAPI_6.8.26_linux_amd64.tar.gz" \
  | tar xz
chmod +x cli-proxy-api
```

**arm64 (aarch64)**:
```bash
cd ~/claude-code-cli-proxy
wget -qO- "https://github.com/router-for-me/CLIProxyAPI/releases/download/v6.8.26/CLIProxyAPI_6.8.26_linux_arm64.tar.gz" \
  | tar xz
chmod +x cli-proxy-api
```

> 새 버전이 나오면 https://github.com/router-for-me/CLIProxyAPI/releases 에서 최신 URL을 확인한다.

### 2.3 Credential 파일 배치

Windows와 동일하게 provider별 폴더에 JSON 토큰 파일을 배치한다.

```
configs/
  claude/
    claude-account1.json
    claude-account2.json
  gemini/
    gemini-account1.json
  codex/
    codex-account1.json
  antigravity/
    antigravity-account1.json
```

---

## 3. 프로필 등록

### 3.1 수동 로드 (1회성)

```bash
source ~/claude-code-cli-proxy/bash/cc-proxy.sh
```

처음 source 시 프로필 등록 여부를 Y/N으로 묻는다.

### 3.2 프로필에 영구 등록

```bash
cc_proxy_install_profile
```

이 명령은 `~/.bashrc`와 `~/.zshrc`(존재하는 경우)에 source 라인을 추가한다.
새 터미널을 열면 자동으로 로드된다.

---

## 4. 사용법

### 4.1 순정 Claude Code (프록시 없이)

```bash
cc
```

프록시 관련 환경변수(`ANTHROPIC_BASE_URL` 등)를 제거하고 `claude`를 실행한다.

### 4.2 Provider별 프록시 경유

```bash
cc-claude          # Claude provider (포트 18417)
cc-gemini          # Gemini provider (포트 18418)
cc-codex           # Codex provider  (포트 18419)
cc-ag-claude       # Antigravity provider, Claude 모델 세트 (포트 18420)
cc-ag-gemini       # Antigravity provider, Gemini 모델 세트 (포트 18420)
```

각 명령은:
1. 해당 provider 프록시가 실행 중이면 재사용
2. 실행 중이지 않으면 자동 시작
3. 헬스체크 후 `claude` 실행

### 4.3 프록시 상태 확인 / 종료

```bash
cc-proxy-status    # 전체 provider 상태 표시
cc-proxy-stop      # 전체 프록시 종료
```

---

## 5. Provider 분리 전략

Windows와 동일한 `auth-dir: "./"` 전략을 사용한다.

- 각 provider의 `configs/<provider>/config.yaml`에 `auth-dir: "./"`가 설정되어 있다.
- CLIProxyAPI가 해당 디렉터리에서 실행되므로, 해당 폴더의 토큰 파일만 로드한다.
- provider 혼입이 구조적으로 불가능하다.

---

## 6. 헬스체크

```bash
# Claude provider
curl -fsS http://127.0.0.1:18417/
curl http://127.0.0.1:18417/v1/models

# Gemini provider
curl -fsS http://127.0.0.1:18418/
curl http://127.0.0.1:18418/v1/models

# Codex provider
curl -fsS http://127.0.0.1:18419/

# Antigravity provider
curl -fsS http://127.0.0.1:18420/
```

### Management UI

```
http://127.0.0.1:<provider-port>/management.html
```

`cc-<provider>` 실행 시 자동으로 브라우저가 열린다(세션당 1회).
Headless 서버에서는 `CC_PROXY_MANAGEMENT_AUTO_OPEN=false`로 비활성화할 수 있다.

---

## 7. 트러블슈팅

### Permission denied

```bash
chmod +x ~/claude-code-cli-proxy/cli-proxy-api
```

### 포트 충돌

```bash
# 해당 포트를 사용하는 프로세스 확인
ss -tlnp sport = :18417
# 또는
lsof -iTCP:18417 -sTCP:LISTEN
```

### Stale PID 파일

프로세스가 비정상 종료된 경우 PID 파일이 남아있을 수 있다.

```bash
# 수동 정리
rm configs/*/.proxy.pid

# 또는 cc-proxy-stop 실행 (자동 정리됨)
cc-proxy-stop
```

### Headless 서버 (GUI 없음)

`xdg-open`이 없는 환경에서는 Management UI URL이 터미널에 출력된다.
자동 오픈을 끄려면 source 전에 설정:

```bash
export CC_PROXY_MANAGEMENT_AUTO_OPEN=false
source ~/claude-code-cli-proxy/bash/cc-proxy.sh
```

### claude CLI를 찾을 수 없음

```bash
# Node.js/npm이 설치되어 있는지 확인
node --version
npm --version

# claude CLI 설치
npm install -g @anthropic-ai/claude-code

# PATH에 npm global bin이 포함되어 있는지 확인
which claude
```

### Bash 버전이 4.2 미만

```bash
bash --version
# 업그레이드 필요 시
sudo apt update && sudo apt install bash
```

---

## 8. Windows와의 차이 요약

| 항목 | Windows | Linux |
|------|---------|-------|
| 바이너리 | `cli-proxy-api.exe` | `cli-proxy-api` |
| 스크립트 로드 | `. .\powershell\cc-proxy.ps1` | `source bash/cc-proxy.sh` |
| 프로필 등록 | `Install-CCProxyProfile` | `cc_proxy_install_profile` |
| base dir | 하드코딩 가능 | `BASH_SOURCE[0]` 기반 자동 감지 |
| 프로세스 추적 | 인메모리 (`$script:`) | PID 파일 |
| 명령 이름 | 동일 (`cc`, `cc-claude`, ...) | 동일 |
| 모델 이름 | 동일 | 동일 |
| 포트 번호 | 동일 (18417~18420) | 동일 |

---

끝.
