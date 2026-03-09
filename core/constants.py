"""
Shared constants for CLIProxyAPI + Claude Code helper.
No imports from other core modules — leaf node in dependency DAG.
"""

import sys

IS_WINDOWS = sys.platform == "win32"

PROVIDERS = ("openai", "claude", "antigravity", "gemini")

PORTS = {
    "antigravity": 18417,
    "claude":      18418,
    "openai":       18419,
    "gemini":      18420,
}

HOST = "127.0.0.1"

PRESETS = {
    "ag-claude": ("antigravity",  "claude-opus-4-6-thinking",  "claude-sonnet-4-6",       "claude-sonnet-4-6"),
    "ag-gemini": ("antigravity",  "gemini-3.1-pro-high",       "gemini-3.1-pro-low",      "gemini-3-flash"),
    "claude":    ("claude",       "claude-opus-4-6",           "claude-sonnet-4-6",       "claude-haiku-4-5-20251001"),
    "openai":    ("openai",       "gpt-5.4(xhigh)",            "gpt-5.4(high)",           "gpt-5.3-codex-spark"),
    "gemini":    ("gemini",       "gemini-3-pro-preview",      "gemini-3-flash-preview",  "gemini-2.5-flash-lite"),
}

LOGIN_FLAGS = {
    "antigravity": "-antigravity-login",
    "claude":      "-claude-login",
    "openai":       "-codex-login",
    "gemini":      "-login",
}

TOKEN_DIR_ENV = "CC_PROXY_TOKEN_DIR"
TOKEN_DIR_META_FILE = ".token-dir"

# Schema versions
QUOTA_CACHE_TTL = 60  # seconds
USAGE_SNAPSHOT_SCHEMA_VERSION = 1
USAGE_CUMULATIVE_SCHEMA_VERSION = 1

# ANSI color codes (empty string fallback keeps output clean when piped)
_C_GREEN   = "\033[32m"
_C_RED     = "\033[31m"
_C_BLUE    = "\033[34m"
_C_MAGENTA = "\033[35m"
_C_CYAN    = "\033[36m"
_C_YELLOW  = "\033[33m"
_C_DIM     = "\033[2m"
_C_BOLD    = "\033[1m"
_C_RESET   = "\033[0m"

_PROVIDER_BRAND_COLORS = {
    # Brand-first pastel palette with TrueColor + xterm-256 fallback
    # (truecolor_rgb, fallback_256)
    "antigravity": ((152, 190, 220), "\033[38;5;110m"),  # pastel cyan-blue
    "claude":      ((233, 168, 142), "\033[38;5;216m"),  # pastel orange
    "openai":      ((137, 197, 175), "\033[38;5;114m"),  # pastel mint
    "gemini":      ((176, 157, 236), "\033[38;5;147m"),  # pastel violet
}

# TUI screen/key constants
_TUI_ALT_ON      = "\033[?1049h"
_TUI_ALT_OFF     = "\033[?1049l"
_TUI_CURSOR_HIDE = "\033[?25l"
_TUI_CURSOR_SHOW = "\033[?25h"
_TUI_CLEAR       = "\033[2J"
_TUI_CLEAR_EOS   = "\033[J"
_TUI_HOME        = "\033[H"
_TUI_KEY_LEFT    = "left"
_TUI_KEY_RIGHT   = "right"
_TUI_KEY_UP      = "up"
_TUI_KEY_DOWN    = "down"
_TUI_KEY_ESC     = "esc"
