"""Discord control for the gear bot (runs on its own, next to the supervisor).

Slash commands (server members with "서버 관리" permission only):
  /상태          running / paused, last games, last log lines
  /스샷          current emulator screen
  /정지          pause after the current game   (data/PAUSE)
  /재개          resume                          (removes data/PAUSE)
  /시작 [until]  start the supervisor if it is not running
  /종료          end the bot after the current game (data/STOP)
Room-code channel: when the webhook posts a new code, older code messages are
deleted so only the current room is visible.

  python tools/discord_bot.py        (token: config/discord.toml bot_token)
"""
import asyncio, datetime, glob, io, json, os, subprocess, sys, tomllib, urllib.request
import discord
from discord import app_commands
import psutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from rdom.input.inject import ADB, resolve_device

DATA = os.path.join(ROOT, "data")
PAUSE, STOP, PID = (os.path.join(DATA, n) for n in ("PAUSE", "STOP", "supervisor.pid"))
CFG = tomllib.load(open(os.path.join(ROOT, "config", "discord.toml"), "rb"))


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


def status_text():
    st = "🟢 실행 중" if running() else "⚫ 꺼짐"
    if os.path.exists(PAUSE):
        st += " · ⏸ 일시정지(판 사이 대기)"
    if os.path.exists(STOP):
        st += " · ⏹ 종료 예약"
    lines = [st]
    try:
        games = [json.loads(l) for l in open(os.path.join(DATA, "gear_rounds.jsonl"), encoding="utf-8") if l.strip()]
        today = datetime.date.today().isoformat()
        n = sum(1 for g in games if g.get("wall_end", "").startswith(today))
        if games:
            g = games[-1]
            lines.append(f"오늘 {n}판 · 마지막 판 {g.get('wall_end', '')[11:16]} 결과 {g.get('result')}")
    except Exception:
        pass
    logs = sorted(glob.glob(os.path.join(DATA, "bot_logs", "*.log")))
    if logs:
        tail = [l for l in open(logs[-1], encoding="utf-8", errors="replace").read().splitlines() if l.strip()][-8:]
        lines.append("```" + "\n".join(tail)[-1500:] + "```")
    return "\n".join(lines)


def screencap():
    dev = resolve_device()
    png = subprocess.run([ADB, "-s", dev, "exec-out", "screencap", "-p"], capture_output=True, timeout=20).stdout
    import numpy as np, cv2                       # shrink: a full 1080x1920 png is ~3 MB
    im = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    ok, buf = cv2.imencode(".jpg", cv2.resize(im, None, fx=0.5, fy=0.5), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()


intents = discord.Intents.default()               # no privileged intents needed
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
admin = app_commands.default_permissions(manage_guild=True)


@admin
@tree.command(name="상태", description="봇 상태와 최근 로그")
async def cmd_status(it: discord.Interaction):
    head, _, rest = status_text().partition("\n")
    e = discord.Embed(title=head, description=rest or None,
                      colour=0x2ECC71 if running() and not os.path.exists(PAUSE) else 0xF1C40F if running() else 0x95A5A6)
    await it.response.send_message(embed=e)


@admin
@tree.command(name="스샷", description="지금 에뮬레이터 화면")
async def cmd_shot(it: discord.Interaction):
    await it.response.defer()
    try:
        jpg = await asyncio.to_thread(screencap)
        await it.followup.send(file=discord.File(io.BytesIO(jpg), "screen.jpg"))
    except Exception as e:
        await it.followup.send(f"스샷 실패: {e}")


@admin
@tree.command(name="정지", description="지금 판이 끝나면 일시정지")
async def cmd_pause(it: discord.Interaction):
    open(PAUSE, "w").close()
    await it.response.send_message("⏸ 지금 판이 끝나면 일시정지합니다. (/재개 로 재개)")


@admin
@tree.command(name="재개", description="일시정지 해제")
async def cmd_resume(it: discord.Interaction):
    if os.path.exists(PAUSE):
        os.remove(PAUSE)
    msg = "▶ 재개합니다." if running() else "봇이 꺼져 있습니다. /시작 으로 켜세요."
    await it.response.send_message(msg)


@admin
@tree.command(name="시작", description="봇 켜기 (꺼져 있을 때)")
@app_commands.describe(until="종료 시각 HH:MM (기본 23:59)")
async def cmd_start(it: discord.Interaction, until: str = "23:59"):
    if running():
        await it.response.send_message("이미 실행 중입니다.")
        return
    try:
        datetime.datetime.strptime(until, "%H:%M")
    except ValueError:
        await it.response.send_message("시각은 HH:MM 형식으로 (예: 23:30)")
        return
    for f in (PAUSE, STOP):
        if os.path.exists(f):
            os.remove(f)
    subprocess.Popen(["cmd", "/c", os.path.join(ROOT, "봇 시작.bat"), "--until", until],
                     cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE)
    await it.response.send_message(f"▶ 봇을 켭니다 (종료 {until}).")


@admin
@tree.command(name="종료", description="지금 판이 끝나면 봇 종료")
async def cmd_stop(it: discord.Interaction):
    if not running():
        await it.response.send_message("봇이 이미 꺼져 있습니다.")
        return
    open(STOP, "w").close()
    await it.response.send_message("⏹ 지금 판이 끝나면 봇을 종료합니다.")


@client.event
async def on_message(msg: discord.Message):
    # a new room code from the webhook -> delete the older ones (only the live room stays)
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
            if not running():
                act, st = "꺼짐", discord.Status.idle
            elif os.path.exists(PAUSE):
                act, st = f"일시정지 · 오늘 {n}판", discord.Status.idle
            else:
                act, st = f"랜다2 협동 · 오늘 {n}판", discord.Status.online
            await client.change_presence(status=st, activity=discord.Game(act))
        except Exception as e:
            print("presence:", e, flush=True)
        await asyncio.sleep(60)


@client.event
async def on_ready():
    if not getattr(client, "_presence", None):
        client._presence = asyncio.create_task(presence_loop())
    for g in client.guilds:                       # guild sync: commands appear immediately
        tree.copy_global_to(guild=g)
        await tree.sync(guild=g)
    print("discord bot ready:", client.user, [g.name for g in client.guilds], flush=True)


@client.event
async def on_guild_join(g):
    tree.copy_global_to(guild=g); await tree.sync(guild=g)
    print("joined", g.name, flush=True)


client.run(CFG["bot_token"], log_handler=None)
