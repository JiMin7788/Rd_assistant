import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("save_frame_tool", ROOT / "tools" / "save_frame.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _claim(mod, folder, stamp, data):
    path, f = mod.claim_file(folder, stamp)
    with f:
        f.write(data)
    return path


def test_claim_never_overwrites(tmp_path):
    mod = _load()
    p1 = _claim(mod, tmp_path, "20261029_120000", b"one")
    p2 = _claim(mod, tmp_path, "20261029_120000", b"two")
    p3 = _claim(mod, tmp_path, "20261029_120000", b"three")
    assert [p.name for p in (p1, p2, p3)] == ["20261029_120000.png", "20261029_120000_2.png", "20261029_120000_3.png"]
    assert p1.read_bytes() == b"one"
    assert p2.read_bytes() == b"two"


def test_claim_skips_precreated_suffix(tmp_path):
    mod = _load()
    (tmp_path / "s.png").write_bytes(b"a")
    (tmp_path / "s_2.png").write_bytes(b"b")   # as if another process claimed it
    p = _claim(mod, tmp_path, "s", b"c")
    assert p.name == "s_3.png"
    assert (tmp_path / "s_2.png").read_bytes() == b"b"


def test_claim_exhausted_returns_none(tmp_path):
    mod = _load()
    (tmp_path / "s.png").write_bytes(b"")
    for n in range(2, 100):
        (tmp_path / f"s_{n}.png").write_bytes(b"")
    assert mod.claim_file(tmp_path, "s") is None


def test_run_all_show_has_memory_lines():
    text = (ROOT / "tools" / "run_all.py").read_text(encoding="utf-8")
    assert '"unreadable"' in text and '"board changed without our action"' in text


def test_run_all_show_has_play_mode_lines():
    text = (ROOT / "tools" / "run_all.py").read_text(encoding="utf-8")
    for s in ("power-up", "Lv check", "look-alike", "game-over screen", "support result",
              "battle still on screen"):
        assert f'"{s}"' in text


def test_h3_runbook_lines_exist_in_code():
    # AI-NOTE: every console line quoted in the H3 runbook must be a real log prefix (R14 runbook).
    code = "".join((ROOT / "tools" / f).read_text(encoding="utf-8")
                   for f in ("support_players.py", "support_bot.py", "gear_loop.py", "gear_bot.py"))
    code += (ROOT / "src" / "rdom" / "policy" / "power.py").read_text(encoding="utf-8")
    todo = (ROOT / "CLAUDE_CODE_TODO.md").read_text(encoding="utf-8")
    h3 = todo.split("### H3")[1]
    for s in ("support deck: play mode", "power-up (SP", "power panel ->","Lv check:",
              "power panel: ", "support result:", "game-over look-alike", "game-over screen seen once",
              "battle still on screen"):
        assert s in h3 and s in code, s


def test_h4_runbook_commands_exist_in_code():
    # AI-NOTE: every tool and flag named in the H4 runbook (rdF04, R17) must exist in the repo.
    todo = (ROOT / "CLAUDE_CODE_TODO.md").read_text(encoding="utf-8")
    h4 = todo.split("### H4")[1]
    needed = {
        "duo_check.py": (),
        "gear_bot.py": ("--profile",),
        "save_frame.py": ("--profile", "--every", "--minutes"),
        "check_ld_profile.py": (),
    }
    for tool, flags in needed.items():
        path = ROOT / "tools" / tool
        assert path.is_file(), tool
        assert "tools/" + tool in h4, tool
        code = path.read_text(encoding="utf-8")
        for flag in flags:
            assert 'add_argument("' + flag + '"' in code, (tool, flag)
            assert flag in h4, (tool, flag)
    for s in ("start check: OK", "invite from 대변먹는자 -- accept", "수락 대기중", "[기어]", "[서폿]",
              "■ 봇 종료", "1.5x", "2.0x", "한 판만 되면 됨"):
        assert s in h4, s
