import discord
from discord.ext import commands
import asyncio
import yt_dlp
import json
import openai
import re
import time

with open("config.json", "r") as f:
    config = json.load(f)

required_keys = ["token", "openai_api_key"]
for key in required_keys:
    if key not in config:
        raise KeyError(f"Missing required config key: '{key}'")

TOKEN = config["token"]
log_channel_id = config.get("musicbot_log_channel")

client = openai.OpenAI(api_key=config["openai_api_key"])

ytdl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'default_search': 'ytsearch1',
    'noplaylist': True
}
ytdl = yt_dlp.YoutubeDL(ytdl_opts)

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

def make_embed(desc, color=discord.Color.blurple(), thumb=None):
    embed = discord.Embed(description=desc, color=color, timestamp=discord.utils.utcnow())
    if thumb:
        embed.set_thumbnail(url=thumb)
    return embed

async def log_embed(msg, color=discord.Color.blurple()):
    if not log_channel_id:
        return
    channel = bot.get_channel(log_channel_id)
    if channel:
        await channel.send(embed=make_embed(msg, color))

tts_lock = asyncio.Lock()
async def generate_tts(text: str) -> str:
    path = "now.mp3"
    try:
        resp = await asyncio.to_thread(
            client.audio.speech.create,
            model="tts-1",
            voice="alloy",
            input=text,
            response_format="mp3"
        )
        with open(path, "wb") as f:
            f.write(resp.content)
        return path
    except Exception as e:
        print(f"TTS error: {e}")
        return None

async def fetch_info(query: str):
    return await asyncio.to_thread(lambda: ytdl.extract_info(query, download=False))

def extract_vid_id(url):
    m = re.search(r"(?:youtube\.com/.+v=|youtu\.be/)([^&?]{11})", url)
    return m.group(1) if m else None

class AudioTrack:
    def __init__(self, data):
        self.title = data["title"]
        self.url = data["url"]
        self.thumbnail = data.get("thumbnail")
        self.video_id = extract_vid_id(self.url)

    @classmethod
    async def from_query(cls, query):
        data = await fetch_info(query)
        if "entries" in data:
            data = data["entries"][0]
        return cls(data)

class MusicPlayer:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.current = None
        self.playing = False
        self.loop_task = None
        self.autoplay = True
        self.last_video_id = None
        self.start_time = None

    async def add(self, track):
        await self.queue.put(track)
        await log_embed(f"✅ Queued: **{track.title}**", discord.Color.green())
        self.last_video_id = track.video_id

    async def start_loop(self, ctx, message):
        if self.loop_task and not self.loop_task.done():
            return
        self.loop_task = asyncio.create_task(self.player_loop(ctx, message))

    async def player_loop(self, ctx, message):
        while True:
            try:
                track = await asyncio.wait_for(self.queue.get(), timeout=300)
            except asyncio.TimeoutError:
                await ctx.send("⚠️ No music played for 5 minutes. Disconnecting.")
                await ctx.guild.voice_client.disconnect()
                self.playing = False
                return

            self.current = track
            self.playing = True
            vc = ctx.guild.voice_client
            if not vc or not vc.is_connected():
                vc = await ctx.author.voice.channel.connect()

            await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=track.title))
            embed = make_embed(f"🎶 Now playing: **{track.title}**", discord.Color.gold(), thumb=track.thumbnail)
            await message.edit(embed=embed)
            await log_embed(f"▶️ Now playing: **{track.title}**", discord.Color.gold())

            done = asyncio.Event()
            try:
                vc.play(
                    discord.PCMVolumeTransformer(
                        discord.FFmpegPCMAudio(
                            track.url,
                            before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -vn',
                            options='-loglevel panic'
                        ),
                        volume=0.3  # hardcoded music volume
                    ),
                    after=lambda e: bot.loop.call_soon_threadsafe(done.set)
                )
                self.start_time = time.time()
                await done.wait()
            except Exception as e:
                await log_embed(f"⚠️ Playback failed: {e}", discord.Color.red())
                continue

music = MusicPlayer()

@bot.command(name="play")
async def play(ctx, *, query: str):
    if not ctx.author.voice:
        return await ctx.send("❌ Join a voice channel first.")
    msg = await ctx.send(embed=make_embed(f"🔍 Searching: `{query}`"))
    await log_embed(f"/play invoked by {ctx.author.display_name}: {query}")

    try:
        track = await AudioTrack.from_query(query)
        tts_path = await generate_tts(f"Now playing: {track.title}")
    except Exception as e:
        return await msg.edit(embed=make_embed(f"❌ Error: {e}", discord.Color.red()))

    vc = ctx.guild.voice_client or await ctx.author.voice.channel.connect()

    if not vc.is_playing() and tts_path:
        done = asyncio.Event()
        def after_play(_): bot.loop.call_soon_threadsafe(done.set)
        try:
            vc.play(
                discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(tts_path, options='-loglevel panic'),
                    volume=1.0  # hardcoded TTS volume
                ),
                after=after_play
            )
            await done.wait()
        except Exception as e:
            await log_embed(f"⚠️ TTS playback error: {e}", discord.Color.red())

    await music.add(track)
    await msg.edit(embed=make_embed(f"✅ Found: **{track.title}**", discord.Color.green(), thumb=track.thumbnail))
    await music.start_loop(ctx, msg)

@bot.command(name="tittiestts")
async def tts(ctx, *, text: str):
    if len(text) > 250:
        return await ctx.send("⚠️ Max 250 characters.")
    if tts_lock.locked():
        return await ctx.send("🔄 TTS is busy.")
    vc = ctx.guild.voice_client or await ctx.author.voice.channel.connect()
    if not music.current or not vc.is_playing():
        return await ctx.send("❌ Nothing currently playing to resume after TTS.")
    if not music.start_time:
        return await ctx.send("⚠️ Cannot resume from timestamp, start_time missing.")

    # Prefetch TTS before pausing music
    tts_path = await generate_tts(text)
    if not tts_path:
        return await ctx.send(embed=make_embed("❌ TTS generation failed.", discord.Color.red()))

    vc.pause()
    await asyncio.sleep(0.1)
    elapsed = max(0, int(time.time() - music.start_time))

    async with tts_lock:
        await ctx.send(embed=make_embed(f"🔊 Speaking: {text}"))
        done = asyncio.Event()
        def after_play(_): bot.loop.call_soon_threadsafe(done.set)
        try:
            vc.play(
                discord.PCMVolumeTransformer(
                    discord.FFmpegPCMAudio(tts_path, options='-loglevel panic'),
                    volume=1.0
                ),
                after=after_play
            )
            await done.wait()
        except Exception as e:
            return await ctx.send(embed=make_embed(f"❌ Audio error: {e}", discord.Color.red()))

    # Resume music from paused timestamp
    try:
        music.start_time = time.time() - elapsed
        vc.play(
            discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(
                    music.current.url,
                    before_options=f"-ss {elapsed} -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -vn",
                    options='-loglevel panic'
                ),
                volume=0.3
            )
        )
        await ctx.send(embed=make_embed(f"🎵 Resumed at {elapsed}s"))
    except Exception as e:
        await ctx.send(embed=make_embed(f"⚠️ Failed to resume: {e}", discord.Color.red()))
    await log_embed(f"TTS by {ctx.author.display_name}: {text} (resumed at {elapsed}s)")


@bot.command(name="skip")
async def skip(ctx):
    vc = ctx.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await ctx.send("⏭ Skipped.")
    else:
        await ctx.send("Nothing playing.")

@bot.command(name="pause")
async def pause(ctx):
    vc = ctx.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await ctx.send("⏸ Paused.")
    else:
        await ctx.send("Nothing is playing.")

@bot.command(name="stop")
async def stop(ctx):
    vc = ctx.guild.voice_client
    if vc:
        vc.stop()
        await vc.disconnect()
        music.playing = False
        music.queue = asyncio.Queue()
        await ctx.send("⏹️ Stopped and disconnected.")
    else:
        await ctx.send("Not connected.")

@bot.command(name="autoplay")
async def autoplay(ctx):
    music.autoplay = not music.autoplay
    await ctx.send(f"Autoplay is now {'enabled' if music.autoplay else 'disabled'}.")

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    await log_embed("🎵 Music bot online.")

@bot.event
async def on_command_error(ctx, error):
    await log_embed(f"⚠️ Command error: {str(error)}", discord.Color.red())
    await ctx.send(f"❌ Error: {str(error)}")

bot.run(TOKEN)
