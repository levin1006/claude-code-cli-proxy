# Require minimum PowerShell version and set TLS policy for older clients
$ErrorActionPreference = 'Stop'

# Set TLS version to 1.2
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Write-Host "Starting cli-proxy-api installation..."

# Check requirements
try {
    $pythonCmd = Get-Command "python" -ErrorAction Stop
} catch {
    Write-Error "Error: python is required for installation. Please install Python 3.8+."
    exit 1
}

# Configuration
$RAW_URL = "https://raw.githubusercontent.com/yolandalalala/claude-code-cli-proxy/main/install.py"
$TEMP_SCRIPT = "$env:TEMP\install_cc_proxy.py"

# Download Python installer
Write-Host "Downloading core installation script..."
Invoke-WebRequest -Uri $RAW_URL -OutFile $TEMP_SCRIPT -UseBasicParsing

# Execute Python installer
Write-Host "Executing core installation script..."
& python $TEMP_SCRIPT

# Cleanup
if (Test-Path $TEMP_SCRIPT) {
    Remove-Item $TEMP_SCRIPT -Force
}
