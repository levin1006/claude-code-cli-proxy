#!/bin/bash
set -e

echo "Starting cli-proxy-api installation..."

# Check requirements
if ! command -v curl &> /dev/null; then
    echo "Error: curl is required for installation."
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required for installation."
    exit 1
fi

# Configuration
RAW_URL="https://raw.githubusercontent.com/yolandalalala/claude-code-cli-proxy/main/install.py"
TEMP_SCRIPT="/tmp/install_cc_proxy.py"

# Download and run Python installer
echo "Downloading core installation script..."
curl -fsSL "$RAW_URL" -o "$TEMP_SCRIPT"

echo "Executing core installation script..."
python3 "$TEMP_SCRIPT"

# Cleanup
rm -f "$TEMP_SCRIPT"
