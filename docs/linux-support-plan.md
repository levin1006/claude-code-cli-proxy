# Linux Ubuntu 지원 구현 계획

> 이 문서는 Linux 지원 추가 작업의 계획과 설계 결정을 기록하는 참조용 문서입니다.

---

## 배경

이 프로젝트는 Windows 전용 CLIProxyAPI 운영 워크스페이스로, 여러 AI provider(Claude, Gemini, Codex, Antigravity) 프록시를 `powershell/cc-proxy.ps1`로 관리합니다. CLIProxyAPI가 공식적으로 Linux(amd64/arm64)를 지원하고, 설정 파일 형식이 동일하므로, Bash 스크립트와 문서만 추가하면 양 플랫폼에서 사용할 수 있습니다.

## 설계 원칙

1. **Windows 스크립트와 1:1 기능 대응**: 동일한 명령어 이름, 동일한 모델 문자열, 동일한 포트 번호
2. **플랫폼별 관용적 구현**: PowerShell 패턴을 무리하게 Bash로 옮기지 않고, Linux 생태계에 맞는 방식 사용
3. **최소 의존성**: Ubuntu 기본 패키지(bash, curl, iproute2)만 필수

## 핵심 설계 결정

### PID 파일 vs 인메모리 상태

PowerShell은 `$script:CLI_PROXY_PROVIDER_PIDS` 해시테이블로 세션 내 프로세스를 추적합니다.
Bash에는 동등한 스코프 메커니즘이 없으므로, `configs/<provider>/.proxy.pid` 파일로 영속적으로 추적합니다.

**장점**: 셸 세션이 끊겨도 프로세스를 추적할 수 있음
**주의**: 비정상 종료 시 stale PID 파일이 남을 수 있음 → `kill -0` 검증으로 보완

### 포트 리스닝 확인

- **Primary**: `ss -tlnp` (iproute2, Ubuntu 기본)
- **Fallback**: `lsof` (설치되어 있을 수 있음)
- PowerShell의 `Get-NetTCPConnection`을 대체

### 백그라운드 실행

```bash
(cd "$wd" && exec nohup "$EXE" -config "$config" > main.log 2>&1 &)
```

- `nohup`: 셸 종료 시에도 프로세스 유지
- 서브셸 `(...)`: 현재 셸의 작업 디렉터리를 변경하지 않음
- stdout/stderr를 `main.log`로 리다이렉션

### Base dir 자동 감지

```bash
CC_PROXY_BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
```

`BASH_SOURCE[0]`은 source된 스크립트의 실제 경로를 가리키므로, 어디서 source하든 올바른 base dir을 계산합니다.

### 프로필 통합

`~/.bashrc`와 `~/.zshrc` 모두 지원합니다. 존재하는 파일에만 source 라인을 추가하며, 둘 다 없으면 `~/.bashrc`를 생성합니다.

## 파일 목록

| 파일 | 유형 | 설명 |
|------|------|------|
| `bash/cc-proxy.sh` | 신규 | Bash 오케스트레이션 스크립트 |
| `docs/claude-code-cliproxy-linux-guide.md` | 신규 | Linux 운용 가이드 |
| `docs/linux-support-plan.md` | 신규 | 이 문서 |
| `.gitignore` | 수정 | Linux 바이너리, PID 파일 규칙 추가 |
| `CLAUDE.md` | 수정 | Linux 관련 섹션 추가 |
| `README.md` | 수정 | Linux 빠른 시작 섹션 추가 |

## 검증 절차

Linux 머신에서 다음 순서로 테스트:

1. `git pull`
2. 바이너리 다운로드 및 `chmod +x`
3. `source bash/cc-proxy.sh` → 에러 없이 로드
4. `cc-proxy-status` → 모든 provider "Stopped"
5. credential JSON 배치
6. `cc-claude` → 프록시 시작, 헬스체크 성공, claude 실행
7. `cc-proxy-stop` → 모든 프록시 종료
8. `cc_proxy_install_profile` → ~/.bashrc에 source 라인 추가
9. 새 터미널에서 `cc-proxy-status` 작동 확인

---

끝.
