"""Input layer (M2): turn policy actions into touch input on Google Play Games.

Google Play Games (PC) has no adb, so input is posted as window messages
(WM_LBUTTON*/WM_MOUSEMOVE, WM_KEYDOWN) straight to the game's render child
window (class CROSVM_1). The real mouse cursor is not moved (verified 2026-10-16:
a posted click opened 퀘스트, a posted Esc closed it). Esc is Android BACK in GPG.

Background input WITHOUT focus is NOT possible with two GPG instances (the Master's
2026-11-05 probe): a posted click to the render child of the non-foreground window is
ignored (3 of 3), while WM_ACTIVATEAPP + WM_NCACTIVATE + WM_ACTIVATE to the top window and
WM_SETFOCUS to the render child made it work (2 of 2) and really made that window the
foreground window. Variants that did not change the foreground window: WM_SETFOCUS only,
WM_ACTIVATEAPP only, WM_NCACTIVATE only, WM_ACTIVATE+WM_SETFOCUS on the render child.
Activation waits until the window is really in front (ACTIVATE_SETTLE_S). So every gesture of the executing
Injector first takes a cross-process named mutex (the two bots take turns, one bot's drag is
never cut by the other activating its window) and the foreground lease (a burst of gestures
stays with one bot, see HOLD_S / QUANTUM_S), activates its own window, then posts.
Rendering/capture of a background window is unaffected. The game windows therefore take the
foreground on every input while the bots run (accepted by the user).

Content-normalized (u,v) map onto the same content rect the capture grabs
(client - chrome, see capture.live), so a (u,v) read off a frame is tapped back
at the same spot. Human-like jitter (a few px, tens of ms) is added per docs/00
to avoid perfectly-constant input.

Cheong's destroy has a 90s cooldown, tracked here. Default is dry-run: nothing
is injected unless execute=True.

LDPlayer (config [input] backend "adb") uses AdbInjector instead: the same
interface, input sent with `adb shell input`. make_injector picks the class
from the config.
"""
from __future__ import annotations
import contextlib
import ctypes
import mmap
import os
import random
import re
import struct
import subprocess
import time
from ctypes import wintypes

from rdom.perception.board import COLS, ROWS
from rdom.recorder.config import load_config
from rdom.recorder.geometry import Viewport, fit_chrome
from rdom.recorder.window import WindowState, find_window, set_dpi_awareness

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.BringWindowToTop.argtypes = [wintypes.HWND]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, wintypes.LPDWORD]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, wintypes.LPDWORD]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
WM_KEYDOWN, WM_KEYUP = 0x100, 0x101
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x200, 0x201, 0x202
WM_ACTIVATE, WM_SETFOCUS, WM_NCACTIVATE, WM_ACTIVATEAPP = 0x6, 0x7, 0x86, 0x1C
MK_LBUTTON = 0x1
INPUT_MUTEX = "Local\\rdom_input"     # shared by every bot process on this desktop session
LOCK_TIMEOUT_MS = 5000                # a gesture that cannot get the lock in 5 s is skipped
# AI-NOTE: the user saw joiner accept taps swallowed with a 0.03 s settle; the game needs time after the
# window really is in front before it accepts a touch.
ACTIVATE_SETTLE_S = 0.15              # pause after the window is confirmed foreground, before the first post
FG_POLL_S = 0.02                      # GetForegroundWindow poll period while waiting for the switch
FG_POLL_MAX_S = 0.6                   # give up waiting for the foreground switch after this
FG_WARN_EVERY_S = 60.0                # rate limit of the "did not become foreground" log line
# AI-NOTE: foreground lease (rdT11). The mutex alone is released after every gesture, so two bots acting at
# once flipped the foreground on almost every gesture (~170 switches per round, each ~0.2 s). The lease lives
# in named shared memory (read/written only while holding the mutex): the bot that owns it keeps the foreground
# for a burst; the other bot waits (polling) instead of grabbing the mutex between two gestures.
LEASE_TAG = "rdom_input_lease"        # named shared memory shared by every bot process
HOLD_S = 0.8                          # a burst: the lease stays with the owner this long after its last gesture
QUANTUM_S = 2.5                       # max continuous turn while the other bot waits, then hand over
LEASE_POLL_S = 0.02                   # sleep between lease checks while the other bot owns it
_LEASE_FMT = "<IIdd"                  # owner pid, waiting pid, lease_until, owner_since (monotonic seconds)
VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x2
WAIT_OBJECT_0, WAIT_ABANDONED = 0, 0x80
VK_ESCAPE = 0x1B
RENDER_CLASS = "CROSVM"            # GPG's game surface child window (CROSVM_1)
# The desktop shortcut "랜덤 다이스 2.lnk" made by Google Play Games runs this.
LAUNCH_URI = "googleplaygames://launch/?id=com.percent.aos.randomdice2&lid=2&pid=1"

SUMMON_UV = (0.50, 0.855)
CHEONG_UV = (0.19, 0.867)
UPGRADE_UV = (0.20, 0.94)
GAME_PACKAGE = "com.percent.aos.randomdice2"
GAME_ACTIVITY = "com.unity3d.player.UnityPlayerActivity"   # cmd package resolve-activity
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


class _LeaseStore:
    """The lease record in named shared memory. Callers hold the input mutex while using it."""

    def __init__(self, tag=LEASE_TAG):
        self._m = mmap.mmap(-1, 64, tagname=tag)     # zero-filled when first created: no owner

    def read(self):
        owner, waiting, until, since = struct.unpack_from(_LEASE_FMT, self._m, 0)
        return {"owner": owner, "waiting": waiting, "lease_until": until, "owner_since": since}

    def write(self, st):
        struct.pack_into(_LEASE_FMT, self._m, 0, st["owner"], st["waiting"], st["lease_until"], st["owner_since"])


def _open_lease_store():
    try:
        return _LeaseStore()
    except (OSError, ValueError) as e:
        print(f"    input lease unavailable ({e}) -- mutex only", flush=True)
        return None


def _pid_alive(pid):
    """True while a process with this pid exists (a dead owner never blocks)."""
    h = _kernel32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ctypes.get_last_error() == 5            # access denied: it exists
    try:
        code = wintypes.DWORD()
        return bool(_kernel32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
    finally:
        _kernel32.CloseHandle(h)


class _ActionBase:
    """Policy-action execution shared by both input backends: the cheong (90 s)
    and switch cooldowns and the op dispatch. A backend only supplies tap/swipe."""

    last_gesture_ok = True      # AdbInjector / dry run: always confirmed

    def __init__(self):
        self._cheong_last = -1e9
        self._switch_last = -1e9
        self._t0 = time.monotonic()

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


class Injector(_ActionBase):
    def __init__(self, execute=False, config="config/recorder.toml"):
        super().__init__()
        self.execute = execute
        self.cfg = load_config(config)
        set_dpi_awareness()
        self._top = self._render = None
        self._mutex = None
        self._fg_warn_at = -1e9
        self.last_gesture_ok = True      # False: last gesture lock-timed-out or window not confirmed in front
        self.stats = {"gestures": 0, "switches": 0, "not_foreground": 0, "lock_timeouts": 0,
                      "ready_ms_total": 0.0, "ready_ms_max": 0.0,      # gesture start -> post, all gestures
                      "waited": 0, "waited_ms_total": 0.0, "waited_ms_max": 0.0}   # same, gestures that waited for the lease
        self._store = None          # lease store, opened on the first executing gesture (False = unavailable)
        self._pid = os.getpid()
        if execute:
            self._target()
            print(f"input: window messages -> hwnd {self._render}", flush=True)

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

    def _lock(self, timeout_ms):
        """Take the cross-process input mutex. False on timeout."""
        if self._mutex is None:
            self._mutex = _kernel32.CreateMutexW(None, False, INPUT_MUTEX)
        r = _kernel32.WaitForSingleObject(self._mutex, timeout_ms)
        return r in (WAIT_OBJECT_0, WAIT_ABANDONED)   # abandoned = the other bot died holding it: ours now

    def _other_waiting(self, st):
        w = st["waiting"]
        return w not in (0, self._pid) and _pid_alive(w)

    def _must_wait(self, st, now):
        """True when the other bot's lease (or our own hand-over) keeps us from starting a gesture now."""
        o = st["owner"]
        if o == self._pid:
            # our turn ran past QUANTUM_S and the other bot waits: it gets the next turn (we did not renew)
            return (now - st["owner_since"] >= QUANTUM_S and now - st["lease_until"] < HOLD_S
                    and self._other_waiting(st))
        if o == 0 or st["lease_until"] <= now or now - st["owner_since"] >= QUANTUM_S:
            return False
        return _pid_alive(o)

    def _take_turn(self, t_begin):
        """Mutex + lease. -> (got the turn with the mutex held, had to wait for the other bot's lease).
        The lease wait counts against LOCK_TIMEOUT_MS."""
        deadline = t_begin + LOCK_TIMEOUT_MS / 1000
        if self._store is None:
            self._store = _open_lease_store() or False
        waited = False
        while True:
            left_ms = int((deadline - time.monotonic()) * 1000)
            if left_ms <= 0 or not self._lock(left_ms):
                print(f"    input lock timeout ({LOCK_TIMEOUT_MS} ms) -- gesture skipped", flush=True)
                return False, waited
            if not self._store:
                return True, waited
            st, now = self._store.read(), time.monotonic()
            if not self._must_wait(st, now):
                if st["owner"] != self._pid or st["lease_until"] <= now:
                    st["owner_since"] = now              # a new turn
                st["owner"] = self._pid
                if st["waiting"] == self._pid:
                    st["waiting"] = 0
                self._store.write(st)
                return True, waited
            if st["owner"] != self._pid:
                st["waiting"] = self._pid
                self._store.write(st)
            _kernel32.ReleaseMutex(self._mutex)
            waited = True
            time.sleep(LEASE_POLL_S)

    def _renew(self):
        """End of a gesture (mutex held): keep the lease for HOLD_S, unless our turn is over."""
        if not self._store:
            return
        st, now = self._store.read(), time.monotonic()
        st["owner"] = self._pid
        over = now - st["owner_since"] >= QUANTUM_S and self._other_waiting(st)
        st["lease_until"] = now if over else now + HOLD_S     # over: do not renew, the other bot is next
        self._store.write(st)

    def _force_foreground(self, top):
        """Robust foreground switch: attach to the current foreground thread's input queue, press and
        release a synthetic ALT (lifts the foreground lock), SetForegroundWindow + BringWindowToTop, detach."""
        fg = _user32.GetForegroundWindow()
        cur = _kernel32.GetCurrentThreadId()
        fg_thread = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = bool(fg_thread and fg_thread != cur and _user32.AttachThreadInput(cur, fg_thread, True))
        try:
            _user32.keybd_event(VK_MENU, 0, 0, 0)
            _user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            _user32.SetForegroundWindow(top)
            _user32.BringWindowToTop(top)
        finally:
            if attached:
                _user32.AttachThreadInput(cur, fg_thread, False)

    def _activate(self):
        """Make our window the foreground window; background posts are ignored with two GPG
        instances (module docstring). True when it is confirmed in front, False if it never got there."""
        top, render = self._top, self._render
        if _user32.GetForegroundWindow() == top:
            return True                      # no switch, no delay
        self.stats["switches"] += 1
        _user32.SendMessageW(top, WM_ACTIVATEAPP, 1, 0)
        _user32.SendMessageW(top, WM_NCACTIVATE, 1, 0)
        _user32.SendMessageW(top, WM_ACTIVATE, 1, 0)
        _user32.SendMessageW(render, WM_SETFOCUS, 0, 0)
        if _user32.GetForegroundWindow() != top:     # the messages alone did not do it
            self._force_foreground(top)
        deadline = time.monotonic() + FG_POLL_MAX_S
        while _user32.GetForegroundWindow() != top:
            if time.monotonic() >= deadline:
                self.stats["not_foreground"] += 1
                if time.monotonic() - self._fg_warn_at >= FG_WARN_EVERY_S:
                    self._fg_warn_at = time.monotonic()
                    print("    window did not become the foreground window (input may be ignored)", flush=True)
                return False
            time.sleep(FG_POLL_S)
        time.sleep(ACTIVATE_SETTLE_S)
        return True

    @contextlib.contextmanager
    def _gesture(self):
        """Mutex + lease + activate for the WHOLE gesture; yields False (post nothing) when the turn
        timed out. The mutex is released in a finally, also when posting raises. Sets last_gesture_ok."""
        self._target()
        t_begin = time.monotonic()
        self.stats["gestures"] += 1
        got, waited = self._take_turn(t_begin)
        if not got:
            self.stats["lock_timeouts"] += 1
            self.last_gesture_ok = False
            yield False
            return
        try:
            # AI-NOTE: posts go out even when the window never came to front (they may still work); the
            # caller learns from last_gesture_ok that the gesture is not trustworthy.
            self.last_gesture_ok = self._activate()
            ms = (time.monotonic() - t_begin) * 1000
            s = self.stats
            s["ready_ms_total"] += ms; s["ready_ms_max"] = max(s["ready_ms_max"], ms)
            if waited:
                s["waited"] += 1; s["waited_ms_total"] += ms; s["waited_ms_max"] = max(s["waited_ms_max"], ms)
            yield True
        finally:
            try:
                self._renew()
            finally:
                _kernel32.ReleaseMutex(self._mutex)
            # AI-NOTE: no LOCK_YIELD_S sleep any more (removed): the other bot waits on the lease by polling,
            # so an immediate re-take by the owner no longer starves it.

    def _post(self, msg, wparam, lparam):
        if not _user32.PostMessageW(self._render, msg, wparam, lparam):
            print(f"    PostMessage failed (err {ctypes.get_last_error()})", flush=True)

    def tap(self, u, v):
        if not self.execute:
            print(f"    [dry-run] tap {u:.3f},{v:.3f}")
            return
        with self._gesture() as ok:
            if not ok:
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
        with self._gesture() as ok:     # the lock covers the whole drag
            if not ok:
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
        with self._gesture() as ok:
            if not ok:
                return
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


ADB_FALLBACK_SIZE = (1440, 2560)


def _px(u, v, res_w, res_h, jitter=5):
    """(u,v) -> android pixels, jittered and clamped to the screen."""
    x = int(u * res_w + random.uniform(-jitter, jitter))
    y = int(v * res_h + random.uniform(-jitter, jitter))
    return max(0, min(res_w - 1, x)), max(0, min(res_h - 1, y))


def parse_wm_size(text):
    """(w, h) from `wm size` output, or None. An 'Override size' line wins over
    'Physical size': it is what the screen currently renders."""
    found = {}
    for kind, w, h in re.findall(r"(Physical|Override) size:\s*(\d+)x(\d+)", text or ""):
        found[kind] = (int(w), int(h))
    return found.get("Override") or found.get("Physical")


def resolve_device(adb, preferred=""):
    """The adb serial to use. LDPlayer shows up as 127.0.0.1:5555 or as
    emulator-5554 depending on how adb was started; a hard-coded serial that is
    not attached makes every tap fail SILENTLY (stdout/err go to DEVNULL) -- a
    2026-10-07 run tapped 친구와 하기 into the void. Prefer `preferred`, else the
    single attached device; raise if there is none or several."""
    import tempfile
    with tempfile.TemporaryFile("w+") as fh:      # a file, not a pipe: see AdbInjector._run on adb pipes
        subprocess.run([adb, "devices"], stdout=fh, stderr=subprocess.DEVNULL, timeout=10)
        fh.seek(0); out = fh.read()
    devs = [l.split()[0] for l in out.splitlines()[1:] if l.strip().endswith("device")]
    if preferred in devs:
        return preferred
    if len(devs) == 1:
        return devs[0]
    raise RuntimeError(f"adb: cannot pick a device (attached: {devs or 'none'})")


class AdbInjector(_ActionBase):
    """Same interface as Injector, input via `adb shell input` (LDPlayer)."""

    def __init__(self, execute=False, config="config/recorder_ld.toml"):
        super().__init__()
        self.execute = execute
        self.cfg = load_config(config)
        self.adb = self.cfg.input.adb
        self.device = self.cfg.input.serial
        self.res_w, self.res_h = ADB_FALLBACK_SIZE
        if execute:
            self.device = resolve_device(self.adb, self.device)
            print(f"adb device: {self.device}", flush=True)
            # AI-NOTE: read once; the size is fixed for a running emulator and every tap needs it.
            size = parse_wm_size(self._out("wm", "size"))
            if size:
                self.res_w, self.res_h = size
            else:
                print("adb: wm size unreadable -- using 1440x2560", flush=True)

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

    def _out(self, *args):
        """adb shell output via a temp FILE (a pipe deadlocks, see _run). '' on failure."""
        import tempfile
        with tempfile.TemporaryFile() as fh:
            try:
                subprocess.run([self.adb, "-s", self.device, "shell", *map(str, args)],
                               stdout=fh, stderr=subprocess.DEVNULL, timeout=10)
            except (subprocess.TimeoutExpired, OSError):
                # AI-NOTE: adb.exe missing or crashing at spawn raises OSError /
                # FileNotFoundError; callers (game_in_front) rely on "" = unknown.
                return ""
            fh.seek(0)
            return fh.read().decode("utf-8", "replace")

    def tap(self, u, v):
        x, y = _px(u, v, self.res_w, self.res_h)
        self._run("input", "tap", x, y)

    def swipe(self, u0, v0, u1, v1, dur_ms=None):
        x0, y0 = _px(u0, v0, self.res_w, self.res_h)
        x1, y1 = _px(u1, v1, self.res_w, self.res_h)
        dur = dur_ms if dur_ms is not None else random.randint(160, 300)
        self._run("input", "swipe", x0, y0, x1, y1, dur)

    def back(self):
        """Android BACK. Used to unwind a half-finished lobby navigation
        (invite popup left open, room created but the friend never accepted)
        so the next round can start from a known screen."""
        self._run("input", "keyevent", "4")

    def game_in_front(self):
        """True if Random Dice 2 is the focused app, False if another app is.
        None if it cannot be told (dry run / adb failure) -- callers must not
        relaunch on None."""
        if not self.execute:
            return None
        out = self._out("dumpsys", "window")
        focus = [l for l in out.splitlines() if "mCurrentFocus" in l]
        if not focus:
            return None
        return GAME_PACKAGE in focus[0]

    def launch_game(self):
        """Start (or bring back) Random Dice 2 -- e.g. the emulator sits on the
        launcher home screen after the game closed (2026-10-11)."""
        # `monkey` is missing on LDPlayer 14 -> start the launcher activity directly
        self._run("am", "start", "-n", f"{GAME_PACKAGE}/{GAME_ACTIVITY}")


def make_injector(config_path="config/recorder.toml", execute=False):
    """AdbInjector when the config's [input] backend is "adb", else Injector."""
    if load_config(config_path).input.backend == "adb":
        return AdbInjector(execute=execute, config=config_path)
    return Injector(execute=execute, config=config_path)
