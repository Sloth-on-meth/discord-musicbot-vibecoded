import discord
from discord.ext import commands
import asyncio
import yt_dlp
import json
import openai
import re

# Load config
with open("config.json", "r") as f:
    config = json.load(f)

TOKEN = config["token"]
log_channel_id = config.get("musicbot_log_channel")

client = openai.OpenAI(api_key=config["openai_api_key"])

ytdl_opts = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'default_search': 'ytsearch1',
    'source_address': '0.0.0.0',
}
ytdl = yt_dlp.YoutubeDL(ytdl_opts)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Helper: embed logger
def make_embed(desc: str, color=discord.Color.blurple(), thumb: str = None):
    embed = discord.Embed(description=desc, color=color, timestamp=discord.utils.utcnow())
    if thumb:
        embed.set_thumbnail(url=thumb)
    return embed

async def log_embed(message: str, color=discord.Color.blurple()):
    if not log_channel_id:
        print("No log channel configured.")
        return
    chan = bot.get_channel(log_channel_id)
    if not chan:
        print("Log channel not found.")
        return
    embed = make_embed(message, color)
    await chan.send(embed=embed)

# TTS
tts_lock = asyncio.Lock()
async def speak_tts(text: str) -> str:
    path = "now.mp3"
    resp = client.audio.speech.create(model="tts-1", voice="alloy", input=text, response_format="mp3")
    with open(path, "wb") as f:
        f.write(resp.content)
    return path

# Music source
def extract_vid_id(url):
    m = re.search(r"(?:youtube\.com/.+v=|youtu\.be/)([^&?]{11})", url)
    return m.group(1) if m else None

class YTDLSource:
    def __init__(self, data):
        self.title = data.get("title")
        self.url = data.get("url")
        self.thumbnail = data.get("thumbnail")
        self.video_id = extract_vid_id(self.url)

    @classmethod
    async def from_query(cls, query, loop):
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
        if "entries" in data:
            data = data["entries"][0]
        return cls(data)

    @classmethod
    async def get_recommendations(cls, vid_id, loop):
        opts = {'extract_flat': True, 'quiet': True, 'get_related': True, 'playlist_items': '1-3'}
        with yt_dlp.YoutubeDL(opts) as ytdl_r:
            data = await loop.run_in_executor(None, lambda: ytdl_r.extract_info(f"https://www.youtube.com/watch?v={vid_id}", download=False))
            return [f"https://www.youtube.com/watch?v={e['id']}" for e in data.get('entries', [])]

# Queue
class MusicQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.current = None
        self.autoplay = True
        self.last_vid = None
        self.next_event = asyncio.Event()

    async def add(self, src):
        await self.queue.put(src)
        if src.video_id:
            self.last_vid = src.video_id
        await log_embed(f"Added to queue: **{src.title}**", discord.Color.green())

    async def player_loop(self, ctx, embed_msg):
        while True:
            self.next_event.clear()
            if self.queue.empty() and self.autoplay and self.last_vid:
                recs = await YTDLSource.get_recommendations(self.last_vid, bot.loop)
                if recs:
                    info_embed = make_embed("Queue empty, fetching recommendations...", discord.Color.blue())
                    await embed_msg.edit(embed=info_embed)
                    for url in recs:
                        try:
                            src = await YTDLSource.from_query(url, bot.loop)
                            await self.add(src)
                        except Exception:
                            continue
            src = await self.queue.get()
            self.current = src
            # update presence
            await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=src.title))
            # announce
            play_embed = make_embed(f"Now playing: **{src.title}**", discord.Color.gold(), thumb=src.thumbnail)
            await embed_msg.edit(embed=play_embed)
            await log_embed(f"Now playing: **{src.title}**", discord.Color.gold())
            # TTS announcement
            try:
                tts = await speak_tts(f"Now playing: {src.title}")
                done = asyncio.Event()
                def after_tts(err): bot.loop.call_soon_threadsafe(done.set)
                ctx.voice_client.play(discord.FFmpegPCMAudio(tts), after=after_tts)
                await done.wait()
            except Exception:
                pass
            # play track
            done2 = asyncio.Event()
            ctx.voice_client.play(
                discord.FFmpegPCMAudio(
                    src.url,
                    before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
                ),
                after=lambda e: bot.loop.call_soon_threadsafe(done2.set)
            )
            await done2.wait()

queue = MusicQueue()

# Commands
@bot.command(name="play")
async def play(ctx, *, query: str):
    if not ctx.author.voice or not ctx.author.voice.channel:
        return await ctx.send("❌ Join a voice channel first.")
    vc = ctx.guild.voice_client or await ctx.author.voice.channel.connect()
    initial_embed = make_embed(f"🔎 Searching for: `{query}`")
    message = await ctx.send(embed=initial_embed)
    await log_embed(f"/play invoked by {ctx.author.display_name}: {query}")
    try:
        src = await YTDLSource.from_query(query, bot.loop)
    except Exception:
        error_embed = make_embed("❌ Failed to find song.", discord.Color.red())
        return await message.edit(embed=error_embed)
    found_embed = make_embed(f"✅ Found: **{src.title}**", discord.Color.green(), thumb=src.thumbnail)
    await message.edit(embed=found_embed)
    await queue.add(src)
    if not vc.is_playing():
        # start player loop after bot is ready
        bot.loop.create_task(queue.player_loop(ctx, message))

@bot.command(name="pause")
async def pause(ctx):
    vc = ctx.guild.voice_client
    if not vc or not vc.is_playing():
        return await ctx.send("❌ Nothing playing.")
    vc.pause()
    await log_embed(f"Paused by {ctx.author.display_name}")
    await ctx.send(embed=make_embed(f"⏸ Paused by {ctx.author.display_name}"))

@bot.command(name="skip")
async def skip(ctx):
    vc = ctx.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await log_embed(f"Skipped by {ctx.author.display_name}")
        await ctx.send(embed=make_embed("⏭ Skipped."))
    else:
        await ctx.send("Nothing playing.")

@bot.command(name="stop")
async def stop(ctx):
    vc = ctx.guild.voice_client
    if vc:
        vc.stop()
        await vc.disconnect()
        queue.queue = asyncio.Queue()
        queue.current = None
        await bot.change_presence(status=discord.Status.idle)
        await log_embed(f"Stopped by {ctx.author.display_name}")
        await ctx.send(embed=make_embed("Disconnected and cleared queue."))
    else:
        await ctx.send("Not connected.")

@bot.command(name="autoplay")
async def autoplay(ctx):
    queue.autoplay = not queue.autoplay
    state = "enabled" if queue.autoplay else "disabled"
    await log_embed(f"Autoplay {state} by {ctx.author.display_name}")
    await ctx.send(embed=make_embed(f"Autoplay is now {state}"))

@bot.command(name="tittiestts")
async def tittiestts(ctx, *, text: str):
    vc = ctx.guild.voice_client
    if not vc:
        if ctx.author.voice and ctx.author.voice.channel:
            vc = await ctx.author.voice.channel.connect()
        else:
            return await ctx.send("❌ Join a voice channel first.")
    if tts_lock.locked():
        return await ctx.send(embed=make_embed("⚠️ TTS busy.", discord.Color.orange()))
    async with tts_lock:
        await ctx.send(embed=make_embed(f"🔊 Speaking: {text}"))
        try:
            tts = await speak_tts(text)
            done = asyncio.Event()
            vc.play(discord.FFmpegPCMAudio(tts), after=lambda e: bot.loop.call_soon_threadsafe(done.set))
            await done.wait()
            await log_embed(f"TTS by {ctx.author.display_name}: {text}")
        except Exception:
            await ctx.send(embed=make_embed("❌ TTS failed.", discord.Color.red()))

# Auto-disconnect helper
def is_bot_alone(vc):
    return vc and vc.channel and len([m for m in vc.channel.members if not m.bot]) == 0

async def check_voice():
    await bot.wait_until_ready()
    while True:
        for g in bot.guilds:
            vc = g.voice_client
            if vc and is_bot_alone(vc):
                if not hasattr(vc, 'alone_since'):
                    vc.alone_since = int(asyncio.get_event_loop().time())
                elif int(asyncio.get_event_loop().time()) - vc.alone_since >= 60:
                    await log_embed(f"Disconnected after being alone for {int(asyncio.get_event_loop().time()) - vc.alone_since} seconds.", discord.Color.red())
                    await vc.disconnect()
                    queue.queue = asyncio.Queue()
                    queue.current = None
                    await bot.change_presence(status=discord.Status.idle)
            elif vc and hasattr(vc, 'alone_since'):
                del vc.alone_since
        await asyncio.sleep(10)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.id != bot.user.id:
        return

    if before.channel != after.channel and after.channel:
        vc = after.channel.guild.voice_client
        if vc and vc.is_playing():
            await asyncio.sleep(1)
            try:
                await vc.move_to(after.channel)
            except Exception as e:
                await log_embed(f"⚠️ Failed to move voice client: {e}", discord.Color.red())

@bot.event
async def on_ready():
    bot.loop.create_task(check_voice())
    print(f"Logged in as {bot.user}")

bot.run(TOKEN)

@bot.event
async def on_command_error(ctx, error):
    await log_embed(f"⚠️ Error in `{ctx.command}`: {str(error)}", discord.Color.red())
    await ctx.send(embed=make_embed(f"❌ An error occurred: `{str(error)}`", discord.Color.red()))
