# deploy.ps1 — Local Deployment Script
# Copies the current LOCAL repo code into ~/.cli-proxy/
# Usage: .\deploy.ps1
#
# NOTE: This is NOT the remote installer.
#       For fresh install from GitHub, use: .\installers\install.ps1

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

# deploy.ps1 is at repo root, so installers/install.py is a direct child
$installScript = Join-Path $PSScriptRoot "installers\install.py"

Write-Host "[deploy] Local deployment: repo -> ~/.cli-proxy/" -ForegroundColor Cyan
Write-Host "[deploy] Using Python: $pythonPath" -ForegroundColor DarkGray
& $pythonPath $installScript --source local

if ($LASTEXITCODE -ne 0) {
    Write-Host "[deploy] Failed." -ForegroundColor Red
} else {
    Write-Host "[deploy] Done. Run '. C:\Users\user\.cli-proxy\shell\powershell\cc-proxy.ps1' to reload." -ForegroundColor Green
}
