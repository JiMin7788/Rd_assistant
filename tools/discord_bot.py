"""Discord control for the gear bot (runs on its own, next to the supervisor).

Everyone:
  /예약          join the reservation queue (place in line by DM; room code by DM on your turn)
  /예약취소      leave the queue / give up your turn
  /대기열        queue and your place in it
  /상태          running / paused, room, queue (admins also see the last log lines)
Admins ("서버 관리" permission):
  /스샷          current emulator screen
  /정지 /재개    pause after the current game / resume   (data/PAUSE)
  /시작          start the supervisor if it is not running
  /종료          end the bot after the current game      (data/STOP)

Room codes: the game loop writes data/room.json (code + waiting/playing/closed).
While this bot runs (data/discord_bot.alive is fresh) it owns handing the code out:
  queue empty     -> public card in the room-code channel
  queue not empty -> the code goes by DM to the person whose turn it is; they have
                     TURN seconds to join, then the turn passes on. The channel card
                     only says "예약자 차례".
A turn ends when that game ends. Queue state: data/queue.json.

  python tools/discord_bot.py        (token: config/discord.toml bot_token)
"""
import asyncio, datetime, glob, io, json, os, subprocess, sys, time, tomllib, urllib.request
import discord
from discord import app_commands
import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from rdom.notify.room_state import read_room, ALIVE

DATA = os.path.join(ROOT, "data")
PAUSE, STOP, PID = (os.path.join(DATA, n) for n in ("PAUSE", "STOP", "supervisor.pid"))
QFILE = os.path.join(DATA, "queue.json")
CFG = tomllib.load(open(os.path.join(ROOT, "config", "discord.toml"), "rb"))
TURN = 300                                         # s to join after the code DM


class _Tee:                                        # console + data/discord_bot.log
    def __init__(self, *s): self.s = s
    def write(self, x):
        for s in self.s: s.write(x); s.flush()
    def flush(self):
        for s in self.s: s.flush()


sys.stdout = sys.stderr = _Tee(sys.__stdout__, open(os.path.join(DATA, "discord_bot.log"), "a", encoding="utf-8"))


def _webhook_channel(url):
    req = urllib.request.Request(url, headers={"User-Agent": "rdom-bot"})
    return int(json.loads(urllib.request.urlopen(req, timeout=10).read())["channel_id"])


CODE_CH = _webhook_channel(CFG["code_webhook"])


def running():
    try:
        pid = int(open(PID).read())
        return psutil.pid_exists(pid) and "python" in psutil.Process(pid).name().lower()
    except Exception:
        return False


# ---------------------------------------------------------------- queue state
def _load_q():
    try:
        return json.load(open(QFILE, encoding="utf-8"))
    except Exception:
        return {"queue": [], "current": None, "card": None}


Q = _load_q()
QLOCK = asyncio.Lock()


def _save_q():
    tmp = QFILE + ".tmp"
    json.dump(Q, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, QFILE)


def room_now():
    r = read_room()
    if not running():
        return {"code": None, "state": "off"}
    return r


def place_of(uid):
    if Q["current"] and Q["current"]["id"] == uid:
        return 0
    for i, e in enumerate(Q["queue"]):
        if e["id"] == uid:
            return i + 1
    return None


async def dm(uid, text=None, embed=None):
    try:
        u = client.get_user(uid) or await client.fetch_user(uid)
        await u.send(content=text, embed=embed)
        return True
    except discord.HTTPException as e:
        print("dm failed", uid, e, flush=True)
        return False


def code_embed(code):
    return discord.Embed(title="🎲 차례가 왔어요!", colour=0x5865F2,
                         description=f"## `{code}`\n친구와 하기 → 코드 입력으로 들어오세요\n"
                                     f"⏱ {TURN // 60}분 안에 안 들어오면 다음 사람에게 넘어가요\n"
                                     f"🚫 기적의 돌 터트리기 금지")


async def notify_positions():
    for i, e in enumerate(Q["queue"]):
        if e.get("told") != i + 1:
            if await dm(e["id"], f"📋 예약 순번: **{i + 1}번째** (앞에 {i}명{' + 진행 중 1명' if Q['current'] else ''})"):
                e["told"] = i + 1


# ---------------------------------------------------------------- channel card
async def set_card(kind, code=None):
    """One bot message in the room-code channel, edited in place."""
    n = len(Q["queue"])
    if kind == "public":
        e = discord.Embed(title="🎲 새 방이 열렸어요", colour=0x5865F2,
                          description=f"## `{code}`\n친구와 하기 → 코드 입력으로 들어오세요")
    elif kind == "private":
        e = discord.Embed(title="🔒 예약자 차례 진행 중", colour=0xF1C40F,
                          description=f"코드는 예약자에게 DM으로 보냈어요\n대기 {n}명 · `/예약` 으로 줄서기")
    elif kind == "playing":
        e = discord.Embed(title="🎮 게임 진행 중", colour=0x3498DB,
                          description=f"판이 끝나면 다음 방이 열려요\n대기 {n}명 · `/예약` 으로 줄서기")
    elif kind == "off":
        e = discord.Embed(title="⚫ 봇 꺼짐", colour=0x95A5A6, description="지금은 방을 열지 않아요")
    else:
        e = discord.Embed(title="⏳ 다음 방 준비 중", colour=0x95A5A6,
                          description=f"대기 {n}명 · `/예약` 으로 줄서기")
    e.set_footer(text="랜다2 기어봇 · 🚫 기적의 돌 터트리기 금지")
    key = [kind, code, n]
    card = Q.get("card") or {}
    if card.get("key") == key:
        return
    ch = client.get_channel(CODE_CH) or await client.fetch_channel(CODE_CH)
    msg = None
    if card.get("id"):
        try:
            msg = await ch.fetch_message(card["id"])
            await msg.edit(embed=e)
        except discord.HTTPException:          # deleted by someone -> post a new one
            msg = None
    if msg is None:
        msg = await ch.send(embed=e)
    Q["card"] = {"id": msg.id, "key": key}
    _save_q()


async def purge_webhook_cards():
    ch = client.get_channel(CODE_CH) or await client.fetch_channel(CODE_CH)
    async for old in ch.history(limit=50):
        if old.webhook_id is not None:
            try:
                await old.delete()
            except discord.HTTPException:
                pass


# ---------------------------------------------------------------- the turn logic
async def tick():
    room = room_now(); code, state = room.get("code"), room.get("state")
    cur = Q["current"]; now = time.time()
    if state == "playing" and cur:
        cur["played"] = True
    if cur and cur.get("played") and state in ("closed", "off", "waiting"):   # their game is over
        await dm(cur["id"], "🙏 함께 해주셔서 고마워요! 다시 하려면 `/예약`")
        Q["current"] = cur = None
    if state == "waiting" and code:
        if cur and cur.get("code") != code:                 # room was remade: same person, new code
            cur.update(code=code, since=now)
            await dm(cur["id"], embed=code_embed(code))
        elif cur and now - cur["since"] > TURN:
            await dm(cur["id"], "⌛ 시간이 지나서 다음 사람에게 차례가 넘어갔어요. 다시 하려면 `/예약`")
            Q["current"] = cur = None
        while not cur and Q["queue"]:
            nxt = Q["queue"].pop(0)
            if await dm(nxt["id"], embed=code_embed(code)):
                Q["current"] = cur = {"id": nxt["id"], "name": nxt["name"], "code": code, "since": now, "played": False}
        await notify_positions()
        await set_card("private" if cur else "public", code)
    elif state == "playing":
        await set_card("playing")
    elif state == "off":
        await set_card("off")
    else:
        await set_card("closed")
    _save_q()


async def tick_loop():
    while True:
        try:
            open(ALIVE, "w").write(str(time.time()))
            async with QLOCK:
                await tick()
        except Exception as e:
            print("tick:", repr(e), flush=True)
        await asyncio.sleep(3)


# ---------------------------------------------------------------- commands
intents = discord.Intents.default()               # no privileged intents needed
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
admin = app_commands.default_permissions(manage_guild=True)


@tree.command(name="예약", description="게임 예약 (순번과 방 코드를 DM으로 보내드려요)")
async def cmd_reserve(it: discord.Interaction):
    async with QLOCK:
        p = place_of(it.user.id)
        if p == 0:
            return await it.response.send_message("지금 차례예요! DM의 방 코드로 들어오세요.", ephemeral=True)
        if p:
            return await it.response.send_message(f"이미 예약됐어요 · {p}번째", ephemeral=True)
        if not running():
            return await it.response.send_message("지금은 봇이 꺼져 있어서 예약할 수 없어요.", ephemeral=True)
        n = len(Q["queue"]) + 1
        if not await dm(it.user.id, f"✅ 예약 완료 · **{n}번째**\n차례가 오면 방 코드를 DM으로 보내드려요. 취소는 `/예약취소`"):
            return await it.response.send_message(
                "DM을 보낼 수 없어요. 서버 설정 → 개인정보 → **다이렉트 메시지 허용**을 켜고 다시 해주세요.", ephemeral=True)
        Q["queue"].append({"id": it.user.id, "name": it.user.display_name, "t": time.time(), "told": n})
        _save_q()
    await it.response.send_message(f"✅ 예약 완료 · {n}번째 (DM 확인)", ephemeral=True)


@tree.command(name="예약취소", description="예약 취소 / 내 차례 넘기기")
async def cmd_cancel(it: discord.Interaction):
    async with QLOCK:
        p = place_of(it.user.id)
        if p is None:
            return await it.response.send_message("예약이 없어요.", ephemeral=True)
        if p == 0:
            Q["current"] = None
        else:
            Q["queue"].pop(p - 1)
        _save_q()
        await notify_positions()
    await it.response.send_message("예약을 취소했어요.", ephemeral=True)


@tree.command(name="대기열", description="예약 대기열과 내 순번")
async def cmd_queue(it: discord.Interaction):
    cur = Q["current"]
    lines = [f"▶ 진행 중: {cur['name']}" if cur else "▶ 진행 중: 없음"]
    lines += [f"{i + 1}. {e['name']}" for i, e in enumerate(Q["queue"][:15])]
    p = place_of(it.user.id)
    me = "지금 내 차례!" if p == 0 else f"내 순번: {p}번째" if p else "예약 안 함 · `/예약`"
    e = discord.Embed(title=f"📋 대기열 ({len(Q['queue'])}명)", description="\n".join(lines), colour=0x5865F2)
    e.set_footer(text=me)
    await it.response.send_message(embed=e, ephemeral=True)


def status_embed(with_log):
    st = "🟢 실행 중" if running() else "⚫ 꺼짐"
    if os.path.exists(PAUSE):
        st += " · ⏸ 일시정지(판 사이 대기)"
    if os.path.exists(STOP):
        st += " · ⏹ 종료 예약"
    room = room_now()
    lines = [{"waiting": "🚪 방 열림 · 참가자 대기 중", "playing": "🎮 게임 진행 중",
              "closed": "⏳ 다음 방 준비 중", "off": "방 없음"}.get(room.get("state"), ""),
             f"📋 예약 대기 {len(Q['queue'])}명" + (" · 예약자 차례 진행 중" if Q["current"] else "")]
    try:
        games = [json.loads(l) for l in open(os.path.join(DATA, "gear_rounds.jsonl"), encoding="utf-8") if l.strip()]
        today = datetime.date.today().isoformat()
        n = sum(1 for g in games if g.get("wall_end", "").startswith(today))
        lines.append(f"🎲 오늘 {n}판" + (f" · 마지막 판 {games[-1].get('wall_end', '')[11:16]}" if games else ""))
    except Exception:
        pass
    if with_log:
        logs = sorted(glob.glob(os.path.join(DATA, "bot_logs", "*.log")))
        if logs:
            tail = [l for l in open(logs[-1], encoding="utf-8", errors="replace").read().splitlines() if l.strip()][-8:]
            lines.append("```" + "\n".join(tail)[-1200:] + "```")
    colour = 0x2ECC71 if running() and not os.path.exists(PAUSE) else 0xF1C40F if running() else 0x95A5A6
    return discord.Embed(title=st, description="\n".join(lines), colour=colour)


@tree.command(name="상태", description="봇 상태 · 방 · 대기열")
async def cmd_status(it: discord.Interaction):
    is_admin = bool(getattr(it.user, "guild_permissions", None) and it.user.guild_permissions.manage_guild)
    await it.response.send_message(embed=status_embed(is_admin), ephemeral=not is_admin)


def _games():
    try:
        return [json.loads(l) for l in open(os.path.join(DATA, "gear_rounds.jsonl"), encoding="utf-8") if l.strip()]
    except Exception:
        return []


@tree.command(name="도움말", description="명령어 안내")
async def cmd_help(it: discord.Interaction):
    e = discord.Embed(title="🎲 랜다2 기어봇 명령어", colour=0x5865F2)
    e.add_field(name="🙋 누구나", inline=False, value=
                "`/예약` 줄서기 (순번·방 코드를 DM으로)\n`/예약취소` 예약 취소·차례 넘기기\n"
                "`/대기열` 대기열과 내 순번\n`/방코드` 지금 공개된 방 코드\n"
                "`/상태` 봇·방 상태\n`/전적` 오늘·최근 판 기록\n`/덱` 봇 덱 소개")
    e.add_field(name="🛡 관리자", inline=False, value=
                "`/스샷` 화면 · `/로그` 최근 로그\n`/정지` `/재개` 판 끝나고 일시정지·재개\n"
                "`/시작` 켜기 · `/종료` 판 끝나고 끄기\n`/건너뛰기` 지금 차례 넘기기 · `/예약초기화` 대기열 비우기\n"
                "`/공지` 안내사항에 공지 올리기")
    e.set_footer(text="🚫 봇 방에서 기적의 돌 터트리기 금지")
    await it.response.send_message(embed=e, ephemeral=True)


@tree.command(name="방코드", description="지금 공개된 방 코드 (예약자 차례면 /예약)")
async def cmd_code(it: discord.Interaction):
    room = room_now()
    if room.get("state") != "waiting" or not room.get("code"):
        msg = {"playing": "🎮 지금은 게임 중이에요. `/예약` 하면 다음 차례에 DM으로 알려드려요.",
               "off": "⚫ 봇이 꺼져 있어요."}.get(room.get("state"), "⏳ 다음 방 준비 중이에요. `/예약` 으로 줄서기")
    elif Q["current"] or Q["queue"]:
        msg = "🔒 지금은 예약자 차례예요. `/예약` 으로 줄서면 차례에 DM으로 코드를 보내드려요."
    else:
        msg = f"🎲 방 코드: **`{room['code']}`** (친구와 하기 → 코드 입력)"
    await it.response.send_message(msg, ephemeral=True)


@tree.command(name="전적", description="오늘·최근 판 기록")
async def cmd_record(it: discord.Interaction):
    games = _games(); today = datetime.date.today().isoformat()
    tg = [g for g in games if g.get("wall_end", "").startswith(today)]
    mins = [(g["t_end"] - g["t_start"]) / 60 for g in tg if "t_end" in g]
    e = discord.Embed(title="📈 전적", colour=0x9B59B6,
                      description=f"오늘 **{len(tg)}판**" + (f" · 평균 {sum(mins) / len(mins):.1f}분" if mins else "")
                                  + f" · 전체 {len(games)}판")
    for g in games[-5:][::-1]:
        st = g.get("stats") or {}
        detail = (f"합성 {st.get('merges', '-')} · 실패 {st.get('fails', '-')} · 완성 {'O' if st.get('complete') else 'X'}"
                  if st else g.get("result", ""))
        e.add_field(name=f"{g.get('wall_end', '')[5:16].replace('T', ' ')} · {(g['t_end'] - g['t_start']) / 60:.0f}분",
                    value=detail, inline=False)
    await it.response.send_message(embed=e, ephemeral=True)


@tree.command(name="덱", description="봇 덱 소개")
async def cmd_deck(it: discord.Interaction):
    e = discord.Embed(title="🃏 봇 덱 · 기어덱", colour=0xE67E22,
                      description="**기어 · 파멸 · 버블 · 적응 · 성장**\n"
                                  "목표 필드: 버블 1~3 + 나머지 전부 이어진 기어 (평균 눈금 2.2↑)\n"
                                  "필드 완성 후 기어 파워업 · 초월 · 사냥")
    e.set_footer(text="협동 모드 · 🚫 기적의 돌 터트리기 금지")
    await it.response.send_message(embed=e, ephemeral=True)


@admin
@tree.command(name="로그", description="[관리자] 최근 로그")
@app_commands.describe(lines="줄 수 (기본 30)")
async def cmd_log(it: discord.Interaction, lines: int = 30):
    logs = sorted(glob.glob(os.path.join(DATA, "bot_logs", "*.log")))
    if not logs:
        return await it.response.send_message("로그가 없어요.", ephemeral=True)
    tail = [l for l in open(logs[-1], encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
    await it.response.send_message("```" + "\n".join(tail[-max(1, min(lines, 60)):])[-1900:] + "```", ephemeral=True)


@admin
@tree.command(name="건너뛰기", description="[관리자] 지금 예약자 차례를 다음 사람에게 넘기기")
async def cmd_skip(it: discord.Interaction):
    async with QLOCK:
        cur = Q["current"]
        if not cur:
            return await it.response.send_message("진행 중인 예약자 차례가 없어요.", ephemeral=True)
        await dm(cur["id"], "⏭ 관리자가 차례를 다음 사람에게 넘겼어요. 다시 하려면 `/예약`")
        Q["current"] = None; _save_q()
    await it.response.send_message(f"⏭ {cur['name']} 차례를 넘겼어요.", ephemeral=True)


@admin
@tree.command(name="예약초기화", description="[관리자] 예약 대기열 비우기")
async def cmd_clear(it: discord.Interaction):
    async with QLOCK:
        users = ([Q["current"]] if Q["current"] else []) + Q["queue"]
        for u in users:
            await dm(u["id"], "📋 관리자가 예약 대기열을 초기화했어요. 다시 하려면 `/예약`")
        Q["queue"] = []; Q["current"] = None; _save_q()
    await it.response.send_message(f"대기열을 비웠어요 ({len(users)}명).", ephemeral=True)


NOTICE_CH = 1558097080390516736                    # 📢┃안내사항


@admin
@tree.command(name="공지", description="[관리자] 안내사항 채널에 공지 올리기")
@app_commands.describe(title="제목", text="내용 (줄바꿈은 \\n)")
async def cmd_notice(it: discord.Interaction, title: str, text: str):
    ch = client.get_channel(NOTICE_CH) or await client.fetch_channel(NOTICE_CH)
    e = discord.Embed(title=f"📢 {title}", description=text.replace("\\n", "\n"), colour=0xE67E22,
                      timestamp=datetime.datetime.now(datetime.timezone.utc))
    e.set_footer(text=it.user.display_name)
    await ch.send(embed=e)
    await it.response.send_message("공지를 올렸어요.", ephemeral=True)


def screencap():
    """The game content area of the Google Play Games window (no adb on GPG)."""
    from PIL import ImageGrab
    from rdom.recorder.config import load_config
    from rdom.recorder.geometry import Viewport, fit_chrome
    from rdom.recorder.window import WindowState, find_window, set_dpi_awareness
    set_dpi_awareness()
    cfg = load_config(os.path.join(ROOT, "config", "recorder.toml"))
    client = WindowState.read(find_window(cfg.target.window_title_re)).client
    c = Viewport(client=client, chrome=fit_chrome(client, cfg.target.chrome)).content
    im = ImageGrab.grab(bbox=c.as_tuple(), all_screens=True)
    im = im.resize((im.width // 2, im.height // 2))   # a full-size png is ~3 MB
    buf = io.BytesIO(); im.convert("RGB").save(buf, "JPEG", quality=85)
    return buf.getvalue()


@admin
@tree.command(name="스샷", description="[관리자] 지금 에뮬레이터 화면")
async def cmd_shot(it: discord.Interaction):
    await it.response.defer()
    try:
        jpg = await asyncio.to_thread(screencap)
        await it.followup.send(file=discord.File(io.BytesIO(jpg), "screen.jpg"))
    except Exception as e:
        await it.followup.send(f"스샷 실패: {e}")


@admin
@tree.command(name="정지", description="[관리자] 지금 판이 끝나면 일시정지")
async def cmd_pause(it: discord.Interaction):
    open(PAUSE, "w").close()
    await it.response.send_message("⏸ 지금 판이 끝나면 일시정지합니다. (/재개 로 재개)")


@admin
@tree.command(name="재개", description="[관리자] 일시정지 해제")
async def cmd_resume(it: discord.Interaction):
    if os.path.exists(PAUSE):
        os.remove(PAUSE)
    msg = "▶ 재개합니다." if running() else "봇이 꺼져 있습니다. /시작 으로 켜세요."
    await it.response.send_message(msg)


@admin
@tree.command(name="시작", description="[관리자] 봇 켜기 (꺼져 있을 때)")
async def cmd_start(it: discord.Interaction):
    if running():
        await it.response.send_message("이미 실행 중입니다.")
        return
    for f in (PAUSE, STOP):
        if os.path.exists(f):
            os.remove(f)
    # same console as run_all.py (no new window); output goes to a log file
    log = open(os.path.join(DATA, "bot_logs", "supervisor.log"), "a", encoding="utf-8")
    subprocess.Popen([sys.executable, "-u", "-W", "ignore", os.path.join(ROOT, "tools", "supervisor.py")],
                     cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    await it.response.send_message("▶ 봇을 켭니다.")


@admin
@tree.command(name="종료", description="[관리자] 지금 판이 끝나면 봇 종료")
async def cmd_stop(it: discord.Interaction):
    if not running():
        await it.response.send_message("봇이 이미 꺼져 있습니다.")
        return
    open(STOP, "w").close()
    await it.response.send_message("⏹ 지금 판이 끝나면 봇을 종료합니다.")


@client.event
async def on_message(msg: discord.Message):
    # fallback webhook code card (posted while this bot was down) -> keep only the newest
    if msg.channel.id != CODE_CH or msg.webhook_id is None:
        return
    async for old in msg.channel.history(limit=50, before=msg):
        if old.webhook_id is not None:
            try:
                await old.delete()
            except discord.HTTPException as e:
                print("delete failed:", e, flush=True)


async def presence_loop():
    """Member-list line under the bot: what it is doing right now."""
    while True:
        try:
            n = 0
            today = datetime.date.today().isoformat()
            for l in open(os.path.join(DATA, "gear_rounds.jsonl"), encoding="utf-8"):
                n += today in l
            q = f" · 대기 {len(Q['queue'])}명" if Q["queue"] else ""
            if not running():
                act, st = "꺼짐", discord.Status.idle
            elif os.path.exists(PAUSE):
                act, st = f"일시정지 · 오늘 {n}판", discord.Status.idle
            else:
                act, st = f"랜다2 협동 · 오늘 {n}판{q}", discord.Status.online
            await client.change_presence(status=st, activity=discord.Game(act))
        except Exception as e:
            print("presence:", e, flush=True)
        await asyncio.sleep(60)


@client.event
async def on_ready():
    if not getattr(client, "_tasks", None):
        await purge_webhook_cards()               # the bot's own card takes over
        client._tasks = [asyncio.create_task(presence_loop()), asyncio.create_task(tick_loop())]
    for g in client.guilds:                       # guild sync: commands appear immediately
        tree.copy_global_to(guild=g)
        await tree.sync(guild=g)
    print("discord bot ready:", client.user, [g.name for g in client.guilds], flush=True)


@client.event
async def on_guild_join(g):
    tree.copy_global_to(guild=g); await tree.sync(guild=g)
    print("joined", g.name, flush=True)


if __name__ == "__main__":
    client.run(CFG["bot_token"], log_handler=None)
