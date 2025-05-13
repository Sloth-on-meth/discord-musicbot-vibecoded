import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import yt_dlp
import json
import openai

# Load config
with open("config.json", "r") as f:
    config = json.load(f)

TOKEN = config["token"]
client = openai.OpenAI(api_key=config["openai_api_key"])

intents = discord.Intents.default()
intents.message_content = True


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        #self.tree = app_commands.CommandTree(self)  # Uncomment this line

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

# Music source
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("url")

    @classmethod
    async def create_source(cls, search, loop):
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))
            if "entries" in data:
                data = data["entries"][0]
            print(f"[INFO] YouTube URL: {data['url']}")
            return cls(discord.FFmpegPCMAudio(
                data['url'],
                before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                options='-vn -f s16le -ar 48000 -ac 2 -loglevel debug'
            ), data=data)
        except Exception as e:
            print(f"[ERROR] Failed to create YTDLSource: {e}")
            raise

# Music queue
class MusicQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.next = asyncio.Event()
        self.current = None

    async def add(self, source):
        await self.queue.put(source)

    async def player_loop(self, ctx):
        while True:
            self.next.clear()
            self.current = await self.queue.get()

            # TTS
            tts_message = f"Now playing {self.current.title}"
            tts_file = await speak_tts(tts_message)
            await ctx.send(f"🔊 {tts_message}")
            print(f"[INFO] TTS generated: {tts_file}")

            done = asyncio.Event()

            def after_tts(e):
                print(f"[INFO] TTS playback finished ({e})")
                ctx.bot.loop.call_soon_threadsafe(done.set)

            ctx.voice_client.play(discord.FFmpegPCMAudio(tts_file, options="-vn -f s16le -ar 48000 -ac 2"), after=after_tts)
            await done.wait()

            print(f"[INFO] Now playing: {self.current.title}")
            ctx.voice_client.play(
                self.current,
                after=lambda _: ctx.bot.loop.call_soon_threadsafe(self.next.set)
            )
            await ctx.send(f"🎶 Now playing: **{self.current.title}**")
            await self.next.wait()

queue = MusicQueue()

# Slash command: /play
@bot.tree.command(name="play", description="Play a song from YouTube")
@app_commands.describe(query="Search term or YouTube URL")
async def slash_play(interaction: discord.Interaction, query: str):
    """Play a song from YouTube"""
    await interaction.response.defer()
    
    # Get the voice client or connect if not connected
    voice_client = interaction.guild.voice_client
    if not voice_client:
        if interaction.user.voice:
            voice_client = await interaction.user.voice.channel.connect()
            print(f"[INFO] Connected to {interaction.user.voice.channel}")
        else:
            return await interaction.followup.send("❌ You're not in a voice channel.")

    await interaction.followup.send(f"🔎 Searching for: `{query}`")
    
    try:
        player = await YTDLSource.create_source(query, loop=bot.loop)
    except Exception as e:
        print(f"[ERROR] Failed to create source: {e}")
        return await interaction.followup.send("❌ Failed to find or play the requested song.")

    await queue.add(player)
    await interaction.followup.send(f"✅ Added to queue: **{player.title}**")
    print(f"[INFO] Queued: {player.title}")

    if not voice_client.is_playing():
        print("[INFO] Starting playback loop...")
        # Create a minimal Context object for the player loop
        ctx = await commands.Context.from_interaction(interaction)
        bot.loop.create_task(queue.player_loop(ctx))

# Additional legacy commands (optional to convert)
from discord import app_commands

@bot.command()
@commands.is_owner()
async def sync(ctx: commands.Context):
    """Sync slash commands (owner only)"""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"Synced {len(synced)} commands.")
    except Exception as e:
        await ctx.send(f"Failed to sync: {e}")

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
    else:
        q = list(queue.queue._queue)
        msg += "**Up Next:**\n" + "\n".join([f"- {track.title}" for track in q])
    await interaction.response.send_message(msg)

@bot.tree.command(name="stop", description="Disconnect the bot and clear the queue")
async def slash_stop(interaction: discord.Interaction):
    voice = interaction.guild.voice_client
    if voice:
        voice.stop()
        await voice.disconnect()
        queue.queue = asyncio.Queue()
        await interaction.response.send_message("Disconnected and cleared queue.")
    else:
        await interaction.response.send_message("Not connected to a voice channel.")
# on_ready
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    # Don't auto-sync here - use the sync command instead during development
    print("Use !sync command to sync slash commands")


# Run the bot
bot.run(TOKEN)

