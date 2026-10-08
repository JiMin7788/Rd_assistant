"""Input layer (M2): turn policy actions into adb touch events on LDPlayer.

Content-normalized (u,v) map directly to android pixels because the capture
covers the game content 1:1 and there is no letterbox: android_x = u * res_w,
android_y = v * res_h (res = wm size, 1440x2560). Human-like jitter (a few px,
tens of ms) is added per docs/00 to avoid perfectly-constant input.

Cheong's destroy has a 90s cooldown, tracked here. Default is dry-run: nothing
is injected unless execute=True.
"""
from __future__ import annotations
import random
import subprocess
import time

from rdom.perception.board import COLS, ROWS

ADB = r"D:\LDPlayer\LDPlayer14\adb.exe"
DEVICE = "127.0.0.1:5555"
RES_W, RES_H = 1440, 2560

SUMMON_UV = (0.50, 0.855)
CHEONG_UV = (0.19, 0.867)
UPGRADE_UV = (0.20, 0.94)
LOBBY_UV = (0.50, 0.869)     # "로비로 가기" on the game-over screen
COOP_UV = (0.497, 0.823)     # "협동" (coop) on the lobby
FRIEND_UV = (0.155, 0.747)   # "친구와 하기" (play with a friend) on the lobby
CREATE_ROOM_UV = (0.50, 0.421)  # "방 생성" in the friend-coop popup
INVITE_FRIEND_UV = (0.48, 0.436)  # "+ 친구 초대" slot in the coop room
START_COOP_UV = (0.48, 0.647)     # "협동 시작" in the coop room
CLOSE_X_UV = (0.500, 0.936)       # the X that closes a shop/event popup
MODAL_X_UV = (0.870, 0.207)       # red X of the 친구와 하기 menu / coop room (BACK can't)
# Measured on the "재설계 패키지" purchase popup (2026-09-27): the dark-red
# close button spans u 0.454-0.547, v 0.910-0.962. Such popups open by
# themselves on the lobby and must be closed with their X (user), not BACK --
# BACK on the lobby root opens the quit dialog instead.
CANCEL_UV = (0.30, 0.62)          # 취소 on the "게임 종료" confirm box
SPEED_UV = (0.781, 0.799)         # 배속 (1.0x/1.5x/2.0x) fast-forward button.
# Measured from a live battle frame (2026-09-27): the button disc spans
# u 0.738-0.824, v 0.775-0.823. The old (0.755, 0.782) sat near its rim, so
# the +-5px tap jitter could miss it entirely and the battle ran at 1.0x.
CHEONG_CD = 90.0
SWITCH_CD = 5.0                   # switch swap cooldown (seconds) -- TODO confirm


def cell_uv(cell):
    """Center (u,v) of a board cell, row-major 1..15."""
    r, c = (cell - 1) // 5, (cell - 1) % 5
    return COLS[c], ROWS[r]


def _px(u, v, jitter=5):
    x = int(u * RES_W + random.uniform(-jitter, jitter))
    y = int(v * RES_H + random.uniform(-jitter, jitter))
    return max(0, min(RES_W - 1, x)), max(0, min(RES_H - 1, y))


def resolve_device(adb=ADB, preferred=DEVICE):
    """The adb serial to use. LDPlayer shows up as 127.0.0.1:5555 or as
    emulator-5554 depending on how adb was started; a hard-coded serial that is
    not attached makes every tap fail SILENTLY (stdout/err go to DEVNULL) -- a
    2026-10-07 run tapped 친구와 하기 into the void. Prefer `preferred`, else the
    single attached device; raise if there is none or several."""
    import tempfile
    with tempfile.TemporaryFile("w+") as fh:      # a file, not a pipe: see _run on adb pipes
        subprocess.run([adb, "devices"], stdout=fh, stderr=subprocess.DEVNULL, timeout=10)
        fh.seek(0); out = fh.read()
    devs = [l.split()[0] for l in out.splitlines()[1:] if l.strip().endswith("device")]
    if preferred in devs:
        return preferred
    if len(devs) == 1:
        return devs[0]
    raise RuntimeError(f"adb: cannot pick a device (attached: {devs or 'none'})")


class Injector:
    def __init__(self, execute=False, adb=ADB, device=DEVICE):
        self.execute = execute
        self.adb = adb
        self.device = resolve_device(adb, device) if execute else device
        if execute:
            print(f"adb device: {self.device}", flush=True)
        self._cheong_last = -1e9
        self._switch_last = -1e9
        self._t0 = time.monotonic()

    def _run(self, *args):
        args = [str(a) for a in args]
        cmd = [self.adb, "-s", self.device, "shell", *args]
        if not self.execute:
            print("    [dry-run]", " ".join(args))
            return
        # NO PIPES. capture_output=True deadlocks on Windows: the adb *fork-server*
        # daemon inherits the pipe handles and never closes them, so after the adb
        # client exits Python still waits for EOF -- and run()'s timeout does not
        # help, it kills the client and then blocks draining the same pipe. A live
        # run sat there silently for 12 minutes mid-battle (2026-09-27). Nothing
        # reads adb's output anyway, so send it to DEVNULL and there is no pipe to
        # wait on.
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)
        except subprocess.TimeoutExpired:
            print("    adb timed out:", " ".join(args), flush=True)

    def tap(self, u, v):
        x, y = _px(u, v)
        self._run("input", "tap", x, y)

    def swipe(self, u0, v0, u1, v1, dur_ms=None):
        x0, y0 = _px(u0, v0)
        x1, y1 = _px(u1, v1)
        dur = dur_ms if dur_ms is not None else random.randint(160, 300)
        self._run("input", "swipe", x0, y0, x1, y1, dur)

    def back(self):
        """Android BACK. Used to unwind a half-finished lobby navigation
        (invite popup left open, room created but the friend never accepted)
        so the next round can start from a known screen."""
        self._run("input", "keyevent", "4")

    def cheong_ready(self):
        return (time.monotonic() - self._cheong_last) >= CHEONG_CD

    def switch_ready(self):
        return (time.monotonic() - self._switch_last) >= SWITCH_CD

    def execute_action(self, action):
        """Run one policy action. Returns True if performed."""
        op = action.get("op")
        if op == "summon":
            self.tap(*SUMMON_UV)
        elif op == "destroy":
            if not self.cheong_ready():
                print("    cheong on cooldown, skipping destroy")
                return False
            u, v = cell_uv(action["cell"])
            self.swipe(u, v, *CHEONG_UV)
            self._cheong_last = time.monotonic()
        elif op == "switch":
            # The switch cooldown VARIES (user) -- a fixed timer wrongly skipped
            # most swaps ("pretending"). Do not gate on a timer here; the caller
            # verifies the swap by re-reading the board and retries until it takes.
            ua, va = cell_uv(action["from"])
            ub, vb = cell_uv(action["to"])
            self.swipe(ua, va, ub, vb)
            self._switch_last = time.monotonic()
        elif op == "merge":
            ua, va = cell_uv(action["from"])
            ub, vb = cell_uv(action["to"])
            self.swipe(ua, va, ub, vb)
        elif op == "merge_destroy":
            # Merge the surplus pair, then DESTROY the (pip-2) result so no
            # higher-pip die is left on the board -- keeps it pip-1 pure for the
            # reader (a pip-2 die read as pip-1 desyncs the swap logic). Frees 2
            # cells per one skill cast (user's efficient method).
            if not self.cheong_ready():
                print("    cheong on cooldown, skipping merge_destroy")
                return False
            ua, va = cell_uv(action["from"])
            ub, vb = cell_uv(action["to"])
            self.swipe(ua, va, ub, vb)          # merge from -> to
            time.sleep(0.4)                      # let the merge settle
            self.swipe(ub, vb, *CHEONG_UV)       # destroy the merged die
            self._cheong_last = time.monotonic()
        elif op in ("align_pip", "wait"):
            print(f"    no-op ({op}): {action.get('why','')}")
            return False
        else:
            print(f"    unknown op: {op}")
            return False
        return True

    def cheong_cooldown_left(self):
        left = CHEONG_CD - (time.monotonic() - self._cheong_last)
        return max(0.0, left)
