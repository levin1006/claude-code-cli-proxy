# 테스트 및 배포 가이드

이 문서는 CLIProxyAPI 래퍼의 테스트 절차 및 바이너리 업데이트 시 배포 검증 과정을 설명합니다.

## 테스트 개요

### 구조

```
tests/
├── conftest.py          # 공통 fixture (tmp 디렉토리, 토큰 파일 생성)
├── run_tests.py         # stdlib unittest 기반 테스트 러너 (CI 연동)
├── test_constants.py    # PORTS, PRESETS, PROVIDERS, LOGIN_FLAGS 무결성
├── test_paths.py        # 경로 해석, 토큰 탐색, 보안 검증
├── test_config.py       # YAML 리라이트, 토큰 파싱, 시간 포맷
├── test_process.py      # PID 관리, 포트 해석, health check (mock)
├── test_proxy.py        # 프록시 라이프사이클, 상태 보고 (mock)
├── test_api.py          # Management API 클라이언트, secret key (mock)
└── test_smoke.py        # 바이너리 실행 검증, 모듈 import 검증
```

### 의존성

- **Python 3.8+** (stdlib만 사용, pip 설치 불필요)
- 스모크 테스트는 CLIProxyAPI 바이너리 필요
- pytest는 선택적 (있으면 활용, 없어도 unittest로 동작)

## 테스트 실행

### 전체 테스트

```powershell
# Windows
py tests\run_tests.py -v

# Linux
python3 tests/run_tests.py -v
```

### 유닛 테스트만 (바이너리 불필요)

```powershell
py tests\run_tests.py --unit -v
```

### 스모크 테스트만 (바이너리 필요)

```powershell
py tests\run_tests.py --smoke -v
```

### pytest 사용 (설치된 경우)

```powershell
# 전체
py -m pytest tests/ -v

# 유닛만
py -m pytest tests/ -v --ignore=tests/test_smoke.py

# 특정 모듈
py -m pytest tests/test_config.py -v
```

### 종료 코드

- `0`: 모든 테스트 통과
- `1`: 하나 이상 실패 → CI 파이프라인에서 빌드 실패로 처리 가능

## 배포 절차

CLIProxyAPI 바이너리 업데이트 또는 래퍼 코드 변경 시 아래 절차를 따릅니다.

### Step 1: 바이너리 배치

새 바이너리를 아키텍처별 경로에 배치합니다:

```
CLIProxyAPI/windows/amd64/cli-proxy-api.exe
CLIProxyAPI/linux/amd64/cli-proxy-api
CLIProxyAPI/linux/arm64/cli-proxy-api
```

### Step 2: 버전 확인

```powershell
.\CLIProxyAPI\windows\amd64\cli-proxy-api.exe -h
# → "CLIProxyAPI Version: X.Y.Z" 확인
```

### Step 3: 유닛 테스트

```powershell
py tests\run_tests.py -v
# → 모든 테스트 통과 확인 (종료 코드 0)
```

> **실패 시**: 릴리즈 노트를 확인하여 인터페이스 변경 사항 파악 후 래퍼 코드 수정.

### Step 4: 설치 동기화

```powershell
# Windows
py installers\install.py --source local

# Linux
python3 installers/install.py --source local
```

### Step 5: 설치 경로 스모크 테스트

반드시 **새 셸 창**에서 수행합니다:

```powershell
# 1) 래퍼 로드
. "$HOME\.cli-proxy\shell\powershell\cc-proxy.ps1"

# 2) 설치 경로 확인
$global:CLI_PROXY_BASE_DIR   # → ~/.cli-proxy 확인

# 3) 프록시 라이프사이클 순환
cc-proxy-start-all            # 모든 프록시 시작
cc-proxy-status               # running/healthy 확인
curl.exe http://127.0.0.1:18417/         # health check
curl.exe http://127.0.0.1:18417/v1/models  # 모델 목록 조회
cc-proxy-links                # management URL 출력
cc-proxy-stop                 # 전체 중지
cc-proxy-status               # stopped 확인
```

### Step 6: Git 커밋

```powershell
git add .
git commit -m "chore: update CLIProxyAPI to vX.Y.Z"
git tag vX.Y.Z   # 선택 사항
git push origin main --tags
```

## 배포 체크리스트 (Quick Reference)

| # | 항목 | 명령어 | 기대 결과 |
|---|------|--------|----------|
| 1 | 바이너리 배치 | (파일 복사) | 아키텍처별 경로에 존재 |
| 2 | 버전 확인 | `cli-proxy-api -h` | 새 버전 번호 표시 |
| 3 | 유닛 테스트 | `py tests/run_tests.py -v` | 종료 코드 0 |
| 4 | 설치 동기화 | `py installers/install.py --source local` | 성공 메시지 |
| 5 | 스모크 테스트 | `cc-proxy-start-all` → `cc-proxy-status` | running/healthy |
| 6 | API 검증 | `curl http://127.0.0.1:<port>/v1/models` | JSON 모델 목록 |
| 7 | 정리 | `cc-proxy-stop` | stopped |
| 8 | 커밋 | `git commit` | — |

## 새 테스트 추가 가이드

### 유닛 테스트 추가

1. `tests/test_<module>.py`에 `unittest.TestCase` 서브클래스 추가
2. 외부 I/O는 `unittest.mock.patch`로 mock
3. `run_tests.py`의 `UNIT_MODULES` 리스트에 모듈명 추가

### 스모크 테스트 추가

1. `tests/test_smoke.py`에 테스트 메서드 추가
2. 바이너리가 없으면 `self.skipTest()` 호출
3. `run_tests.py`의 `SMOKE_MODULES`에 이미 포함됨

### Mock 규칙

- `core/` 모듈은 `urllib.request`를 함수 내부에서 import → `@patch("urllib.request.urlopen")` 사용
- `subprocess.run`은 모듈 레벨 import → `@patch("모듈명.subprocess.run")` 사용
- 파일시스템은 `tempfile.mkdtemp()`로 임시 디렉토리 생성, `tearDown`에서 정리
