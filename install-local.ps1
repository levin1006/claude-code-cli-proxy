# install-local.ps1 — Entry Point (Windows, Local)
# Delegates to shell/powershell/install-local.ps1
$script = Join-Path $PSScriptRoot "shell\powershell\install-local.ps1"
& $script @args
