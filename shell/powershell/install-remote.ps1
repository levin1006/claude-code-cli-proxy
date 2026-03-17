# install-remote.ps1 — Remote Bootstrap Installer
# Downloads code from GitHub and installs to ~/.cli-proxy/
# Usage (from anywhere): irm https://raw.githubusercontent.com/.../install-remote.ps1 | iex
#
# WARNING: This downloads from the REMOTE main branch.
#          For local installation, use: .\install-local.ps1
$ErrorActionPreference = 'Stop'

# Set TLS version to 1.2
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Write-Host "Starting cli-proxy-api REMOTE installation..."

function Get-CCProxyPython {
  if (Get-Command py -ErrorAction SilentlyContinue) { return "py" }
  if (Get-Command python3 -ErrorAction SilentlyContinue) { return "python3" }
  if (Get-Command python -ErrorAction SilentlyContinue) { return "python" }
  
  $searchPaths = @(
      Join-Path $env:LOCALAPPDATA "Programs\Python\Python*\python.exe",
      Join-Path $env:ProgramFiles "Python*\python.exe",
      Join-Path $env:SystemDrive "Python*\python.exe"
  )
  foreach ($pattern in $searchPaths) {
      $found = Get-Item $pattern -ErrorAction SilentlyContinue | Sort-Object CreationTime -Descending | Select-Object -First 1
      if ($found) { return $found.FullName }
  }
  Write-Error "Error: python is required for installation. Please install Python 3.8+."
  exit 1
}

$pythonCmd = Get-CCProxyPython

$repo = if ($env:CC_PROXY_INSTALL_REPO) { $env:CC_PROXY_INSTALL_REPO } else { "levin1006/claude-code-cli-proxy" }
$requestedTag = if ($env:CC_PROXY_INSTALL_TAG) { $env:CC_PROXY_INSTALL_TAG } else { "main" }
$sourceMode = ""
$localPath = ""
$doUninstall = $false

# Parse optional args: --tag vX.Y.Z --repo owner/name --source remote|local|auto --local-path <path> --uninstall
for ($i = 0; $i -lt $args.Count; $i++) {
    switch ($args[$i]) {
        "--tag" {
            if ($i + 1 -ge $args.Count) { Write-Error "Error: --tag requires a value"; exit 1 }
            $requestedTag = $args[$i + 1]; $i++
        }
        "--repo" {
            if ($i + 1 -ge $args.Count) { Write-Error "Error: --repo requires a value"; exit 1 }
            $repo = $args[$i + 1]; $i++
        }
        "--source" {
            if ($i + 1 -ge $args.Count) { Write-Error "Error: --source requires a value"; exit 1 }
            $sourceMode = $args[$i + 1]; $i++
        }
        "--local-path" {
            if ($i + 1 -ge $args.Count) { Write-Error "Error: --local-path requires a value"; exit 1 }
            $localPath = $args[$i + 1]; $i++
        }
        "--uninstall" { $doUninstall = $true }
        default {
            Write-Error "Error: unknown argument '$($args[$i])'"
            Write-Host "Usage: install-remote.ps1 [--tag <tag>] [--repo <owner/name>] [--source remote|local|auto] [--uninstall]"
            exit 1
        }
    }
}

if ($doUninstall) {
    $pyArgs = @("--uninstall")
} else {
    if (-not $localPath) {
        if ($sourceMode -eq "local" -or $sourceMode -eq "auto") {
            $localPath = (Get-Location).Path
        }
    }
    if ($sourceMode -and @("remote", "local", "auto") -notcontains $sourceMode) {
        Write-Error "Error: --source must be one of: remote, local, auto"; exit 1
    }
    if (-not $sourceMode) { $sourceMode = "remote" }
    Write-Host "Using repository ref: $requestedTag"
    $pyArgs = @("--repo", $repo, "--tag", $requestedTag, "--source", $sourceMode)
    if ($localPath) { $pyArgs += @("--local-path", $localPath) }
}

$timestamp = [int][double]::Parse((Get-Date -UFormat %s))
$installerUrl = "https://raw.githubusercontent.com/$repo/$requestedTag/installers/install.py?v=$timestamp"
$tempScript = "$env:TEMP\install_cc_proxy.py"

# Download Python installer
Write-Host "Downloading core installation script from repository ref..."
Invoke-WebRequest -Uri $installerUrl -OutFile $tempScript -UseBasicParsing

# Execute Python installer
& $pythonCmd $tempScript @pyArgs

# Cleanup
if (Test-Path $tempScript) { Remove-Item $tempScript -Force }

# Handle uninstall alias cleanup
$uninstallFlag = "$env:TEMP\cc_proxy_uninstall_flag"
if (Test-Path $uninstallFlag) {
    Remove-Item $uninstallFlag -Force -ErrorAction SilentlyContinue
    Remove-Item Function:cc* -ErrorAction SilentlyContinue
    Remove-Item Function:_cc* -ErrorAction SilentlyContinue
    Remove-Item Function:Install-CCProxyProfile -ErrorAction SilentlyContinue
    Remove-Item Function:Show-CCProxyProfileSetupHint -ErrorAction SilentlyContinue
    exit 0
}

# Auto-load into current session
$proxyScript = "$env:USERPROFILE\.cli-proxy\shell\powershell\cc-proxy.ps1"
if (Test-Path $proxyScript) {
    Write-Host "`nAuto-loading CLIProxyAPI into the current PowerShell session..." -ForegroundColor Cyan
    . $proxyScript
    Write-Host "Done! You can now use cc, cc-proxy-start-all, etc." -ForegroundColor Green
}
