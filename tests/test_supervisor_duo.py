"""Supervisor duo/gear modes (rdf04-t9). Fake children and a fake clock in a tmp data dir:
no process is started, nothing is sent to Discord, nothing under the real data dir is touched."""
import datetime
import importlib
import json
import os
import re
import sys

import pytest

import rdom.notify.room_state as room_state

T0 = 1_700_000_000


@pytest.fixture
def sup_mod(monkeypatch):
    for n in ("tools.supervisor", "supervisor"):
        monkeypatch.delitem(sys.modules, n, raising=False)
    mod = importlib.import_module("tools.supervisor")
    sys.modules.pop("tools.supervisor", None)       # other tests assert it was never imported
    return mod


class FakeProc:
    def __init__(self, env, pid, life, rc):
        self.env, self.pid, self.end, self.rc = env, pid, env.now + life, rc

    def poll(self):
        return self.rc if self.env.now >= self.end else None


class Env:
    """lives[profile] = list of (seconds alive, exit code), one entry per start of that bot."""

    def __init__(self, tmp_path, mon, mod, lives):
        self.dir = str(tmp_path / "data")
        os.makedirs(self.dir, exist_ok=True)
        self.now = float(T0)
        self.lives, self.starts, self.cmds, self.notes = lives, {}, [], []
        self.sleeps = []                             # (clock, STOP exists, bot_mode.json content or None)
        self.pid = 1000
        mon.setattr(room_state, "ROOM", os.path.join(self.dir, "room.json"))
        self.mod = mod

    def p(self, name):
        return os.path.join(self.dir, name)

    def exists(self, name):
        return os.path.exists(self.p(name))

    def read(self, name):
        with open(self.p(name), encoding="utf-8") as fh:
            return json.load(fh)

    def spawn(self, cmd, log_path):
        prof = cmd[cmd.index("--profile") + 1]
        k = self.starts.get(prof, 0)
        self.starts[prof] = k + 1
        self.cmds.append(cmd)
        life, rc = self.lives[prof][k]
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(f"{prof} start {k} line {i}" for i in range(10)) + "\n")
        self.pid += 1
        return FakeProc(self, self.pid, life, rc)

    def sleep(self, s):
        mode = self.read("bot_mode.json") if self.exists("bot_mode.json") else None
        self.sleeps.append((self.now, self.exists("STOP"), mode))
        self.now += s
        assert self.now < T0 + 100000, "supervisor does not terminate"

    def notify(self, text, frame=None):
        self.notes.append((text, frame))

    def texts(self):
        return [t for t, _ in self.notes]

    def run(self, mode="duo"):
        sup = self.mod.Supervisor(mode, self.dir, spawn=self.spawn, clock=lambda: self.now,
                                  sleep=self.sleep, notify=self.notify,
                                  screenshot=lambda prof: "shot:" + prof.name)
        return sup.run()


@pytest.fixture
def mk(tmp_path, monkeypatch, sup_mod):
    def make(lives):
        return Env(tmp_path, monkeypatch, sup_mod, lives)
    return make


def test_children_commands(mk):
    e = mk({"gpg": [(5, 0)], "gpg2": [(5, 0)]})
    assert e.run() == 0
    tails = sorted(c[c.index("--profile"):] for c in e.cmds)
    assert tails == [["--profile", "gpg", "--role", "inviter", "--execute"],
                     ["--profile", "gpg2", "--role", "joiner", "--execute"]]
    assert all(c[-1] == "--execute" and c[4].endswith("gear_loop.py") for c in e.cmds)
    g = mk({"gpg": [(5, 0)]})
    assert g.run("gear") == 0
    assert [c[c.index("--profile"):] for c in g.cmds] == [["--profile", "gpg", "--role", "public", "--execute"]]


def test_crashes_counted_per_bot(mk):
    e = mk({"gpg": [(5, 1)] * 4 + [(5, 0)], "gpg2": [(20, 1), (100, 0)]})
    assert e.run() == 0
    ld = [(t, f) for t, f in e.notes if "[기어1]" in t]
    sp = [(t, f) for t, f in e.notes if "[서폿]" in t]
    assert [t.split("\n")[0] for t, _ in ld] == [f"⚠ [기어1] 봇 오류로 재시작 ({n}/5)" for n in (1, 2, 3, 4)]
    assert [t.split("\n")[0] for t, _ in sp] == ["⚠ [서폿] 봇 오류로 재시작 (1/5)"]
    assert all(f == "shot:gpg" for _, f in ld) and sp[0][1] == "shot:gpg2"
    # last 6 log lines of the crashed run, in a code block
    assert ld[0][0].split("\n", 1)[1] == "```" + "\n".join(f"gpg start 0 line {i}" for i in range(4, 10)) + "```"
    assert e.starts == {"gpg": 5, "gpg2": 2}
    assert not e.exists("STOP")


def test_restart_after_10_seconds(mk):
    e = mk({"gpg": [(5, 1), (5, 0)], "gpg2": [(300, 0)]})
    starts = []
    orig = e.spawn
    e.spawn = lambda cmd, log: (starts.append((cmd[cmd.index("--profile") + 1], e.now)), orig(cmd, log))[1]
    e.run()
    ld = [t for p, t in starts if p == "gpg"]
    assert ld[1] - (ld[0] + 5) >= 10


def test_crashes_older_than_30_minutes_do_not_count(mk):
    e = mk({"gpg": [(5, 1), (2000, 1), (5, 0)], "gpg2": [(5, 0)]})
    assert e.run() == 0
    assert [t.split("\n")[0] for t in e.texts()] == ["⚠ [기어1] 봇 오류로 재시작 (1/5)"] * 2


def _stopped_while_other_ran(e, other_end):
    """STOP was already on disk at a poll while the other child was still alive."""
    return any(stop and t < other_end for t, stop, _ in e.sleeps)


def test_fifth_crash_stops_both_duo(mk):
    e = mk({"gpg": [(5, 1)] * 5, "gpg2": [(100, 0)]})
    assert e.run() == 1
    assert e.starts == {"gpg": 5, "gpg2": 1}           # nothing restarted after the 5th crash
    limit = [(t, f) for t, f in e.notes if t.startswith("⛔")]
    assert len(limit) == 1
    head, tail = limit[0][0].split("\n", 1)
    assert head == "⛔ [기어1] 30분 안에 5번 오류 -- 두 봇 모두 정지 (다른 봇은 지금 판을 끝내고 멈춰요). 확인 필요"
    assert tail.startswith("```gpg start 4 line 4") and limit[0][1] == "shot:gpg"
    assert [t.split("\n")[0] for t in e.texts()][:4] == [f"⚠ [기어1] 봇 오류로 재시작 ({n}/5)" for n in (1, 2, 3, 4)]
    assert e.texts()[-1] == "■ 두 봇 모두 정지됨"
    gpg_end = T0 + 100
    assert _stopped_while_other_ran(e, gpg_end)       # STOP written while gpg still ran
    assert e.now >= gpg_end                           # and the supervisor waited for gpg
    assert not e.exists("STOP")


@pytest.mark.parametrize("bad,bad_tag,other", [("gpg2", "[서폿]", "gpg"), ("gpg", "[기어1]", "gpg2")])
def test_guard_stop_of_one_stops_both(mk, bad, bad_tag, other):
    e = mk({bad: [(30, 3)], other: [(100, 0)]})
    assert e.run() == 1
    assert e.starts == {bad: 1, other: 1}
    assert e.texts() == [f"⛔ {bad_tag} 봇이 멈춰서 두 봇 모두 정지 (다른 봇은 지금 판을 끝내고 멈춰요)",
                         "■ 두 봇 모두 정지됨"]
    other_end = T0 + 100
    assert _stopped_while_other_ran(e, other_end)
    assert not any(stop for t, stop, _ in e.sleeps if t < T0 + 30)   # not before the guard stop
    assert e.now >= other_end
    assert not e.exists("STOP")


def test_no_restart_of_other_bot_crashing_after_stop(mk):
    e = mk({"gpg": [(10, 3)], "gpg2": [(50, 1)]})
    assert e.run() == 1
    assert e.starts == {"gpg": 1, "gpg2": 1}
    assert e.texts()[-1] == "■ 두 봇 모두 정지됨" and len(e.texts()) == 2


def test_pending_restart_cancelled_by_stop(mk):
    e = mk({"gpg": [(5, 1)], "gpg2": [(7, 3)]})        # ld crash pending its 10 s delay when gpg stops
    assert e.run() == 1
    assert e.starts == {"gpg": 1, "gpg2": 1}


def test_clean_exit(mk):
    e = mk({"gpg": [(10, 0)], "gpg2": [(40, 0)]})
    assert e.run() == 0
    assert e.notes == []
    assert not any(stop for _, stop, _ in e.sleeps)
    for n in ("supervisor.pid", "bot_mode.json", "STOP"):
        assert not e.exists(n)


def test_gear_mode_single_child(mk):
    e = mk({"gpg": [(5, 1), (5, 0)]})
    assert e.run("gear") == 0
    assert e.starts == {"gpg": 2}
    assert e.texts()[0].split("\n")[0] == "⚠ [기어1] 봇 오류로 재시작 (1/5)"
    assert not e.exists("room.json")


def test_gear_mode_crash_limit(mk):
    e = mk({"gpg": [(5, 1)] * 5})
    assert e.run("gear") == 1
    assert e.starts == {"gpg": 5}
    assert e.texts()[-1].split("\n")[0] == "⛔ [기어1] 30분 안에 5번 오류 -- 봇 정지. 확인 필요"
    assert e.notes[-1][1] == "shot:gpg"
    assert "■ 두 봇 모두 정지됨" not in e.texts()
    assert any(stop for _, stop, _ in e.sleeps)       # STOP written, then removed at the end
    assert not e.exists("STOP")


def test_gear_mode_guard_stop(mk):
    e = mk({"gpg": [(5, 3)]})
    assert e.run("gear") == 1
    assert e.starts == {"gpg": 1} and e.notes == []    # the child posted its own guard stop


def test_bot_mode_and_room_json_duo(mk):
    e = mk({"gpg": [(5, 1), (30, 0)], "gpg2": [(60, 0)]})
    seen = {}
    orig = e.sleep

    def spy(s):
        if "room" not in seen and e.exists("room.json"):
            seen["room"] = e.read("room.json")
            seen["pidfile"] = open(e.p("supervisor.pid")).read()
        orig(s)
    e.sleep = spy
    assert e.run() == 0
    assert seen["pidfile"] == str(os.getpid())
    assert seen["room"]["code"] is None and seen["room"]["state"] == "duo"
    first = e.sleeps[0][2]
    assert first["mode"] == "duo" and isinstance(first["t"], float)
    assert first["bots"] == [{"bot": "gear", "tag": "[기어1]", "profile": "gpg", "pid": 1001},
                             {"bot": "support", "tag": "[서폿]", "profile": "gpg2", "pid": 1002}]
    # the restarted ld child has a new pid in the file
    latest = [m for _, _, m in e.sleeps if m and m["bots"][0]["pid"] == 1003]
    assert latest and latest[0]["bots"][1]["pid"] == 1002


def test_bot_mode_json_gear(mk):
    e = mk({"gpg": [(5, 0)]})
    assert e.run("gear") == 0
    mode = e.sleeps[0][2]
    assert mode["mode"] == "gear"
    assert mode["bots"] == [{"bot": "gear", "tag": "[기어1]", "profile": "gpg", "pid": 1001}]
    assert not e.exists("room.json")                  # room.json only in duo


@pytest.mark.parametrize("lives,mode,rc", [
    ({"gpg": [(5, 0)], "gpg2": [(5, 0)]}, "duo", 0),
    ({"gpg": [(5, 3)], "gpg2": [(9, 0)]}, "duo", 1),
    ({"gpg": [(5, 1)] * 5}, "gear", 1),
])
def test_runtime_files_removed_at_exit(mk, lives, mode, rc):
    e = mk(lives)
    assert e.run(mode) == rc
    for n in ("supervisor.pid", "bot_mode.json", "STOP"):
        assert not e.exists(n)


def test_files_removed_when_supervisor_raises(mk):
    e = mk({"gpg": [(5, 0)], "gpg2": [(5, 0)]})
    e.sleep = lambda s: (_ for _ in ()).throw(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        e.run()
    for n in ("supervisor.pid", "bot_mode.json", "STOP"):
        assert not e.exists(n)


def test_log_file_per_start(mk):
    e = mk({"gpg": [(5, 1), (5, 1), (5, 0)], "gpg2": [(300, 0)]})
    names = []
    orig = e.spawn
    e.spawn = lambda cmd, log: (names.append(os.path.basename(log)), orig(cmd, log))[1]
    e.run()
    stamp = datetime.datetime.fromtimestamp(T0).strftime("%Y%m%d_%H%M")
    assert names[0] == f"{stamp}_gpg.log" and names[1] == f"{stamp}_gpg2.log"
    ld = [n for n in names if "_gpg." in n or "_gpg_" in n]
    assert len(ld) == 3 and len(set(names)) == len(names)      # one new file per (re)start
    assert all(re.fullmatch(r"\d{8}_\d{4}_(gpg2?)(_\d+)?\.log", n) for n in names)
    assert sorted(os.listdir(os.path.join(e.dir, "bot_logs"))) == sorted(names)


def test_duo_children_are_gear_inviter_gpg_and_support_joiner_gpg2(sup_mod):
    from rdom import profile
    assert sup_mod.CHILDREN["duo"] == (("gear", "gpg", "inviter"), ("support", "gpg2", "joiner"))
    assert sup_mod.CHILDREN["gear"] == (("gear", "gpg", "public"),)
    p1, p2 = profile.get("gpg"), profile.get("gpg2")
    assert (p1.bot, p2.bot) == ("gear", "support") and (p1.tag, p2.tag) == ("[기어1]", "[서폿]")
    assert (p1.config, p2.config) == ("config/recorder.toml", "config/recorder_gpg2.toml")


def test_import_has_no_side_effects(sup_mod):
    assert not hasattr(sup_mod, "PID") and callable(sup_mod.main)
