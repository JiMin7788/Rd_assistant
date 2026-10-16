"""Input layer (M2): turn policy actions into touch input on Google Play Games.

Google Play Games (PC) has no adb, so input is posted as window messages
(WM_LBUTTON*/WM_MOUSEMOVE, WM_KEYDOWN) straight to the game's render child
window (class CROSVM_1). That works in the background -- the real mouse cursor
is not moved and the window does not need focus (verified 2026-10-16: a posted
click opened 퀘스트, a posted Esc closed it). Esc is Android BACK in GPG.

Content-normalized (u,v) map onto the same content rect the capture grabs
(client - chrome, see capture.live), so a (u,v) read off a frame is tapped back
at the same spot. Human-like jitter (a few px, tens of ms) is added per docs/00
to avoid perfectly-constant input.

Cheong's destroy has a 90s cooldown, tracked here. Default is dry-run: nothing
is injected unless execute=True.
"""
from __future__ import annotations
import ctypes
import os
import random
import time
from ctypes import wintypes

from rdom.perception.board import COLS, ROWS
from rdom.recorder.config import load_config
from rdom.recorder.geometry import Viewport, fit_chrome
from rdom.recorder.window import WindowState, find_window, set_dpi_awareness

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
WM_KEYDOWN, WM_KEYUP = 0x100, 0x101
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x200, 0x201, 0x202
MK_LBUTTON = 0x1
VK_ESCAPE = 0x1B
RENDER_CLASS = "CROSVM"            # GPG's game surface child window (CROSVM_1)
# The desktop shortcut "랜덤 다이스 2.lnk" made by Google Play Games runs this.
LAUNCH_URI = "googleplaygames://launch/?id=com.percent.aos.randomdice2&lid=2&pid=1"

SUMMON_UV = (0.50, 0.855)
CHEONG_UV = (0.19, 0.867)
UPGRADE_UV = (0.20, 0.94)
GAME_PACKAGE = "com.percent.aos.randomdice2"
LOBBY_UV = (0.50, 0.869)     # "로비로 가기" on the game-over screen
COOP_UV = (0.50, 0.745)      # "협동" (coop) on the lobby; button spans v 0.703-0.807 (GPG, 2026-10-16)
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


def _lparam(x, y):
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def _render_child(top):
    """The GPG render surface under the game's top-level window. Clicks posted
    to the top-level window or to its 'subWin' sibling are ignored."""
    hit = []

    def cb(h, _):
        cls = ctypes.create_unicode_buffer(64)
        _user32.GetClassNameW(h, cls, 64)
        if cls.value.startswith(RENDER_CLASS):
            hit.append(h)
            return False
        return True

    _user32.EnumChildWindows(top, _WNDENUMPROC(cb), 0)
    if not hit:
        raise RuntimeError(f"no {RENDER_CLASS}* child under the game window")
    return hit[0]


class Injector:
    def __init__(self, execute=False, config="config/recorder.toml"):
        self.execute = execute
        self.cfg = load_config(config)
        set_dpi_awareness()
        self._top = self._render = None
        if execute:
            self._target()
            print(f"input: window messages -> hwnd {self._render}", flush=True)
        self._cheong_last = -1e9
        self._switch_last = -1e9
        self._t0 = time.monotonic()

    def _target(self):
        """(top-level hwnd, render hwnd); re-found if the game was restarted."""
        if not (self._render and _user32.IsWindow(self._render)):
            self._top = find_window(self.cfg.target.window_title_re)
            self._render = _render_child(self._top)
        return self._top, self._render

    def _point(self, u, v, jitter=4):
        """(u,v) -> client coords of the render window (screen px of the
        captured content rect, then ScreenToClient)."""
        top, render = self._target()
        client = WindowState.read(top).client
        c = Viewport(client=client, chrome=fit_chrome(client, self.cfg.target.chrome)).content
        x = c.left + u * c.width + random.uniform(-jitter, jitter)
        y = c.top + v * c.height + random.uniform(-jitter, jitter)
        x = min(max(x, c.left), c.right - 1)
        y = min(max(y, c.top), c.bottom - 1)
        pt = wintypes.POINT(int(x), int(y))
        _user32.ScreenToClient(render, ctypes.byref(pt))
        return pt.x, pt.y

    def _post(self, msg, wparam, lparam):
        if not _user32.PostMessageW(self._render, msg, wparam, lparam):
            print(f"    PostMessage failed (err {ctypes.get_last_error()})", flush=True)

    def tap(self, u, v):
        if not self.execute:
            print(f"    [dry-run] tap {u:.3f},{v:.3f}")
            return
        lp = _lparam(*self._point(u, v))
        self._post(WM_MOUSEMOVE, 0, lp)
        self._post(WM_LBUTTONDOWN, MK_LBUTTON, lp)
        time.sleep(random.uniform(0.05, 0.09))
        self._post(WM_LBUTTONUP, 0, lp)

    def swipe(self, u0, v0, u1, v1, dur_ms=None):
        dur = dur_ms if dur_ms is not None else random.randint(160, 300)
        if not self.execute:
            print(f"    [dry-run] swipe {u0:.3f},{v0:.3f} -> {u1:.3f},{v1:.3f} {dur}ms")
            return
        x0, y0 = self._point(u0, v0)
        x1, y1 = self._point(u1, v1)
        self._post(WM_MOUSEMOVE, 0, _lparam(x0, y0))
        self._post(WM_LBUTTONDOWN, MK_LBUTTON, _lparam(x0, y0))
        time.sleep(0.03)
        steps = max(6, dur // 16)
        for i in range(1, steps + 1):
            t = i / steps
            self._post(WM_MOUSEMOVE, MK_LBUTTON,
                       _lparam(round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t)))
            time.sleep(dur / 1000 / steps)
        time.sleep(0.03)
        self._post(WM_LBUTTONUP, 0, _lparam(x1, y1))

    def back(self):
        """Android BACK (Esc in GPG). Used to unwind a half-finished lobby
        navigation (invite popup left open, room created but the friend never
        accepted) so the next round can start from a known screen."""
        if not self.execute:
            print("    [dry-run] back")
            return
        self._target()
        sc = _user32.MapVirtualKeyW(VK_ESCAPE, 0)
        self._post(WM_KEYDOWN, VK_ESCAPE, 1 | (sc << 16))
        time.sleep(0.06)
        self._post(WM_KEYUP, VK_ESCAPE, 1 | (sc << 16) | (0xC0 << 24))

    def game_in_front(self):
        """True if the Random Dice 2 window exists, False if it is gone (game
        closed). None in a dry run -- callers must not relaunch on None."""
        if not self.execute:
            return None
        try:
            self._target()
            return True
        except RuntimeError:
            return False

    def launch_game(self):
        """Start Random Dice 2 through Google Play Games (same URI as the
        desktop shortcut) -- e.g. after the game window closed."""
        if not self.execute:
            print("    [dry-run] launch", LAUNCH_URI)
            return
        self._render = None
        os.startfile(LAUNCH_URI)

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
