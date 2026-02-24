# CLIProxyAPI + Claude Code helpers (Windows) — thin wrapper
# Delegates all logic to python/cc_proxy.py
# Load: . .\powershell\cc-proxy.ps1

# Auto-detect base dir (fixes hardcoded D:\OneDrive\... path bug)
$global:CLI_PROXY_BASE_DIR = Split-Path -Parent $PSScriptRoot

$script:_CC_PROXY_PY     = if (Get-Command py      -ErrorAction SilentlyContinue) { "py"      } `
                          elseif (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } `
                          else { "python" }
$script:_CC_PROXY_SCRIPT = Join-Path $global:CLI_PROXY_BASE_DIR "python\cc_proxy.py"

function _cc_proxy { & $script:_CC_PROXY_PY $script:_CC_PROXY_SCRIPT @args }

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
function cc-claude     { _cc_proxy run claude    -- @args }
function cc-gemini     { _cc_proxy run gemini    -- @args }
function cc-codex      { _cc_proxy run codex     -- @args }
function cc-ag-claude  { _cc_proxy run ag-claude -- @args }
function cc-ag-gemini  { _cc_proxy run ag-gemini -- @args }

# Management
function cc-proxy-status     { _cc_proxy status     @args }
function cc-proxy-stop       { _cc_proxy stop       @args }
function cc-proxy-auth       { _cc_proxy auth       @args }
function cc-proxy-set-secret { _cc_proxy set-secret @args }
function Install-CCProxyProfile { _cc_proxy install-profile }

# Profile hint on first dot-source
function Show-CCProxyProfileSetupHint {
  $profileLine = ". `"$(Join-Path $global:CLI_PROXY_BASE_DIR 'powershell\cc-proxy.ps1')`""
  if (Test-Path $PROFILE) {
    $c = Get-Content $PROFILE -Raw -ErrorAction SilentlyContinue
    if ($c -and $c.Contains($profileLine)) { return }
  }
  _cc_proxy install-profile --hint-only
}
Show-CCProxyProfileSetupHint
