# Claude Code + CLIProxyAPI (Windows) 멀티‑프로바이더 연결/분산 운용 가이드
> **환경 기준**: Windows + PowerShell + CLIProxyAPI **6.8.24 (windows_amd64)** + Claude Code(claude CLI)  
> **목표**: Claude Code에서 **OpenAI Codex / Google Gemini / Antigravity / Anthropic Claude**를 **로컬 프록시(CLIProxyAPI)** 경유로 사용하고,  
> provider별로 **자격증명(토큰) 후보 풀을 강제 분리**하여 **원치 않는 provider 혼입을 방지**하며, 필요 시 **라운드로빈 분산**을 확인/운영한다.

---

## 0. 개요(Architecture)
Claude Code는 기본적으로 Anthropic API를 호출한다. 하지만 아래 환경변수를 주면 호출 대상을 바꿀 수 있다.

- `ANTHROPIC_BASE_URL` : Claude Code가 호출할 API 베이스 URL
- `ANTHROPIC_AUTH_TOKEN` : Claude Code가 Anthropic API를 호출할 때 쓰는 토큰 (프록시 사용 시 **더미**로 둠)
- `ANTHROPIC_DEFAULT_OPUS_MODEL / _SONNET_MODEL / _HAIKU_MODEL` : Claude Code 내부 슬롯(Opus/Sonnet/Haiku)에 대응할 “모델 ID”

**CLIProxyAPI**는 로컬에서 OpenAI/Anthropic 호환 API를 제공하는 프록시 서버로 동작한다.

- Claude Code → `ANTHROPIC_BASE_URL=http://127.0.0.1:8317` 로 CLIProxyAPI 호출
- CLIProxyAPI → 내부에 저장된 OAuth 토큰(또는 API 키)로 업스트림(OpenAI/Gemini/Anthropic/Antigravity 등) 호출
- **결론**: “실제 인증 토큰”은 Claude Code가 아니라 **CLIProxyAPI의 auth-dir에 저장된 토큰 파일**이 들고 있다.

---

## 1. 왜 provider를 분리해야 했나?
처음에는 하나의 auth-dir에 여러 provider의 토큰 파일을 넣고 `routing.strategy: round-robin`으로 분산 운용을 시도했다.

그러나 관찰 결과(Management Center 로그 기반):

- 모델명이 `claude-sonnet-4-6`처럼 **동일하거나 유사**하면,
- CLIProxyAPI가 **provider를 강제하지 않고**(또는 fallback/우회 정책 때문에)  
  **Antigravity credential까지 후보로 포함**하여 요청을 처리하는 현상이 있었다.

즉, “Claude만 쓰고 싶은데 Antigravity가 섞여 호출되는 문제”가 발생.

그래서 최종적으로 선택한 전략은:

✅ **한 번에 CLIProxyAPI 인스턴스는 1개(포트 8317 하나)**만 띄우되,  
✅ **WorkingDirectory를 provider별 configs 폴더로 바꿔 재시작**하여,  
✅ `auth-dir: "./"`로 각 provider 폴더의 토큰만 로드하게 강제한다.

이렇게 하면 **원치 않는 provider 혼입이 구조적으로 불가능**해진다.

---

## 2. 디렉터리 구조(최종)
아래 구조를 CLIProxyAPI 실행 파일 위치 아래에 만든다.

```
CLIProxyAPI_6.8.24_windows_amd64/
  cli-proxy-api.exe
  configs/
    claude/
      config.yaml
      claude-<account1>.json
      claude-<account2>.json
      claude-<account3>.json
    gemini/
      config.yaml
      gemini-<account1>.json
      gemini-<account2>.json
      ...
    codex/
      config.yaml
      codex-<account>.json
    antigravity/
      config.yaml
      antigravity-<account1>.json
      antigravity-<account2>.json
      antigravity-<account3>.json
```

### 2.1 `auth-dir: "./"`의 의미
각 provider 폴더에서 CLIProxyAPI가 실행되므로, `./`는 해당 폴더를 의미한다.

- `configs/claude`에서 실행 ⇒ `auth-dir: "./"` ⇒ Claude 토큰만 로드
- `configs/antigravity`에서 실행 ⇒ Antigravity 토큰만 로드

### 2.2 한 PC에서 여러 인스턴스를 동시에 띄울 수 있나?
구조적으로는 **가능**하지만, 현재 제공한 `cc-*` 함수 동작은 의도적으로 **항상 단일 인스턴스**다.

- `Start-CLIProxy` 내부에서 먼저 `Stop-CLIProxy`를 호출해 기존 프로세스를 종료함
- 모든 provider config가 기본적으로 같은 포트(`8317`)를 사용함
- 결과적으로 여러 터미널에서 서로 다른 `cc-*`를 실행하면 마지막 실행이 이전 인스턴스를 대체함

즉, 지금 관찰한 "마지막 것만 남는" 현상은 정상 동작이다.

동시 다중 인스턴스가 필요하면 다음 두 조건을 만족해야 한다.
1. provider별로 서로 다른 `port`를 사용
2. 각 터미널/세션에서 `ANTHROPIC_BASE_URL`을 해당 포트로 별도 지정

---

## 3. config.yaml 템플릿(공통)
provider별로 거의 동일하게 유지 가능. 핵심은 `auth-dir`가 로컬(`./`)로 잡힌다는 점.

```yaml
host: "127.0.0.1"
port: 8317

# provider 폴더에 토큰 json을 같이 두는 전략
auth-dir: "./"

routing:
  strategy: "round-robin"  # round-robin (default), fill-first

# 재시도/쿼터 정책(필요 시)
request-retry: 3
max-retry-interval: 30

quota-exceeded:
  switch-project: true
  switch-preview-model: true
```

> 참고: 위 `quota-exceeded` 정책이 실제로 provider 혼입까지 유발할 수 있으므로, provider 분리 구조(이번 문서)가 사실상 “안전장치”다.

---

## 4. 모델 목록 확인(로컬 프록시 기준)
Claude Code에 넣는 모델 ID는 **항상 CLIProxyAPI가 수용 가능한 문자열**이어야 한다.

가장 신뢰할 수 있는 기준은 아래 엔드포인트:

```powershell
curl.exe http://127.0.0.1:8317/v1/models
```

PowerShell 내장 alias `curl`은 `Invoke-WebRequest`로 매핑되는 경우가 있으므로, **반드시 `curl.exe`를 권장**.

### 4.1 `owned_by` 기준 예시 분류(관찰된 목록 기반)
- `owned_by=openai` : `gpt-5`, `gpt-5.3-codex`, `gpt-5.3-codex-spark` 등
- `owned_by=google` : `gemini-2.5-pro`, `gemini-3-pro-preview` 등
- `owned_by=anthropic` : `claude-sonnet-4-6`, `claude-opus-4-6` 등
- `owned_by=antigravity` : `gemini-3.1-pro-high`, `claude-opus-4-6-thinking` 등(가상/확장 카탈로그 포함 가능)

> 주의: `/v1/models`는 “노출 카탈로그”일 뿐, 라우팅 후보 집합과 1:1로 완전히 일치하지 않을 수 있다.  
> 그래서 provider 혼입을 막으려면 **auth-dir 분리**가 가장 강하다.

---

## 5. Google `--login` vs `--antigravity-login` 차이
CLIProxyAPI는 서로 다른 로그인 플로우를 제공한다.

- `-login` : Google Account 로그인(Gemini CLI provider)
- `-antigravity-login` : Antigravity OAuth 로그인(Antigravity provider)

같은 Google 계정이라도:
- 토큰의 audience/scope가 다르고
- 접근 가능한 모델/정책/쿼터가 달라질 수 있다.

관찰상:
- `--login` 경로는 Gemini 모델이 보이되 최신(예: 일부 3.1 변형)이 제한될 수 있음
- `--antigravity-login` 경로는 Antigravity가 제공하는 최신/확장 모델(Claude/Gemini 혼합 포함)이 보일 수 있음

---

## 6. Management Center(대시보드) 활용
Management Center에서는 다음을 확인할 수 있다.

- 어떤 auth 파일(credential)이 사용되었는지
- 모델명, 입력/출력 토큰, 캐시 토큰, 결과 상태 등
- 분산(라운드로빈)이 실제로 일어나는지 검증

하지만 본 문서의 최종 구조에서는, 대시보드 ON/OFF 대신:

✅ provider별 auth-dir 강제 분리로 “후보 풀”을 완전히 고정  
✅ PowerShell로 provider를 전환하면서 운용  
이 목적이므로, 대시보드는 주로 **검증/관찰 도구**로만 쓰면 된다.

---

## 7. PowerShell Profile(최신)
아래 스크립트는 다음을 제공한다.

- `cc` : 순정 Claude Code 실행(프록시 관련 env 제거)
- `cc-claude / cc-gemini / cc-codex / cc-ag-claude / cc-ag-gemini` : provider 전용 CLIProxyAPI 재시작 + 모델 매핑 후 Claude Code 실행
- `cc-proxy-status` : 프록시 상태 확인
- `cc-proxy-stop` : 프록시 종료
- 프록시 health check 성공 시 Management UI 자동 오픈(세션당 1회)

> 경로는 자신의 설치 위치에 맞게 `$CLI_PROXY_BASE_DIR`만 수정하면 된다.

```powershell
# =============================
# CLIProxyAPI + Claude Code helpers (Windows / PowerShell Profile)
# =============================

# ---- CONFIG ----
$global:CLI_PROXY_BASE_DIR = "D:\OneDrive\Tool\Productivity\CLIProxyAPI_6.8.24_windows_amd64"
$global:CLI_PROXY_EXE      = Join-Path $global:CLI_PROXY_BASE_DIR "cli-proxy-api.exe"
$global:CLI_PROXY_PORT     = 8317
$global:CLI_PROXY_HOST     = "127.0.0.1"
$global:CLI_PROXY_URL      = "http://$($global:CLI_PROXY_HOST):$($global:CLI_PROXY_PORT)"
$global:CLI_PROXY_MANAGEMENT_PATH = "/management.html"
$global:CLI_PROXY_MANAGEMENT_AUTO_OPEN = $true
$script:CLI_PROXY_MANAGEMENT_OPENED = $false

# ---- Utilities ----
function Get-CLIProxyProcess {
  Get-Process -Name "cli-proxy-api" -ErrorAction SilentlyContinue
}

function Test-CLIProxyHealth {
  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
  if (-not $curl) { return $false }

  & $curl.Source -fsS --max-time 1 "$($global:CLI_PROXY_URL)/" *> $null
  return ($LASTEXITCODE -eq 0)
}

function Stop-CLIProxy {
  $p = Get-CLIProxyProcess
  if (-not $p) { return }

  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
  Start-Sleep -Milliseconds 250
}

function Start-CLIProxy([Parameter(Mandatory=$true)][ValidateSet("claude","gemini","codex","antigravity")][string]$Provider) {
  if (-not (Test-Path $global:CLI_PROXY_EXE)) {
    throw "cli-proxy-api.exe not found at: $($global:CLI_PROXY_EXE)"
  }

  $wd = Join-Path $global:CLI_PROXY_BASE_DIR ("configs\" + $Provider)
  if (-not (Test-Path $wd)) {
    throw "Provider config directory not found: $wd"
  }

  Stop-CLIProxy
  Start-Process -WindowStyle Hidden -FilePath $global:CLI_PROXY_EXE -WorkingDirectory $wd

  for ($i=0; $i -lt 15; $i++) {
    if (Test-CLIProxyHealth) {
      Open-CLIProxyManagementUI
      return
    }
    Start-Sleep -Milliseconds 200
  }

  throw "CLIProxyAPI failed to become healthy at $($global:CLI_PROXY_URL)"
}

function Get-CLIProxyStatus {
  $p = Get-CLIProxyProcess
  [PSCustomObject]@{
    Running = [bool]$p
    Pid     = if ($p) { $p.Id } else { $null }
    Healthy = if ($p) { Test-CLIProxyHealth } else { $false }
    Url     = $global:CLI_PROXY_URL
  }
}

function Open-CLIProxyManagementUI {
  if (-not $global:CLI_PROXY_MANAGEMENT_AUTO_OPEN) { return }
  if ($script:CLI_PROXY_MANAGEMENT_OPENED) { return }

  $managementUrl = "$($global:CLI_PROXY_URL)$($global:CLI_PROXY_MANAGEMENT_PATH)"
  Start-Process $managementUrl
  $script:CLI_PROXY_MANAGEMENT_OPENED = $true
}

# ---- Claude Code (no proxy) ----
function cc {
  Remove-Item Env:ANTHROPIC_BASE_URL -ErrorAction SilentlyContinue
  Remove-Item Env:ANTHROPIC_AUTH_TOKEN -ErrorAction SilentlyContinue
  Remove-Item Env:ANTHROPIC_DEFAULT_OPUS_MODEL -ErrorAction SilentlyContinue
  Remove-Item Env:ANTHROPIC_DEFAULT_SONNET_MODEL -ErrorAction SilentlyContinue
  Remove-Item Env:ANTHROPIC_DEFAULT_HAIKU_MODEL -ErrorAction SilentlyContinue

  claude
}

# ---- Claude Code via CLIProxyAPI (sets env temporarily, then restores) ----
function Invoke-CCProxy(
  [Parameter(Mandatory=$true)][string]$Opus,
  [Parameter(Mandatory=$true)][string]$Sonnet,
  [Parameter(Mandatory=$true)][string]$Haiku
) {
  $old = @{
    BASE   = $env:ANTHROPIC_BASE_URL
    TOKEN  = $env:ANTHROPIC_AUTH_TOKEN
    OPUS   = $env:ANTHROPIC_DEFAULT_OPUS_MODEL
    SONNET = $env:ANTHROPIC_DEFAULT_SONNET_MODEL
    HAIKU  = $env:ANTHROPIC_DEFAULT_HAIKU_MODEL
  }

  try {
    $env:ANTHROPIC_BASE_URL = $global:CLI_PROXY_URL
    $env:ANTHROPIC_AUTH_TOKEN = "sk-dummy"
    $env:ANTHROPIC_DEFAULT_OPUS_MODEL = $Opus
    $env:ANTHROPIC_DEFAULT_SONNET_MODEL = $Sonnet
    $env:ANTHROPIC_DEFAULT_HAIKU_MODEL = $Haiku

    claude
  }
  finally {
    if ($null -eq $old.BASE)   { Remove-Item Env:ANTHROPIC_BASE_URL -ErrorAction SilentlyContinue } else { $env:ANTHROPIC_BASE_URL = $old.BASE }
    if ($null -eq $old.TOKEN)  { Remove-Item Env:ANTHROPIC_AUTH_TOKEN -ErrorAction SilentlyContinue } else { $env:ANTHROPIC_AUTH_TOKEN = $old.TOKEN }
    if ($null -eq $old.OPUS)   { Remove-Item Env:ANTHROPIC_DEFAULT_OPUS_MODEL -ErrorAction SilentlyContinue } else { $env:ANTHROPIC_DEFAULT_OPUS_MODEL = $old.OPUS }
    if ($null -eq $old.SONNET) { Remove-Item Env:ANTHROPIC_DEFAULT_SONNET_MODEL -ErrorAction SilentlyContinue } else { $env:ANTHROPIC_DEFAULT_SONNET_MODEL = $old.SONNET }
    if ($null -eq $old.HAIKU)  { Remove-Item Env:ANTHROPIC_DEFAULT_HAIKU_MODEL -ErrorAction SilentlyContinue } else { $env:ANTHROPIC_DEFAULT_HAIKU_MODEL = $old.HAIKU }
  }
}

# ---- Provider-specific entrypoints ----
function cc-claude {
  Start-CLIProxy "claude"
  Invoke-CCProxy `
    "claude-opus-4-6" `
    "claude-sonnet-4-6" `
    "claude-haiku-4-5-20251001"
}

function cc-gemini {
  Start-CLIProxy "gemini"
  Invoke-CCProxy `
    "gemini-3-pro-preview" `
    "gemini-3-flash-preview" `
    "gemini-2.5-flash-lite"
}

function cc-codex {
  Start-CLIProxy "codex"
  Invoke-CCProxy `
    "gpt-5.3-codex(xhigh)" `
    "gpt-5.3-codex(high)" `
    "gpt-5.3-codex-spark"
}

function cc-ag-claude {
  Start-CLIProxy "antigravity"
  Invoke-CCProxy `
    "claude-opus-4-6-thinking" `
    "claude-sonnet-4-6" `
    "claude-sonnet-4-6"
}

function cc-ag-gemini {
  Start-CLIProxy "antigravity"
  Invoke-CCProxy `
    "gemini-3.1-pro-high" `
    "gemini-3.1-pro-low" `
    "gemini-3-flash"
}

# Convenience
function cc-proxy-status { Get-CLIProxyStatus }
function cc-proxy-stop   { Stop-CLIProxy }
```

---

## 8. 운영 절차(How to Use)
### 8.1 순정 Claude Code(프록시 없이)
```powershell
cc
```

### 8.2 Claude provider만 사용(Claude 토큰들끼리 라운드로빈)
```powershell
cc-claude
```

### 8.3 Gemini provider만 사용
```powershell
cc-gemini
```

### 8.4 Codex(OpenAI) provider만 사용
```powershell
cc-codex
```

### 8.5 Antigravity provider 사용 (Claude 계열 세트)
```powershell
cc-ag-claude
```

### 8.6 Antigravity provider 사용 (Gemini 계열 세트)
```powershell
cc-ag-gemini
```

### 8.7 프록시 상태 확인/종료
```powershell
cc-proxy-status
cc-proxy-stop
```

---

## 9. 라운드로빈 분산이 실제로 일어나는지 검증
Management Center(대시보드)에서 아래를 확인한다.

- Model Name = 요청한 모델 ID
- Source = 어떤 auth 파일이 선택됐는지(토큰 파일명)
- Auth Index = 어떤 credential이 사용됐는지 식별자
- Token usage = 입력/출력/캐시 토큰

**provider 폴더 분리 이후**에는 Source가 해당 provider 폴더의 토큰 파일만 순환해야 정상이다.

---

## 10. FAQ / 트러블슈팅

### Q1) `cc-claude`/`cc-codex` 첫 실행 시 `Invoke-WebRequest` 보안 경고가 떠요.
A) 헬스체크가 `Invoke-WebRequest`를 타는 구현일 때 발생할 수 있다.
현재 권장 구현은 헬스체크를 `curl.exe`로 고정하여 해당 보안 프롬프트를 원천적으로 피하는 방식이다.

```powershell
$curl = Get-Command curl.exe -ErrorAction SilentlyContinue
& $curl.Source -fsS --max-time 1 "$($global:CLI_PROXY_URL)/" *> $null
return ($LASTEXITCODE -eq 0)
```

### Q2) PowerShell에서 `curl`이 이상한 경고를 뿜고 출력이 잘려요.
A) PowerShell의 `curl`은 `Invoke-WebRequest` alias일 수 있다. `curl.exe`를 사용하라.

```powershell
curl.exe http://127.0.0.1:8317/v1/models
```

### Q3) 프록시 쓰면 `cc`도 프록시로 가요.
A) 세션 env가 남아있을 수 있다. 이 문서의 `cc` 함수는 프록시 env를 강제로 제거하므로 그대로 사용하면 해결된다.

### Q4) provider 섞여 호출되는 문제를 다시 겪고 싶지 않아요.
A) auth-dir 분리(본 문서 구조)가 가장 확실한 해결책이다.
한 서버에서 여러 provider 토큰을 동시에 로드하면, fallback/alias 때문에 섞일 수 있다.

### Q5) `(high)/(low)` 같은 괄호 표기는 모든 모델에서 되나요?
A) 아니다. 대체로 OpenAI GPT 계열에서 `reasoning.effort` 같은 파라미터가 의미가 있을 때만 유효하다.  
프록시가 그 표기를 해석/매핑해야 하므로, 실패하면 괄호 없이 실제 모델 ID로 운영하는 것을 권장한다.

### Q6) 토큰 파일을 OneDrive 아래에 둬도 되나요?
A) 가능은 하지만 권장하지 않는다. 동기화/충돌/보안 위험이 있다. 가능하면 BitLocker 등으로 보호되는 로컬 전용 경로 권장.

---

## 11. 추천 개선(선택)
- `configs/<provider>/auth/` 하위로 토큰을 분리하고 `auth-dir: "./auth"`로 설정 (깔끔/안전)
- `Start-CLIProxy`에 로그 파일 위치를 provider별로 분리(디버깅 편의)
- 필요 시 Windows Task Scheduler로 CLIProxyAPI 자동 실행(하지만 본 구조는 provider 전환 시 재시작이 필요하므로, “항상 실행”은 상황에 따라 장단)

---

## 12. 변경 기록(요약)
- 단일 auth-dir + round-robin → provider 혼입 가능성 확인
- Management Center에서 Source(토큰 파일) 확인으로 혼입 증명
- configs/provider 폴더 분리 + auth-dir "./" 전략으로 완전 분리 달성
- PowerShell 프로필: env 원복 + 프록시 재시작 + 헬스체크 자동화
- 헬스체크를 `curl.exe + $LASTEXITCODE` 기반으로 개선 (PS 5.x 보안 프롬프트 회피)
- Management UI 자동 오픈(세션당 1회) 추가

---

끝.
