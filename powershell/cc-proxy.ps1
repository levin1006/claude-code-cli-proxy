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
$global:CLI_PROXY_MANAGEMENT_AUTO_OPEN = if ($env:CLI_PROXY_MANAGEMENT_AUTO_OPEN) {
  $env:CLI_PROXY_MANAGEMENT_AUTO_OPEN
} else {
  "auto"
}
$script:CLI_PROXY_MANAGEMENT_OPENED = @{}
$script:CLI_PROXY_PROVIDER_PIDS = @{}

# Providers correspond to: configs\<provider>\config.yaml (and auth tokens inside that folder)
$global:CLI_PROXY_PROVIDERS = @("claude", "gemini", "codex", "antigravity")

# ---- Profile bootstrap helpers ----
$script:CC_PROXY_SCRIPT_PATH = if ($PSCommandPath) {
  $PSCommandPath
} else {
  Join-Path $global:CLI_PROXY_BASE_DIR "powershell\cc-proxy.ps1"
}
$script:CC_PROXY_PROFILE_PROMPTED = $false

function Get-CCProxyProfileLine {
  return ". `"$($script:CC_PROXY_SCRIPT_PATH)`""
}

function Test-CCProxyProfile {
  if (-not (Test-Path $PROFILE)) { return $false }

  $profileContent = Get-Content -Path $PROFILE -Raw -ErrorAction SilentlyContinue
  if ($null -eq $profileContent) { return $false }

  return $profileContent.Contains((Get-CCProxyProfileLine))
}

function Install-CCProxyProfile {
  $profileDir = Split-Path -Parent $PROFILE
  if (-not (Test-Path $profileDir)) {
    New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
  }

  if (-not (Test-Path $PROFILE)) {
    New-Item -ItemType File -Path $PROFILE -Force | Out-Null
  }

  if (Test-CCProxyProfile) {
    Write-Host "[cc-proxy] Profile already contains cc-proxy loader."
    Write-Host "[cc-proxy] Profile path: $PROFILE"
    return
  }

  $profileLine = Get-CCProxyProfileLine
  Add-Content -Path $PROFILE -Value "`r`n$profileLine`r`n"

  Write-Host "[cc-proxy] Added loader to PowerShell profile."
  Write-Host "[cc-proxy] Profile path: $PROFILE"

  try {
    . $PROFILE
    Write-Host "[cc-proxy] Loaded updated profile into current session."
  }
  catch {
    Write-Host "[cc-proxy] Failed to load profile in current session: $($_.Exception.Message)"
    Write-Host "[cc-proxy] You can still open a new PowerShell session to apply it."
  }
}

function Show-CCProxyProfileSetupHint {
  if (Test-CCProxyProfile) { return }
  if ($script:CC_PROXY_PROFILE_PROMPTED) { return }

  $script:CC_PROXY_PROFILE_PROMPTED = $true

  Write-Host "[cc-proxy] First-time setup detected."
  $answer = Read-Host "[cc-proxy] Add loader to your PowerShell profile now? (Y/N)"

  if ($answer -match '^(?i:y|yes)$') {
    Install-CCProxyProfile
    return
  }

  Write-Host "[cc-proxy] Skipped. You can run Install-CCProxyProfile later."
}

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

function Find-CLIProxyFreeAuthPort {
  param([int]$StartPort = 3000, [int]$MaxPort = 3010)
  for ($p = $StartPort; $p -le $MaxPort; $p++) {
    $conn = Get-NetTCPConnection -LocalAddress $global:CLI_PROXY_HOST -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $conn) {
      return $p
    }
  }
  return $StartPort
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
    $rootBootstrapConfigPath = Join-Path $global:CLI_PROXY_BASE_DIR "config.yaml"
    if (-not (Test-Path $rootBootstrapConfigPath)) {
      throw "Provider config.yaml not found and root bootstrap config.yaml is missing: $baseConfigPath"
    }

    Copy-Item -Path $rootBootstrapConfigPath -Destination $baseConfigPath -Force
  }

  $existingPid = Resolve-CLIProxyPidByPort $Provider
  if ($existingPid) {
    $script:CLI_PROXY_PROVIDER_PIDS[$Provider] = $existingPid

    if (Test-CLIProxyHealth -Provider $Provider) {
      Open-CLIProxyManagementUI -Provider $Provider
      return
    }

    throw "Existing CLIProxyAPI process is listening on $(Get-CLIProxyUrl $Provider) but is not healthy. Run cc-proxy-stop (or Stop-CLIProxy -Provider `"$Provider`") and retry."
  }

  $port = Get-CLIProxyPort $Provider
  $configContent = Get-Content -Path $baseConfigPath -Raw

  if ($configContent -match "(?m)^\s*port\s*:\s*\d+\s*$") {
    $configContent = $configContent -replace "(?m)^\s*port\s*:\s*\d+\s*$", "port: $port"
  } else {
    $configContent = "port: $port`r`n" + $configContent
  }

  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($baseConfigPath, $configContent, $utf8NoBom)

  $proc = Start-Process -WindowStyle Hidden -FilePath $global:CLI_PROXY_EXE -WorkingDirectory $wd -ArgumentList @("-config", $baseConfigPath) -PassThru
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

function Invoke-CLIProxyAuth([Parameter(Mandatory=$true)][ValidateSet("claude","gemini","codex","antigravity")][string]$Provider) {
  if (-not (Test-Path $global:CLI_PROXY_EXE)) {
    throw "cli-proxy-api.exe not found at: $($global:CLI_PROXY_EXE)"
  }

  $wd = Join-Path $global:CLI_PROXY_BASE_DIR ("configs\" + $Provider)
  if (-not (Test-Path $wd)) {
    throw "Provider config directory not found: $wd"
  }

  # Ensure provider config exists (copy from root bootstrap if missing)
  $baseConfigPath = Join-Path $wd "config.yaml"
  if (-not (Test-Path $baseConfigPath)) {
    $rootBootstrapConfigPath = Join-Path $global:CLI_PROXY_BASE_DIR "config.yaml"
    if (Test-Path $rootBootstrapConfigPath) {
      Copy-Item -Path $rootBootstrapConfigPath -Destination $baseConfigPath -Force
    }
  }

  # Map provider name to binary login flag
  $loginFlag = switch ($Provider) {
    "claude"      { "-claude-login" }
    "gemini"      { "-login" }
    "codex"       { "-codex-login" }
    "antigravity" { "-antigravity-login" }
  }

  # Suppress automatic browser launch in headless/SSH environments
  $extraFlags = @()
  if (-not (Test-CLIProxyShouldOpenManagementUI)) {
    $extraFlags += "-no-browser"
  }

  # Find a free port for the OAuth callback to avoid "address already in use" errors
  $freePort = Find-CLIProxyFreeAuthPort -StartPort 3000 -MaxPort 3020
  $extraFlags += "-oauth-callback-port"
  $extraFlags += "$freePort"

  Write-Host "[cc-proxy] Starting auth for provider '$Provider' (using callback port $freePort)..."
  Write-Host "[cc-proxy] Token file will be saved to: $wd"

  # Run binary from provider directory so auth-dir "./" resolves there
  Push-Location $wd
  try {
    & $global:CLI_PROXY_EXE -config $baseConfigPath $loginFlag @extraFlags
  }
  finally {
    Pop-Location
  }
}

function Test-CLIProxyShouldOpenManagementUI {
  $mode = "$($global:CLI_PROXY_MANAGEMENT_AUTO_OPEN)".ToLowerInvariant()

  switch ($mode) {
    "never" { return $false }
    "false" { return $false }
    "0"     { return $false }
    "always" { return $true }
    "true"   { return $true }
    "1"      { return $true }
    "auto" {
      # Do not auto-open browser in SSH sessions
      if ($env:SSH_CONNECTION -or $env:SSH_TTY) { return $false }

      # Auto-open only when running in an interactive desktop session
      if (-not [Environment]::UserInteractive) { return $false }

      return $true
    }
    default { return $false }
  }
}

function Open-CLIProxyManagementUI([Parameter(Mandatory=$true)][ValidateSet("claude","gemini","codex","antigravity")][string]$Provider) {
  if (-not (Test-CLIProxyShouldOpenManagementUI)) { return }
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
  Ensure-CLIProxyTokens "claude"; Start-CLIProxy "claude"
  Invoke-CCProxy `
    "claude" `
    "claude-opus-4-6" `
    "claude-sonnet-4-6" `
    "claude-haiku-4-5-20251001"
}

function cc-gemini {
  Ensure-CLIProxyTokens "gemini"; Start-CLIProxy "gemini"
  Invoke-CCProxy `
    "gemini" `
    "gemini-3-pro-preview" `
    "gemini-3-flash-preview" `
    "gemini-2.5-flash-lite"
}

function cc-codex {
  Ensure-CLIProxyTokens "codex"; Start-CLIProxy "codex"
  # NOTE: Parenthesis effort requires CLIProxyAPI mapping support.
  Invoke-CCProxy `
    "codex" `
    "gpt-5.3-codex(xhigh)" `
    "gpt-5.3-codex(high)" `
    "gpt-5.3-codex-spark"
}

function cc-ag-claude {
  Ensure-CLIProxyTokens "antigravity"; Start-CLIProxy "antigravity"
  Invoke-CCProxy `
    "antigravity" `
    "claude-opus-4-6-thinking" `
    "claude-sonnet-4-6" `
    "claude-sonnet-4-6"
}

function cc-ag-gemini {
  Ensure-CLIProxyTokens "antigravity"; Start-CLIProxy "antigravity"
  Invoke-CCProxy `
    "antigravity" `
    "gemini-3.1-pro-high" `
    "gemini-3.1-pro-low" `
    "gemini-3-flash"
}

# Convenience
function cc-proxy-status { Get-CLIProxyStatus }
function cc-proxy-stop   { Stop-CLIProxy }
function cc-proxy-auth   { Invoke-CLIProxyAuth @args }

function Set-CLIProxySecret {
  param([Parameter(Mandatory=$true)][string]$Secret)

  $configFiles = @(
    (Join-Path $global:CLI_PROXY_BASE_DIR "config.yaml"),
    (Join-Path $global:CLI_PROXY_BASE_DIR "configs\claude\config.yaml"),
    (Join-Path $global:CLI_PROXY_BASE_DIR "configs\gemini\config.yaml"),
    (Join-Path $global:CLI_PROXY_BASE_DIR "configs\codex\config.yaml"),
    (Join-Path $global:CLI_PROXY_BASE_DIR "configs\antigravity\config.yaml")
  )

  $updated = 0
  foreach ($f in $configFiles) {
    if (Test-Path $f) {
      $content = Get-Content $f -Raw
      $content = $content -replace '(?m)^(\s*secret-key:\s*)".*"', "`$1`"$Secret`""
      $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
      [System.IO.File]::WriteAllText($f, $content, $utf8NoBom)
      Write-Host "[cc-proxy] Updated: $f"
      $updated++
    }
  }

  Write-Host "[cc-proxy] Secret key set to '$Secret' in $updated file(s)."
  Write-Host "[cc-proxy] Restart the proxy (cc-proxy-stop; cc-<provider>) to apply."
}
function cc-proxy-set-secret { Set-CLIProxySecret @args }

Show-CCProxyProfileSetupHint
function Ensure-CLIProxyTokens([Parameter(Mandatory=$true)][ValidateSet("claude","gemini","codex","antigravity")][string]$Provider) {
  $tokenDir = Join-Path $global:CLI_PROXY_BASE_DIR "configs\$Provider"
  
  if (-not (Test-Path $tokenDir)) {
    Write-Host "[cc-proxy] Config directory for $Provider does not exist. Running auth..."
    Invoke-CLIProxyAuth -Provider $Provider
    return
  }

  $tokenFiles = Get-ChildItem -Path $tokenDir -Filter "$Provider-*.json" -File
  if ($tokenFiles.Count -eq 0) {
    Write-Host "[cc-proxy] No token files found for $Provider. Running auth..."
    Invoke-CLIProxyAuth -Provider $Provider
    return
  }

  $currentTime = [DateTimeOffset]::UtcNow
  $validTokens = 0
  $expiredTokens = 0

  Write-Host "[cc-proxy] Checking tokens for provider: $Provider"
  foreach ($file in $tokenFiles) {
    try {
      $json = Get-Content $file.FullName -Raw | ConvertFrom-Json
      $label = if ($json.email) { $json.email } else { $file.Name }
      if ($null -ne $json.expired) {
        $expireTime = [DateTimeOffset]::Parse($json.expired)
        if ($expireTime -gt $currentTime) {
          $validTokens++
          $remainingHours = [int](($expireTime - $currentTime).TotalHours)
          Write-Host "[cc-proxy]   OK      $label  (expires in ${remainingHours}h)"
        } else {
          $expiredTokens++
          Write-Host "[cc-proxy]   EXPIRED $label  (expired: $($json.expired))"
        }
      } else {
        Write-Host "[cc-proxy]   SKIP    $label  (no expiry field)"
      }
    } catch {
      Write-Host "[cc-proxy]   SKIP    $($file.Name)  (parse error)"
    }
  }
  Write-Host "[cc-proxy] Result: $validTokens valid, $expiredTokens expired"

  if ($validTokens -gt 0) {
    return
  }

  Write-Host "[cc-proxy] All tokens for $Provider are expired. Running auth..."
  Invoke-CLIProxyAuth -Provider $Provider
}
