#!/bin/bash
# install-remote.sh — Entry Point (Linux/macOS, Remote/GitHub)
# Works both as a local entry point (./install-remote.sh)
# and as a one-liner (curl ... | bash)
set -e

REPO="${CC_PROXY_INSTALL_REPO:-levin1006/claude-code-cli-proxy}"
REF="${CC_PROXY_INSTALL_TAG:-main}"

# When piped via curl | bash, BASH_SOURCE[0] is empty or a temp fd.
# Detect whether we are running from a real file in the repo.
_SELF="${BASH_SOURCE[0]:-}"
_SCRIPT_DIR=""
if [ -n "$_SELF" ] && [ -f "$_SELF" ]; then
    _CANDIDATE="$(cd "$(dirname "$_SELF")" && pwd)/shell/bash/install-remote.sh"
    if [ -f "$_CANDIDATE" ]; then
        _SCRIPT_DIR="$(cd "$(dirname "$_SELF")" && pwd)"
    fi
fi

if [ -n "$_SCRIPT_DIR" ]; then
    # Running from a cloned repo — delegate to local copy
    bash "$_SCRIPT_DIR/shell/bash/install-remote.sh" "$@"
else
    # Running via curl | bash — download and execute directly
    _URL="https://raw.githubusercontent.com/${REPO}/${REF}/shell/bash/install-remote.sh"
    echo "[install-remote] Fetching installer from ${_URL} ..."
    curl -fsSL "$_URL" | bash -s -- "$@"
fi
