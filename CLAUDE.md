# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository overview
- This repo is an **operations/config workspace** for a prebuilt CLIProxyAPI binary, not the source code of the proxy itself.
- **Supported platforms**: Windows (PowerShell) and Linux Ubuntu (Bash).
- **Python 3.8+** required (stdlib only, no pip install).
- Binary version in this repo: `CLIProxyAPI_6.8.24_windows_amd64`.
- Main moving parts:
  - `cli-proxy-api.exe` (Windows binary, prebuilt)
  - `cli-proxy-api` (Linux binary, user downloads separately; gitignored)
  - `configs/<provider>/config.yaml` (+ provider credential JSON files)
  - `python/cc_proxy.py` (cross-platform core logic — single source of truth)
  - `powershell/cc-proxy.ps1` (Windows thin wrapper, ~50 lines, delegates to Python core)
  - `bash/cc-proxy.sh` (Linux thin wrapper, ~50 lines, delegates to Python core)
  - `docs/claude-code-cliproxy-windows-guide.md` (Windows operational background)
  - `docs/claude-code-cliproxy-linux-guide.md` (Linux operational background)
  - `config.yaml` at repo root (bootstrap config used when issuing new auth tokens near the binary)
- References:
  - Official repository: https://github.com/router-for-me/CLIProxyAPI
  - API guide: https://help.router-for.me/

## High-level architecture

### New architecture (Python core + thin wrappers)
```
Shell wrappers (thin)             Python core (shared)
┌──────────────────────┐         ┌──────────────────────────┐
│ bash/cc-proxy.sh     │─call──> │                          │
│  ~50 lines           │         │  python/cc_proxy.py      │
├──────────────────────┤         │  ~650 lines, stdlib only │
│ powershell/          │─call──> │  cross-platform          │
│  cc-proxy.ps1        │         │                          │
│  ~50 lines           │         └──────────────────────────┘
└──────────────────────┘
```

1. Shell wrappers (`cc-<provider>` functions) call `python3 python/cc_proxy.py run <preset> -- [args]`.
2. `python/cc_proxy.py` contains ALL logic: token validation, proxy start/stop, health check, claude invocation.
3. Provider isolation is done by working directory + `auth-dir: "./"` in each provider config, so each instance only sees credentials in its own folder.
4. Startup rewrites provider base `config.yaml` with provider-specific port and launches the binary with `-config <base-config-file>`.
5. `python/cc_proxy.py run` sets env vars for the claude child process directly (no shell env modification needed):
   - `ANTHROPIC_BASE_URL`
   - `ANTHROPIC_AUTH_TOKEN=sk-dummy`
   - `ANTHROPIC_DEFAULT_OPUS_MODEL`
   - `ANTHROPIC_DEFAULT_SONNET_MODEL`
   - `ANTHROPIC_DEFAULT_HAIKU_MODEL`

### Platform abstraction in Python core
| Operation | Linux | Windows |
|---|---|---|
| Binary name | `cli-proxy-api` | `cli-proxy-api.exe` |
| Port → PID | `ss -tlnp` / `lsof` fallback | `netstat -ano -p TCP` |
| PID alive | `os.kill(pid, 0)` | `tasklist /FI "PID eq N"` |
| Kill process | `os.kill(SIGTERM)` | `taskkill /PID N /F` |
| Background launch | `Popen(start_new_session=True)` | `Popen(creationflags=CREATE_NO_WINDOW)` |
| Health check | `urllib.request.urlopen()` | same |
| Browser open | `webbrowser.open()` + SSH/DISPLAY guard | `webbrowser.open()` + SSH guard |

### Process tracking
- **PID files**: `configs/<provider>/.proxy.pid` on both platforms (replaces PowerShell in-memory `$script:` state).
- **Base dir**: Auto-detected via `Path(__file__).parent.parent` in Python (no hardcoded paths).

### Port model in this repo
Defined in `python/cc_proxy.py` (single source of truth, synced to both shell wrappers):
- `antigravity`: `18417`
- `claude`: `18418`
- `codex`: `18419`
- `gemini`: `18420`

## Common commands
> If your shell profile already loads these functions, use commands directly.
> Otherwise, load first from repo root.

### Windows (PowerShell)

#### Load helper functions (one-off shell)
```powershell
. .\powershell\cc-proxy.ps1
```

#### Register helpers in PowerShell profile (recommended first-time setup)
```powershell
. .\powershell\cc-proxy.ps1
Install-CCProxyProfile
```
`Install-CCProxyProfile` updates `$PROFILE` and loads it into the current session immediately.
New PowerShell sessions will auto-load helpers via the profile line.

### Linux (Bash)

#### Load helper functions (one-off shell)
```bash
source bash/cc-proxy.sh
```

#### Register helpers in shell profile (recommended first-time setup)
```bash
source bash/cc-proxy.sh
cc_proxy_install_profile
```
`cc_proxy_install_profile` adds a source line to `~/.bashrc` and `~/.zshrc` (if they exist).
New terminal sessions will auto-load helpers.

### Run Claude Code (both platforms)
```
cc
```
Runs native Claude Code (proxy env vars removed).

### Run Claude Code via provider-specific proxy (both platforms)
```
cc-claude
cc-gemini
cc-codex
cc-ag-claude
cc-ag-gemini
```

### Proxy status and stop (both platforms)
```
cc-proxy-status
cc-proxy-stop
```
`cc-*` commands do not force-stop a healthy running provider proxy; they reuse it and only start if needed.
Use `cc-proxy-stop` when you want an explicit shutdown.

### Health/model checks (single-provider smoke test)
Use `curl` (on Linux) or `curl.exe` (on Windows, not PowerShell `curl` alias):
```
curl -fsS http://127.0.0.1:18417/
curl http://127.0.0.1:18417/v1/models
```
Swap port for other providers (`18418`, `18419`, `18420`).

### Management UI
```text
http://127.0.0.1:<provider-port>/management.html
```

## Editing guidance for future Claude instances
- **To change model names or ports**: edit `python/cc_proxy.py` ONLY — single source of truth. Shell wrappers delegate automatically.
- Prefer editing `python/cc_proxy.py` for all logic changes. Shell wrappers (`bash/cc-proxy.sh`, `powershell/cc-proxy.ps1`) are thin and rarely need editing.
- Treat `configs/*/.config.runtime.yaml` as generated artifacts and keep them untracked.
- Treat `configs/*/.proxy.pid` as runtime state and keep them untracked.
- Use provider base `config.yaml` as dashboard-connected runtime source of truth.
- Do not enforce `remote-management.secret-key`; allow dashboard-managed values.
- For new providers, copy root `config.yaml` as a template and then set provider port.
- Treat `**/main.log` as runtime log output and keep it untracked.
- Keep root `config.yaml` tracked as a bootstrap config for issuing new auth tokens near the binary.
- If adding new providers/ports, update `PORTS` and `PRESETS` in `python/cc_proxy.py`; add entrypoint functions to both shell wrappers.
- `routing.strategy` is set to `round-robin` in provider configs.
- Linux binary (`cli-proxy-api`) is gitignored; users download it separately.

## Build / lint / test reality
- No repo-local build/lint/test pipeline was found (`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `Makefile`, and `README.md` are absent).
- For this repo, practical verification is operational smoke testing via `cc-*`, `cc-proxy-status`, and `/v1/models` checks.

## External instruction files check
- No existing `CLAUDE.md` was found before creation.
- No `.cursorrules` / `.cursor/rules/*` / `.github/copilot-instructions.md` were found in this repo at scan time.