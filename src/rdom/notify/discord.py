"""Discord webhook notifications (room codes / bot status). Never raises: a failed
post is printed and ignored so the bot keeps playing."""
from __future__ import annotations
import io, json, os, time, tomllib, urllib.request, uuid

_CFG = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "discord.toml")


def _urls():
    try:
        with open(_CFG, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _post(url, content, png=None):
    if not url:
        return False
    try:
        if png is None:
            body = json.dumps({"content": content[:1900]}).encode()
            req = urllib.request.Request(url, body, {"Content-Type": "application/json",
                                                     "User-Agent": "rdom-bot"})
        else:
            b = uuid.uuid4().hex
            parts = [f"--{b}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                     f"Content-Type: application/json\r\n\r\n{json.dumps({'content': content[:1900]})}\r\n".encode(),
                     f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"screen.png\"\r\n"
                     f"Content-Type: image/png\r\n\r\n".encode(), png, f"\r\n--{b}--\r\n".encode()]
            req = urllib.request.Request(url, b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={b}",
                                                                "User-Agent": "rdom-bot"})
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception as e:
        print("discord post failed:", e, flush=True)
        return False


def send_code(content):
    return _post(_urls().get("code_webhook"), content)


def send_status(content, frame_rgb=None):
    png = None
    if frame_rgb is not None:
        try:
            import cv2
            small = cv2.resize(frame_rgb, None, fx=0.4, fy=0.4)
            ok, buf = cv2.imencode(".png", cv2.cvtColor(small, cv2.COLOR_RGB2BGR)); png = buf.tobytes() if ok else None
        except Exception:
            png = None
    return _post(_urls().get("status_webhook"), f"[{time.strftime('%H:%M')}] {content}", png)
