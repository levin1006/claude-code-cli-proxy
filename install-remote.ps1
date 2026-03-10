# install-remote.ps1 — Entry Point (Windows, Remote/GitHub)
# Delegates to shell/powershell/install-remote.ps1
$script = Join-Path $PSScriptRoot "shell\powershell\install-remote.ps1"
& $script @args
