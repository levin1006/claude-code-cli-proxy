# CLIProxyAPI + Claude Code Helper Installer Wrapper (Windows)

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
$installScript = Join-Path $PSScriptRoot "installers\install.py"

Write-Host "[Installer] Using Python executable at: $pythonPath" -ForegroundColor Cyan
& $pythonPath $installScript --source local

if ($LASTEXITCODE -ne 0) {
    Write-Host "[Installer] Failed to complete installation." -ForegroundColor Red
} else {
    Write-Host "[Installer] Done." -ForegroundColor Green
}
