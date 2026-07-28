from __future__ import annotations

from typing import Any, Dict, Tuple

try:
    import mss
    from PIL import Image
except Exception:
    mss = None
    Image = None


def capture_screen() -> Tuple[Any, Dict[str, int]]:
    if mss is None or Image is None:
        raise RuntimeError("capture_unavailable")
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        shot = sct.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        monitor_info = {
            "left": int(monitor.get("left") or 0),
            "top": int(monitor.get("top") or 0),
            "width": int(monitor.get("width") or 0),
            "height": int(monitor.get("height") or 0),
        }
    return image, monitor_info
