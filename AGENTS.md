# AGENTS.md

This file provides guidance to OpenAI (OpenAI.ai/code) when working with code in this repository.

## Repository overview
- This repo is an **operations/config workspace** for a prebuilt CLIProxyAPI binary, not the source code of the proxy itself.
- **Supported platforms**: Windows (PowerShell) and Linux Ubuntu (Bash).
- **Python 3.8+** required (stdlib only, no pip install).
- Binary version: Dynamically query by running `cli-proxy-api -h`. Do not hardcode version numbers in this repo.
- Main moving parts:
  - `CLIProxyAPI/windows/amd64/cli-proxy-api.exe` (Windows binary, prebuilt)
  - `CLIProxyAPI/linux/amd64/cli-proxy-api` (Linux amd64 binary)
  - `CLIProxyAPI/linux/arm64/cli-proxy-api` (Linux arm64 binary)
  - `configs/<provider>/config.yaml` (+ provider credential JSON files)
  - `core/cc_proxy.py` (cross-platform core logic — single source of truth)
  - `shell/powershell/cc-proxy.ps1` (Windows thin wrapper, ~50 lines, delegates to Python core)
  - `shell/bash/cc-proxy.sh` (Linux thin wrapper, ~50 lines, delegates to Python core)
  - `docs/OpenAI-cliproxy-guide.md` (Operational background and guide)
  - `config.yaml` at repo root (bootstrap config used when issuing new auth tokens near the binary)
- References:
  - Official repository: https://github.com/router-for-me/CLIProxyAPI
  - API guide: https://help.router-for.me/

## High-level architecture

### New architecture (Python core + thin wrappers)
```
Shell wrappers (thin)             Python core (shared)
┌──────────────────────┐         ┌──────────────────────────┐
│ shell/bash/cc-proxy.sh│─call──> │                          │
│  ~50 lines            │         │  core/cc_proxy.py        │
├───────────────────────┤         │  ~650 lines, stdlib only │
│ shell/powershell/     │─call──> │  cross-platform          │
│  cc-proxy.ps1         │         │                          │
│  ~50 lines           │         └──────────────────────────┘
└──────────────────────┘
```

1. Shell wrappers (`cc-<provider>` functions) call `python3 core/cc_proxy.py run <preset> -- [args]`.
2. `core/cc_proxy.py` contains ALL logic: token validation, proxy start/stop, health check, OpenAI invocation.
3. Provider isolation is done by working directory + `auth-dir: "./"` in each provider config, so each instance only sees credentials in its own folder.
4. Startup rewrites provider base `config.yaml` with provider-specific port and launches the binary with `-config <base-config-file>`.
5. `core/cc_proxy.py run` sets env vars for the OpenAI child process directly (no shell env modification needed):
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
Defined in `core/cc_proxy.py` (single source of truth, synced to both shell wrappers):
- `antigravity`: `18417`
- `OpenAI`: `18418`
- `openai`: `18419`
- `gemini`: `18420`

## Common commands
> If your shell profile already loads these functions, use commands directly.
> Runtime execution should be performed from installed path (`~/.cli-proxy`).

### Windows (PowerShell)

#### Load helper functions (one-off shell)
```powershell
. "~\.cli-proxy\shell\powershell\cc-proxy.ps1"
```

> Legacy note: root one-liner URLs (`.../install.ps1`, `.../install.sh`) are intentionally unsupported. Use `installers/install.ps1` / `installers/install.sh`.

#### Register helpers in PowerShell profile (recommended first-time setup)
```powershell
. "~\.cli-proxy\shell\powershell\cc-proxy.ps1"
Install-CCProxyProfile
```
`Install-CCProxyProfile` updates `$PROFILE` and loads it into the current session immediately.
New PowerShell sessions will auto-load helpers via the profile line.

### Linux (Bash)

#### Load helper functions (one-off shell)
```bash
source ~/.cli-proxy/shell/bash/cc-proxy.sh
```

#### Register helpers in shell profile (recommended first-time setup)
```bash
source ~/.cli-proxy/shell/bash/cc-proxy.sh
cc_proxy_install_profile
```
`cc_proxy_install_profile` adds a source line to `~/.bashrc` and `~/.zshrc` (if they exist).
New terminal sessions will auto-load helpers.

### Run OpenAI (both platforms)
```
cc
```
Runs native OpenAI (proxy env vars removed).

### Run OpenAI via provider-specific proxy (both platforms)
```
cc-OpenAI
cc-gemini
cc-openai
cc-ag-OpenAI
cc-ag-gemini
```

### Proxy start, status, links, and stop (both platforms)
```
cc-proxy-start-all
cc-proxy-status
cc-proxy-links [provider]
cc-proxy-stop
```
`cc-*` commands do not force-stop a healthy running provider proxy; they reuse it and only start if needed.
Use `cc-proxy-start-all` to launch all proxies in the background at once (useful for monitoring).
Use `cc-proxy-stop` when you want an explicit shutdown.
Use `cc-proxy-links` to print management URLs and the generated combined dashboard `http://` link.

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

## Verification policy (installed-only runtime)
- Do not treat repository-source execution as valid runtime verification.
- Runtime commands must be executed from installed path wrappers only:
  - Bash: `source ~/.cli-proxy/shell/bash/cc-proxy.sh`
  - PowerShell: `. "~\.cli-proxy\shell\powershell\cc-proxy.ps1"`
- Repository wrappers now block execution by default; temporary bypass is possible with `CC_PROXY_ALLOW_REPO_RUN=1` only for emergency debugging.

### Required verification flow
1. **Sync step (development reflection)**
   - After editing repository files, run installer sync from repo root:
     - Linux: `python3 installers/install.py --source local`
     - Windows: `python installers/install.py --source local`
2. **Installed runtime check (release gate)**
   - Open a fresh shell and load from `~/.cli-proxy/shell/...`.
   - Run lifecycle checks: `cc-proxy-start-all` / `cc-proxy-status` / `cc-proxy-links` / `cc-proxy-stop`.
   - Re-run smoke checks (`/` and `/v1/models`).
   - Only this track is valid evidence for deployment readiness.

### Safety rules to avoid false positives
- Confirm active base dir before tests:
  - Bash: `echo "$CC_PROXY_BASE_DIR"`
  - PowerShell: `$global:CLI_PROXY_BASE_DIR`
- Confirm install metadata source before runtime verification:
  - `cat ~/.cli-proxy/.install-meta.json` (or PowerShell equivalent)

## Editing guidance for future OpenAI instances
- **To change model names or ports**: edit `core/cc_proxy.py` ONLY — single source of truth. Shell wrappers delegate automatically.
- Prefer editing `core/cc_proxy.py` for all logic changes. Shell wrappers (`shell/bash/cc-proxy.sh`, `shell/powershell/cc-proxy.ps1`) are thin and rarely need editing.
- Treat `configs/*/.config.runtime.yaml` as generated artifacts and keep them untracked.
- Treat `configs/*/.proxy.pid` as runtime state and keep them untracked.
- Use provider base `config.yaml` as dashboard-connected runtime source of truth.
- Do not enforce `remote-management.secret-key`; allow dashboard-managed values.
- For new providers, copy root `config.yaml` as a template and then set provider port.
- Treat `**/main.log` as runtime log output and keep it untracked.
- Keep root `config.yaml` tracked as a bootstrap config for issuing new auth tokens near the binary.
- If adding new providers/ports, update `PORTS` and `PRESETS` in `core/cc_proxy.py`; add entrypoint functions to both shell wrappers.
- `routing.strategy` is set to `round-robin` in provider configs.
- Repository-managed binaries are stored under `CLIProxyAPI/<os>/<arch>/` and `core/cc_proxy.py` resolves host-appropriate paths automatically.

## Build / lint / test reality
- **Unit tests**: `tests/` directory contains stdlib `unittest` tests covering all core modules. Run with `py tests/run_tests.py -v` (or `python3 tests/run_tests.py -v` on Linux). Tests require no external dependencies.
- **Smoke tests**: `tests/test_smoke.py` validates binary presence, version output, login flags, and module imports. Requires the CLIProxyAPI binary.
- **Test runner**: `tests/run_tests.py` supports `--unit` (no binary needed), `--smoke` (binary needed), and `-v` flags. Returns exit code 0/1 for CI integration.
- **Deployment guide**: `docs/testing-and-deployment.md` documents the full testing and deployment procedure.
- Practical runtime verification is operational smoke testing via `cc-*`, `cc-proxy-status`, and `/v1/models` checks (see verification policy below).

## External instruction files check
- No existing `AGENTS.md` was found before creation.
- No `.cursorrules` / `.cursor/rules/*` / `.github/copilot-instructions.md` were found in this repo at scan time.