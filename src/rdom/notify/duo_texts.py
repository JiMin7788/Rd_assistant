"""Discord texts and small pure helpers for duo / solo / gear-only mode (rdF04, spec R15; solo rdT17).

Import-safe and pure: no Discord, no tools/discord_bot.py. The bot passes in whether the supervisor
runs, so this module never touches pids itself. Gear-only texts are today's production texts.
Solo ("한 창 모드", rdT17): the supervisor found only one game window; that bot invites the other account.
"""
from __future__ import annotations
import json, os

DUO_BLOCK = "지금은 봇 두 대가 같이 플레이 중이라 참가할 수 없어요"
DUO_CARD_TITLE = "🤖 봇 두 대가 같이 플레이 중"
DUO_STATUS = "🟢 실행 중 · 🤖 두 봇 (기어1=구글 대변먹는자 · 서폿=구글 배속봇)"
DUO_ROOM_LINE = "🤖 봇 두 대가 같이 플레이 중"
SHOT_CONTENT = "기어1(구글) · 서폿(구글)"
START_HELP = "`/시작` 켜기 (둘 다 · 기어만)"

START_REPLY = {"duo": "▶ 두 봇을 켭니다. (기어1=구글 대변먹는자 · 서폿=구글 배속봇)",
               "gear": "▶ 기어봇만 켭니다. (구글 · 방 코드 공개 + 예약)"}

SOLO_BLOCK = "지금은 봇이 친구를 초대해서 플레이 중이라 참가할 수 없어요"
SOLO_TITLE = "🤖 봇이 친구를 초대해서 플레이 중"
_SOLO_LABEL = {"gpg": "기어1", "gpg2": "서폿"}

_GPG, _GPG2 = "config/recorder.toml", "config/recorder_gpg2.toml"
_ROOM_LINES = {"waiting": "🚪 방 열림 · 참가자 대기 중", "playing": "🎮 게임 진행 중",
               "closed": "⏳ 다음 방 준비 중", "off": "방 없음"}


def _bot_mode(data_dir):
    try:
        with open(os.path.join(data_dir, "bot_mode.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def mode_now(data_dir, supervisor_alive):
    """'duo' | 'solo' | 'gear' | 'off' from data/bot_mode.json; 'off' when the supervisor is not alive."""
    if not supervisor_alive:
        return "off"
    mode = _bot_mode(data_dir).get("mode")
    return mode if mode in ("duo", "solo", "gear") else "off"


def solo_now(data_dir):
    """{'profile', 'name', 'partner'} of the solo bot from data/bot_mode.json, None outside solo."""
    doc = _bot_mode(data_dir)
    solo = doc.get("solo")
    return solo if doc.get("mode") == "solo" and isinstance(solo, dict) else None


def solo_start_text(name, partner):
    """The one line the supervisor logs/sends (and run_all prints) when it chose solo mode."""
    return f"▶ 한 창 모드: {name} 혼자 -- {partner} 초대"


def solo_status(solo):
    """'🤖 한 창 모드 (서폿=구글 배속봇, 대변먹는자 초대)'; without bot_mode details just '🤖 한 창 모드'."""
    if not solo:
        return "🤖 한 창 모드"
    label = _SOLO_LABEL.get(solo.get("profile"), solo.get("profile"))
    return f"🤖 한 창 모드 ({label}=구글 {solo.get('name')}, {solo.get('partner')} 초대)"


def reserve_blocked(mode):
    return {"duo": DUO_BLOCK, "solo": SOLO_BLOCK}.get(mode)


def code_reply(mode, room, queue_busy):
    """/방코드 reply text."""
    if mode in ("duo", "solo"):
        return reserve_blocked(mode)
    if room.get("state") != "waiting" or not room.get("code"):
        return {"playing": "🎮 지금은 게임 중이에요. `/예약` 하면 다음 차례에 DM으로 알려드려요.",
                "off": "⚫ 봇이 꺼져 있어요."}.get(room.get("state"), "⏳ 다음 방 준비 중이에요. `/예약` 으로 줄서기")
    if queue_busy:
        return "🔒 지금은 예약자 차례예요. `/예약` 으로 줄서면 차례에 DM으로 코드를 보내드려요."
    return f"🎲 방 코드: **`{room['code']}`** (친구와 하기 → 코드 입력)"


def card_for(mode, state, n):
    """(title, description) of the duo / solo card in the room-code channel, None otherwise."""
    if mode not in ("duo", "solo"):
        return None
    return DUO_CARD_TITLE if mode == "duo" else SOLO_TITLE, f"지금은 참가할 수 없어요\n대기 {n}명"


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


def status_title(mode, paused, stopping, solo=None):
    """solo: the solo_now() dict (which window plays, whom it invites)."""
    st = {"duo": DUO_STATUS, "solo": "🟢 실행 중 · " + solo_status(solo),
          "gear": "🟢 실행 중"}.get(mode, "⚫ 꺼짐")
    if paused:
        st += " · ⏸ 일시정지(판 사이 대기)"
    if stopping:
        st += " · ⏹ 종료 예약"
    return st


def room_line(mode, state):
    if mode == "duo":
        return DUO_ROOM_LINE
    if mode == "solo":
        return SOLO_TITLE
    return _ROOM_LINES.get(state, "")


def presence(mode, n, q):
    """Activity text. q is the ' · 대기 N명' suffix (gear only; duo/solo have no reservations)."""
    if mode == "duo":
        return f"랜다2 봇 두 대 · 오늘 {n}판"
    if mode == "solo":
        return f"랜다2 한 창 모드 · 오늘 {n}판"
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


def screens_for(mode, solo=None):
    """[(tag, recorder config, file name)] to capture for /스샷. solo: the solo_now() dict."""
    if mode == "duo":
        return [("[기어1]", _GPG, "gear.jpg"), ("[서폿]", _GPG2, "support.jpg")]
    # AI-NOTE: solo has one window open; capturing the closed one would fail the whole /스샷.
    if mode == "solo" and (solo or {}).get("profile") == "gpg2":
        return [("[서폿]", _GPG2, "support.jpg")]
    # AI-NOTE: gear-only (and off) show the first GPG window, the only window that bot uses.
    return [("[기어1]", _GPG, "screen.jpg")]
