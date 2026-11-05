"""Repeat coop rounds (no end time; stop with /종료 or data/STOP): lobby -> room -> 배속 once -> bot plays ->
로비로 가기 -> repeat. One process per bot; the role decides how a round gets its partner:

  public   today's gear-only loop: 방 생성 (no invite), wait for any joiner, 협동 시작
  inviter  duo, gear bot (gpg): invite the partner from config/duo.toml, 협동 시작 when accepted
  joiner   duo, gear bot (gpg2): wait for the host's invite popup, accept it

Models are hot-reloaded before every round (training runs alongside). Each round's start/end
(perf_counter, same clock as the recorder) goes to data/gear_rounds.jsonl (gear profile) or
data/joiner_rounds.jsonl (joiner role). Stops after 3 failed rounds in a row (fix the cause,
don't loop blindly).

Exit code: 0 clean (/종료), 3 guard stop (window moved, 3 failed rounds, wrong deck, start check),
anything else = crash. Real input only with --execute.

  python tools/gear_loop.py [--profile gpg|gpg2|ld] [--role public|inviter|joiner] [--execute]
"""
import argparse, datetime, functools, glob, json, os, sys, time, tomllib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from rdom import profile as profiles
from rdom.capture import preflight
from rdom.capture.live import LiveGrabber
from rdom.input.inject import make_injector
from rdom.input import coop_join, friend_coop
from rdom.input.friend_coop import open_room_and_wait
from rdom.notify import discord
from rdom.notify.room_state import write_room
from rdom.perception.board import (is_battle, is_game_over, is_lobby, read_speed,
                                   has_popup_close, has_modal_x, is_exit_dialog, is_coop_room,
                                   is_friend_menu)


def network_error(f):
    """The 알림 dialog with a single yellow 확인 at v~0.627 over a dark panel."""
    import cv2
    h, w = f.shape[:2]; W = round(h * 9 / 16)
    btn = cv2.cvtColor(f[int(0.605*h):int(0.650*h), int(0.30*W):int(0.70*W)], cv2.COLOR_RGB2HSV)
    yellow = ((btn[..., 0] >= 18) & (btn[..., 0] <= 35) & (btn[..., 1] > 120) & (btn[..., 2] > 150)).mean()
    panel = cv2.cvtColor(f[int(0.40*h):int(0.55*h), int(0.10*W):int(0.90*W)], cv2.COLOR_RGB2HSV)
    dark = (panel[..., 2] < 60).mean()
    return yellow > 0.5 and dark > 0.6
from rdom.perception import gear, support
from tools.bot_live import exit_to_lobby
from tools import gear_bot, support_bot
from tools.gear_bot import play
from rdom.notify.discord import send_status

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = r"C:\dev\rdom\data"
GEAR_LOG = os.path.join(DATA, "gear_rounds.jsonl")       # public / inviter role
JOINER_LOG = os.path.join(DATA, "joiner_rounds.jsonl")   # joiner role
PAUSE = os.path.join(DATA, "PAUSE")
STOP = os.path.join(DATA, "STOP")                  # /종료 (Discord): end cleanly between games
DUO_CFG = os.path.join(ROOT, "config", "duo.toml")

EXIT_CLEAN = 0
EXIT_GUARD = 3                                     # anything else (an exception) is a crash

FAIL_TEXT = {
    "public": "⛔ 방 만들기 3회 연속 실패 -- 정지. 화면 확인 필요",
    "inviter": "⛔ {partner} 초대 3회 연속 실패 -- 정지. 화면 확인 필요",
    "joiner": "⛔ 초대 수락 후 판이 3회 연속 시작되지 않음 -- 정지. 화면 확인 필요",
}
WRONG_DECK_TEXT = {
    "gear": "⛔ 기어덱이 아니에요 -- 덱 확인 후 다시 시작해 주세요",
    "support": "⛔ 서포팅덱이 아니에요 -- 덱 확인 후 다시 시작해 주세요",
}
MOVED_TEXT = "⛔ 에뮬레이터 창이 움직여서 정지"


def load_duo(path=None):
    """config/duo.toml: host, partner, invite_wait_s."""
    with open(path or DUO_CFG, "rb") as fh:
        return tomllib.load(fh)


def should_stop():
    """For the duo wait loops: 'stop' (data/STOP), 'pause' (data/PAUSE) or None. STOP wins."""
    if os.path.exists(STOP):
        return "stop"
    if os.path.exists(PAUSE):
        return "pause"
    return None


def after_battle(res, g, inj, exit_fn=exit_to_lobby, battle_fn=is_battle, report=None):
    """Log the battle result, then leave the finished game. Returns True when the loop must stop
    (res == "moved"). `report` runs right after the result line (room/Discord updates), so the
    log order stays what it was when this code was inline."""
    print("battle result:", res, flush=True)
    if report: report()
    if res == "moved": return True
    if res in ("game_over", "clear"):
        time.sleep(3.0)
        # AI-NOTE: exit_to_lobby taps blindly; a battle still on screen (false game over) must not be left.
        if battle_fn(g.grab()):
            print("battle still on screen -- 로비로 가기 skipped", flush=True)
        else:
            ok = exit_fn(g, inj)
            if not ok:
                # AI-NOTE: 2026-11-05 CleanCardinal never left the result screen; one more full try
                # after a pause, then keep the frame for measuring.
                print("로비로 가기 failed -- retrying once", flush=True)
                time.sleep(3.0)
                f = g.grab()
                if battle_fn(f):
                    print("battle still on screen -- 로비로 가기 skipped", flush=True)
                    ok = None
                else:
                    ok = exit_fn(g, inj)
                    if not ok:
                        path = friend_coop.save_debug_frame("lobby_fail", g.grab())
                        print(f"로비로 가기 failed again -- frame saved: {path}", flush=True)
            print("로비로 가기:", ok, flush=True)
        time.sleep(3.0)
    return False


def leave_result_screen(f, g, inj, exit_fn=exit_to_lobby, over_fn=is_game_over, battle_fn=is_battle):
    """Round start: leave a leftover result screen. Returns the frame to go on with."""
    if not over_fn(f):
        return f
    # AI-NOTE: the game-over colour test also fires on battle frames; exit_to_lobby taps blindly, so
    # a battle on the same frame means no result screen -- go on without a tap (architecture §7).
    if battle_fn(f):
        print("battle still on screen -- 로비로 가기 skipped", flush=True)
        return f
    exit_fn(g, inj); time.sleep(3)
    return g.grab()


def round_start(g, rnd):
    """Between games: None to go on with the round, else the exit code to stop with.

    STOP -> EXIT_CLEAN; PAUSE waits here; a moved window -> EXIT_GUARD."""
    # pause switch: "봇 일시정지.bat" creates data/PAUSE, "봇 재개.bat" removes it.
    # Checked only between games, so the game in progress is always finished.
    # AI-NOTE: data/STOP is never removed here -- two bots read it, and the supervisor/Discord bot
    # owns it; the one that sees it first must not hide it from the other.
    if os.path.exists(STOP):
        send_status("⏹ 종료 요청 -- 봇 종료"); return EXIT_CLEAN
    if os.path.exists(PAUSE):
        send_status("⏸ 일시정지 -- 판 사이에서 대기 중 (봇 재개.bat 로 재개)")
        while os.path.exists(PAUSE) and not os.path.exists(STOP):
            time.sleep(2)
        if os.path.exists(STOP):
            send_status("⏹ 종료 요청 -- 봇 종료"); return EXIT_CLEAN
        send_status("▶ 재개")
    print(f"=== round {rnd} ({datetime.datetime.now():%H:%M}) ===", flush=True)
    if g.window_moved():
        print("window moved -- stop"); send_status(MOVED_TEXT, g.grab()); return EXIT_GUARD
    return None


UNKNOWN_WAIT_S = 5.0          # unknown screen: look again after this long before the first BACK
# AI-NOTE: the joiner's room -> battle loading screen is "unknown" and lasted well over 5 s (2026-11-05: two
# BACKs right before its battle); 15 s makes sure a loading screen is never BACKed.
JOINER_UNKNOWN_WAIT_S = 15.0


def recover_step(f, g, inj, prof, stop_on=None, unknown_wait_s=UNKNOWN_WAIT_S):
    """Get from whatever is on screen to a screen a round can start from (lobby, 친구와 하기
    menu, coop room or battle): relaunch a closed game, close popups, BACK on unknown screens.
    Returns (frame to go on with, gave_up). gave_up is True when the game cannot be relaunched or
    3 BACKs found no known screen: the round is failed. The joiner calls it (via _joiner_recover)
    on every idle frame of wait_and_accept.
    stop_on(frame) -> truthy ends the loop at once with (frame, False), checked on every frame
    before any tap or BACK (the joiner: invite popup, STOP/PAUSE)."""
    # shop/event popups open by themselves on the lobby after a game (재설계 패키지,
    # 2026-10-08): close them with their X before starting a room
    unknown = 0; launches = 0; gave_up = False
    for _ in range(30):
        if stop_on is not None and stop_on(f):
            break
        # game closed (emulator on the launcher home screen, 2026-10-11): start it
        # again; BACK / taps on the home screen would never get back to the lobby
        if inj.game_in_front() is False:
            if launches >= 2:
                print("game does not start -- give up this round", flush=True)
                gave_up = True; break
            launches += 1
            print(f"게임이 꺼져 있음 -- 랜덤다이스 실행 ({launches}/2)", flush=True)
            send_status("🔄 게임이 꺼져 있어서 다시 실행합니다")
            inj.launch_game()
            # wait for a screen we know -- never BACK during splash/loading (it can
            # close the game again)
            t_l = time.monotonic()
            while time.monotonic() - t_l < 120:
                time.sleep(3.0); f = g.grab()
                if stop_on is not None and stop_on(f):
                    break
                if (is_lobby(f) or has_popup_close(f) or has_modal_x(f) or network_error(f)
                        or is_exit_dialog(f) or is_battle(f) or is_coop_room(f)):
                    break
            print(f"  loaded after {time.monotonic() - t_l:.0f}s", flush=True)
            unknown = 0; continue
        # popups first: a shop popup's green buy button sits where the lobby's 협동
        # button is (스텝업 패키지, 2026-10-10), so never decide "lobby" under a popup
        # the 친구와 하기 menu is a fine start too: open_room_and_wait taps 방 생성 there
        if (is_battle(f) or is_coop_room(f) or is_friend_menu(f)
                or (is_lobby(f) and not has_popup_close(f))):
            break
        if network_error(f):
            # "네트워크 에러가 발생하여 게임을 재시작합니다." -- its only button is 확인;
            # the game then reloads (shop popups follow), 2026-10-09
            print("네트워크 에러 -- 확인, waiting for reload", flush=True)
            inj.tap(0.50, 0.627); time.sleep(8.0); f = g.grab(); continue
        if is_exit_dialog(f):
            print("종료 확인창 -- 취소", flush=True); inj.tap(*profiles.uv(prof, "CANCEL_UV"))
        elif has_popup_close(f):
            print("팝업 -- X 닫기", flush=True); inj.tap(*profiles.uv(prof, "CLOSE_X_UV"))
        elif is_game_over(f):
            exit_to_lobby(g, inj)
        elif has_modal_x(f) and unknown < 3:
            unknown += 1                         # BACK does not close these modals
            print(f"modal -- X 닫기 ({unknown}/3)", flush=True); inj.tap(*profiles.uv(prof, "MODAL_X_UV"))
        elif unknown < 3:
            # some other popup / screen without the bottom X: Android BACK closes
            # game popups (on the lobby it opens the exit dialog, cancelled above).
            # Never tap blind -- a popup is full of buy buttons.
            # A loading / transition screen is "unknown" too and BACK there can close
            # the game (2026-10-11, right after a relaunch): give it unknown_wait_s first.
            time.sleep(unknown_wait_s); f2 = g.grab()
            if (is_lobby(f2) or has_popup_close(f2) or has_modal_x(f2) or is_battle(f2)
                    or is_coop_room(f2) or is_exit_dialog(f2) or network_error(f2)):
                f = f2; continue
            if stop_on is not None and stop_on(f2):
                f = f2; break
            unknown += 1
            print(f"unknown screen -- BACK ({unknown}/3)", flush=True); inj.back()
        else:
            gave_up = True; break
        time.sleep(1.5); f = g.grab()
    return f, gave_up


def _joiner_recover(f, g, inj, prof):
    """wait_and_accept's recover callback: a truthy return ends the wait as 'failed'."""
    # AI-NOTE: wait_and_accept checks the invite popup and STOP/PAUSE only between recover calls,
    # so recover_step must stop itself on them -- a BACK/MODAL_X would close an incoming invite.
    def stop_on(fr):
        return coop_join.invite.invite_popup(fr) is not None or should_stop() is not None
    return recover_step(f, g, inj, prof, stop_on=stop_on, unknown_wait_s=JOINER_UNKNOWN_WAIT_S)[1]


def _invite_uvs(prof):
    return {k: profiles.uv(prof, k + "_UV")
            for k in ("FRIEND", "CREATE_ROOM", "INVITE_FRIEND", "START_COOP", "CLOSE_X", "MODAL_X")}


def lobby_phase(role, g, inj, prof, duo):
    """Get the room started with the role's partner logic.
    -> "ok" (battle can start) | "wait" (nothing wrong, go round again) | "fail" | "stop" (/종료)."""
    if role == "public":
        ok = open_room_and_wait(g, inj, timeout=1800)
        if ok is False:                         # nobody joined: keep waiting, not a fault
            print("nobody joined -- waiting again", flush=True); return "wait"
        if not ok:
            print(f"round did not start ({ok})", flush=True); return "fail"
        return "ok"
    if role == "inviter":
        r = friend_coop.invite_and_start(g, inj, duo["partner"], duo["invite_wait_s"], should_stop,
                                         uv=_invite_uvs(prof))
        if r == "stopped": return "stop"
        if r == "paused": return "wait"
        if r is True: return "ok"
        print(f"round did not start ({r})", flush=True); return "fail"
    r = coop_join.wait_and_accept(g, inj, duo["host"], should_stop,
                                  recover=functools.partial(_joiner_recover, g=g, inj=inj, prof=prof))
    if r == "battle": return "ok"
    if r == "stopped": return "stop"
    if r == "paused": return "wait"
    print(f"round did not start ({r})", flush=True); return "fail"


def _duo_support_play(g, inj, minutes):
    """support_bot.play with the duo flag; play.stats is copied so gear_loop reads it as before."""
    res = support_bot.play(g, inj, minutes=minutes, duo=True)
    _duo_support_play.stats = dict(getattr(support_bot.play, "stats", {}))
    return res


SPEED_TAPS_MAX = 5
SPEED_WINDOW_S = 20.0     # confirm_speed gives up after this long
SPEED_RETAP_S = 1.5       # wait after a tap before the caption is re-read
SPEED_DEBUG_KEEP = 30     # speed_* debug frames kept in COOP_DEBUG_DIR
SPEED_REREAD_S = 3.0      # an unreadable speed caption after a tap is re-read (every 0.5 s) this long


def log_input_stats(inj):
    """One 'input: ...' line per round from the Injector's counters, then reset them (per-round numbers).
    AdbInjector has no counters -> nothing."""
    s = getattr(inj, "stats", None)
    if not s:
        return
    n, w = s["gestures"], s.get("waited", 0)
    print(f"input: {n} gestures, {s['switches']} switches, {s['not_foreground']} not in front, "
          f"{s['lock_timeouts']} lock timeouts, waited {w} "
          f"(avg {s.get('waited_ms_total', 0) / w if w else 0:.0f} ms, max {s.get('waited_ms_max', 0):.0f} ms), "
          f"start-to-post avg {s.get('ready_ms_total', 0) / n if n else 0:.0f} ms, "
          f"max {s.get('ready_ms_max', 0):.0f} ms", flush=True)
    for k in s:
        s[k] = 0


def _save_speed_frame(prof, stamp, n, frame):
    """Save frame as COOP_DEBUG_DIR/speed_<profile>_<stamp>_<n>.png, keep the newest SPEED_DEBUG_KEEP
    speed_* files. Never raises (a debug dump must not break the bot)."""
    try:
        d = friend_coop.COOP_DEBUG_DIR
        os.makedirs(d, exist_ok=True)
        cv2, np = friend_coop.cv2, friend_coop.np
        cv2.imwrite(os.path.join(d, f"speed_{prof.name}_{stamp}_{n}.png"),
                    cv2.cvtColor(np.asarray(frame), cv2.COLOR_RGB2BGR))
        old = sorted(glob.glob(os.path.join(d, "speed_*.png")), key=os.path.getmtime)
        for p in old[:-SPEED_DEBUG_KEEP]:
            os.remove(p)
    except Exception as e:
        print(f"speed frame not saved: {e}", flush=True)


def confirm_speed(g, inj, prof, tap_first):
    """Tap 배속 until the caption reads >= 2.0: at most SPEED_TAPS_MAX taps SPEED_RETAP_S apart within
    SPEED_WINDOW_S. A rise caused by us does not stop the loop. Each tap logs one line and saves frames.
    tap_first=False (a resumed battle) taps only when the first reading is legible and below 2.0.
    An unreadable caption after a tap ends the loop: another blind tap could cycle 2.0 -> 1.0."""
    frame = g.grab()
    before = read_speed(frame)
    if (not tap_first and before is None) or (before is not None and before >= 2.0):
        print(f"배속 {before} -> {before}", flush=True)
        return before
    stamp = time.strftime("%Y%m%d_%H%M%S")
    after, taps, cur, t0 = before, 0, before, time.monotonic()
    while taps < SPEED_TAPS_MAX and time.monotonic() - t0 < SPEED_WINDOW_S:
        if taps == 0:
            _save_speed_frame(prof, stamp, 0, frame)      # the frame read right before the first tap
        inj.tap(*profiles.uv(prof, "SPEED_UV")); taps += 1
        time.sleep(SPEED_RETAP_S)
        frame = g.grab()
        after = read_speed(frame)
        # AI-NOTE: the caption can be unreadable for a moment right after the tap (2026-11-05: '1.0 -> None'
        # ended the loop); re-read for up to SPEED_REREAD_S before deciding.
        waited = 0.0
        while after is None and waited < SPEED_REREAD_S:
            time.sleep(0.5); waited += 0.5
            frame = g.grab()
            after = read_speed(frame)
        front = "front ok" if getattr(inj, "last_gesture_ok", True) else "NOT in front"
        print(f"  배속 tap {taps}/{SPEED_TAPS_MAX}: {cur} -> {after} ({front})", flush=True)
        _save_speed_frame(prof, stamp, taps, frame)
        cur = after
        # AI-NOTE: user 2026-11-05 23:5x '배속 둘 다 눌러서 2.0 만들어야한다고 대변먹는자가 안누르잖아'. Live run
        # 23:14 (rdT12 stopped at the first rise): round 3 inviter '배속 1.5 -> 1.5' after 3 taps, joiner
        # '1.0 -> 1.5'; rounds ended at 1.5. Whether a press adds a step, toggles a vote or is swallowed is
        # unknown, so every bot keeps tapping until 2.0 (or the cap / window); per-tap lines and speed_*
        # frames are the evidence for the next run.
        if after is None or after >= 2.0: break
    print(f"배속 {before} -> {after}", flush=True)
    return after


def battle_phase(role, g, inj, prof, rnd, tap_speed=True):
    """Wait for the battle, 배속 once, play, record, leave.
    -> "ok" | "wrong_deck" | "moved" (the loop stops with EXIT_GUARD on the last two).
    tap_speed is False when the round resumed an already running battle (speed state unknown)."""
    if tap_speed:
        t0 = time.monotonic()
        while not is_battle(g.grab()):
            if time.monotonic() - t0 > 90: break
            time.sleep(1.0)
        for _ in range(30):
            if read_speed(g.grab()) is not None: break
            time.sleep(0.5)
        confirm_speed(g, inj, prof, tap_first=True)
        send_status(f"🎮 {rnd}판 시작")
    else:
        confirm_speed(g, inj, prof, tap_first=False)
    rl = gear.reload_if_changed()
    if rl: print("models reloaded:", rl, flush=True)
    rl = support.reload_if_changed()
    if rl: print("support models reloaded:", rl, flush=True)
    t_start = time.perf_counter()
    # AI-NOTE: keyword args -- run_battle's 3rd positional is `minutes`; gear_play=play keeps the
    # `player is gear_play` hand-over check true for the gear bot.
    kw = {"minutes": 40, "gear_play": play, "expect": prof.bot}
    if role != "public":
        kw["support_play"] = _duo_support_play
    res, player = support_bot.run_battle(g, inj, **kw)
    t_end = time.perf_counter()
    log_input_stats(inj)
    if res == "wrong_deck":
        # AI-NOTE: no record, no 로비로 가기 and no other tap -- the wrong deck stays on screen for the user.
        print(f"wrong deck: expected {prof.bot}", flush=True)
        if role == "public":
            write_room(None, "closed")
        send_status(WRONG_DECK_TEXT[prof.bot], g.grab())
        return "wrong_deck"
    st = getattr(player, "stats", {})
    # AI-NOTE: rdT06: both duo bots are gear bots, so the record file follows the role (the joiner keeps
    # JOINER_LOG), not prof.bot; otherwise inviter and joiner would append to the same file.
    log = JOINER_LOG if role == "joiner" else GEAR_LOG
    os.makedirs(os.path.dirname(os.path.abspath(log)), exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"round": rnd, "t_start": t_start, "t_end": t_end, "result": res,
                             "wall_end": datetime.datetime.now().isoformat(),
                             "bot": prof.bot, "mode": "gear" if role == "public" else "duo",
                             "stats": {k: st.get(k) for k in ("merges", "fails", "support", "complete")}},
                            ensure_ascii=False) + "\n")
    def report():
        if role == "public":
            write_room(None, "closed")                      # reservation turn is over
        send_status(f"🏁 {rnd}판 종료 · {(t_end - t_start)/60:.1f}분\n합성 {st.get('merges', 0)}회 · "
                    f"실패 {st.get('fails', 0)}회 · 서포터 {st.get('support', 0)}회 · "
                    f"필드 완성 {'O' if st.get('complete') else 'X'}")
    if after_battle(res, g, inj, report=report):
        print("window moved -- stop"); send_status(MOVED_TEXT, g.grab())
        return "moved"
    return "ok"


def run_loop(role, prof, duo, g, inj):
    """The round loop. Returns EXIT_CLEAN or EXIT_GUARD; an exception propagates (crash)."""
    fails = 0; rnd = 0
    while True:
        rnd += 1
        code = round_start(g, rnd)
        if code is not None:
            return code
        f = g.grab()
        f = leave_result_screen(f, g, inj)
        # AI-NOTE: the joiner skips the round-start recover: it could close the host's invite popup with
        # the modal X; wait_and_accept checks the popup first and calls recover only on idle frames.
        gave_up = False
        if role != "joiner":
            f, gave_up = recover_step(f, g, inj, prof)
        came_from_lobby = not is_battle(f)
        if came_from_lobby:
            r = "fail" if gave_up else lobby_phase(role, g, inj, prof, duo)
            if r == "stop":
                return EXIT_CLEAN
            if r == "wait":
                continue
            if r == "fail":
                fails += 1; print(f"fails={fails}", flush=True)
                if fails >= 3:
                    print("!! 3 failed rounds in a row -- stopping")
                    send_status(FAIL_TEXT[role].format(partner=duo["partner"]), g.grab())
                    return EXIT_GUARD
                time.sleep(5); continue
        fails = 0
        if battle_phase(role, g, inj, prof, rnd, tap_speed=came_from_lobby) != "ok":
            return EXIT_GUARD


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", choices=sorted(profiles.PROFILES), default="gpg",
                    help="gpg = Google Play Games window 1 (gear, default), gpg2 = window 2 (gear), ld = LDPlayer (gear, unused)")
    ap.add_argument("--role", choices=("public", "inviter", "joiner"), default="public")
    ap.add_argument("--execute", action="store_true", help="really inject input (default: dry run)")
    a = ap.parse_args(argv)
    prof = profiles.get(a.profile)
    duo = load_duo()
    discord.set_tag(prof.tag)
    # AI-NOTE: the start check runs before any injector exists; the duo inviter also checks the
    # partner's window so the two windows are known not to overlap.
    names = ["gpg", "gpg2"] if a.role == "inviter" else [a.profile]
    results = preflight.check(names)
    for line in preflight.format_lines(results):
        print(line, flush=True)
    bad = [why for _, ok, why in results if not ok]
    if bad:
        send_status(f"⛔ 시작 점검 실패: {bad[0]}")
        return EXIT_GUARD
    if a.profile == "ld":
        gear_bot.SUPPORT_SCALES = gear_bot.LD_SUPPORT_SCALES
    cfg = os.path.join(ROOT, prof.config)
    g = LiveGrabber(config=cfg)
    inj = make_injector(cfg, execute=a.execute)
    send_status("▶ 봇 시작")
    try:
        code = run_loop(a.role, prof, duo, g, inj)
    finally:
        g.close()
    if code == EXIT_CLEAN:
        send_status("■ 봇 종료")
    return code


if __name__ == "__main__":
    sys.exit(main())
