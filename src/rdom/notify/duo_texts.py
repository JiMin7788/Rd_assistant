"""Discord texts and small pure helpers for duo / gear-only mode (rdF04, spec R15).

Import-safe and pure: no Discord, no tools/discord_bot.py. The bot passes in whether the supervisor
runs, so this module never touches pids itself. Gear-only texts are today's production texts.
"""
from __future__ import annotations
import json, os

DUO_BLOCK = "지금은 봇 두 대가 같이 플레이 중이라 참가할 수 없어요"
DUO_CARD_TITLE = "🤖 봇 두 대가 같이 플레이 중"
DUO_STATUS = "🟢 실행 중 · 🤖 두 봇 (기어1=구글 대변먹는자 · 기어2=구글 배속봇)"
DUO_ROOM_LINE = "🤖 봇 두 대가 같이 플레이 중"
SHOT_CONTENT = "기어1(구글) · 기어2(구글)"
START_HELP = "`/시작` 켜기 (둘 다 · 기어만)"

START_REPLY = {"duo": "▶ 두 봇을 켭니다. (기어1=구글 대변먹는자 · 기어2=구글 배속봇)",
               "gear": "▶ 기어봇만 켭니다. (구글 · 방 코드 공개 + 예약)"}

_GPG, _GPG2 = "config/recorder.toml", "config/recorder_gpg2.toml"
_ROOM_LINES = {"waiting": "🚪 방 열림 · 참가자 대기 중", "playing": "🎮 게임 진행 중",
               "closed": "⏳ 다음 방 준비 중", "off": "방 없음"}


def mode_now(data_dir, supervisor_alive):
    """'duo' | 'gear' | 'off' from data/bot_mode.json; 'off' when the supervisor is not alive."""
    if not supervisor_alive:
        return "off"
    try:
        with open(os.path.join(data_dir, "bot_mode.json"), encoding="utf-8") as fh:
            mode = json.load(fh).get("mode")
    except (OSError, ValueError, AttributeError):
        return "off"
    return mode if mode in ("duo", "gear") else "off"


def reserve_blocked(mode):
    return DUO_BLOCK if mode == "duo" else None


def code_reply(mode, room, queue_busy):
    """/방코드 reply text."""
    if mode == "duo":
        return DUO_BLOCK
    if room.get("state") != "waiting" or not room.get("code"):
        return {"playing": "🎮 지금은 게임 중이에요. `/예약` 하면 다음 차례에 DM으로 알려드려요.",
                "off": "⚫ 봇이 꺼져 있어요."}.get(room.get("state"), "⏳ 다음 방 준비 중이에요. `/예약` 으로 줄서기")
    if queue_busy:
        return "🔒 지금은 예약자 차례예요. `/예약` 으로 줄서면 차례에 DM으로 코드를 보내드려요."
    return f"🎲 방 코드: **`{room['code']}`** (친구와 하기 → 코드 입력)"


def card_for(mode, state, n):
    """(title, description) of the duo card in the room-code channel, None outside duo."""
    if mode != "duo":
        return None
    return DUO_CARD_TITLE, f"지금은 참가할 수 없어요\n대기 {n}명"


def start_reply(target):
    return START_REPLY.get(target, START_REPLY["duo"])


def stop_reply(mode):
    if mode == "duo":
        return "⏹ 지금 판이 끝나면 두 봇 모두 종료합니다."
    return "⏹ 지금 판이 끝나면 봇을 종료합니다."


def pause_reply(mode):
    if mode == "duo":
        return "⏸ 지금 판이 끝나면 두 봇 모두 일시정지합니다. (/재개 로 재개)"
    return "⏸ 지금 판이 끝나면 일시정지합니다. (/재개 로 재개)"


def status_title(mode, paused, stopping):
    st = {"duo": DUO_STATUS, "gear": "🟢 실행 중"}.get(mode, "⚫ 꺼짐")
    if paused:
        st += " · ⏸ 일시정지(판 사이 대기)"
    if stopping:
        st += " · ⏹ 종료 예약"
    return st


def room_line(mode, state):
    if mode == "duo":
        return DUO_ROOM_LINE
    return _ROOM_LINES.get(state, "")


def presence(mode, n, q):
    """Activity text. q is the ' · 대기 N명' suffix (gear only; duo has no reservations)."""
    if mode == "duo":
        return f"랜다2 봇 두 대 · 오늘 {n}판"
    if mode == "gear":
        return f"랜다2 협동 · 오늘 {n}판{q}"
    return "꺼짐"


def log_blocks(paths_by_tag, lines, limit=1900):
    """One message: per tag a header line and a code block with the last `lines` lines, <= limit chars."""
    if not paths_by_tag:
        return "로그가 없어요."
    share = limit // len(paths_by_tag)
    parts = []
    for tag, path in paths_by_tag.items():
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                tail = [l for l in fh.read().splitlines() if l.strip()][-max(1, lines):]
        except (OSError, TypeError):
            tail = ["(로그 없음)"]
        head = f"{tag}\n```"
        room = max(0, share - len(head) - len("```") - 1)    # -1: the "\n" between blocks
        body = "\n".join(tail)
        body = body[-room:] if room else ""
        parts.append(f"{head}{body}```")
    return "\n".join(parts)[:limit]


def screens_for(mode):
    """[(tag, recorder config, file name)] to capture for /스샷."""
    if mode == "duo":
        return [("[기어1]", _GPG, "gear.jpg"), ("[기어2]", _GPG2, "gear2.jpg")]
    # AI-NOTE: gear-only (and off) show the first GPG window, the only window that bot uses.
    return [("[기어1]", _GPG, "screen.jpg")]
