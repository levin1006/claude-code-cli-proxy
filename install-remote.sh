#!/bin/bash
# install-remote.sh — Remote Installation Entry Point (Linux/macOS)
# Always fetches the actual installer from GitHub and executes it.
# Works as: ./install-remote.sh  OR  curl ... | bash
set -e

REPO="${CC_PROXY_INSTALL_REPO:-levin1006/claude-code-cli-proxy}"
REF="${CC_PROXY_INSTALL_TAG:-main}"
_URL="https://raw.githubusercontent.com/${REPO}/${REF}/shell/bash/install-remote.sh"

echo "[install-remote] Fetching installer from ${_URL} ..."
curl -fsSL "$_URL" | bash -s -- "$@"
