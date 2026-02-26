# Installation Architecture (Tag-Based Raw)

## Background

기존 설치 체계는 `main` raw와 외부 release URL이 혼합되어 있어 설치 결과 재현성이 약하고,
아키텍처 매칭(amd64/arm64) 오류가 발생할 수 있었습니다.

현재 구조의 목표는 다음 3가지를 동시에 만족하는 것입니다.

1. 검증된 커밋 기준 배포 (tag gate)
2. OS/아키텍처 자동 선택 (amd64/arm64)
3. 레포 내부 바이너리 경로 일원화로 운영 단순화

---

## 1) Tag-based raw 설치 흐름

one-liner 진입점(`installers/install.sh`, `installers/install.ps1`)은 저장소 raw URL에서 `installers/install.py`를 내려받아 실행합니다.
핵심은 브랜치 고정이 아니라 **ref 고정**입니다.

- 기본 동작: `main`
- 권장 운영: `--tag vX.Y.Z`
- 비호환 정책: 루트 one-liner(`.../install.sh`, `.../install.ps1`)는 미지원. `.../installers/install.sh`, `.../installers/install.ps1`만 지원

검증 완료 후 생성한 tag를 ref로 지정하면,
release asset 없이도 설치 결과 재현성을 확보할 수 있습니다.

---

## 2) Repository internal binary layout

바이너리는 저장소 내부의 아키텍처별 경로로 관리합니다.

- `CLIProxyAPI/windows/amd64/cli-proxy-api.exe`
- `CLIProxyAPI/linux/amd64/cli-proxy-api`
- `CLIProxyAPI/linux/arm64/cli-proxy-api`

설치 시에는 위 경로에서 플랫폼에 맞는 바이너리를 내려받아 아래 canonical 이름으로 배치합니다.

- Linux: `~/.cli-proxy/cli-proxy-api`
- Windows: `~/.cli-proxy/cli-proxy-api.exe`

---

## 3) install.py 플랫폼 매트릭스 해석

`install.py`는 아래 순서로 설치를 수행합니다.

1. Python 버전 검사 (3.8+)
2. 설치 디렉토리 생성 (`~/.cli-proxy/...`)
3. `config.yaml`, wrapper 스크립트, `core/cc_proxy.py` 다운로드
4. `platform.system()` + `platform.machine()` 정규화
   - `x86_64|amd64 -> amd64`
   - `aarch64|arm64 -> arm64`
5. 플랫폼 키(`linux-amd64`, `linux-arm64`, `windows-amd64`)로 레포 내부 바이너리 경로 선택
6. 바이너리 다운로드 + canonical 이름으로 설치
7. profile 연결

미지원 조합은 즉시 명확한 에러 메시지로 종료합니다.

또한 설치 완료 시 아래 파일로 배포 tag 추적 정보를 남깁니다.

- `~/.cli-proxy/.installed-tag` (단일 태그 문자열)
- `~/.cli-proxy/.install-meta.json` (`repo`, `tag`, `platform`, `installed_at_utc`, `binary_source`)

---

## 4) Deployment procedure (tag gate)

### 배포 전 필수 확인

1. 설치 스모크 테스트 (임시 경로)
   - Linux amd64
   - Linux arm64
   - Windows amd64
2. 설치 후 기본 동작 확인
   - `cc-proxy-status`
   - `cc-proxy-links`
   - `cc-codex` 시작 단계
3. 설치 추적 파일 확인
   - `~/.cli-proxy/.installed-tag`
   - `~/.cli-proxy/.install-meta.json`

### 배포 순서

1. 검증 완료 커밋 확정
2. tag 생성 (`vX.Y.Z`)
3. 사용자 설치 시 `--tag vX.Y.Z` 사용

핵심 원칙: **검증 완료 이전에는 운영용 tag를 생성하지 않습니다.**

---

## 5) Rollback model

이 구조에서는 이전 tag를 지정해 즉시 롤백 설치가 가능합니다.

- Linux: `installers/install.sh --tag vX.Y.Z`
- Windows: `installers/install.ps1 --tag vX.Y.Z`

설치 결과가 tag 기준으로 고정되므로, 재현 가능한 복구 경로를 제공합니다.
