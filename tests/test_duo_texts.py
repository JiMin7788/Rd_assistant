"""rdf04-t11: Discord texts for duo / gear-only mode (pure module; discord_bot.py is only read as text)."""
import json
import os

from rdom.notify import duo_texts as d

BOT = os.path.join(os.path.dirname(__file__), "..", "tools", "discord_bot.py")


def _mode_file(tmp_path, mode):
    (tmp_path / "bot_mode.json").write_text(json.dumps({"mode": mode, "bots": []}), encoding="utf-8")


def test_mode_now(tmp_path):
    assert d.mode_now(str(tmp_path), True) == "off"            # no file
    _mode_file(tmp_path, "duo")
    assert d.mode_now(str(tmp_path), True) == "duo"
    assert d.mode_now(str(tmp_path), False) == "off"           # dead supervisor pid
    _mode_file(tmp_path, "gear")
    assert d.mode_now(str(tmp_path), True) == "gear"
    (tmp_path / "bot_mode.json").write_text("{broken", encoding="utf-8")
    assert d.mode_now(str(tmp_path), True) == "off"
    _mode_file(tmp_path, "weird")
    assert d.mode_now(str(tmp_path), True) == "off"


def test_exact_spec_texts():
    assert d.DUO_BLOCK == "지금은 봇 두 대가 같이 플레이 중이라 참가할 수 없어요"
    assert d.start_reply("duo") == "▶ 두 봇을 켭니다. (기어1=구글 대변먹는자 · 기어2=구글 배속봇)"
    assert d.start_reply("gear") == "▶ 기어봇만 켭니다. (구글 · 방 코드 공개 + 예약)"
    assert d.stop_reply("duo") == "⏹ 지금 판이 끝나면 두 봇 모두 종료합니다."
    assert d.stop_reply("gear") == "⏹ 지금 판이 끝나면 봇을 종료합니다."
    assert d.pause_reply("duo") == "⏸ 지금 판이 끝나면 두 봇 모두 일시정지합니다. (/재개 로 재개)"
    assert d.pause_reply("gear") == "⏸ 지금 판이 끝나면 일시정지합니다. (/재개 로 재개)"
    assert d.status_title("duo", False, False) == "🟢 실행 중 · 🤖 두 봇 (기어1=구글 대변먹는자 · 기어2=구글 배속봇)"
    assert d.status_title("duo", True, True).endswith(" · ⏸ 일시정지(판 사이 대기) · ⏹ 종료 예약")
    assert d.status_title("gear", False, False) == "🟢 실행 중"
    assert d.status_title("off", False, False) == "⚫ 꺼짐"
    assert d.room_line("duo", "playing") == "🤖 봇 두 대가 같이 플레이 중"
    assert d.room_line("gear", "playing") == "🎮 게임 진행 중"
    assert d.presence("duo", 3, "") == "랜다2 봇 두 대 · 오늘 3판"
    assert d.presence("gear", 3, " · 대기 2명") == "랜다2 협동 · 오늘 3판 · 대기 2명"
    assert d.presence("off", 3, "") == "꺼짐"
    assert d.SHOT_CONTENT == "기어1(구글) · 기어2(구글)"
    assert d.START_HELP == "`/시작` 켜기 (둘 다 · 기어만)"


def test_code_and_reserve_duo_vs_gear():
    room = {"state": "waiting", "code": "12345"}
    assert d.code_reply("duo", room, False) == d.DUO_BLOCK
    assert d.code_reply("duo", {"state": "playing"}, True) == d.DUO_BLOCK
    assert d.code_reply("gear", room, False) == "🎲 방 코드: **`12345`** (친구와 하기 → 코드 입력)"
    assert d.code_reply("gear", room, True).startswith("🔒 지금은 예약자 차례예요.")
    assert d.code_reply("gear", {"state": "playing"}, False).startswith("🎮 지금은 게임 중이에요.")
    assert d.code_reply("gear", {"state": "off"}, False) == "⚫ 봇이 꺼져 있어요."
    assert d.reserve_blocked("duo") == d.DUO_BLOCK
    assert d.reserve_blocked("gear") is None
    assert d.reserve_blocked("off") is None


def test_card_for():
    assert d.card_for("duo", "duo", 2) == ("🤖 봇 두 대가 같이 플레이 중", "지금은 참가할 수 없어요\n대기 2명")
    assert d.card_for("gear", "waiting", 2) is None


def test_log_blocks_both_headers_within_limit(tmp_path):
    a, b = tmp_path / "a_gear.log", tmp_path / "b_support.log"
    a.write_text("\n".join(f"gear line {i} " + "x" * 80 for i in range(100)), encoding="utf-8")
    b.write_text("\n".join(f"support line {i} " + "y" * 80 for i in range(100)), encoding="utf-8")
    out = d.log_blocks({"[기어]": str(a), "[서폿]": str(b)}, 60)
    assert len(out) <= 1900
    assert "[기어]" in out and "[서폿]" in out
    assert "gear line 99" in out and "support line 99" in out
    assert out.count("```") == 4


def test_log_blocks_missing_file_still_has_headers(tmp_path):
    out = d.log_blocks({"[기어]": None, "[서폿]": str(tmp_path / "nope.log")}, 5)
    assert "[기어]" in out and "[서폿]" in out and len(out) <= 1900


def test_screens_for():
    duo = d.screens_for("duo")
    assert [(t, f) for t, _c, f in duo] == [("[기어1]", "gear.jpg"), ("[기어2]", "gear2.jpg")]
    assert duo[0][1] == "config/recorder.toml" and duo[1][1] == "config/recorder_gpg2.toml"
    gear = d.screens_for("gear")
    assert len(gear) == 1 and gear[0][1] == "config/recorder.toml"


def test_discord_bot_source_uses_duo_texts():
    src = open(BOT, encoding="utf-8").read()
    assert 'app_commands.Choice(name="둘 다", value="duo")' in src
    assert 'app_commands.Choice(name="기어만", value="gear")' in src
    assert '"--mode", target' in src
    for name in ("duo_texts.reserve_blocked", "duo_texts.code_reply", "duo_texts.card_for", "duo_texts.log_blocks",
                 "duo_texts.screens_for", "duo_texts.start_reply", "duo_texts.stop_reply", "duo_texts.pause_reply",
                 "duo_texts.status_title", "duo_texts.room_line", "duo_texts.presence", "duo_texts.START_HELP"):
        assert name in src, name
    # /예약 returns the duo block before it takes the queue lock; tick() returns before any queue work
    reserve = src[src.index("async def cmd_reserve"):]
    assert reserve.index("reserve_blocked") < reserve.index("async with QLOCK")
    tick = src[src.index("async def tick()"):]
    assert tick.index('== "duo"') < tick.index("Q[\"queue\"].pop")
