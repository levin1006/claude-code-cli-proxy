# Context
사용자가 저장소(클론) 없이 쉽게 프로그램을 설치하고 사용할 수 있는 배포 방식을 문의했습니다.
유지보수를 용이하게 하기 위해, 운영체제별 진입점(`install.sh`, `install.ps1`)은 최소화하고 실제 설치 로직(디렉토리 생성, 파일 다운로드, 프로필 등록 등)은 파이썬 스크립트(`install.py`)로 통합하는 아키텍처를 적용합니다.
이 계획 문서는 `docs/installation-architecture.md`에도 저장하여 개발 완료 시 함께 커밋하고 이후 이 문서를 기반으로 유지보수합니다.

# Implementation Plan

## 1. 계획 문서 저장 (선행 작업)
- 현재까지 작성된 이 계획을 `docs/installation-architecture.md` 파일로 복사하여 프로젝트 히스토리로 남깁니다.

## 2. Core 설치 로직 (`install.py`) 작성
플랫폼(Windows/Linux/macOS)을 자동 감지하고 동일한 로직으로 설치를 수행하는 독립적인 파이썬 스크립트입니다.
- **사전 검사**: Python 3.8 이상 확인.
- **경로 설정**: 홈 디렉토리 아래 `~/.cli-proxy` (`$HOME/.cli-proxy`)를 설치 경로로 지정.
- **디렉토리 생성**: `bash/`, `powershell/`, `python/`, `configs/antigravity/`, `configs/claude/`, `configs/codex/`, `configs/gemini/`
- **파일 다운로드**:
    - `urllib.request`를 사용하여 GitHub Raw URL에서 직접 다운로드.
    - 다운로드 대상 저장소 정보는 파이썬 내장 `urllib`를 이용해 설치 스크립트 실행 환경에서 동적으로(또는 인자/환경 변수 통해) 유추 가능하도록 구성 (기본값은 현재 작업 중인 main 브랜치).
    - 대상 파일: `config.yaml`, `bash/cc-proxy.sh`, `powershell/cc-proxy.ps1`, `python/cc_proxy.py`.
- **바이너리 처리**:
    - **Linux/macOS**: 공식 릴리즈(`v6.8.24`) 압축파일(`CLIProxyAPI_6.8.24_linux_amd64.tar.gz`)을 다운로드 및 압축 해제 후 `~/.cli-proxy/cli-proxy-api`로 저장.
    - **Windows**: 저장소에 포함된 `CLIProxyAPI_6.8.24_windows_amd64.exe`를 Raw URL에서 다운로드하여 `~/.cli-proxy/cli-proxy-api.exe`로 저장.
    - Unix 환경일 경우 다운로드한 바이너리와 `bash/cc-proxy.sh` 쉘 래퍼 파일에 실행 권한(`chmod +x`) 부여.
- **프로필 등록**:
    - 다운로드한 `python/cc_proxy.py` 모듈을 임포트하거나 하위 프로세스로 실행하여 기존의 `install_profile()` (또는 쉘 스크립트의 해당 로직) 기능을 수행하도록 연동.
    - 혹은 `.bashrc`/`.zshrc` (Linux/macOS) 및 `$PROFILE` (Windows) 파일에 안전하게 래퍼를 `source` 하도록 문자열 추가.
- **완료 안내**: 사용자가 터미널을 재시작하거나 프로필을 리로드하도록 안내 메시지 출력.

## 3. 진입점 래퍼 스크립트 작성
사용자가 "복사 & 붙여넣기" 할 수 있는 아주 얇은 래퍼 스크립트입니다.

### 3.1 `install.sh` (Linux/macOS 용)
- `curl` 명령어 확인.
- `python3` 명령어 확인.
- GitHub Raw URL에서 `install.py`를 `/tmp/install_cc_proxy.py`로 다운로드.
- `python3 /tmp/install_cc_proxy.py` 실행.
- 스크립트 종료 후 임시 파일 삭제.

### 3.2 `install.ps1` (Windows 용)
- `[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12` 설정 (오래된 PowerShell 호환성).
- `python` 실행 파일 확인 (없으면 에러 출력).
- `Invoke-WebRequest`로 `install.py`를 `$env:TEMP\install_cc_proxy.py`로 다운로드.
- `python $env:TEMP\install_cc_proxy.py` 실행.
- 스크립트 종료 후 임시 파일 삭제.

# Critical Files
- `docs/installation-architecture.md` (계획 및 아키텍처 문서)
- `install.py` (핵심 설치 로직)
- `install.sh` (Linux/macOS 진입점 래퍼)
- `install.ps1` (Windows 진입점 래퍼)
