"""Discord webhook notifications (room codes / bot status). Never raises: a failed
post is printed and ignored so the bot keeps playing."""
from __future__ import annotations
import datetime, io, json, os, time, tomllib, urllib.request, uuid

_CFG = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "discord.toml")


def _urls():
    try:
        with open(_CFG, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


NAME = "랜다2 기어봇"
# status colour by the leading emoji of the message
COLOURS = {"▶": 0x2ECC71, "🎮": 0x3498DB, "🏁": 0x9B59B6, "⏸": 0xF1C40F, "⏹": 0x95A5A6,
           "■": 0x95A5A6, "⚠": 0xE67E22, "⛔": 0xE74C3C}


def _post(url, content, png=None, embed=None):
    """content -> plain message; embed -> card (png shown inside it as its image)."""
    if not url:
        return False
    try:
        payload = {"username": NAME}
        if embed is not None:
            if png is not None:
                embed["image"] = {"url": "attachment://screen.png"}
            payload["embeds"] = [embed]
        else:
            payload["content"] = content[:1900]
        if png is None:
            body = json.dumps(payload).encode()
            req = urllib.request.Request(url, body, {"Content-Type": "application/json",
                                                     "User-Agent": "rdom-bot"})
        else:
            b = uuid.uuid4().hex
            parts = [f"--{b}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                     f"Content-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n".encode(),
                     f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"screen.png\"\r\n"
                     f"Content-Type: image/png\r\n\r\n".encode(), png, f"\r\n--{b}--\r\n".encode()]
            req = urllib.request.Request(url, b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={b}",
                                                                "User-Agent": "rdom-bot"})
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception as e:
        print("discord post failed:", e, flush=True)
        return False


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def send_code(content):
    return _post(_urls().get("code_webhook"), content)


def send_room_code(code):
    """Big, copyable room code card (the Discord bot deletes the previous one)."""
    embed = {"title": "🎲 새 방이 열렸어요", "color": 0x5865F2,
             "description": f"## `{code}`\n친구와 하기 → 코드 입력으로 들어오세요",
             "footer": {"text": "협동 · 기어덱"}, "timestamp": _now_iso()}
    return _post(_urls().get("code_webhook"), "", embed=embed)


_tag = ""


def set_tag(tag):
    """Profile tag ("[기어]") put after the leading emoji of every later status message."""
    global _tag
    _tag = tag or ""


def _tagged(content):
    if not _tag:
        return content
    # AI-NOTE: the emoji (first char) stays first so the colour lookup and the card layout don't change.
    return f"{content[:1]} {_tag}{content[1:]}" if content[1:2] == " " else f"{content[:1]} {_tag} {content[1:]}"


def send_status(content, frame_rgb=None):
    content = _tagged(content)
    png = None
    if frame_rgb is not None:
        try:
            import cv2
            small = cv2.resize(frame_rgb, None, fx=0.4, fy=0.4)
            ok, buf = cv2.imencode(".png", cv2.cvtColor(small, cv2.COLOR_RGB2BGR)); png = buf.tobytes() if ok else None
        except Exception:
            png = None
    head, _, rest = content.partition("\n")
    embed = {"description": f"**{head}**" + (f"\n{rest}" if rest else ""),
             "color": COLOURS.get(content[:1], 0x99AAB5), "timestamp": _now_iso()}
    return _post(_urls().get("status_webhook"), content, png, embed=embed)
