# install.ps1 — Windows thin wrapper for the cli-proxy installer.
#
# Usage (recommended — remote):
#   irm https://raw.githubusercontent.com/levin1006/claude-code-cli-proxy/main/installers/install.ps1 | iex
#
# Usage (local, from repo root):
#   powershell -File installers/install.ps1 [--source local] [--port-offset 10000] [...]
#
# All arguments are forwarded to installers/install.py unchanged.

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PassThroughArgs
)

$ErrorActionPreference = "Stop"

# ── 1. Locate Python ──────────────────────────────────────────────────────────
$PythonBin = $null
foreach ($candidate in @("py", "python", "python3")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $PythonBin = $candidate
        break
    }
}
if (-not $PythonBin) {
    Write-Error "Python 3.8+ is required. Install from https://www.python.org and re-run."
    exit 1
}

# ── 2. Resolve install.py (local tree or remote download) ─────────────────────
$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot     = Split-Path -Parent $ScriptDir
$LocalInstall = Join-Path $ScriptDir "install.py"
$TempInstall  = [System.IO.Path]::GetTempFileName() -replace '\.tmp$', '_install_cc_proxy.py'

# Detect whether this script is running from the local repo tree
$LocalCoreMarker = Join-Path $RepoRoot "core\cc_proxy.py"
$IsLocalTree = Test-Path $LocalCoreMarker

# If running via iex (no file on disk), $ScriptDir will point to system32 or similar
# and $LocalInstall won't exist — fall through to remote download.
if (Test-Path $LocalInstall) {
    $InstallScript = $LocalInstall
    Write-Host "Using local install.py: $InstallScript"
} else {
    $Repo = if ($env:CC_PROXY_INSTALL_REPO) { $env:CC_PROXY_INSTALL_REPO } else { "levin1006/claude-code-cli-proxy" }
    $Tag  = if ($env:CC_PROXY_INSTALL_TAG)  { $env:CC_PROXY_INSTALL_TAG  } else { "main" }
    $Url  = "https://raw.githubusercontent.com/$Repo/$Tag/installers/install.py"

    Write-Host "Downloading install.py from $Url ..."
    try {
        Invoke-WebRequest -Uri $Url -OutFile $TempInstall -UseBasicParsing
    } catch {
        Write-Error "Failed to download install.py: $_"
        exit 1
    }
    $InstallScript = $TempInstall
    Write-Host "Downloaded to $InstallScript"

    # Inject --source remote if caller did not specify it
    $hasSource = $PassThroughArgs | Where-Object { $_ -eq "--source" }
    if (-not $hasSource) {
        $PassThroughArgs = @("--source", "remote") + $PassThroughArgs
    }
}

# ── 3. Run install.py ─────────────────────────────────────────────────────────
try {
    & $PythonBin $InstallScript @PassThroughArgs
    $ExitCode = $LASTEXITCODE
} finally {
    if ($InstallScript -eq $TempInstall -and (Test-Path $TempInstall)) {
        Remove-Item $TempInstall -Force -ErrorAction SilentlyContinue
    }
}

exit $ExitCode
