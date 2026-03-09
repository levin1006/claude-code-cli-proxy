# CLIProxyAPI + Claude Code helpers (Windows) — thin wrapper
# Delegates all logic to core/cc_proxy.py
# Load: . .\shell\powershell\cc-proxy.ps1

# Auto-detect base dir (fixes hardcoded D:\OneDrive\... path bug)
$global:CLI_PROXY_BASE_DIR = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

$script:_CC_PROXY_PY     = if (Get-Command py      -ErrorAction SilentlyContinue) { "py"      } `
                          elseif (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } `
                          else { "python" }
$script:_CC_PROXY_SCRIPT = Join-Path $global:CLI_PROXY_BASE_DIR "core\cc_proxy.py"

function _cc_proxy_guard_repo_run {
  $installedBase = Join-Path $HOME ".cli-proxy"
  if ($global:CLI_PROXY_BASE_DIR -ne $installedBase -and $env:CC_PROXY_ALLOW_REPO_RUN -ne "1") {
    Write-Error "[cc-proxy] repository execution is disabled. Run installer sync first, then load from ~/.cli-proxy/shell/powershell/cc-proxy.ps1 (temporary override: `$env:CC_PROXY_ALLOW_REPO_RUN='1')."
    return $false
  }
  return $true
}

function _cc_proxy {
  if (-not (_cc_proxy_guard_repo_run)) { return }
  & $script:_CC_PROXY_PY $script:_CC_PROXY_SCRIPT @args
}

# Native claude (no proxy) — removes proxy env vars from parent session
function cc {
  Remove-Item Env:ANTHROPIC_BASE_URL             -ErrorAction SilentlyContinue
  Remove-Item Env:ANTHROPIC_AUTH_TOKEN           -ErrorAction SilentlyContinue
  Remove-Item Env:ANTHROPIC_DEFAULT_OPUS_MODEL   -ErrorAction SilentlyContinue
  Remove-Item Env:ANTHROPIC_DEFAULT_SONNET_MODEL -ErrorAction SilentlyContinue
  Remove-Item Env:ANTHROPIC_DEFAULT_HAIKU_MODEL  -ErrorAction SilentlyContinue
  claude @args
}

# Provider entrypoints
function cc-ag-claude  { _cc_proxy run ag-claude -- @args }
function cc-claude     { _cc_proxy run claude    -- @args }
function cc-openai     { _cc_proxy run openai    -- @args }
function cc-gemini     { _cc_proxy run gemini    -- @args }
function cc-ag-gemini  { _cc_proxy run ag-gemini -- @args }

# Management
function cc-proxy-start-all  { _cc_proxy start      all }
function cc-proxy-status     { _cc_proxy status        @args }
function cc-proxy-check      { _cc_proxy status --check @args }  # alias → status --check
function cc-proxy-quota      { _cc_proxy status --quota @args }
function cc-proxy-short      { _cc_proxy status -s      @args }  # compact one-line-per-provider
function cc-proxy-ui         { _cc_proxy ui            @args }
function cc-proxy-links      { _cc_proxy links      @args }
function cc-proxy-stop         { _cc_proxy stop         @args }
function cc-proxy-auth         { _cc_proxy auth         @args }
function cc-proxy-token-dir    { _cc_proxy token-dir    @args }
function cc-proxy-token-list   { _cc_proxy token-list   @args }
function cc-proxy-token-delete { _cc_proxy token-delete @args }
function cc-proxy-set-secret   { _cc_proxy set-secret   @args }
function cc-proxy-version      { _cc_proxy version      @args }
function Install-CCProxyProfile { _cc_proxy install-profile }

# Profile hint on first dot-source
function Show-CCProxyProfileSetupHint {
  $installedBase = Join-Path $HOME ".cli-proxy"
  if ($global:CLI_PROXY_BASE_DIR -ne $installedBase -and $env:CC_PROXY_ALLOW_REPO_RUN -ne "1") {
    return
  }

  $profileLine = ". `"$(Join-Path $global:CLI_PROXY_BASE_DIR 'shell\powershell\cc-proxy.ps1')`""
  if (Test-Path $PROFILE) {
    $c = Get-Content $PROFILE -Raw -ErrorAction SilentlyContinue
    if ($c -and $c.Contains($profileLine)) { return }
  }
  _cc_proxy install-profile --hint-only
}
Show-CCProxyProfileSetupHint
