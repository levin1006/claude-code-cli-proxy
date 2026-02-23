#!/usr/bin/env bash
# =============================
# CLIProxyAPI + Claude Code helpers (Linux / Bash Profile)
# =============================
# Requires: Bash 4.2+, curl, ss (iproute2) or lsof
# Source this file:  source /path/to/bash/cc-proxy.sh

# ---- CONFIG ----
# Detect script path: BASH_SOURCE for bash, $0 for zsh (where $0 is the sourced file path)
if [[ -n "${BASH_VERSION:-}" ]]; then
  CC_PROXY_BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
else
  CC_PROXY_BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi
CC_PROXY_EXE="${CC_PROXY_BASE_DIR}/cli-proxy-api"
CC_PROXY_HOST="127.0.0.1"
CC_PROXY_MANAGEMENT_PATH="/management.html"
CC_PROXY_MANAGEMENT_AUTO_OPEN="${CC_PROXY_MANAGEMENT_AUTO_OPEN:-auto}"

declare -A CC_PROXY_PORTS=(
  [claude]=18417
  [gemini]=18418
  [codex]=18419
  [antigravity]=18420
)

CC_PROXY_PROVIDERS=(claude gemini codex antigravity)

# Session-level state: management UI opened per provider
declare -A _CC_PROXY_MANAGEMENT_OPENED=()

# ---- PID file helpers ----
_cc_proxy_pid_file() {
  local provider="$1"
  echo "${CC_PROXY_BASE_DIR}/configs/${provider}/.proxy.pid"
}

_cc_proxy_read_pid() {
  local provider="$1"
  local pidfile
  pidfile="$(_cc_proxy_pid_file "$provider")"
  if [[ -f "$pidfile" ]]; then
    cat "$pidfile"
  fi
}

_cc_proxy_write_pid() {
  local provider="$1" pid="$2"
  echo "$pid" > "$(_cc_proxy_pid_file "$provider")"
}

_cc_proxy_remove_pid() {
  local provider="$1"
  rm -f "$(_cc_proxy_pid_file "$provider")"
}

# ---- Validation ----
_cc_proxy_validate_provider() {
  local provider="$1"
  case "$provider" in
    claude|gemini|codex|antigravity) return 0 ;;
    *)
      echo "[cc-proxy] Invalid provider: ${provider}" >&2
      echo "[cc-proxy] Valid providers: claude, gemini, codex, antigravity" >&2
      return 1
      ;;
  esac
}

# ---- Utilities ----
cc_proxy_get_port() {
  local provider="$1"
  _cc_proxy_validate_provider "$provider" || return 1
  echo "${CC_PROXY_PORTS[$provider]}"
}

cc_proxy_get_url() {
  local provider="$1"
  _cc_proxy_validate_provider "$provider" || return 1
  echo "http://${CC_PROXY_HOST}:${CC_PROXY_PORTS[$provider]}"
}

cc_proxy_test_health() {
  local provider="$1"
  _cc_proxy_validate_provider "$provider" || return 1
  local url
  url="$(cc_proxy_get_url "$provider")"
  curl -fsS --max-time 1 "${url}/" > /dev/null 2>&1
}

# Resolve PID by port using ss (primary) or lsof (fallback)
_cc_proxy_resolve_pid_by_port() {
  local provider="$1"
  _cc_proxy_validate_provider "$provider" || return 1
  local port="${CC_PROXY_PORTS[$provider]}"
  local pid=""

  # Try ss first (iproute2, available on most modern Linux)
  if command -v ss > /dev/null 2>&1; then
    pid=$(ss -tlnp "sport = :${port}" 2>/dev/null \
      | grep -oP 'pid=\K[0-9]+' | head -1)
  fi

  # Fallback to lsof
  if [[ -z "$pid" ]] && command -v lsof > /dev/null 2>&1; then
    pid=$(lsof -iTCP:"${port}" -sTCP:LISTEN -t 2>/dev/null | head -1)
  fi

  [[ -n "$pid" ]] && echo "$pid"
}

# ---- Lifecycle ----
cc_proxy_start() {
  local provider="$1"
  _cc_proxy_validate_provider "$provider" || return 1

  if [[ ! -x "$CC_PROXY_EXE" ]]; then
    echo "[cc-proxy] cli-proxy-api not found or not executable: ${CC_PROXY_EXE}" >&2
    return 1
  fi

  local wd="${CC_PROXY_BASE_DIR}/configs/${provider}"
  if [[ ! -d "$wd" ]]; then
    echo "[cc-proxy] Provider config directory not found: ${wd}" >&2
    return 1
  fi

  local base_config="${wd}/config.yaml"
  if [[ ! -f "$base_config" ]]; then
    local root_bootstrap="${CC_PROXY_BASE_DIR}/config.yaml"
    if [[ ! -f "$root_bootstrap" ]]; then
      echo "[cc-proxy] Provider config.yaml not found and root bootstrap missing: ${base_config}" >&2
      return 1
    fi
    cp "$root_bootstrap" "$base_config"
  fi

  # Check if already running on this port
  local existing_pid
  existing_pid="$(_cc_proxy_resolve_pid_by_port "$provider")"
  if [[ -n "$existing_pid" ]]; then
    _cc_proxy_write_pid "$provider" "$existing_pid"
    if cc_proxy_test_health "$provider"; then
      _cc_proxy_open_management "$provider"
      return 0
    fi
    echo "[cc-proxy] Process listening on $(cc_proxy_get_url "$provider") but not healthy." >&2
    echo "[cc-proxy] Run cc-proxy-stop and retry." >&2
    return 1
  fi

  # Rewrite port in config
  local port="${CC_PROXY_PORTS[$provider]}"
  if grep -qE '^\s*port\s*:\s*[0-9]+' "$base_config"; then
    sed -i -E "s/^(\s*port\s*:\s*)[0-9]+/\1${port}/" "$base_config"
  else
    sed -i "1i port: ${port}" "$base_config"
  fi

  # Launch in background
  (cd "$wd" && exec nohup "$CC_PROXY_EXE" -config "$base_config" \
    > "${wd}/main.log" 2>&1 &)
  local launched_pid=$!

  # Small delay so nohup child gets its own PID
  sleep 0.3

  # Re-resolve to get actual child PID
  local actual_pid
  actual_pid="$(_cc_proxy_resolve_pid_by_port "$provider")"
  if [[ -n "$actual_pid" ]]; then
    _cc_proxy_write_pid "$provider" "$actual_pid"
  else
    _cc_proxy_write_pid "$provider" "$launched_pid"
  fi

  # Health check (bounded)
  local i
  for i in $(seq 1 15); do
    if cc_proxy_test_health "$provider"; then
      _cc_proxy_open_management "$provider"
      return 0
    fi
    sleep 0.2
  done

  echo "[cc-proxy] Failed to become healthy at $(cc_proxy_get_url "$provider")" >&2
  return 1
}

cc_proxy_stop() {
  local provider="$1"

  if [[ -n "$provider" ]]; then
    _cc_proxy_validate_provider "$provider" || return 1

    # Try PID file first
    local pid
    pid="$(_cc_proxy_read_pid "$provider")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
      _cc_proxy_remove_pid "$provider"
      sleep 0.25
      return 0
    fi

    # Fallback: resolve by port
    pid="$(_cc_proxy_resolve_pid_by_port "$provider")"
    if [[ -n "$pid" ]]; then
      kill "$pid" 2>/dev/null
      _cc_proxy_remove_pid "$provider"
      sleep 0.25
    fi
    return 0
  fi

  # Stop all providers
  local pvd
  for pvd in "${CC_PROXY_PROVIDERS[@]}"; do
    local pid
    pid="$(_cc_proxy_read_pid "$pvd")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
    fi
    _cc_proxy_remove_pid "$pvd"

    # Also check by port
    pid="$(_cc_proxy_resolve_pid_by_port "$pvd")"
    if [[ -n "$pid" ]]; then
      kill "$pid" 2>/dev/null
    fi
  done

  # Additional fallback: kill any cli-proxy-api process
  pkill -f "cli-proxy-api" 2>/dev/null || true
  sleep 0.25
}

cc_proxy_status() {
  local provider="$1"

  _cc_proxy_status_one() {
    local pvd="$1"
    local pid running healthy url

    pid="$(_cc_proxy_read_pid "$pvd")"
    if [[ -z "$pid" ]]; then
      pid="$(_cc_proxy_resolve_pid_by_port "$pvd")"
      [[ -n "$pid" ]] && _cc_proxy_write_pid "$pvd" "$pid"
    fi

    running=false
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      running=true
    fi

    healthy=false
    if $running && cc_proxy_test_health "$pvd"; then
      healthy=true
    fi

    url="$(cc_proxy_get_url "$pvd")"

    if $running; then
      printf "  %-14s  Running   PID=%-7s  Healthy=%-5s  %s\n" \
        "$pvd" "$pid" "$healthy" "$url"
    else
      printf "  %-14s  Stopped   %-17s Healthy=%-5s  %s\n" \
        "$pvd" "" "false" "$url"
    fi
  }

  echo "[cc-proxy] Status:"
  if [[ -n "$provider" ]]; then
    _cc_proxy_validate_provider "$provider" || return 1
    _cc_proxy_status_one "$provider"
  else
    for pvd in "${CC_PROXY_PROVIDERS[@]}"; do
      _cc_proxy_status_one "$pvd"
    done
  fi

  unset -f _cc_proxy_status_one
}

# ---- Management UI ----
_cc_proxy_should_open_management() {
  local mode="${CC_PROXY_MANAGEMENT_AUTO_OPEN}"

  case "$mode" in
    never|false|0)
      return 1
      ;;
    always|true|1)
      return 0
      ;;
    auto)
      # Do not auto-open browser in SSH sessions (including X11 forwarding)
      if [[ -n "${SSH_CONNECTION:-}" || -n "${SSH_TTY:-}" ]]; then
        return 1
      fi

      # Only auto-open when a local GUI session is available
      if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
        return 1
      fi

      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

_cc_proxy_open_management() {
  local provider="$1"
  _cc_proxy_should_open_management || return
  [[ "${_CC_PROXY_MANAGEMENT_OPENED[$provider]}" == "true" ]] && return

  local url
  url="$(cc_proxy_get_url "$provider")${CC_PROXY_MANAGEMENT_PATH}"

  if command -v xdg-open > /dev/null 2>&1; then
    xdg-open "$url" > /dev/null 2>&1 &
  elif command -v open > /dev/null 2>&1; then
    open "$url" > /dev/null 2>&1 &
  else
    echo "[cc-proxy] Management UI: ${url}"
  fi

  _CC_PROXY_MANAGEMENT_OPENED[$provider]=true
}

# ---- Claude Code (no proxy) ----
cc() {
  unset ANTHROPIC_BASE_URL
  unset ANTHROPIC_AUTH_TOKEN
  unset ANTHROPIC_DEFAULT_OPUS_MODEL
  unset ANTHROPIC_DEFAULT_SONNET_MODEL
  unset ANTHROPIC_DEFAULT_HAIKU_MODEL

  claude "$@"
}

# ---- Claude Code via CLIProxyAPI ----
_cc_proxy_invoke() {
  local provider="$1" opus="$2" sonnet="$3" haiku="$4"
  shift 4

  # Save old values
  local old_base="${ANTHROPIC_BASE_URL-}"
  local old_token="${ANTHROPIC_AUTH_TOKEN-}"
  local old_opus="${ANTHROPIC_DEFAULT_OPUS_MODEL-}"
  local old_sonnet="${ANTHROPIC_DEFAULT_SONNET_MODEL-}"
  local old_haiku="${ANTHROPIC_DEFAULT_HAIKU_MODEL-}"
  local had_base=${ANTHROPIC_BASE_URL+set}
  local had_token=${ANTHROPIC_AUTH_TOKEN+set}
  local had_opus=${ANTHROPIC_DEFAULT_OPUS_MODEL+set}
  local had_sonnet=${ANTHROPIC_DEFAULT_SONNET_MODEL+set}
  local had_haiku=${ANTHROPIC_DEFAULT_HAIKU_MODEL+set}

  export ANTHROPIC_BASE_URL="$(cc_proxy_get_url "$provider")"
  export ANTHROPIC_AUTH_TOKEN="sk-dummy"
  export ANTHROPIC_DEFAULT_OPUS_MODEL="$opus"
  export ANTHROPIC_DEFAULT_SONNET_MODEL="$sonnet"
  export ANTHROPIC_DEFAULT_HAIKU_MODEL="$haiku"

  claude "$@"
  local rc=$?

  # Restore old values
  if [[ "$had_base" == "set" ]]; then
    export ANTHROPIC_BASE_URL="$old_base"
  else
    unset ANTHROPIC_BASE_URL
  fi
  if [[ "$had_token" == "set" ]]; then
    export ANTHROPIC_AUTH_TOKEN="$old_token"
  else
    unset ANTHROPIC_AUTH_TOKEN
  fi
  if [[ "$had_opus" == "set" ]]; then
    export ANTHROPIC_DEFAULT_OPUS_MODEL="$old_opus"
  else
    unset ANTHROPIC_DEFAULT_OPUS_MODEL
  fi
  if [[ "$had_sonnet" == "set" ]]; then
    export ANTHROPIC_DEFAULT_SONNET_MODEL="$old_sonnet"
  else
    unset ANTHROPIC_DEFAULT_SONNET_MODEL
  fi
  if [[ "$had_haiku" == "set" ]]; then
    export ANTHROPIC_DEFAULT_HAIKU_MODEL="$old_haiku"
  else
    unset ANTHROPIC_DEFAULT_HAIKU_MODEL
  fi

  return $rc
}

# ---- Provider-specific entrypoints ----
cc-claude() {
  cc_proxy_start "claude" || return 1
  _cc_proxy_invoke \
    "claude" \
    "claude-opus-4-6" \
    "claude-sonnet-4-6" \
    "claude-haiku-4-5-20251001" \
    "$@"
}

cc-gemini() {
  cc_proxy_start "gemini" || return 1
  _cc_proxy_invoke \
    "gemini" \
    "gemini-3-pro-preview" \
    "gemini-3-flash-preview" \
    "gemini-2.5-flash-lite" \
    "$@"
}

cc-codex() {
  cc_proxy_start "codex" || return 1
  # NOTE: Parenthesis effort requires CLIProxyAPI mapping support.
  _cc_proxy_invoke \
    "codex" \
    "gpt-5.3-codex(xhigh)" \
    "gpt-5.3-codex(high)" \
    "gpt-5.3-codex-spark" \
    "$@"
}

cc-ag-claude() {
  cc_proxy_start "antigravity" || return 1
  _cc_proxy_invoke \
    "antigravity" \
    "claude-opus-4-6-thinking" \
    "claude-sonnet-4-6" \
    "claude-sonnet-4-6" \
    "$@"
}

cc-ag-gemini() {
  cc_proxy_start "antigravity" || return 1
  _cc_proxy_invoke \
    "antigravity" \
    "gemini-3.1-pro-high" \
    "gemini-3.1-pro-low" \
    "gemini-3-flash" \
    "$@"
}

# ---- Convenience aliases ----
cc-proxy-status() { cc_proxy_status "$@"; }
cc-proxy-stop()   { cc_proxy_stop "$@"; }

# ---- Profile bootstrap ----
_cc_proxy_profile_line() {
  echo "source \"${CC_PROXY_BASE_DIR}/bash/cc-proxy.sh\""
}

cc_proxy_install_profile() {
  local line
  line="$(_cc_proxy_profile_line)"
  local installed=false

  for rcfile in "${HOME}/.bashrc" "${HOME}/.zshrc"; do
    if [[ -f "$rcfile" ]]; then
      if grep -qF "$line" "$rcfile" 2>/dev/null; then
        echo "[cc-proxy] ${rcfile} already contains cc-proxy loader."
      else
        printf '\n%s\n' "$line" >> "$rcfile"
        echo "[cc-proxy] Added loader to ${rcfile}."
        installed=true
      fi
    fi
  done

  # If neither .bashrc nor .zshrc exists, create .bashrc entry
  if [[ ! -f "${HOME}/.bashrc" && ! -f "${HOME}/.zshrc" ]]; then
    printf '\n%s\n' "$line" >> "${HOME}/.bashrc"
    echo "[cc-proxy] Created ${HOME}/.bashrc with cc-proxy loader."
    installed=true
  fi

  if $installed; then
    echo "[cc-proxy] New terminals will auto-load helpers."
    echo "[cc-proxy] Functions are already available in this session."
  fi
}

_cc_proxy_show_profile_hint() {
  local line
  line="$(_cc_proxy_profile_line)"

  # Check if already in any profile
  for rcfile in "${HOME}/.bashrc" "${HOME}/.zshrc"; do
    if [[ -f "$rcfile" ]] && grep -qF "$line" "$rcfile" 2>/dev/null; then
      return
    fi
  done

  echo "[cc-proxy] First-time setup detected."
  printf "[cc-proxy] Add loader to your shell profile now? (Y/N) "
  read -r answer
  case "$answer" in
    [Yy]|[Yy][Ee][Ss]) cc_proxy_install_profile ;;
    *) echo "[cc-proxy] Skipped. Run cc_proxy_install_profile later." ;;
  esac
}

# ---- Auto-run on source ----
_cc_proxy_show_profile_hint
