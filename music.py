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
import random
###skbidi babidi boo 
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
#test
# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

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

# Ensure user_voice table exists
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_voice (
    user_id INTEGER PRIMARY KEY,
    voice TEXT
)
""")
conn.commit()

# Helpers
def make_embed(desc, color=discord.Color.blurple(), thumb=None, title=None, footer=None):
    embed = discord.Embed(description=desc, color=color, timestamp=discord.utils.utcnow())
    if title:
        embed.title = title
    if thumb:
        embed.set_thumbnail(url=thumb)
    if footer:
        embed.set_footer(text=footer)
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
TTS_VOICES = ["nova", "echo", "fable", "onyx", "shimmer", "alloy", "daisy", "dewey", "dylan", "grace", "jane", "jason", "jenny", "karen", "kevin", "laura", "lisa", "logan", "matt", "melissa", "michael", "nancy", "paul", "richard", "samantha", "steven", "susan", "taylor", "william"]

async def get_user_voice(user_id):
    cursor.execute("SELECT voice FROM user_voice WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else "nova"

@bot.command(name="ttsvoice", help="Set or show your TTS voice. Usage: !ttsvoice <voice>")
async def ttsvoice(ctx, *, voice: str = None):
    """Set or show your TTS voice. Usage: !ttsvoice <voice>"""
    if voice is None:
        user_voice = await get_user_voice(ctx.author.id)
        available = ', '.join(TTS_VOICES)
        embed = make_embed(
            f"Your current TTS voice: **{user_voice}**\n\n**Available voices:**\n{available}",
            discord.Color.blurple(),
            title="TTS Voice Selection"
        )
        await ctx.send(embed=embed)
        return
    voice = voice.lower()
    if voice not in TTS_VOICES:
        embed = make_embed(
            f"❌ Invalid voice.\n**Available voices:**\n{', '.join(TTS_VOICES)}",
            discord.Color.red(),
            title="TTS Voice Error"
        )
        await ctx.send(embed=embed)
        return
    await set_user_voice(ctx.author.id, voice)
    await ctx.send(embed=make_embed(f"✅ Your TTS voice has been set to **{voice}**.", discord.Color.green(), title="TTS Voice Updated"))

async def set_user_voice(user_id, voice):
    cursor.execute("INSERT INTO user_voice (user_id, voice) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET voice=excluded.voice", (user_id, voice))
    conn.commit()

async def generate_tts(text: str, user_id=None) -> str:
    path = "now.mp3"
    if user_id:
        voice = await get_user_voice(user_id)
    else:
        voice = "nova"
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
        await log_embed(f"\U0001f5e3️ TTS voice used: {voice}")
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
                # Send text message
                await ctx.send(embed=make_embed("✅ Queue empty. Disconnecting. Goodbye!", discord.Color.green(), title="Queue Empty"))
                
                # Generate and play TTS
                tts_text = "Queue empty. Disconnecting. Goodbye!"
                tts_task = asyncio.create_task(generate_tts(tts_text))
                
                # Wait for TTS to be generated
                tts_path = await tts_task
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
                
                self.playing = False
                if ctx.guild.voice_client:
                    await ctx.guild.voice_client.disconnect()
                return

            self.current = track
            self.playing = True
            vc = ctx.guild.voice_client
            if not vc or not vc.is_connected():
                if ctx.author.voice and ctx.author.voice.channel:
                    try:
                        vc = await ctx.author.voice.channel.connect()
                    except discord.errors.ClientException:
                        vc = ctx.guild.voice_client
                        if not vc:
                            await ctx.send(embed=make_embed('⚠️ Failed to join voice channel.', discord.Color.red(), title="Connection Error"))
                            await log_embed('⚠️ Failed to join voice channel.', discord.Color.red())
                            continue
                else:
                    await ctx.send(embed=make_embed('⚠️ You must be in a voice channel!', discord.Color.orange(), title="Connection Error"))
                    await log_embed('⚠️ User not in a voice channel.', discord.Color.red())
                    continue

            await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=track.title))
            await message.edit(embed=make_embed(f"🎶 Now playing: **{track.title}**", discord.Color.gold(), thumb=track.thumbnail))
            await log_embed(f"▶️ Now playing: **{track.title}**", discord.Color.gold())

            tts_text = f"Now playing: {track.title}"
            tts_task = asyncio.create_task(generate_tts(tts_text))
            audio_stream = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(
                    track.url,
                    before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -vn',
                    options='-loglevel panic'
                ),
                volume=0.3
            )

            tts_path = await tts_task
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

            done = asyncio.Event()
            def song_done(_): bot.loop.call_soon_threadsafe(done.set)
            try:
                vc.play(audio_stream, after=song_done)
                self.start_time = time.time()
                await done.wait()
            except Exception as e:
                await log_embed(f"⚠️ Playback failed: {e}", discord.Color.red())
                continue

music = MusicPlayer()

@bot.command(name="play", help="Play a song from YouTube via search or URL.")
async def play(ctx, *, query: str):
    if not ctx.author.voice:
        return await ctx.send(embed=make_embed("❌ Join a voice channel first.", discord.Color.orange(), title="Connection Error"))
    msg = await ctx.send(embed=make_embed(f"🔍 Searching: `{query}`"))
    try:
        track = await AudioTrack.from_query(query)
        await music.add_to_queue(ctx.guild.id, track)
        await msg.edit(embed=make_embed(f"✅ Queued: **{track.title}**", discord.Color.green(), thumb=track.thumbnail))
        await log_embed(f"✅ Queued by {ctx.author.display_name}: {track.title}")
        await music.start_loop(ctx, msg)
    except Exception as e:
        await msg.edit(embed=make_embed(f"❌ Error: {e}", discord.Color.red(), title="Error"))

@bot.command(name="commands", help="List all commands.")
async def commands_list(ctx):
    embed = discord.Embed(
        title="Available Commands",
        description="Here are all the commands you can use:",
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow()
    )
    for command in bot.commands:
        embed.add_field(
            name=f"!{command.name}",
            value=command.help or "No description.",
            inline=False
        )
    embed.set_footer(text="Use !help for more details on each command.")
    await ctx.send(embed=embed)

@bot.command(name="help", help="Show detailed help and bot features.")
async def help_command(ctx):
    embed = discord.Embed(
        title="Music Bot Help",
        description="A feature-rich Discord music bot with TTS and OpenAI voices!",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(
        name="!play [query]",
        value="Play a song from YouTube via search or URL.",
        inline=False
    )
    embed.add_field(
        name="!skip",
        value="Skip the current song.",
        inline=False
    )
    embed.add_field(
        name="!stop",
        value="Stop playback and disconnect the bot.",
        inline=False
    )
    embed.add_field(
        name="!showqueue",
        value="Display the current music queue.",
        inline=False
    )
    embed.add_field(
        name="!tts [text]",
        value="Speak a message in your chosen TTS voice in the voice channel.",
        inline=False
    )
    embed.add_field(
        name="!commands",
        value="List all available commands.",
        inline=False
    )
    embed.set_footer(text="Made with ❤️ using discord.py, yt-dlp, and OpenAI TTS.")
    await ctx.send(embed=embed)

@bot.command(name="tts", help="Speak a message in your voice in the current voice channel.")
async def tts(ctx, *, text: str):
    """Generate TTS and play in voice. Usable at any time."""
    async with tts_lock:
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send(embed=make_embed("⚠️ You must be in a voice channel!", discord.Color.orange(), title="TTS Error"))
            await log_embed("⚠️ TTS playback error: Not connected to voice.", discord.Color.red())
            return
        vc = ctx.guild.voice_client
        if not vc or not vc.is_connected():
            try:
                vc = await ctx.author.voice.channel.connect()
            except discord.errors.ClientException:
                vc = ctx.guild.voice_client
                if not vc:
                    await ctx.send(embed=make_embed('⚠️ Failed to join voice channel.', discord.Color.red(), title="TTS Error"))
                    await log_embed('⚠️ Failed to join voice channel.', discord.Color.red())
                    return
        tts_path = await generate_tts(text, user_id=ctx.author.id)
        if not tts_path:
            await ctx.send(embed=make_embed("⚠️ TTS generation failed.", discord.Color.red(), title="TTS Error"))
            await log_embed("⚠️ TTS generation failed.", discord.Color.red())
            return
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
            await ctx.send(embed=make_embed(f"🗣️ Spoke your message in **{await get_user_voice(ctx.author.id)}** voice.", discord.Color.green(), title="TTS Complete"))
        except Exception as e:
            await ctx.send(embed=make_embed(f"⚠️ TTS playback error: {e}", discord.Color.red(), title="TTS Error"))
            await log_embed(f"⚠️ TTS playback error: {e}", discord.Color.red())

@bot.command(name="showqueue", help="Display the current music queue.")
async def showqueue(ctx):
    queue = await music.show_queue(ctx.guild.id)
    if not queue:
        await ctx.send(embed=make_embed("📭 The queue is empty.", discord.Color.orange(), title="Queue Empty"))
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
    # Prevent duplicate error messages
    if hasattr(ctx, 'handled_error') and ctx.handled_error:
        return
    ctx.handled_error = True
    if isinstance(error, commands.CommandNotFound):
        embed = make_embed("❌ Unknown command. Use `!commands` to see a list of available commands.", discord.Color.red(), title="Command Not Found")
        await ctx.send(embed=embed)
        await log_embed(f"⚠️ Command error: Command not found.", discord.Color.red())
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = make_embed("❌ Missing argument. Check `!help` for usage.", discord.Color.orange(), title="Missing Argument")
        await ctx.send(embed=embed)
        await log_embed(f"⚠️ Command error: Missing argument.", discord.Color.red())
    elif isinstance(error, commands.MissingPermissions):
        embed = make_embed("❌ You don't have permission to do that.", discord.Color.red(), title="Missing Permissions")
        await ctx.send(embed=embed)
        await log_embed(f"⚠️ Command error: Missing permissions.", discord.Color.red())
    else:
        embed = make_embed(f"❌ {error}", discord.Color.red(), title="Command Error")
        await ctx.send(embed=embed)
        await log_embed(f"⚠️ Command error: {error}", discord.Color.red())

bot.run(TOKEN)
