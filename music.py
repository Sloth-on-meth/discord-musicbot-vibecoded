import discord
from discord.ext import commands
import asyncio
import yt_dlp
import json
import openai
import re
import time
import sqlite3
import os

# Load config
with open("config.json", "r") as f:
    config = json.load(f)

TOKEN = config["token"]
log_channel_id = config.get("musicbot_log_channel")
client = openai.OpenAI(api_key=config["openai_api_key"])

# Prepare yt_dlp
ytdl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'default_search': 'ytsearch1',
    'noplaylist': True
}
ytdl = yt_dlp.YoutubeDL(ytdl_opts)

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Setup DB (reset each run)
if os.path.exists("queue.db"):
    os.remove("queue.db")
conn = sqlite3.connect("queue.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    title TEXT,
    url TEXT,
    thumbnail TEXT,
    video_id TEXT
)
""")
conn.commit()

# Helpers
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

def extract_vid_id(url):
    m = re.search(r"(?:youtube\\.com/.+v=|youtu\\.be/)([^&?]{11})", url)
    return m.group(1) if m else None

async def fetch_info(query: str):
    return await asyncio.to_thread(lambda: ytdl.extract_info(query, download=False))

tts_lock = asyncio.Lock()
import random

TTS_VOICES = ["nova"]
#TTS_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
async def generate_tts(text: str) -> str:
    path = "now.mp3"
    voice = random.choice(TTS_VOICES)
    try:
        resp = await asyncio.to_thread(
            client.audio.speech.create,
            model="tts-1",
            voice=voice,
            input=text,
            response_format="mp3"
        )
        with open(path, "wb") as f:
            f.write(resp.content)
        await log_embed(f"🗣️ TTS voice used: {voice}")
        return path
    except Exception as e:
        print(f"TTS error ({voice}): {e}")
        return None


class AudioTrack:
    def __init__(self, title, url, thumbnail, video_id):
        self.title = title
        self.url = url
        self.thumbnail = thumbnail
        self.video_id = video_id

    @classmethod
    async def from_query(cls, query):
        data = await fetch_info(query)
        if "entries" in data:
            data = data["entries"][0]
        return cls(data["title"], data["url"], data.get("thumbnail"), extract_vid_id(data["url"]))

class MusicPlayer:
    def __init__(self):
        self.current = None
        self.playing = False
        self.loop_task = None
        self.start_time = None

    async def add_to_queue(self, guild_id, track):
        cursor.execute("INSERT INTO queue (guild_id, title, url, thumbnail, video_id) VALUES (?, ?, ?, ?, ?)",
                       (guild_id, track.title, track.url, track.thumbnail, track.video_id))
        conn.commit()

    async def pop_next(self, guild_id):
        cursor.execute("SELECT id, title, url, thumbnail, video_id FROM queue WHERE guild_id=? ORDER BY id ASC LIMIT 1", (guild_id,))
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute("DELETE FROM queue WHERE id=?", (row[0],))
        conn.commit()
        return AudioTrack(row[1], row[2], row[3], row[4])

    async def show_queue(self, guild_id):
        cursor.execute("SELECT title FROM queue WHERE guild_id=? ORDER BY id", (guild_id,))
        return [row[0] for row in cursor.fetchall()]

    async def start_loop(self, ctx, message):
        if self.loop_task and not self.loop_task.done():
            return
        self.loop_task = asyncio.create_task(self.player_loop(ctx, message))

    async def player_loop(self, ctx, message):
        while True:
            track = await self.pop_next(ctx.guild.id)
            if not track:
                await ctx.send("✅ Queue finished.")
                self.playing = False
                return

            self.current = track
            self.playing = True
            vc = ctx.guild.voice_client
            if not vc or not vc.is_connected():
                vc = await ctx.author.voice.channel.connect()

            await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=track.title))
            await message.edit(embed=make_embed(f"🎶 Now playing: **{track.title}**", discord.Color.gold(), thumb=track.thumbnail))
            await log_embed(f"▶️ Now playing: **{track.title}**", discord.Color.gold())

            # Prefetch TTS
            tts_text = f"Now playing: {track.title}"
            tts_path = await generate_tts(tts_text)
            if tts_path:
                done = asyncio.Event()
                def tts_done(_): bot.loop.call_soon_threadsafe(done.set)
                try:
                    vc.play(
                        discord.PCMVolumeTransformer(
                            discord.FFmpegPCMAudio(tts_path, options='-loglevel panic'),
                            volume=1.0
                        ),
                        after=tts_done
                    )
                    await done.wait()
                except Exception as e:
                    await log_embed(f"⚠️ TTS playback error: {e}", discord.Color.red())

            # Play actual song
            done = asyncio.Event()
            def song_done(_): bot.loop.call_soon_threadsafe(done.set)
            try:
                vc.play(
                    discord.PCMVolumeTransformer(
                        discord.FFmpegPCMAudio(
                            track.url,
                            before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -vn',
                            options='-loglevel panic'
                        ),
                        volume=0.3
                    ),
                    after=song_done
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
    try:
        track = await AudioTrack.from_query(query)
        await music.add_to_queue(ctx.guild.id, track)
        await msg.edit(embed=make_embed(f"✅ Queued: **{track.title}**", discord.Color.green(), thumb=track.thumbnail))
        await log_embed(f"✅ Queued by {ctx.author.display_name}: {track.title}")
        await music.start_loop(ctx, msg)
    except Exception as e:
        await msg.edit(embed=make_embed(f"❌ Error: {e}", discord.Color.red()))

@bot.command(name="tittiestts")
async def tts(ctx, *, text: str):
    if len(text) > 1000:
        return await ctx.send("⚠️ Max 1000 characters.")
    if tts_lock.locked():
        return await ctx.send("🔄 TTS is busy.")
    vc = ctx.guild.voice_client or await ctx.author.voice.channel.connect()
    if not music.current or not vc.is_playing():
        return await ctx.send("❌ Nothing currently playing to resume after TTS.")
    if not music.start_time:
        return await ctx.send("⚠️ Cannot resume from timestamp, start_time missing.")

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

@bot.command(name="showqueue")
async def showqueue(ctx):
    queue = await music.show_queue(ctx.guild.id)
    if not queue:
        await ctx.send("📭 The queue is empty.")
    else:
        msg = "\n".join(f"{i+1}. {title}" for i, title in enumerate(queue))
        await ctx.send(embed=make_embed(f"🎵 Queue:\n{msg}"))

@bot.command(name="skip")
async def skip(ctx):
    vc = ctx.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await ctx.send("⏭ Skipped.")
        await music.start_loop(ctx, await ctx.send("⏳ Loading next track..."))
    else:
        await ctx.send("❌ Nothing is playing.")

@bot.command(name="stop")
async def stop(ctx):
    vc = ctx.guild.voice_client
    if vc and vc.is_connected():
        await vc.disconnect(force=True)
    music.current = None
    music.playing = False
    music.start_time = None
    if music.loop_task and not music.loop_task.done():
        music.loop_task.cancel()
    await ctx.send("🛑 Stopped and disconnected.")

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    await log_embed("🎵 Music bot online.")

@bot.event
async def on_command_error(ctx, error):
    await log_embed(f"⚠️ Command error: {str(error)}", discord.Color.red())
    await ctx.send(f"❌ Error: {str(error)}")

bot.run(TOKEN)
