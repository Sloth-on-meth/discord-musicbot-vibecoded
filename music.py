import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import yt_dlp
import json
import openai
import re
import random
import uuid
tts_lock = asyncio.Lock()

# Load config
with open("config.json", "r") as f:
    config = json.load(f)

TOKEN = config["token"]
client = openai.OpenAI(api_key=config["openai_api_key"])

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True  # Needed for voice state updates

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

bot = MyBot()

# YouTube DL
ytdl_opts = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'default_search': 'ytsearch1',
    'source_address': '0.0.0.0',
}
ffmpeg_opts = {
    'before_options': '-nostdin',
    'options': '-vn',
}
ytdl = yt_dlp.YoutubeDL(ytdl_opts)

# Helper function to check if bot is alone
def is_bot_alone(voice_client):
    if not voice_client or not voice_client.channel:
        return False
    return len([m for m in voice_client.channel.members if not m.bot]) == 0

# TTS function
async def speak_tts(text: str) -> str:
    tts_path = "now_playing.mp3"
    response = client.audio.speech.create(
        model="tts-1",
        voice="alloy",
        input=text,
        response_format="mp3"
    )
    with open(tts_path, "wb") as f:
        f.write(response.content)
    return tts_path

# Music source with recommendations
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.1):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("url")
        self.video_id = self.extract_video_id(self.url)

    @staticmethod
    def extract_video_id(url):
        regex = r"(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^\"&?\/\s]{11})"
        match = re.search(regex, url)
        return match.group(1) if match else None

    @classmethod
    async def create_source(cls, search, loop):
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))
            if "entries" in data:
                data = data["entries"][0]
            return cls(discord.FFmpegPCMAudio(
                data['url'],
                before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                options='-vn -f s16le -ar 48000 -ac 2 -loglevel debug'
            ), data=data)
        except Exception as e:
            print(f"[ERROR] Failed to create YTDLSource: {e}")
            raise

    @classmethod
    async def get_recommendations(cls, video_id, loop):
        ytdl_rec_opts = {
            'extract_flat': True,
            'quiet': True,
            'get_related': True,
            'playlist_items': '1-3'
        }
        try:
            with yt_dlp.YoutubeDL(ytdl_rec_opts) as ytdl_rec:
                data = await loop.run_in_executor(
                    None,
                    lambda: ytdl_rec.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                )
                return [f"https://www.youtube.com/watch?v={rec['id']}" 
                        for rec in data.get('entries', [])[:3] if rec.get('id')]
        except Exception as e:
            print(f"[ERROR] Failed to get recommendations: {e}")
            return []

# Music queue with autoplay
class MusicQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.next = asyncio.Event()
        self.current = None
        self.autoplay = True
        self.last_video_id = None

    async def add(self, source):
        await self.queue.put(source)
        if source.video_id:
            self.last_video_id = source.video_id

    async def player_loop(self, ctx):
        while True:
            self.next.clear()

            if self.queue.empty() and self.autoplay and self.last_video_id:
                try:
                    recommendations = await YTDLSource.get_recommendations(self.last_video_id, ctx.bot.loop)
                    if recommendations:
                        tts_message = "🔍 Queue empty - adding recommended songs..."
                        tts_file = await speak_tts(tts_message)
                        await ctx.send(f"🔊 {tts_message}")
                        for url in recommendations:
                            try:
                                player = await YTDLSource.create_source(url, ctx.bot.loop)
                                await self.add(player)
                                await ctx.send(f"➕ Added recommendation: **{player.title}**")
                            except Exception as e:
                                print(f"[ERROR] Failed to add recommendation: {e}")
                except Exception as e:
                    print(f"[ERROR] Failed to get recommendations: {e}")

            self.current = await self.queue.get()
            await ctx.send(f"🎶 Now playing: **{self.current.title}**")

            # 🔊 TTS announcement
            try:
                tts_text = f"Now playing: {self.current.title}"
                tts_file = await speak_tts(tts_text)

                # Wait for TTS to finish before playing song
                tts_done = asyncio.Event()
                def after_tts(e):
                    ctx.bot.loop.call_soon_threadsafe(tts_done.set)
                ctx.voice_client.play(discord.FFmpegPCMAudio(tts_file), after=after_tts)
                await tts_done.wait()
            except Exception as e:
                print(f"[ERROR] Failed to TTS announce: {e}")

            # ▶️ Play the actual song
            ctx.voice_client.play(
                self.current,
                after=lambda e: ctx.bot.loop.call_soon_threadsafe(self.next.set)
            )

            await self.next.wait()

queue = MusicQueue()

async def log_to_discord(bot, message: str):
    log_channel_id = config.get("musicbot_log_channel")
    if log_channel_id:
        channel = bot.get_channel(log_channel_id)
        if channel:
            try:
                await channel.send(message)
            except Exception as e:
                print(f"[ERROR] Failed to send log message: {e}")
        else:
            print("[ERROR] Logging channel not found.")
    else:
        print("[WARNING] No log channel configured in config.json")

# Slash commands
@bot.tree.command(name="play", description="Play a song from YouTube")
@app_commands.describe(query="The song to search for or YouTube URL")
async def slash_play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    voice_client = interaction.guild.voice_client
    if not voice_client:
        if interaction.user.voice:
            voice_client = await interaction.user.voice.channel.connect()
        else:
            return await interaction.followup.send("❌ You're not in a voice channel.")
    await interaction.followup.send(f"🔎 Searching for: `{query}`")
    try:
        player = await YTDLSource.create_source(query, loop=bot.loop)
    except Exception as e:
        print(f"[ERROR] Failed to find or play song: {e}")
        await interaction.followup.send("❌ Failed to find or play the requested song.")
        return
    await queue.add(player)
    await interaction.followup.send(f"✅ Added to queue: **{player.title}**")
    if not voice_client.is_playing():
        ctx = await commands.Context.from_interaction(interaction)
        bot.loop.create_task(queue.player_loop(ctx))

    # Logging
    await log_to_discord(bot, f"[{interaction.created_at:%Y-%m-%d %H:%M:%S}] `/play` command by **{interaction.user.display_name}** (`{interaction.user.id}`): `{query}`")

@bot.tree.command(name="pause", description="Pause the current music")
async def slash_pause(interaction: discord.Interaction):
    voice = interaction.guild.voice_client
    if not voice or not voice.is_playing():
        return await interaction.response.send_message("❌ Nothing is currently playing.", ephemeral=True)

    voice.pause()
    user = interaction.user.display_name
    tts_message = f"Music paused by {user}."

    try:
        tts_file = await speak_tts(tts_message)
        tts_audio = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(tts_file), volume=1)

        tts_done = asyncio.Event()
        def after_tts(e):
            interaction.client.loop.call_soon_threadsafe(tts_done.set)

        voice.play(tts_audio, after=after_tts)
        await interaction.response.send_message(f"⏸ Paused music (requested by **{user}**).")
        await tts_done.wait()
    except Exception as e:
        print(f"[ERROR] TTS failed: {e}")
        await interaction.followup.send("❌ TTS announcement failed.")

    # Logging
    await log_to_discord(bot, f"[{interaction.created_at:%Y-%m-%d %H:%M:%S}] `/pause` command by **{interaction.user.display_name}** (`{interaction.user.id}`)")

@bot.tree.command(name="skip", description="Skip the current song")
async def slash_skip(interaction: discord.Interaction):
    voice = interaction.guild.voice_client
    if voice and voice.is_playing():
        voice.stop()
        await interaction.response.send_message("⏭ Skipped.")
    else:
        await interaction.response.send_message("Nothing is playing.")

@bot.tree.command(name="queue", description="Show the current and upcoming songs")
async def slash_queue(interaction: discord.Interaction):
    if queue.current:
        msg = f"**Now Playing**: {queue.current.title}\n"
    else:
        msg = "Nothing playing.\n"
    if queue.queue.empty():
        msg += "_Queue is empty._"
        if queue.autoplay:
            msg += "\n🔁 Autoplay is enabled"
    else:
        q = list(queue.queue._queue)
        msg += "**Up Next:**\n" + "\n".join([f"- {track.title}" for track in q])
    await interaction.response.send_message(msg)

@bot.tree.command(name="stop", description="Disconnect the bot and clear the queue")
async def slash_stop(interaction: discord.Interaction):
    voice = interaction.guild.voice_client
    if voice:
        await log_to_discord(bot, f"🔌 Disconnected from {voice.channel.name} in {interaction.guild.name} by command from {interaction.user.display_name}")
        voice.stop()
        await voice.disconnect()
        queue.queue = asyncio.Queue()
        queue.current = None
        await interaction.response.send_message("Disconnected and cleared queue.")
    else:
        await interaction.response.send_message("Not connected to a voice channel.")

@bot.tree.command(name="autoplay", description="Toggle autoplay of recommended songs")
async def slash_autoplay(interaction: discord.Interaction):
    queue.autoplay = not queue.autoplay
    status = "✅ enabled" if queue.autoplay else "❌ disabled"
    await interaction.response.send_message(f"Autoplay is now {status}")

@bot.tree.command(name="tittiestts", description="Pause music, speak something with TTS, then resume")
@app_commands.describe(text="What you want the bot to say out loud")
async def slash_tittiestts(interaction: discord.Interaction, text: str):
    await interaction.response.defer()
    voice = interaction.guild.voice_client

    if not voice:
        if interaction.user.voice:
            voice = await interaction.user.voice.channel.connect()
        else:
            return await interaction.followup.send("❌ You're not in a voice channel.")

    if tts_lock.locked():
        return await interaction.followup.send("⚠️ Another TTS command is currently running. Please wait and try again.", ephemeral=True)

    async with tts_lock:
        try:
            tts_file = await speak_tts(text)
        except Exception as e:
            print(f"[ERROR] TTS generation failed: {e}")
            return await interaction.followup.send("❌ Failed to generate TTS audio.")

        was_playing = voice.is_playing()
        current_source = voice.source if was_playing else None

        if was_playing:
            voice.pause()
            await interaction.followup.send(f"⏸ Music paused by **{interaction.user.display_name}**. Speaking...")
        else:
            await interaction.followup.send("🔊 Speaking...")

        try:
            tts_done = asyncio.Event()

            def after_tts(e):
                interaction.client.loop.call_soon_threadsafe(tts_done.set)

            tts_audio = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(tts_file), volume=1)
            voice.play(tts_audio, after=after_tts)

            await tts_done.wait()

            if was_playing and current_source:
                voice.play(current_source, after=lambda e: queue.next.set())
                await interaction.followup.send("▶️ Resumed music.")
            else:
                await interaction.followup.send("✅ TTS finished.")
        except Exception as e:
            print(f"[ERROR] TTS playback failed: {e}")
            await interaction.followup.send("❌ Failed to play TTS audio.")

@bot.event
async def on_voice_state_update(member, before, after):
    # Ignore our own voice state changes
    if member.id == bot.user.id:
        return
    
    voice_client = member.guild.voice_client
    if voice_client and voice_client.channel == before.channel:
        if is_bot_alone(voice_client):
            voice_client.alone_since = asyncio.get_event_loop().time()
        elif hasattr(voice_client, 'alone_since'):
            del voice_client.alone_since

async def check_voice_channels():
    await bot.wait_until_ready()
    while not bot.is_closed():
        for guild in bot.guilds:
            voice_client = guild.voice_client
            if voice_client and is_bot_alone(voice_client):
                # If we're alone and not in the grace period yet, start tracking
                if not hasattr(voice_client, 'alone_since'):
                    voice_client.alone_since = asyncio.get_event_loop().time()
                else:
                    # Check if we've been alone for 5 minutes (300 seconds)
                    alone_time = asyncio.get_event_loop().time() - voice_client.alone_since
                    if alone_time >= 3:
                        try:
                            await log_to_discord(bot, f"🔌 Disconnected from {voice_client.channel.name} in {guild.name} after being alone for 5 minutes.")
                            await voice_client.disconnect()
                            # Clear the queue
                            queue.queue = asyncio.Queue()
                            queue.current = None
                        except Exception as e:
                            print(f"Error disconnecting from voice: {e}")
            elif voice_client and hasattr(voice_client, 'alone_since'):
                # Someone joined - reset the timer
                del voice_client.alone_since
        
        await asyncio.sleep(10)  # Check every 10 seconds

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(f"Error syncing commands: {e}")
    bot.loop.create_task(check_voice_channels())

bot.run(TOKEN)
