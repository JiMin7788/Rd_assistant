"""gear_loop roles (rdf04-t8): exit codes, role phases, per-bot records, tagged status. Fakes only:
no window, no input, no network; STOP/PAUSE and the record files live in a tmp dir."""
import importlib
import os
import json
import sys
import types

import pytest

from rdom import profile as profiles
from rdom.input import coop_join, friend_coop
from rdom.input.friend_coop import invite_and_start as REAL_INVITE_AND_START
from rdom.input.inject import SPEED_UV
import rdom.notify.discord as discord


@pytest.fixture
def gl(monkeypatch):
    """tools.gear_loop imported (and dropped from sys.modules again: other tests assert it was never
    imported), with every live entry point replaced by a fake. Returns the module; env in gl.env."""
    for n in ("tools.gear_loop", "gear_loop"):
        monkeypatch.delitem(sys.modules, n, raising=False)
    mod = importlib.import_module("tools.gear_loop")
    sys.modules.pop("tools.gear_loop", None)
    return mod


class FakeG:
    def __init__(self, moved=False):
        self.moved, self.closed, self.grabs = moved, 0, 0

    def grab(self):
        self.grabs += 1
        return "frame"

    def window_moved(self):
        return self.moved

    def close(self):
        self.closed += 1


class FakeInj:
    execute = True

    def __init__(self):
        self.taps = []

    def tap(self, u, v):
        self.taps.append((u, v))


class Player:
    stats = {"merges": 4, "fails": 1, "support": 2, "complete": True}


@pytest.fixture
def env(gl, monkeypatch, tmp_path):
    """Wire gl to fakes. env.state['battle'] is what is_battle returns; env.stop_after_battle
    makes run_battle create data/STOP so the loop ends after one battle."""
    e = types.SimpleNamespace(g=FakeG(), inj=FakeInj(), status=[], rooms=[], checks=[], injectors=[],
                              grabbers=[], battles=[], state={"battle": False},
                              stop_after_battle=True, battle_res="timeout", gl=gl,
                              stop=tmp_path / "STOP", pause=tmp_path / "PAUSE")
    monkeypatch.setattr(gl, "STOP", str(e.stop))
    monkeypatch.setattr(gl, "PAUSE", str(e.pause))
    monkeypatch.setattr(gl, "GEAR_LOG", str(tmp_path / "gear_rounds.jsonl"))
    monkeypatch.setattr(gl, "JOINER_LOG", str(tmp_path / "joiner_rounds.jsonl"))
    monkeypatch.setattr(gl.time, "sleep", lambda s: None)
    monkeypatch.setattr(friend_coop, "COOP_DEBUG_DIR", str(tmp_path / "coop_debug"))   # never write data/
    monkeypatch.setattr(gl, "send_status", lambda text, frame=None: e.status.append((text, frame)))
    monkeypatch.setattr(gl, "write_room", lambda code, state: e.rooms.append((code, state)))
    monkeypatch.setattr(gl.discord, "set_tag", lambda t: e.status.append(("tag", t)))
    monkeypatch.setattr(gl.preflight, "check",
                        lambda names, **k: e.checks.append(list(names)) or [(n, True, "ok") for n in names])

    def make_grabber(config=None):
        e.grabbers.append(config)
        return e.g
    monkeypatch.setattr(gl, "LiveGrabber", make_grabber)
    monkeypatch.setattr(gl, "make_injector",
                        lambda cfg, execute=False: e.injectors.append((cfg, execute)) or e.inj)
    monkeypatch.setattr(gl, "leave_result_screen", lambda f, g, inj: f)
    e.real_recover = gl.recover_step
    monkeypatch.setattr(gl, "recover_step", lambda f, g, inj, prof: (f, False))
    monkeypatch.setattr(gl, "is_battle", lambda f: e.state["battle"])
    monkeypatch.setattr(gl, "read_speed", lambda f: 2.0 if e.inj.taps else 1.0)   # the 배속 tap takes
    monkeypatch.setattr(gl, "gear", types.SimpleNamespace(reload_if_changed=lambda: None))
    monkeypatch.setattr(gl, "support", types.SimpleNamespace(reload_if_changed=lambda: None))
    monkeypatch.setattr(gl.gear_bot, "SUPPORT_SCALES", gl.gear_bot.SUPPORT_SCALES)   # restored at teardown

    def run_battle(g, inj, **kw):
        e.battles.append(kw)
        if e.stop_after_battle:
            e.stop.write_text("")
        e.state["battle"] = False
        if e.battle_res == "wrong_deck":
            return "wrong_deck", None
        return e.battle_res, Player
    monkeypatch.setattr(gl.support_bot, "run_battle", run_battle)

    def partner(*a, **k):                       # the lobby partner logic: the battle begins
        e.state["battle"] = True
        return True
    monkeypatch.setattr(gl, "open_room_and_wait", partner)
    monkeypatch.setattr(friend_coop, "invite_and_start", partner)
    e.real_wait = coop_join.wait_and_accept
    monkeypatch.setattr(coop_join, "wait_and_accept", lambda *a, **k: partner() and "battle")
    return e


class DeadGameInj(FakeInj):
    """The game is closed and never comes back."""
    def __init__(self):
        super().__init__(); self.launches = 0

    def game_in_front(self):
        return False

    def launch_game(self):
        self.launches += 1


def _dead_game(env, monkeypatch):
    env.inj = DeadGameInj()
    gl = env.gl
    for n in ("has_popup_close", "has_modal_x", "network_error", "is_exit_dialog"):
        monkeypatch.setattr(gl, n, lambda f: False)
    monkeypatch.setattr(gl, "is_lobby", lambda f: True)         # ends the post-launch wait at once
    monkeypatch.setattr(gl, "recover_step", env.real_recover)


def test_joiner_whose_game_cannot_start_ends_in_guard(env, monkeypatch):
    _dead_game(env, monkeypatch)
    monkeypatch.setattr(coop_join.board, "is_battle", lambda f: False)
    monkeypatch.setattr(coop_join.invite, "invite_popup", lambda f: None)
    monkeypatch.setattr(coop_join.invite, "joined_room", lambda f: False)
    monkeypatch.setattr(coop_join, "wait_and_accept",
                        lambda *a, **k: env.real_wait(*a, sleep=lambda s: None, **k))
    assert env.gl.main(["--role", "joiner"]) == 3
    assert ("⛔ 초대 수락 후 판이 3회 연속 시작되지 않음 -- 정지. 화면 확인 필요", "frame") in env.status
    assert env.inj.launches == 6 and env.battles == []          # 2 per round, 3 rounds


def test_round_start_give_up_is_a_failed_round(env, monkeypatch):
    _dead_game(env, monkeypatch)
    calls = []
    monkeypatch.setattr(env.gl, "lobby_phase", lambda *a: calls.append(a) or "ok")
    assert env.gl.main(["--profile", "ld", "--role", "inviter"]) == 3
    assert calls == [] and env.inj.launches == 6
    assert ("⛔ 배속봇 초대 3회 연속 실패 -- 정지. 화면 확인 필요", "frame") in env.status


def test_recover_step_gives_up_after_three_backs(env, monkeypatch):
    class Inj(FakeInj):
        backs = 0
        def game_in_front(self): return True
        def back(self): self.backs += 1
    inj = Inj()
    for n in ("has_popup_close", "has_modal_x", "network_error", "is_exit_dialog", "is_lobby", "is_game_over",
              "is_coop_room", "is_friend_menu"):
        monkeypatch.setattr(env.gl, n, lambda f: False)
    f, gave_up = env.real_recover("frame", env.g, inj, profiles.get("ld"))
    assert gave_up is True and inj.backs == 3


def _unknown_screen(env, monkeypatch):
    class Inj(FakeInj):
        backs = 0
        def game_in_front(self): return True
        def back(self): self.backs += 1
    for n in ("has_popup_close", "has_modal_x", "network_error", "is_exit_dialog", "is_lobby", "is_game_over",
              "is_coop_room", "is_friend_menu"):
        monkeypatch.setattr(env.gl, n, lambda f: False)
    monkeypatch.setattr(env.gl, "recover_step", env.real_recover)
    return Inj()


def test_joiner_recover_stops_before_any_tap_on_an_invite_popup(env, monkeypatch):
    inj = _unknown_screen(env, monkeypatch)
    monkeypatch.setattr(coop_join.invite, "invite_popup", lambda f: {"x": 1})
    assert env.gl._joiner_recover("frame", env.g, inj, profiles.get("gpg")) is False
    assert inj.backs == 0 and inj.taps == [] and env.g.grabs == 0


def test_joiner_recover_stops_on_stop_file(env, monkeypatch):
    inj = _unknown_screen(env, monkeypatch)
    monkeypatch.setattr(coop_join.invite, "invite_popup", lambda f: None)
    env.stop.write_text("")
    assert env.gl._joiner_recover("frame", env.g, inj, profiles.get("gpg")) is False
    assert inj.backs == 0 and env.g.grabs == 0


def test_joiner_recover_stops_when_an_invite_shows_during_the_unknown_wait(env, monkeypatch):
    inj = _unknown_screen(env, monkeypatch)
    shown = iter([None, {"x": 1}])
    monkeypatch.setattr(coop_join.invite, "invite_popup", lambda f: next(shown))
    assert env.gl._joiner_recover("frame", env.g, inj, profiles.get("gpg")) is False
    assert inj.backs == 0


def test_joiner_skips_round_start_recover(env, monkeypatch):
    monkeypatch.setattr(env.gl, "recover_step", lambda *a: (_ for _ in ()).throw(AssertionError("recover")))
    assert env.gl.main(["--role", "joiner"]) == 0
    assert len(env.battles) == 1


def texts(e):
    return [t for t, _ in e.status]


# ---- exit codes ----

@pytest.mark.parametrize("args", [["--profile", "ld", "--role", "inviter"], ["--role", "joiner"],
                                  ["--profile", "ld"]])
def test_stop_is_clean_and_the_file_stays(env, args):
    env.stop.write_text("")
    assert env.gl.main(args) == env.gl.EXIT_CLEAN == 0
    assert env.stop.exists()                       # the other bot must still see it
    assert "■ 봇 종료" in texts(env) and env.g.closed == 1 and env.battles == []


def test_window_moved_is_guard(env):
    env.g.moved = True
    assert env.gl.main(["--role", "joiner"]) == env.gl.EXIT_GUARD == 3
    assert ("⛔ 에뮬레이터 창이 움직여서 정지", "frame") in env.status
    assert "■ 봇 종료" not in texts(env)


@pytest.mark.parametrize("args,text", [
    (["--profile", "ld", "--role", "inviter"], "⛔ 배속봇 초대 3회 연속 실패 -- 정지. 화면 확인 필요"),
    (["--role", "joiner"], "⛔ 초대 수락 후 판이 3회 연속 시작되지 않음 -- 정지. 화면 확인 필요"),
    (["--profile", "ld"], "⛔ 방 만들기 3회 연속 실패 -- 정지. 화면 확인 필요"),
])
def test_three_failed_rounds_is_guard(env, monkeypatch, args, text):
    calls = []
    monkeypatch.setattr(env.gl, "lobby_phase", lambda *a: calls.append(a) or "fail")
    assert env.gl.main(args) == 3
    assert len(calls) == 3 and (text, "frame") in env.status


def test_failed_round_counter_resets_after_a_battle(env, monkeypatch):
    results = iter(["fail", "fail", "ok", "fail", "fail", "stop"])
    def lobby(*a):
        r = next(results)
        env.state["battle"] = r == "ok"
        return r
    monkeypatch.setattr(env.gl, "lobby_phase", lobby)
    env.stop_after_battle = False
    assert env.gl.main(["--profile", "ld", "--role", "inviter"]) == 0


@pytest.mark.parametrize("profile,text", [
    ("ld", "⛔ 기어덱이 아니에요 -- 덱 확인 후 다시 시작해 주세요"),
    ("gpg", "⛔ 기어덱이 아니에요 -- 덱 확인 후 다시 시작해 주세요"),
])
def test_wrong_deck_is_guard_without_further_input(env, capsys, profile, text):
    env.battle_res = "wrong_deck"
    assert env.gl.main(["--profile", profile, "--role", "joiner" if profile == "gpg" else "inviter"]) == 3
    assert (text, "frame") in env.status
    # only the 배속 tap before the deck was seen (rdT12: every role taps 배속)
    assert env.inj.taps == [SPEED_UV]
    assert env.battles[0]["expect"] == "gear"
    assert f"wrong deck: expected gear" in capsys.readouterr().out
    assert not (env.stop.parent / "gear_rounds.jsonl").exists()
    assert not (env.stop.parent / "joiner_rounds.jsonl").exists()


def test_support_joiner_expects_a_support_deck(env, capsys):
    """gpg2 is the support joiner: run_battle gets expect='support' + the duo support player, a gear deck stops it."""
    env.battle_res = "wrong_deck"
    assert env.gl.main(["--profile", "gpg2", "--role", "joiner"]) == 3
    assert env.battles[0]["expect"] == "support"
    assert env.battles[0]["support_play"] is env.gl._duo_support_play
    assert ("⛔ 서포팅덱이 아니에요 -- 덱 확인 후 다시 시작해 주세요", "frame") in env.status
    assert "wrong deck: expected support" in capsys.readouterr().out
    assert env.inj.taps == [SPEED_UV]
    assert not (env.stop.parent / "joiner_rounds.jsonl").exists()


def test_start_check_failure_is_guard_before_any_injector(env, capsys):
    env.gl.preflight.check = lambda names, **k: env.checks.append(list(names)) or [
        (names[0], False, "LD플레이어 창을 못 찾았어요")]
    assert env.gl.main(["--profile", "ld", "--role", "inviter"]) == 3
    assert "⛔ 시작 점검 실패: LD플레이어 창을 못 찾았어요" in texts(env)
    assert env.injectors == [] and env.grabbers == []
    assert "start check: FAIL LD플레이어 창을 못 찾았어요" in capsys.readouterr().out


def test_start_check_covers_the_own_window_and_the_pair_for_the_inviter(env):
    env.stop.write_text("")
    env.gl.main(["--profile", "gpg", "--role", "inviter"])
    env.gl.main(["--profile", "gpg2", "--role", "joiner"])
    env.gl.main(["--profile", "ld"])
    assert env.checks == [["gpg", "gpg2"], ["gpg2"], ["ld"]]


@pytest.mark.parametrize("raiser", ["lobby", "battle"])
def test_exception_is_a_crash_not_an_exit_code(env, monkeypatch, raiser):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(env.gl, "lobby_phase" if raiser == "lobby" else "battle_phase", boom)
    env.state["battle"] = raiser == "battle"
    with pytest.raises(RuntimeError):
        env.gl.main(["--profile", "ld", "--role", "inviter"])
    assert env.g.closed == 1


# ---- arguments, injector, tag ----

def test_main_builds_injector_from_profile_and_execute(env):
    env.stop.write_text("")
    env.gl.main(["--profile", "ld", "--role", "inviter"])
    env.gl.main(["--role", "joiner", "--execute"])
    cfgs = [os.path.join(env.gl.ROOT, profiles.get(n).config) for n in ("ld", "gpg")]
    assert env.injectors == [(cfgs[0], False), (cfgs[1], True)]
    assert env.grabbers == cfgs


def test_default_is_gpg_public_dry_run(env):
    env.stop.write_text("")
    env.gl.main([])
    assert env.checks == [["gpg"]]
    assert env.injectors == [(os.path.join(env.gl.ROOT, profiles.get("gpg").config), False)]


def test_tag_set_at_start_and_ld_scales(env):
    env.stop.write_text("")
    env.gl.main(["--profile", "ld"])
    assert env.status[0] == ("tag", "[기어]")
    assert env.gl.gear_bot.SUPPORT_SCALES == env.gl.gear_bot.LD_SUPPORT_SCALES
    env.gl.gear_bot.SUPPORT_SCALES = None
    env.gl.main(["--profile", "gpg2", "--role", "joiner"])
    assert ("tag", "[서폿]") in env.status and env.gl.gear_bot.SUPPORT_SCALES is None


def test_duo_config_file():
    from tools.gear_loop import load_duo   # noqa: F401  (import-safe, see test_gear_loop_result)
    sys.modules.pop("tools.gear_loop", None)
    d = load_duo()
    assert (d["host"], d["partner"], d["invite_wait_s"]) == ("대변먹는자", "배속봇", 300)


# ---- roles ----

def test_joiner_uses_wait_and_accept_with_recover_step(env, monkeypatch):
    seen = {}
    def wait(g, inj, host, stop, recover, **k):
        seen.update(host=host, stop=stop, recover=recover); return "stopped"
    monkeypatch.setattr(coop_join, "wait_and_accept", wait)
    def forbidden(*a, **k):
        raise AssertionError("joiner must not create or invite")
    monkeypatch.setattr(env.gl, "open_room_and_wait", forbidden)
    monkeypatch.setattr(friend_coop, "invite_and_start", forbidden)
    assert env.gl.main(["--role", "joiner"]) == 0
    assert seen["host"] == "대변먹는자" and seen["stop"] is env.gl.should_stop
    rec = seen["recover"]
    assert rec.func is env.gl._joiner_recover
    assert rec.keywords == {"g": env.g, "inj": env.inj, "prof": profiles.get("gpg")}


def test_inviter_invites_the_partner_from_duo_toml(env, monkeypatch):
    seen = {}
    def invite(g, inj, name, wait_s, stop, uv=None):
        seen.update(name=name, wait_s=wait_s, stop=stop, uv=uv); return "stopped"
    monkeypatch.setattr(friend_coop, "invite_and_start", invite)
    monkeypatch.setattr(env.gl, "open_room_and_wait", lambda *a, **k: 1 / 0)
    assert env.gl.main(["--profile", "ld", "--role", "inviter"]) == 0
    assert (seen["name"], seen["wait_s"], seen["stop"]) == ("배속봇", 300, env.gl.should_stop)
    assert seen["uv"]["FRIEND"] == profiles.uv(profiles.get("ld"), "FRIEND_UV")


def test_public_creates_an_open_room(env, monkeypatch):
    monkeypatch.setattr(friend_coop, "invite_and_start", lambda *a, **k: 1 / 0)
    monkeypatch.setattr(coop_join, "wait_and_accept", lambda *a, **k: 1 / 0)
    assert env.gl.main(["--profile", "ld"]) == 0
    assert env.battles and env.rooms == [(None, "closed")]


def test_inviter_starts_from_a_coop_room_frame(env, monkeypatch):
    # recover_step ends on a coop room; the inviter must go on from there, not fail the round
    from rdom.perception import board
    taps = []
    inj = types.SimpleNamespace(tap=lambda u, v: taps.append((u, v)))
    for n, v in (("is_lobby", False), ("is_friend_menu", False), ("is_coop_room", True)):
        monkeypatch.setattr(board, n, lambda f, _v=v: _v)
    monkeypatch.setattr(friend_coop, "invite_and_start", REAL_INVITE_AND_START)
    monkeypatch.setattr(friend_coop, "start_ready", lambda f: True)
    prof, duo = profiles.get("ld"), {"host": "h", "partner": "p", "invite_wait_s": 5}
    assert env.gl.lobby_phase("inviter", env.g, inj, prof, duo) == "ok"
    assert taps == [profiles.uv(prof, "START_COOP_UV")]


def test_lobby_phase_results(env, monkeypatch):
    prof, duo = profiles.get("ld"), {"host": "h", "partner": "p", "invite_wait_s": 5}
    for inv, want in ((True, "ok"), (False, "fail"), (None, "fail"), ("stopped", "stop"), ("paused", "wait")):
        monkeypatch.setattr(friend_coop, "invite_and_start", lambda *a, _r=inv, **k: _r)
        assert env.gl.lobby_phase("inviter", env.g, env.inj, prof, duo) == want
    for acc, want in (("battle", "ok"), ("failed", "fail"), ("stopped", "stop"), ("paused", "wait")):
        monkeypatch.setattr(coop_join, "wait_and_accept", lambda *a, _r=acc, **k: _r)
        assert env.gl.lobby_phase("joiner", env.g, env.inj, prof, duo) == want
    for pub, want in ((True, "ok"), (False, "wait"), (None, "fail")):
        monkeypatch.setattr(env.gl, "open_room_and_wait", lambda *a, _r=pub, **k: _r)
        assert env.gl.lobby_phase("public", env.g, env.inj, prof, duo) == want


@pytest.mark.parametrize("args", [["--profile", "ld", "--role", "inviter"], ["--role", "joiner"], ["--profile", "ld"]])
def test_speed_tapped_once_per_battle_by_every_role(env, args):
    # rdT12: both duo bots use 배속 (each use raises the shared speed), so every role taps
    assert env.gl.main(args) == 0
    assert env.inj.taps.count(SPEED_UV) == 1 and len(env.battles) == 1


def test_inviter_resumed_battle_below_2x_is_tapped(env, monkeypatch):
    _speed_reads(monkeypatch, env.gl, [1.0, 2.0])
    assert env.gl.battle_phase("inviter", env.g, env.inj, profiles.get("gpg"), 1, tap_speed=False) == "ok"
    assert len(env.inj.taps) == 1



def test_joiner_unknown_screen_waits_15s_before_back_others_5s(env, monkeypatch):
    inj = _unknown_screen(env, monkeypatch)
    monkeypatch.setattr(coop_join.invite, "invite_popup", lambda f: None)
    sleeps = []
    monkeypatch.setattr(env.gl.time, "sleep", lambda s: sleeps.append(s))
    env.gl._joiner_recover("frame", env.g, inj, profiles.get("gpg"))
    assert sleeps[0] == 15.0 and env.gl.JOINER_UNKNOWN_WAIT_S == 15.0 and inj.backs >= 1
    sleeps.clear()
    env.real_recover("frame", env.g, _unknown_screen(env, monkeypatch), profiles.get("gpg"))
    assert sleeps[0] == 5.0


# ---- rdT07: 배속 confirm / resume, 로비로 가기 retry
def _speed_reads(monkeypatch, gl, seq):
    """read_speed returns the next value of seq (the last one repeats)."""
    it = iter(seq)
    last = [None]
    def rd(f):
        last[0] = next(it, last[0])
        return last[0]
    monkeypatch.setattr(gl, "read_speed", rd)


def test_speed_a_rise_does_not_stop_it_taps_until_2_0(env, monkeypatch, capsys):
    _speed_reads(monkeypatch, env.gl, [1.0, 1.5, 2.0, 1.0])   # before, tap 1 -> 1.5 (keep going), tap 2 -> 2.0
    assert env.gl.confirm_speed(env.g, env.inj, profiles.get("gpg"), tap_first=True) == 2.0
    assert len(env.inj.taps) == 2
    assert "배속 1.0 -> 2.0" in capsys.readouterr().out


def test_speed_already_2_0_is_not_tapped(env, monkeypatch, capsys):
    _speed_reads(monkeypatch, env.gl, [2.0])
    assert env.gl.confirm_speed(env.g, env.inj, profiles.get("gpg"), tap_first=True) == 2.0
    assert env.inj.taps == []
    assert "배속 2.0 -> 2.0" in capsys.readouterr().out


def test_speed_1_5_never_rising_taps_5_times_then_stops(env, monkeypatch, capsys):
    _speed_reads(monkeypatch, env.gl, [1.5])
    assert env.gl.confirm_speed(env.g, env.inj, profiles.get("gpg"), tap_first=True) == 1.5
    assert len(env.inj.taps) == env.gl.SPEED_TAPS_MAX == 5
    assert "배속 1.5 -> 1.5" in capsys.readouterr().out


def test_speed_tap_log_line_and_not_in_front(env, monkeypatch, capsys):
    _speed_reads(monkeypatch, env.gl, [1.0, 1.5, 2.0])
    env.inj.last_gesture_ok = True
    def tap(u, v):
        env.inj.taps.append((u, v))
        env.inj.last_gesture_ok = len(env.inj.taps) != 2     # tap 2 not confirmed in front
    env.inj.tap = tap
    env.gl.confirm_speed(env.g, env.inj, profiles.get("gpg"), tap_first=True)
    out = capsys.readouterr().out
    assert "  배속 tap 1/5: 1.0 -> 1.5 (front ok)" in out
    assert "  배속 tap 2/5: 1.5 -> 2.0 (NOT in front)" in out


def test_speed_frames_saved_to_patched_dir_and_capped(env, monkeypatch, tmp_path):
    import numpy as np
    d = tmp_path / "coop_debug"
    d.mkdir()
    for i in range(30):                                     # 30 old speed files already there
        (d / f"speed_gpg_20200101_000000_{i}.png").write_bytes(b"x")
        os.utime(d / f"speed_gpg_20200101_000000_{i}.png", (1000 + i, 1000 + i))
    monkeypatch.setattr(env.g, "grab", lambda: np.zeros((8, 8, 3), np.uint8))
    _speed_reads(monkeypatch, env.gl, [1.0, 1.5, 2.0])
    env.gl.confirm_speed(env.g, env.inj, profiles.get("gpg"), tap_first=True)
    files = sorted(os.listdir(d))
    assert len(files) == 30                                 # 30 old + 3 new (before, tap 1, tap 2), oldest removed
    assert sum(f.endswith(("_0.png", "_1.png", "_2.png")) and not f.startswith("speed_gpg_2020") for f in files) == 3
    assert "speed_gpg_20200101_000000_0.png" not in files


def test_speed_none_after_tap_is_reread_then_succeeds(env, monkeypatch, capsys):
    _speed_reads(monkeypatch, env.gl, [1.0, None, None, 2.0])   # before, tap 1 -> unreadable twice -> 2.0
    assert env.gl.confirm_speed(env.g, env.inj, profiles.get("gpg"), tap_first=True) == 2.0
    assert len(env.inj.taps) == 1
    assert "배속 1.0 -> 2.0" in capsys.readouterr().out


def test_speed_none_for_3s_then_ends(env, monkeypatch, capsys):
    reads = []
    def rd(f):
        reads.append(1)
        return 1.0 if len(reads) == 1 else None
    monkeypatch.setattr(env.gl, "read_speed", rd)
    assert env.gl.confirm_speed(env.g, env.inj, profiles.get("gpg"), tap_first=True) is None
    assert len(env.inj.taps) == 1 and len(reads) == 1 + 1 + 6      # initial, after tap, 6 re-reads (3 s)


def test_speed_window_ends_the_loop(env, monkeypatch):
    _speed_reads(monkeypatch, env.gl, [1.0])
    clock = iter(range(0, 1000, 8))                          # monotonic jumps 8 s per call: t0=0, 8, 16, 24
    monkeypatch.setattr(env.gl.time, "monotonic", lambda: next(clock))
    env.gl.confirm_speed(env.g, env.inj, profiles.get("gpg"), tap_first=True)
    assert len(env.inj.taps) == 2                            # 20 s window ran out before the 5-tap cap


def test_resumed_battle_below_2x_is_tapped_toward_2_0(env, monkeypatch):
    _speed_reads(monkeypatch, env.gl, [1.5, 1.5, 2.0])
    env.gl.confirm_speed(env.g, env.inj, profiles.get("gpg"), tap_first=False)
    assert len(env.inj.taps) == 2


@pytest.mark.parametrize("seen", [2.0, None])
def test_resumed_battle_at_2x_or_unreadable_is_not_tapped(env, monkeypatch, seen):
    _speed_reads(monkeypatch, env.gl, [seen])
    env.gl.confirm_speed(env.g, env.inj, profiles.get("gpg"), tap_first=False)
    assert env.inj.taps == []


def test_battle_phase_resumed_applies_speed(env, monkeypatch):
    _speed_reads(monkeypatch, env.gl, [1.0, 2.0])
    assert env.gl.battle_phase("joiner", env.g, env.inj, profiles.get("gpg"), 1, tap_speed=False) == "ok"
    assert len(env.inj.taps) == 1


def _lobby_run(gl, monkeypatch, tmp_path, results):
    import numpy as np
    monkeypatch.setattr(gl.time, "sleep", lambda s: None)
    monkeypatch.setattr(friend_coop, "COOP_DEBUG_DIR", str(tmp_path / "cd"))
    class G:
        def grab(self):
            return np.zeros((8, 8, 3), np.uint8)
    calls = iter(results)
    gl.after_battle("clear", G(), "inj", exit_fn=lambda g, i: next(calls), battle_fn=lambda f: False)
    return list((tmp_path / "cd").glob("lobby_fail_*.png")) if (tmp_path / "cd").exists() else []


def test_lobby_exit_retried_once_then_ok(gl, monkeypatch, tmp_path, capsys):
    assert _lobby_run(gl, monkeypatch, tmp_path, [False, True]) == []
    assert "retrying once" in capsys.readouterr().out


def test_lobby_exit_failing_twice_saves_frame(gl, monkeypatch, tmp_path, capsys):
    assert len(_lobby_run(gl, monkeypatch, tmp_path, [False, False])) == 1
    assert "frame saved:" in capsys.readouterr().out


def test_lobby_exit_not_retried_when_it_works(gl, monkeypatch, tmp_path, capsys):
    _lobby_run(gl, monkeypatch, tmp_path, [True])
    assert "retrying" not in capsys.readouterr().out


def test_resumed_battle_already_at_2x_gets_no_speed_tap(env, monkeypatch):
    # rdT07: a resumed battle is tapped only when the caption is legible and below 2.0
    monkeypatch.setattr(env.gl, "read_speed", lambda f: 2.0)
    env.state["battle"] = True
    assert env.gl.main(["--profile", "ld", "--role", "inviter"]) == 0
    assert env.inj.taps == [] and len(env.battles) == 1


def test_inviter_and_joiner_never_write_room_json(env):
    env.gl.main(["--profile", "ld", "--role", "inviter"])
    env.stop.unlink(); env.state["battle"] = False
    env.gl.main(["--role", "joiner"])
    assert env.rooms == []


def test_duo_roles_pass_the_duo_support_player(env):
    env.gl.main(["--role", "joiner"])
    env.stop.unlink()
    env.gl.main(["--profile", "ld"])
    assert env.battles[0]["support_play"] is env.gl._duo_support_play
    assert "support_play" not in env.battles[1]
    assert env.battles[0]["gear_play"] is env.gl.play and env.battles[0]["minutes"] == 40


def test_duo_support_play_sets_duo_flag_and_stats(env, monkeypatch):
    calls = []
    def fake_play(g, inj, minutes=40, duo=False):
        calls.append((minutes, duo)); return "clear"
    fake_play.stats = {"merges": 7}
    monkeypatch.setattr(env.gl.support_bot, "play", fake_play)
    assert env.gl._duo_support_play(env.g, env.inj, minutes=40) == "clear"
    assert calls == [(40, True)] and env.gl._duo_support_play.stats == {"merges": 7}


# ---- records ----

@pytest.mark.parametrize("args,fname,other,bot,mode", [
    (["--profile", "ld", "--role", "inviter"], "gear_rounds.jsonl", "joiner_rounds.jsonl", "gear", "duo"),
    (["--profile", "ld"], "gear_rounds.jsonl", "joiner_rounds.jsonl", "gear", "gear"),
    (["--profile", "gpg2", "--role", "joiner"], "joiner_rounds.jsonl", "gear_rounds.jsonl", "support", "duo"),
])
def test_round_record_goes_to_the_bots_file(env, args, fname, other, bot, mode):
    assert env.gl.main(args) == 0
    d = env.stop.parent
    assert not (d / other).exists()
    (line,) = (d / fname).read_text(encoding="utf-8").splitlines()
    rec = json.loads(line)
    assert (rec["bot"], rec["mode"], rec["round"], rec["result"]) == (bot, mode, 1, "timeout")
    assert rec["stats"] == {"merges": 4, "fails": 1, "support": 2, "complete": True}
    assert {"t_start", "t_end", "wall_end"} <= set(rec)


# ---- solo window mode (rdT17) ----

SOLO_GPG2 = ["--profile", "gpg2", "--role", "solo", "--partner", "대변먹는자"]
SOLO_GPG = ["--profile", "gpg", "--role", "solo", "--partner", "배속봇"]


def test_solo_needs_a_partner(env):
    with pytest.raises(SystemExit):
        env.gl.main(["--profile", "gpg", "--role", "solo"])
    assert env.checks == [] and env.injectors == []


@pytest.mark.parametrize("args,own,partner,expect", [(SOLO_GPG, "gpg", "배속봇", "gear"),
                                                     (SOLO_GPG2, "gpg2", "대변먹는자", "support")])
def test_solo_invites_the_partner_checks_only_its_window_and_plays_its_deck(env, monkeypatch, args, own,
                                                                            partner, expect):
    seen = {}
    def invite(g, inj, name, wait_s, stop, uv=None):
        seen.update(name=name, wait_s=wait_s, stop=stop, uv=uv)
        env.state["battle"] = True
        return True
    monkeypatch.setattr(friend_coop, "invite_and_start", invite)
    monkeypatch.setattr(env.gl, "open_room_and_wait", lambda *a, **k: 1 / 0)
    monkeypatch.setattr(coop_join, "wait_and_accept", lambda *a, **k: 1 / 0)
    assert env.gl.main(args) == 0
    assert env.checks == [[own]]                         # own window only, no pair / overlap check
    assert (seen["name"], seen["wait_s"], seen["stop"]) == (partner, 300, env.gl.should_stop)
    assert seen["uv"]["FRIEND"] == profiles.uv(profiles.get(own), "FRIEND_UV")
    b = env.battles[0]
    assert b["expect"] == expect and b["support_play"] is env.gl._duo_support_play
    assert env.inj.taps == [SPEED_UV]                    # 배속 as every role
    rec = json.loads((env.stop.parent / "gear_rounds.jsonl").read_text(encoding="utf-8"))
    assert (rec["bot"], rec["mode"]) == (expect, "solo")
    assert env.rooms == []


def test_solo_lobby_phase_results(env, monkeypatch):
    prof, duo = profiles.get("gpg2"), {"host": "h", "partner": "p", "invite_wait_s": 5}
    for inv, want in ((True, "ok"), (False, "absent"), (None, "fail"), ("stopped", "stop"), ("paused", "wait")):
        monkeypatch.setattr(friend_coop, "invite_and_start", lambda *a, _r=inv, **k: _r)
        assert env.gl.lobby_phase("solo", env.g, env.inj, prof, duo) == want
    monkeypatch.setattr(friend_coop, "invite_and_start", lambda *a, **k: False)
    assert env.gl.lobby_phase("inviter", env.g, env.inj, prof, duo) == "fail"    # duo inviter unchanged


def test_solo_partner_offline_or_not_joining_is_invited_again(env, monkeypatch, capsys):
    """The real invite_and_start with the partner never in the friend list: wait_s runs out, the room is
    left (MODAL_X) -> 'absent'; the loop waits SOLO_RETRY_S and invites again, fails never rise."""
    from rdom.perception import board
    for n, v in (("is_lobby", False), ("is_friend_menu", False), ("is_coop_room", True),
                 ("has_popup_close", True)):
        monkeypatch.setattr(board, n, lambda f, _v=v: _v)
    monkeypatch.setattr(friend_coop, "start_ready", lambda f: False)
    monkeypatch.setattr(friend_coop, "slot_pending", lambda f: False)
    monkeypatch.setattr(friend_coop, "find_friend_in_popup", lambda f, name: None)   # not online
    clock = [0.0]
    def now():
        clock[0] += 1.0
        return clock[0]
    rounds = []
    real = REAL_INVITE_AND_START
    def invite(g, inj, name, wait_s, stop, uv=None):
        rounds.append(name)
        if len(rounds) > 4:
            env.stop.write_text("")
            return "stopped"
        return real(g, inj, name, wait_s, stop, uv=uv, now=now, sleep=lambda s: None)
    monkeypatch.setattr(friend_coop, "invite_and_start", invite)
    sleeps = []
    monkeypatch.setattr(env.gl.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(env.gl, "_clock", now)
    assert env.gl.main(SOLO_GPG2) == env.gl.EXIT_CLEAN
    out = capsys.readouterr().out
    assert rounds == ["대변먹는자"] * 5
    assert out.count("대변먹는자 not online / not found") >= 4
    assert out.count("invite wait over -- leaving the room") == 4
    assert out.count("partner did not join -- invite again") == 4
    assert "fails=" not in out and sleeps.count(env.gl.SOLO_RETRY_S) == 4
    assert env.inj.taps.count(profiles.uv(profiles.get("gpg2"), "MODAL_X_UV")) == 4
    assert not any(t.startswith("⛔") for t in texts(env))


def test_solo_absent_rounds_do_not_count_but_other_failures_do(env, monkeypatch):
    results = iter(["fail", "absent", "absent", "fail", "absent", "fail", "absent"])
    monkeypatch.setattr(env.gl, "lobby_phase", lambda *a: next(results))
    assert env.gl.main(SOLO_GPG2) == env.gl.EXIT_GUARD
    assert ("⛔ 대변먹는자 초대 3회 연속 실패 -- 정지. 화면 확인 필요", "frame") in env.status


def test_solo_wait_status_at_most_once_per_10_minutes(env, monkeypatch):
    n = 40
    results = iter(["absent"] * n + ["stop"])
    monkeypatch.setattr(env.gl, "lobby_phase", lambda *a: next(results))
    t = [0.0]
    def clock():                                     # every round (invite_wait_s + retry) takes 330 s
        t[0] += 330.0
        return t[0]
    monkeypatch.setattr(env.gl, "_clock", clock)
    assert env.gl.main(SOLO_GPG) == 0
    waits = [s for s in texts(env) if s.startswith("⏳")]
    assert waits[0] == "⏳ 배속봇 아직 안 들어옴 -- 계속 다시 초대 중"
    assert len(waits) == 20                          # 40 rounds 330 s apart: rounds 1, 3, 5, ... (>= 600 s gap)


def test_solo_wait_status_throttle_restarts_after_a_battle(env, monkeypatch):
    results = iter(["absent", "absent", "ok", "absent", "stop"])
    def lobby(*a):
        r = next(results)
        env.state["battle"] = r == "ok"
        return r
    monkeypatch.setattr(env.gl, "lobby_phase", lobby)
    monkeypatch.setattr(env.gl, "_clock", lambda: 100.0)          # no time passes
    env.stop_after_battle = False
    assert env.gl.main(SOLO_GPG) == 0
    assert len([s for s in texts(env) if s.startswith("⏳")]) == 2  # first wait, and first wait after the battle


# ---- tagged status ----

def test_send_status_inserts_tag_after_the_emoji(monkeypatch):
    posts = []
    monkeypatch.setattr(discord, "_urls", lambda: {"status_webhook": "http://x"})
    monkeypatch.setattr(discord, "_post", lambda url, content, png=None, embed=None: posts.append(embed) or True)
    monkeypatch.setattr(discord, "_tag", "")
    discord.send_status("▶ 봇 시작")
    discord.set_tag("[기어]")
    discord.send_status("▶ 봇 시작")
    discord.send_status("🏁 3판 종료\n합성 4회")
    discord.set_tag("")
    discord.send_status("⛔ 정지")
    assert posts[0]["description"] == "**▶ 봇 시작**"
    assert posts[1]["description"] == "**▶ [기어] 봇 시작**" and posts[1]["color"] == discord.COLOURS["▶"]
    assert posts[2]["description"] == "**🏁 [기어] 3판 종료**\n합성 4회"
    assert posts[2]["color"] == discord.COLOURS["🏁"]
    assert posts[3]["description"] == "**⛔ 정지**"
