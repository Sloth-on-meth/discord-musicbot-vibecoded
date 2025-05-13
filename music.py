import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import yt_dlp
import json
import openai
import re

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

# Music source with recommendations
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("url")
        self.video_id = self.extract_video_id(self.url)

    @staticmethod
    def extract_video_id(url):
        # Extract YouTube video ID from URL
        regex = r"(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^\"&?\/\s]{11})"
        match = re.search(regex, url)
        return match.group(1) if match else None

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

    @classmethod
    async def get_recommendations(cls, video_id, loop):
        """Get recommended videos from YouTube"""
        ytdl_rec_opts = {
            'extract_flat': True,
            'quiet': True,
            'get_related': True,
            'playlist_items': '1-3'  # Get first 3 recommendations
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
            
            # Autoplay recommendations if queue is empty
            if self.queue.empty() and self.autoplay and self.last_video_id:
                try:
                    recommendations = await YTDLSource.get_recommendations(self.last_video_id, ctx.bot.loop)
                    if recommendations:
                        await ctx.send("🔍 Queue empty - adding recommended songs...")
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

            # TTS Announcement
            tts_message = f"Now playing {self.current.title}"
            tts_file = await speak_tts(tts_message)
            await ctx.send(f"🔊 {tts_message}")

            done = asyncio.Event()
            def after_tts(e):
                ctx.bot.loop.call_soon_threadsafe(done.set)
            ctx.voice_client.play(discord.FFmpegPCMAudio(tts_file), after=after_tts)
            await done.wait()

            # Play the actual song
            ctx.voice_client.play(
                self.current,
                after=lambda _: ctx.bot.loop.call_soon_threadsafe(self.next.set)
            )
            await ctx.send(f"🎶 Now playing: **{self.current.title}**")
            await self.next.wait()

queue = MusicQueue()

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
        return await interaction.followup.send("❌ Failed to find or play the requested song.")

    await queue.add(player)
    await interaction.followup.send(f"✅ Added to queue: **{player.title}**")

    if not voice_client.is_playing():
        ctx = await commands.Context.from_interaction(interaction)
        bot.loop.create_task(queue.player_loop(ctx))

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
        voice.stop()
        await voice.disconnect()
        queue.queue = asyncio.Queue()
        await interaction.response.send_message("Disconnected and cleared queue.")
    else:
        await interaction.response.send_message("Not connected to a voice channel.")

@bot.tree.command(name="autoplay", description="Toggle autoplay of recommended songs")
async def slash_autoplay(interaction: discord.Interaction):
    queue.autoplay = not queue.autoplay
    status = "✅ enabled" if queue.autoplay else "❌ disabled"
    await interaction.response.send_message(f"Autoplay is now {status}")

# Bot events
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(f"Error syncing commands: {e}")

# Run the bot
bot.run(TOKEN)
