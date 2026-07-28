from __future__ import annotations

from typing import Any, Dict, Tuple
import os
import sys

try:
    import mss
except Exception:
    mss = None

try:
    import pyautogui
except Exception:
    pyautogui = None

try:
    import ctypes
    from ctypes import wintypes
except Exception:
    ctypes = None
    wintypes = None

_MOUSE_DEBUG = bool(os.environ.get("LLMLOADER_MOUSE_DEBUG"))

_CLICK_XFORM_READY = False
_CLICK_SX = 1.0
_CLICK_SY = 1.0
_CLICK_OX = 0.0
_CLICK_OY = 0.0


def _debug_log(msg: str) -> None:
    if _MOUSE_DEBUG:
        print(msg)


def _win_enable_dpi_awareness() -> None:
    if ctypes is None:
        return
    try:
        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            return
        except Exception:
            pass
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    except Exception:
        pass


_win_enable_dpi_awareness()  # type: ignore


def _ensure_click_transform() -> None:
    global _CLICK_XFORM_READY, _CLICK_SX, _CLICK_SY, _CLICK_OX, _CLICK_OY
    if _CLICK_XFORM_READY:
        return
    _CLICK_XFORM_READY = True
    _CLICK_SX = 1.0
    _CLICK_SY = 1.0
    _CLICK_OX = 0.0
    _CLICK_OY = 0.0
    if mss is None or pyautogui is None:
        return
    try:
        with mss.mss() as sct:
            vs = sct.monitors[0]
            vs_left = int(vs.get("left") or 0)
            vs_top = int(vs.get("top") or 0)
            vs_w = int(vs.get("width") or 0)
            vs_h = int(vs.get("height") or 0)
        pw, ph = pyautogui.size()
        pw = int(pw or 0)
        ph = int(ph or 0)
        if vs_w > 0 and vs_h > 0 and pw > 0 and ph > 0:
            _CLICK_SX = float(pw) / float(vs_w)
            _CLICK_SY = float(ph) / float(vs_h)
            _CLICK_OX = float(-vs_left) * _CLICK_SX
            _CLICK_OY = float(-vs_top) * _CLICK_SY
            _debug_log(
                f"[mouse] click_xform: vs=({vs_left},{vs_top},{vs_w}x{vs_h}) py=({pw}x{ph}) "
                f"scale=({_CLICK_SX:.4f},{_CLICK_SY:.4f}) off=({_CLICK_OX:.2f},{_CLICK_OY:.2f})"
            )
    except Exception:
        return


def _apply_click_transform(x: int, y: int) -> tuple[int, int]:
    if not _CLICK_XFORM_READY:
        _ensure_click_transform()
    nx = int(round(float(x) * _CLICK_SX + _CLICK_OX))
    ny = int(round(float(y) * _CLICK_SY + _CLICK_OY))
    return nx, ny


def _send_input_move_click_button(x: int, y: int, button: str = "left", clicks: int = 1) -> bool:
    if os.name != "nt":
        return False
    if ctypes is None or wintypes is None:
        return False
    button = (button or "left").lower()
    if button not in ("left", "right"):
        return False
    clicks = max(1, int(clicks or 1))
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        if screen_w <= 1 or screen_h <= 1:
            return False
        abs_x = int(x * 65535 / (screen_w - 1))
        abs_y = int(y * 65535 / (screen_h - 1))
        INPUT_MOUSE = 0
        MOUSEEVENTF_MOVE = 0x0001
        MOUSEEVENTF_ABSOLUTE = 0x8000
        if button == "left":
            DOWN = 0x0002
            UP = 0x0004
        else:
            DOWN = 0x0008
            UP = 0x0010

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", wintypes.ULONG_PTR),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [
                ("type", wintypes.DWORD),
                ("mi", MOUSEINPUT),
            ]

        def _send(flags: int) -> int:
            mi = MOUSEINPUT(dx=abs_x, dy=abs_y, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=0)
            inp = INPUT(type=INPUT_MOUSE, mi=mi)
            return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

        moved = _send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)
        ok = moved == 1
        for _ in range(clicks):
            down = _send(DOWN | MOUSEEVENTF_ABSOLUTE)
            up = _send(UP | MOUSEEVENTF_ABSOLUTE)
            ok = ok and down == 1 and up == 1
        return bool(ok)
    except Exception as exc:
        _debug_log(f"[mouse] SendInput button failed: {exc}")
        return False


def _send_input_text(text: str) -> bool:
    if os.name != "nt":
        return False
    if ctypes is None or wintypes is None:
        return False
    if not text:
        return True
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        INPUT_KEYBOARD = 1
        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", wintypes.ULONG_PTR),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [
                ("type", wintypes.DWORD),
                ("ki", KEYBDINPUT),
            ]

        def _send(ch: int, flags: int) -> int:
            ki = KEYBDINPUT(wVk=0, wScan=ch, dwFlags=flags, time=0, dwExtraInfo=0)
            inp = INPUT(type=INPUT_KEYBOARD, ki=ki)
            return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

        ok = True
        for ch in text:
            code = ord(ch)
            ok = ok and (_send(code, KEYEVENTF_UNICODE) == 1)
            ok = ok and (_send(code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP) == 1)
        return bool(ok)
    except Exception as exc:
        _debug_log(f"[kb] SendInput text failed: {exc}")
        return False


def _send_input_key(key: str) -> bool:
    if os.name != "nt":
        return False
    if ctypes is None or wintypes is None:
        return False
    key = (key or "").strip().lower()
    vk_map = {
        "enter": 0x0D,
        "return": 0x0D,
        "tab": 0x09,
        "esc": 0x1B,
        "escape": 0x1B,
        "backspace": 0x08,
        "delete": 0x2E,
        "space": 0x20,
        "win": 0x5B,
        "windows": 0x5B,
        "lwin": 0x5B,
        "winleft": 0x5B,
        "rwin": 0x5C,
        "winright": 0x5C,
    }
    vk = vk_map.get(key)
    if vk is None:
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        INPUT_KEYBOARD = 1
        KEYEVENTF_KEYUP = 0x0002

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", wintypes.ULONG_PTR),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [
                ("type", wintypes.DWORD),
                ("ki", KEYBDINPUT),
            ]

        def _send(flags: int) -> int:
            ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
            inp = INPUT(type=INPUT_KEYBOARD, ki=ki)
            return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

        down = _send(0)
        up = _send(KEYEVENTF_KEYUP)
        return down == 1 and up == 1
    except Exception as exc:
        _debug_log(f"[kb] SendInput key failed: {exc}")
        return False


def is_ui_available() -> bool:
    if pyautogui is not None:
        return True
    if os.name == "nt" and ctypes is not None:
        return True
    return False


def normalized_box_to_screen_xy(
    box: Tuple[float, float, float, float],
    monitor: Dict[str, int],
) -> tuple[int, int]:
    x0, y0, x1, y1 = box
    cx = (float(x0) + float(x1)) / 2.0
    cy = (float(y0) + float(y1)) / 2.0
    mw = int(monitor.get("width") or 0)
    mh = int(monitor.get("height") or 0)
    w1 = max(1, mw - 1)
    h1 = max(1, mh - 1)
    px = int(monitor.get("left", 0) + int(round(cx * w1)))
    py = int(monitor.get("top", 0) + int(round(cy * h1)))
    return px, py


def click_element_at(box: Tuple[float, float, float, float], monitor: Dict[str, int], *, button: str = "left", clicks: int = 1) -> None:
    x, y = normalized_box_to_screen_xy(box, monitor)
    x, y = _apply_click_transform(x, y)
    if pyautogui is not None:
        try:
            pyautogui.moveTo(x, y)
            if button == "right":
                pyautogui.click(button="right")
            else:
                pyautogui.click(clicks=clicks)
            return
        except Exception as exc:
            _debug_log(f"[mouse] pyautogui click failed: {exc}")
    if _send_input_move_click_button(x, y, button=button, clicks=clicks):
        return
    raise RuntimeError("mouse click failed")


def drag_element(
    start_box: Tuple[float, float, float, float],
    end_box: Tuple[float, float, float, float],
    monitor: Dict[str, int],
) -> None:
    sx, sy = normalized_box_to_screen_xy(start_box, monitor)
    ex, ey = normalized_box_to_screen_xy(end_box, monitor)
    sx, sy = _apply_click_transform(sx, sy)
    ex, ey = _apply_click_transform(ex, ey)
    if pyautogui is not None:
        try:
            pyautogui.moveTo(sx, sy)
            pyautogui.dragTo(ex, ey, duration=0.2)
            return
        except Exception as exc:
            _debug_log(f"[mouse] pyautogui drag failed: {exc}")
    raise RuntimeError("drag failed (pyautogui required)")


def scroll_at(
    box: Tuple[float, float, float, float],
    monitor: Dict[str, int],
    direction: str = "down",
    amount: int = 3,
) -> None:
    if pyautogui is None:
        raise RuntimeError("scroll failed (pyautogui required)")
    x, y = normalized_box_to_screen_xy(box, monitor)
    x, y = _apply_click_transform(x, y)
    try:
        pyautogui.moveTo(x, y)
        dist = int(max(1, amount)) * 120
        if direction in ("up", "u"):
            pyautogui.scroll(dist)
        elif direction in ("down", "d"):
            pyautogui.scroll(-dist)
        elif direction in ("left", "l"):
            pyautogui.hscroll(-dist)
        elif direction in ("right", "r"):
            pyautogui.hscroll(dist)
    except Exception as exc:
        _debug_log(f"[mouse] scroll failed: {exc}")
        raise


def type_text(text: str) -> bool:
    if text is None:
        return False
    if pyautogui is not None:
        try:
            pyautogui.write(str(text), interval=0.02)
            return True
        except Exception as exc:
            _debug_log(f"[kb] pyautogui type failed: {exc}")
    return _send_input_text(str(text))


def press_keys(keys: Any) -> bool:
    if keys is None:
        return False
    if isinstance(keys, (list, tuple)):
        key_list = [str(k) for k in keys if k]
    else:
        key_list = [str(keys)]
    if not key_list:
        return False
    if pyautogui is not None:
        try:
            if len(key_list) == 1 and "+" in key_list[0]:
                parts = [p.strip() for p in key_list[0].split("+") if p.strip()]
                parts = [_normalize_key(p) for p in parts]
                pyautogui.hotkey(*parts)
            elif len(key_list) == 1:
                pyautogui.press(_normalize_key(key_list[0]))
            else:
                parts = [_normalize_key(p) for p in key_list]
                pyautogui.hotkey(*parts)
            return True
        except Exception as exc:
            _debug_log(f"[kb] pyautogui press failed: {exc}")
    if len(key_list) == 1:
        return _send_input_key(_normalize_key(key_list[0]))
    return False


def _normalize_key(key: str) -> str:
    k = (key or "").strip().lower()
    if k in ("win", "windows", "lwin", "winleft"):
        return "winleft"
    if k in ("rwin", "winright"):
        return "winright"
    if k in ("control", "ctl"):
        return "ctrl"
    if k == "command":
        return "command"
    return k
