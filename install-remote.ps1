# install-remote.ps1 — Remote Installation Entry Point (Windows/GitHub)
# Always fetches the actual installer from GitHub and executes it.
# Works as: .\install-remote.ps1  OR  irm ... | iex
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repo = if ($env:CC_PROXY_INSTALL_REPO) { $env:CC_PROXY_INSTALL_REPO } else { "levin1006/claude-code-cli-proxy" }
$ref = if ($env:CC_PROXY_INSTALL_TAG) { $env:CC_PROXY_INSTALL_TAG } else { "main" }
$url = "https://raw.githubusercontent.com/$repo/$ref/shell/powershell/install-remote.ps1"

Write-Host "`n[install-remote] Fetching installer from $url ..." -ForegroundColor Cyan
$tempScript = Join-Path $env:TEMP "cc_proxy_install_remote_boot_$([guid]::NewGuid().ToString().Substring(0,8)).ps1"

try {
    Invoke-WebRequest -Uri $url -OutFile $tempScript -UseBasicParsing
    & $tempScript @args
} finally {
    if (Test-Path $tempScript) { Remove-Item $tempScript -Force -ErrorAction SilentlyContinue }
}
