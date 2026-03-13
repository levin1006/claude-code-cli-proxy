# shell/powershell/install-local.ps1 — Local Installation Logic
# Copies the current LOCAL repo code into ~/.cli-proxy/
# (Invoked by root entry point: install-local.ps1)
#
# For fresh install from GitHub, use: install-remote.ps1

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
  return "python"
}

$pythonPath = Get-CCProxyPython

# Script is in shell/powershell/, so repo root is two levels up
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$installScript = Join-Path $repoRoot "installers\install.py"

if ($args -contains "--uninstall") {
    Write-Host "[install-local] Uninstalling cli-proxy..." -ForegroundColor Yellow
    & $pythonPath $installScript --uninstall
} else {
    Write-Host "[install-local] Local installation: repo -> ~/.cli-proxy/" -ForegroundColor Cyan
    Write-Host "[install-local] Using Python: $pythonPath" -ForegroundColor DarkGray
    & $pythonPath $installScript --source local
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "[install-local] Failed." -ForegroundColor Red
} else {
    Write-Host "[install-local] Done." -ForegroundColor Green
    # Reload helpers into the current session so new functions (e.g. cc-proxy-update)
    # are available immediately without restarting the terminal.
    $installedPs1 = Join-Path $HOME ".cli-proxy\shell\powershell\cc-proxy.ps1"
    if (Test-Path $installedPs1) {
        . $installedPs1
        Write-Host "[install-local] Session reloaded — new commands available." -ForegroundColor Cyan
    }
}
