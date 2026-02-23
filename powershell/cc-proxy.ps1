# =============================
# CLIProxyAPI + Claude Code helpers (Windows / PowerShell Profile)
# =============================

# ---- CONFIG ----
$global:CLI_PROXY_BASE_DIR = "D:\OneDrive\Tool\Productivity\claude-code-cli-proxy"
$global:CLI_PROXY_EXE      = Join-Path $global:CLI_PROXY_BASE_DIR "cli-proxy-api.exe"
$global:CLI_PROXY_HOST     = "127.0.0.1"
$global:CLI_PROXY_PORTS    = @{
  claude      = 18417
  gemini      = 18418
  codex       = 18419
  antigravity = 18420
}
$global:CLI_PROXY_MANAGEMENT_PATH = "/management.html"
$global:CLI_PROXY_MANAGEMENT_AUTO_OPEN = $true
$script:CLI_PROXY_MANAGEMENT_OPENED = @{}
$script:CLI_PROXY_PROVIDER_PIDS = @{}

# Providers correspond to: configs\<provider>\config.yaml (and auth tokens inside that folder)
$global:CLI_PROXY_PROVIDERS = @("claude", "gemini", "codex", "antigravity")

# ---- Utilities ----
function Get-CLIProxyProcess {
  Get-Process -Name "cli-proxy-api" -ErrorAction SilentlyContinue
}

function Get-CLIProxyPort([Parameter(Mandatory=$true)][ValidateSet("claude","gemini","codex","antigravity")][string]$Provider) {
  return [int]$global:CLI_PROXY_PORTS[$Provider]
}

function Get-CLIProxyUrl([Parameter(Mandatory=$true)][ValidateSet("claude","gemini","codex","antigravity")][string]$Provider) {
  $port = Get-CLIProxyPort $Provider
  return "http://$($global:CLI_PROXY_HOST):$port"
}

function Test-CLIProxyHealth([Parameter(Mandatory=$true)][ValidateSet("claude","gemini","codex","antigravity")][string]$Provider) {
  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
  if (-not $curl) { return $false }

  $url = "$(Get-CLIProxyUrl $Provider)/"
  & $curl.Source -fsS --max-time 1 $url *> $null
  return ($LASTEXITCODE -eq 0)
}

function Resolve-CLIProxyPidByPort([Parameter(Mandatory=$true)][ValidateSet("claude","gemini","codex","antigravity")][string]$Provider) {
  $port = Get-CLIProxyPort $Provider
  $conn = Get-NetTCPConnection -LocalAddress $global:CLI_PROXY_HOST -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($conn) { return $conn.OwningProcess }
  return $null
}

function Stop-CLIProxy([ValidateSet("claude","gemini","codex","antigravity")][string]$Provider) {
  if ($Provider) {
    $proxyPid = $script:CLI_PROXY_PROVIDER_PIDS[$Provider]
    if ($proxyPid) {
      Stop-Process -Id $proxyPid -Force -ErrorAction SilentlyContinue
      $script:CLI_PROXY_PROVIDER_PIDS.Remove($Provider)
      Start-Sleep -Milliseconds 250
      return
    }

    # Fallback: stop process bound to provider port
    $fallbackPid = Resolve-CLIProxyPidByPort $Provider
    if ($fallbackPid) {
      Stop-Process -Id $fallbackPid -Force -ErrorAction SilentlyContinue
      Start-Sleep -Milliseconds 250
    }
    return
  }

  # Stop all tracked provider proxy processes
  foreach ($trackedPid in @($script:CLI_PROXY_PROVIDER_PIDS.Values)) {
    Stop-Process -Id $trackedPid -Force -ErrorAction SilentlyContinue
  }
  $script:CLI_PROXY_PROVIDER_PIDS.Clear()

  # Additional fallback: stop any cli-proxy-api process
  $p = Get-CLIProxyProcess
  if ($p) {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
  }

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

  $baseConfigPath = Join-Path $wd "config.yaml"
  if (-not (Test-Path $baseConfigPath)) {
    throw "Provider config.yaml not found: $baseConfigPath"
  }

  $port = Get-CLIProxyPort $Provider
  $runtimeConfigPath = Join-Path $wd ".config.runtime.yaml"
  $configContent = Get-Content -Path $baseConfigPath -Raw

  if ($configContent -match "(?m)^\s*port\s*:\s*\d+\s*$") {
    $configContent = $configContent -replace "(?m)^\s*port\s*:\s*\d+\s*$", "port: $port"
  } else {
    $configContent = "port: $port`r`n" + $configContent
  }

  Set-Content -Path $runtimeConfigPath -Value $configContent -Encoding UTF8

  Stop-CLIProxy -Provider $Provider

  $proc = Start-Process -WindowStyle Hidden -FilePath $global:CLI_PROXY_EXE -WorkingDirectory $wd -ArgumentList @("-config", $runtimeConfigPath) -PassThru
  $script:CLI_PROXY_PROVIDER_PIDS[$Provider] = $proc.Id

  # Health check (fast, bounded)
  for ($i=0; $i -lt 15; $i++) {
    if (Test-CLIProxyHealth -Provider $Provider) {
      Open-CLIProxyManagementUI -Provider $Provider
      return
    }
    Start-Sleep -Milliseconds 200
  }

  throw "CLIProxyAPI failed to become healthy at $(Get-CLIProxyUrl $Provider)"
}

function Get-CLIProxyStatus([ValidateSet("claude","gemini","codex","antigravity")][string]$Provider) {
  if ($Provider) {
    $proxyPid = $script:CLI_PROXY_PROVIDER_PIDS[$Provider]
    if (-not $proxyPid) {
      $proxyPid = Resolve-CLIProxyPidByPort $Provider
      if ($proxyPid) { $script:CLI_PROXY_PROVIDER_PIDS[$Provider] = $proxyPid }
    }

    $running = $false
    if ($proxyPid) {
      $running = [bool](Get-Process -Id $proxyPid -ErrorAction SilentlyContinue)
    }

    [PSCustomObject]@{
      Provider = $Provider
      Running  = $running
      Pid      = if ($running) { $proxyPid } else { $null }
      Healthy  = if ($running) { Test-CLIProxyHealth -Provider $Provider } else { $false }
      Url      = Get-CLIProxyUrl $Provider
    }
    return
  }

  foreach ($pvd in $global:CLI_PROXY_PROVIDERS) {
    $proxyPid = $script:CLI_PROXY_PROVIDER_PIDS[$pvd]
    if (-not $proxyPid) {
      $proxyPid = Resolve-CLIProxyPidByPort $pvd
      if ($proxyPid) { $script:CLI_PROXY_PROVIDER_PIDS[$pvd] = $proxyPid }
    }

    $running = $false
    if ($proxyPid) {
      $running = [bool](Get-Process -Id $proxyPid -ErrorAction SilentlyContinue)
    }

    [PSCustomObject]@{
      Provider = $pvd
      Running  = $running
      Pid      = if ($running) { $proxyPid } else { $null }
      Healthy  = if ($running) { Test-CLIProxyHealth -Provider $pvd } else { $false }
      Url      = Get-CLIProxyUrl $pvd
    }
  }
}

function Open-CLIProxyManagementUI([Parameter(Mandatory=$true)][ValidateSet("claude","gemini","codex","antigravity")][string]$Provider) {
  if (-not $global:CLI_PROXY_MANAGEMENT_AUTO_OPEN) { return }
  if ($script:CLI_PROXY_MANAGEMENT_OPENED[$Provider]) { return }

  $managementUrl = "$(Get-CLIProxyUrl $Provider)$($global:CLI_PROXY_MANAGEMENT_PATH)"
  Start-Process $managementUrl
  $script:CLI_PROXY_MANAGEMENT_OPENED[$Provider] = $true
}

# ---- Claude Code (no proxy) ----
function cc {
  # Ensure "native Claude Code" (no proxy env)
  Remove-Item Env:ANTHROPIC_BASE_URL -ErrorAction SilentlyContinue
  Remove-Item Env:ANTHROPIC_AUTH_TOKEN -ErrorAction SilentlyContinue
  Remove-Item Env:ANTHROPIC_DEFAULT_OPUS_MODEL -ErrorAction SilentlyContinue
  Remove-Item Env:ANTHROPIC_DEFAULT_SONNET_MODEL -ErrorAction SilentlyContinue
  Remove-Item Env:ANTHROPIC_DEFAULT_HAIKU_MODEL -ErrorAction SilentlyContinue

  claude
  # If needed:
  # claude --dangerously-skip-permissions
}

# ---- Claude Code via CLIProxyAPI (sets env temporarily, then restores) ----
function Invoke-CCProxy(
  [Parameter(Mandatory=$true)][ValidateSet("claude","gemini","codex","antigravity")][string]$Provider,
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
    $env:ANTHROPIC_BASE_URL = Get-CLIProxyUrl $Provider
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
    "claude" `
    "claude-opus-4-6" `
    "claude-sonnet-4-6" `
    "claude-haiku-4-5-20251001"
}

function cc-gemini {
  Start-CLIProxy "gemini"
  Invoke-CCProxy `
    "gemini" `
    "gemini-3-pro-preview" `
    "gemini-3-flash-preview" `
    "gemini-2.5-flash-lite"
}

function cc-codex {
  Start-CLIProxy "codex"
  # NOTE: Parenthesis effort requires CLIProxyAPI mapping support.
  Invoke-CCProxy `
    "codex" `
    "gpt-5.3-codex(xhigh)" `
    "gpt-5.3-codex(high)" `
    "gpt-5.3-codex-spark"
}

function cc-ag {
  Start-CLIProxy "antigravity"
  Invoke-CCProxy `
    "antigravity" `
    "claude-opus-4-6-thinking" `
    "gemini-3.1-pro-high" `
    "gemini-3.1-pro-low"
}

# Convenience
function cc-proxy-status { Get-CLIProxyStatus }
function cc-proxy-stop   { Stop-CLIProxy }