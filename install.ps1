# Require minimum PowerShell version and set TLS policy for older clients
$ErrorActionPreference = 'Stop'

# Set TLS version to 1.2
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Write-Host "Starting cli-proxy-api installation..."

# Check requirements
try {
    $null = Get-Command "python" -ErrorAction Stop
} catch {
    Write-Error "Error: python is required for installation. Please install Python 3.8+."
    exit 1
}

$repo = if ($env:CC_PROXY_INSTALL_REPO) { $env:CC_PROXY_INSTALL_REPO } else { "levin1006/claude-code-cli-proxy" }
$requestedTag = if ($env:CC_PROXY_INSTALL_TAG) { $env:CC_PROXY_INSTALL_TAG } else { "main" }

# Parse optional args: --tag vX.Y.Z --repo owner/name
for ($i = 0; $i -lt $args.Count; $i++) {
    switch ($args[$i]) {
        "--tag" {
            if ($i + 1 -ge $args.Count) {
                Write-Error "Error: --tag requires a value"
                exit 1
            }
            $requestedTag = $args[$i + 1]
            $i++
        }
        "--repo" {
            if ($i + 1 -ge $args.Count) {
                Write-Error "Error: --repo requires a value"
                exit 1
            }
            $repo = $args[$i + 1]
            $i++
        }
        default {
            Write-Error "Error: unknown argument '$($args[$i])'"
            Write-Host "Usage: install.ps1 [--tag <tag-or-branch>] [--repo <owner/name>]"
            exit 1
        }
    }
}

Write-Host "Using repository ref: $requestedTag"

$installerUrl = "https://raw.githubusercontent.com/$repo/$requestedTag/install.py"
$tempScript = "$env:TEMP\install_cc_proxy.py"

# Download Python installer
Write-Host "Downloading core installation script from repository ref..."
Invoke-WebRequest -Uri $installerUrl -OutFile $tempScript -UseBasicParsing

# Execute Python installer
Write-Host "Executing core installation script..."
& python $tempScript --repo $repo --tag $requestedTag

# Cleanup
if (Test-Path $tempScript) {
    Remove-Item $tempScript -Force
}
