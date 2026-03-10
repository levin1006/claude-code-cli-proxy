"""
Terminal UI: key input handling, rendering loop, and account toggle.
Depends on: constants, paths, process, proxy, display
"""

import json
import os
import re
import shutil
import sys
import time
import unicodedata
from datetime import datetime

from constants import (
    _C_BOLD, _C_DIM, _C_GREEN, _C_RED, _C_RESET,
    _TUI_ALT_OFF, _TUI_ALT_ON,
    _TUI_CLEAR, _TUI_CURSOR_HIDE, _TUI_CURSOR_SHOW, _TUI_HOME,
    _TUI_KEY_DOWN, _TUI_KEY_ESC, _TUI_KEY_LEFT, _TUI_KEY_RIGHT, _TUI_KEY_UP,
    IS_WINDOWS, PROVIDERS,
)
from paths import resolve_account_file_path
from proxy import get_status, start_proxy, stop_proxy
from display import (
    _account_identity, _box_bottom, _box_line, _box_sep, _box_top,
    _dedupe_auth_files, _prefetch_provider_data, _print_status_dashboard,
    _provider_frame_color,
)

# Module-level stdin buffers for key reading
_TUI_STDIN_BUF = ""
_TUI_WIN_BUF = []


# ---------------------------------------------------------------------------
# Screen control
# ---------------------------------------------------------------------------

def _tui_write(s):
    sys.stdout.write(s)


def _tui_flush():
    sys.stdout.flush()


def _tui_enter_screen():
    _tui_write(_TUI_ALT_ON + _TUI_CURSOR_HIDE + _TUI_HOME + _TUI_CLEAR)
    _tui_flush()


def _tui_leave_screen():
    _tui_write(_TUI_CURSOR_SHOW + _TUI_ALT_OFF)
    _tui_flush()


# ---------------------------------------------------------------------------
# Key input
# ---------------------------------------------------------------------------

def _tui_key_to_action(key):
    if not key:
        return None
    if key in (_TUI_KEY_ESC,):
        return key
    if key == "\x1b":
        return _TUI_KEY_ESC
    if key == " ":
        return "toggle"

    lk = unicodedata.normalize("NFKC", key.lower())
    # Support Korean 2-set layout without switching to English:
    # ㅁ/ㄴ/ㅈ/ㅇ → a/s/w/d, ㄱ/ㅂ → r/q
    lk = {
        "ㅁ": "a", "\u1106": "a",
        "ㄴ": "s", "\u1102": "s",
        "ㅈ": "w", "\u110c": "w",
        "ㅇ": "d", "\u110b": "d",
        "ㄱ": "r", "\u1100": "r",
        "ㅂ": "q", "\u1107": "q",
    }.get(lk, lk)

    if lk in ("q", "r"):
        return lk
    if lk in ("a", "s", "w", "d"):
        return {
            "a": _TUI_KEY_LEFT,
            "s": _TUI_KEY_DOWN,
            "w": _TUI_KEY_UP,
            "d": _TUI_KEY_RIGHT,
        }[lk]
    if lk in ("1", "2", "3", "4"):
        return lk
    return None


def _read_key_timeout(timeout_sec=0.5):
    global _TUI_STDIN_BUF, _TUI_WIN_BUF

    if IS_WINDOWS:
        import msvcrt

        # return buffered key first (preserve exact order)
        if _TUI_WIN_BUF:
            return _TUI_WIN_BUF.pop(0)

        end = time.time() + max(0.0, timeout_sec)
        while time.time() < end:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                action = None
                if ch in (b"\x00", b"\xe0"):
                    ch2 = msvcrt.getch()
                    mapping = {
                        b"K": _TUI_KEY_LEFT,
                        b"M": _TUI_KEY_RIGHT,
                        b"H": _TUI_KEY_UP,
                        b"P": _TUI_KEY_DOWN,
                    }
                    action = mapping.get(ch2)
                elif ch == b"\x1b":
                    action = _TUI_KEY_ESC
                else:
                    try:
                        action = ch.decode("utf-8", errors="ignore")
                    except Exception:
                        action = None

                if action is not None:
                    _TUI_WIN_BUF.append(action)

                # drain additional pending keys quickly into buffer
                drain_deadline = time.time() + 0.01
                while time.time() < drain_deadline and msvcrt.kbhit():
                    chx = msvcrt.getch()
                    ax = None
                    if chx in (b"\x00", b"\xe0"):
                        chx2 = msvcrt.getch()
                        ax = {
                            b"K": _TUI_KEY_LEFT,
                            b"M": _TUI_KEY_RIGHT,
                            b"H": _TUI_KEY_UP,
                            b"P": _TUI_KEY_DOWN,
                        }.get(chx2)
                    elif chx == b"\x1b":
                        ax = _TUI_KEY_ESC
                    else:
                        try:
                            ax = chx.decode("utf-8", errors="ignore")
                        except Exception:
                            ax = None
                    if ax is not None:
                        _TUI_WIN_BUF.append(ax)

                return _TUI_WIN_BUF.pop(0) if _TUI_WIN_BUF else None

            time.sleep(0.002)

        return None

    import termios
    import tty
    import select

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)

        r, _, _ = select.select([sys.stdin], [], [], max(0.0, timeout_sec))
        if r:
            while True:
                r2, _, _ = select.select([sys.stdin], [], [], 0)
                if not r2:
                    break
                _TUI_STDIN_BUF += sys.stdin.read(1)

        if not _TUI_STDIN_BUF:
            return None

        # If ESC starts a sequence, wait a tiny bit for the remaining bytes.
        if _TUI_STDIN_BUF.startswith("\x1b") and len(_TUI_STDIN_BUF) == 1:
            r3, _, _ = select.select([sys.stdin], [], [], 0.03)
            if r3:
                _TUI_STDIN_BUF += sys.stdin.read(1)
                while True:
                    r4, _, _ = select.select([sys.stdin], [], [], 0)
                    if not r4:
                        break
                    _TUI_STDIN_BUF += sys.stdin.read(1)

        seq_map = {
            "\x1b[A": _TUI_KEY_UP,
            "\x1b[B": _TUI_KEY_DOWN,
            "\x1b[C": _TUI_KEY_RIGHT,
            "\x1b[D": _TUI_KEY_LEFT,
            "\x1bOA": _TUI_KEY_UP,
            "\x1bOB": _TUI_KEY_DOWN,
            "\x1bOC": _TUI_KEY_RIGHT,
            "\x1bOD": _TUI_KEY_LEFT,
        }
        for seq in sorted(seq_map.keys(), key=len, reverse=True):
            if _TUI_STDIN_BUF.startswith(seq):
                _TUI_STDIN_BUF = _TUI_STDIN_BUF[len(seq):]
                return seq_map[seq]

        ch = _TUI_STDIN_BUF[0]
        _TUI_STDIN_BUF = _TUI_STDIN_BUF[1:]
        if ch == "\x1b":
            return _TUI_KEY_ESC
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _tui_clear_input_buffer():
    global _TUI_STDIN_BUF, _TUI_WIN_BUF
    _TUI_STDIN_BUF = ""
    _TUI_WIN_BUF = []


def _tui_discard_pending_input(settle_ms=0):
    """Discard queued key events (local + OS buffer).

    settle_ms>0이면 짧은 시간 동안 반복적으로 비워서 토글 직후 key repeat 꼬임을 줄인다.
    """
    _tui_clear_input_buffer()

    def _flush_once():
        try:
            if IS_WINDOWS:
                import msvcrt
                while msvcrt.kbhit():
                    msvcrt.getch()
            else:
                import termios
                termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
        except Exception:
            pass
        _tui_clear_input_buffer()

    _flush_once()
    if settle_ms and settle_ms > 0:
        end = time.time() + (float(settle_ms) / 1000.0)
        while time.time() < end:
            _flush_once()
            time.sleep(0.005)


# ---------------------------------------------------------------------------
# Data fetch helpers
# ---------------------------------------------------------------------------

def _tui_fetch_provider(base_dir, provider):
    d = _prefetch_provider_data(
        base_dir,
        provider,
        fetch_quota=True,
        fetch_check=True,
    )
    d["auth_data"] = _dedupe_auth_files(d.get("auth_data"), provider=provider)
    return d


def _tui_fetch_provider_light(base_dir, provider):
    """Faster refresh path: skip quota/check heavy calls."""
    d = _prefetch_provider_data(
        base_dir,
        provider,
        fetch_quota=False,
        fetch_check=False,
    )
    d["auth_data"] = _dedupe_auth_files(d.get("auth_data"), provider=provider)
    return d


# ---------------------------------------------------------------------------
# Account toggle
# ---------------------------------------------------------------------------

def _tui_toggle_account(base_dir, provider, account, progress_cb=None):
    """Toggle disabled flag by directly editing the selected account JSON file.

    원칙:
    - 반드시 선택된 account의 path 파일만 수정
    - runtime-only/non-file 계정은 수정하지 않음
    - atomic write(임시파일 + replace)로 파일 손상 방지
    """
    def _progress(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    if not account:
        return False, "no account selected"

    if account.get("runtime_only"):
        return False, "toggle unsupported: runtime-only account"
    if account.get("source") and account.get("source") != "file":
        return False, "toggle unsupported: non-file account"

    rel_path = (account.get("path") or "").strip()
    if not rel_path:
        return False, "toggle unsupported: no file path"

    file_path, err = resolve_account_file_path(base_dir, provider, rel_path)
    if err:
        return False, "toggle blocked: {}".format(err)
    if file_path is None:
        return False, "toggle unsupported: file path resolve failed"

    if not file_path.exists() or not file_path.is_file():
        return False, "toggle unsupported: file not found"

    _progress(_C_DIM + "파일 읽는 중..." + _C_RESET)
    try:
        raw = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return False, "read failed: {}".format(e)

    try:
        obj = json.loads(raw)
    except Exception as e:
        return False, "json parse failed: {}".format(e)

    if not isinstance(obj, dict):
        return False, "json shape invalid"

    obj["disabled"] = not bool(obj.get("disabled", False))

    payload = json.dumps(obj, ensure_ascii=False, indent=2)
    if not payload.endswith("\n"):
        payload += "\n"

    _progress(_C_DIM + "파일 저장 중..." + _C_RESET)
    tmp = file_path.with_name(file_path.name + ".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(str(tmp), str(file_path))
    except Exception as e:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False, "write failed: {}".format(e)

    # binary가 파일 변경을 즉시 반영하지 않는 환경이 있어 provider 재기동으로 확정 반영
    try:
        status = get_status(base_dir, provider)
        if status.get("running"):
            _progress(_C_DIM + "provider 재시작 중..." + _C_RESET)
            stop_proxy(base_dir, provider, quiet=True)
            if not start_proxy(base_dir, provider, quiet=True):
                return False, "toggle saved but restart failed"
    except Exception as e:
        return False, "toggle saved but reload failed: {}".format(e)

    return True, "toggled"


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _tui_render(base_dir, state):
    provider = state["providers"][state["provider_idx"]]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    term_w = shutil.get_terminal_size(fallback=(100, 24)).columns
    W = max(84, min(term_w - 2, 140))

    data = state["data"].get(provider)
    if data is None:
        data = _tui_fetch_provider(base_dir, provider)
        state["data"][provider] = data

    files = (data.get("auth_data") or {}).get("files", [])
    if files:
        state["account_idx"] = max(0, min(state["account_idx"], len(files) - 1))
        selected = files[state["account_idx"]]
        selected_name = selected.get("name")
        selected_key = _account_identity(selected)
    else:
        state["account_idx"] = 0
        selected = None
        selected_name = None
        selected_key = None

    tabs = []
    for i, pvd in enumerate(state["providers"]):
        label = "{} {}".format(i + 1, pvd)
        if i == state["provider_idx"]:
            label = _C_BOLD + "[{}]".format(label) + _C_RESET
        tabs.append(label)
    tab_line = "  " + "   ".join(tabs)

    footer_keys = "  a/d provider   w/s account   space toggle   r refresh   q quit"
    if state.get("message"):
        msg = "  " + state["message"]
    else:
        msg = "  " + _C_DIM + "ready" + _C_RESET

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        frame_color = _provider_frame_color(provider)
        if frame_color:
            print(frame_color + _box_top(W) + _C_RESET)
        else:
            print(_box_top(W))
        title = "  cc-proxy ui"
        padding = W - 4 - len(re.sub(r"\033\[[0-9;]*m", "", title)) - len(now_str)
        if frame_color:
            print(frame_color + _box_line(title + " " * max(1, padding) + now_str, W) + _C_RESET)
            print(frame_color + _box_sep(W) + _C_RESET)
            print(frame_color + _box_line(tab_line, W) + _C_RESET)
        else:
            print(_box_line(title + " " * max(1, padding) + now_str, W))
            print(_box_sep(W))
            print(_box_line(tab_line, W))

        _print_status_dashboard(
            base_dir,
            provider,
            data.get("status") or get_status(base_dir, provider),
            W,
            auth_data=data.get("auth_data"),
            usage_data=data.get("usage_data"),
            auth_error=data.get("auth_error", False),
            usage_source=data.get("usage_source", "none"),
            usage_snapshot_at=data.get("usage_snapshot_at"),
            models_per_account=data.get("models_per_account"),
            quota_data=data.get("quota_data"),
            proxy_models=data.get("proxy_models"),
            show_check=True,
            selected_account_name=selected_name,
            selected_account_key=selected_key,
            frame_color=frame_color,
        )

        if frame_color:
            print(frame_color + _box_sep(W) + _C_RESET)
        else:
            print(_box_sep(W))
        if frame_color:
            print(frame_color + _box_line(msg, W) + _C_RESET)
            print(frame_color + _box_line(footer_keys, W) + _C_RESET)
            print(frame_color + _box_bottom(W) + _C_RESET)
        else:
            print(_box_line(msg, W))
            print(_box_line(footer_keys, W))
            print(_box_bottom(W))

    rendered = buf.getvalue()

    # Full-frame repaint for stable terminal compatibility.
    _tui_write(_TUI_HOME + _TUI_CLEAR)
    _tui_write(rendered)
    _tui_flush()

    return selected


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _tui_main_loop(base_dir, provider=None):
    state = {
        "providers": [provider] if provider else list(PROVIDERS),
        "provider_idx": 0,
        "account_idx": 0,
        "data": {},
        "last_fetch": {},
        "message": "",
        "busy": False,
        "toggle_cooldown_until": 0.0,
    }

    def _mark_busy(on):
        state["busy"] = bool(on)

    refresh_interval = 5.0

    def _refresh_provider(pvd, force=False, heavy=False):
        last = state["last_fetch"].get(pvd, 0)
        if force or (time.time() - last) >= refresh_interval:
            if heavy:
                fresh = _tui_fetch_provider(base_dir, pvd)
                state["data"][pvd] = fresh
            else:
                fresh = _tui_fetch_provider_light(base_dir, pvd)
                cur = state["data"].get(pvd, {})
                # keep previously fetched heavy sections (quota/models) to avoid flicker/latency
                if cur.get("quota_data") and not fresh.get("quota_data"):
                    fresh["quota_data"] = cur.get("quota_data")
                if cur.get("models_per_account") and not fresh.get("models_per_account"):
                    fresh["models_per_account"] = cur.get("models_per_account")
                if cur.get("proxy_models") and not fresh.get("proxy_models"):
                    fresh["proxy_models"] = cur.get("proxy_models")
                state["data"][pvd] = fresh
            state["last_fetch"][pvd] = time.time()
            return True
        return False

    def _refresh_current(force=False, heavy=False):
        pvd = state["providers"][state["provider_idx"]]
        return _refresh_provider(pvd, force=force, heavy=heavy)

    def _prefetch_all_once():
        import threading

        results = {}
        ts = time.time()

        def _one(pvd):
            try:
                results[pvd] = _tui_fetch_provider(base_dir, pvd)
            except Exception:
                results[pvd] = {"status": get_status(base_dir, pvd)}

        threads = [threading.Thread(target=_one, args=(pvd,)) for pvd in state["providers"]]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        for pvd in state["providers"]:
            if pvd in results:
                state["data"][pvd] = results[pvd]
                state["last_fetch"][pvd] = ts

    _tui_enter_screen()
    try:
        _prefetch_all_once()
        selected = _tui_render(base_dir, state)

        while True:
            action = _tui_key_to_action(_read_key_timeout(0.03))
            dirty = False

            if not state.get("busy"):
                if _refresh_current(force=False, heavy=False):
                    dirty = True

            if action is None:
                if dirty:
                    selected = _tui_render(base_dir, state)
                continue

            if action == "q":
                return 0
            if action == _TUI_KEY_ESC:
                # Windows Terminal에서 화살표 시퀀스가 ESC로 축약되는 경우가 있어
                # 오동작 종료를 방지하기 위해 ESC 단독 종료는 임시 비활성화.
                state["message"] = _C_DIM + "press q to quit" + _C_RESET
                dirty = True

            # when busy (toggle in-flight), ignore all inputs except quit.
            if state.get("busy"):
                state["message"] = _C_DIM + "toggle in progress..." + _C_RESET
                dirty = True
                if dirty:
                    selected = _tui_render(base_dir, state)
                continue

            if action == _TUI_KEY_LEFT:
                state["provider_idx"] = (state["provider_idx"] - 1) % len(state["providers"])
                state["account_idx"] = 0
                state["message"] = ""
                _refresh_current(force=True, heavy=False)
                dirty = True
            elif action == _TUI_KEY_RIGHT:
                state["provider_idx"] = (state["provider_idx"] + 1) % len(state["providers"])
                state["account_idx"] = 0
                state["message"] = ""
                _refresh_current(force=True, heavy=False)
                dirty = True
            elif action == _TUI_KEY_UP:
                prev = state["account_idx"]
                state["account_idx"] = max(0, state["account_idx"] - 1)
                state["message"] = ""
                dirty = (state["account_idx"] != prev)
            elif action == _TUI_KEY_DOWN:
                pvd = state["providers"][state["provider_idx"]]
                files = (state["data"].get(pvd, {}).get("auth_data") or {}).get("files", [])
                prev = state["account_idx"]
                if files:
                    state["account_idx"] = min(len(files) - 1, state["account_idx"] + 1)
                state["message"] = ""
                dirty = (state["account_idx"] != prev)
            elif action in ("1", "2", "3", "4"):
                idx = int(action) - 1
                if idx < len(state["providers"]) and idx != state["provider_idx"]:
                    state["provider_idx"] = idx
                    state["account_idx"] = 0
                    state["message"] = ""
                    _refresh_current(force=True, heavy=False)
                    dirty = True
            elif action == "r":
                _mark_busy(True)
                _tui_discard_pending_input(settle_ms=20)
                _refresh_current(force=True, heavy=True)
                _tui_discard_pending_input(settle_ms=20)
                _mark_busy(False)
                state["message"] = _C_DIM + "refreshed" + _C_RESET
                dirty = True
            elif action == "toggle":
                now = time.time()
                if now < state.get("toggle_cooldown_until", 0.0):
                    state["message"] = _C_DIM + "toggle cooldown..." + _C_RESET
                    dirty = True
                else:
                    pvd = state["providers"][state["provider_idx"]]
                    files = (state["data"].get(pvd, {}).get("auth_data") or {}).get("files", [])
                    if not files:
                        state["message"] = _C_DIM + "no account" + _C_RESET
                        dirty = True
                    else:
                        idx = max(0, min(state["account_idx"], len(files) - 1))
                        target = files[idx]
                        target_key = _account_identity(target)
                        target_email = target.get("email") or target.get("account") or target.get("name") or "?"

                        _mark_busy(True)
                        state["toggle_cooldown_until"] = time.time() + 1.0

                        try:
                            def _progress(msg):
                                state["message"] = msg
                                _tui_render(base_dir, state)

                            state["message"] = _C_DIM + "[1/3] toggling file: {}".format(target_email[:24]) + _C_RESET
                            selected = _tui_render(base_dir, state)
                            ok, m = _tui_toggle_account(base_dir, pvd, target, progress_cb=_progress)

                            state["message"] = _C_DIM + "[2/3] refreshing provider data..." + _C_RESET
                            selected = _tui_render(base_dir, state)

                            _refresh_current(force=True, heavy=True)
                            files2 = (state["data"].get(pvd, {}).get("auth_data") or {}).get("files", [])
                            if files2:
                                restored = None
                                for i2, f2 in enumerate(files2):
                                    if _account_identity(f2) == target_key:
                                        restored = i2
                                        break
                                if restored is None:
                                    for i2, f2 in enumerate(files2):
                                        em2 = f2.get("email") or f2.get("account") or f2.get("name") or ""
                                        if em2 == target_email:
                                            restored = i2
                                            break
                                if restored is not None:
                                    state["account_idx"] = restored
                                else:
                                    state["account_idx"] = min(idx, len(files2) - 1)

                            if ok:
                                state["message"] = _C_GREEN + "[3/3] toggled: {}".format(target_email[:24]) + _C_RESET
                            else:
                                state["message"] = _C_RED + m + _C_RESET
                            dirty = True
                        finally:
                            _tui_discard_pending_input(settle_ms=120)
                            _mark_busy(False)

            if dirty:
                selected = _tui_render(base_dir, state)

    finally:
        _tui_leave_screen()
