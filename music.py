import discord
from discord.ext import commands
import asyncio
import yt_dlp
import functools
import itertools
import json
import openai


with open("config.json", "r") as f:
    config = json.load(f)

TOKEN = config["token"]

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
client = openai.OpenAI(api_key=config["openai_api_key"])
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
async def speak_tts(text: str) -> str:
    tts_path = "now_playing.mp3"
    response = client.audio.speech.create(
        model="tts-1",
        voice="alloy",
        input=text,
        response_format="mp3"
    )
    with open(tts_path, "wb") as f:
        f.write(response.content)  # not await, just .content
    return tts_path




class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def create_source(cls, search, loop):
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search, download=False))
            if 'entries' in data:
                data = data['entries'][0]
            print(f"[INFO] YouTube URL: {data['url']}")
            return cls(discord.FFmpegPCMAudio(
                data['url'],
                before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                options='-vn -f s16le -ar 48000 -ac 2 -loglevel debug'
            ), data=data)

        except Exception as e:
            print(f"[ERROR] Failed to create YTDLSource: {e}")
            raise


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
    
            # 1. Generate TTS
            tts_message = f"Now playing {self.current.title}, requested by {ctx.author.display_name}"
            tts_file = await speak_tts(tts_message)
            await ctx.send(f"🔊 {tts_message}")
            print(f"[INFO] TTS generated: {tts_file}")
    
            # 2. Play TTS and wait for it to finish
            done = asyncio.Event()
    
            def after_tts(e):
                print(f"[INFO] TTS playback finished ({e})")
                ctx.bot.loop.call_soon_threadsafe(done.set)
    
            ctx.voice_client.play(discord.FFmpegPCMAudio(tts_file, options="-vn -f s16le -ar 48000 -ac 2"), after=after_tts)
            await done.wait()
    
            # 3. Now play actual song
            print(f"[INFO] Now playing: {self.current.title}")
            ctx.voice_client.play(
                self.current,
                after=lambda _: ctx.bot.loop.call_soon_threadsafe(self.next.set)
            )
            await ctx.send(f"🎶 Now playing: **{self.current.title}**")
            await self.next.wait()


queue = MusicQueue()


@bot.command()
async def join(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        await channel.connect()
    else:
        await ctx.send("You're not in a voice channel.")



@bot.command()
async def play(ctx, *, query):
    try:
        if not ctx.voice_client:
            if ctx.author.voice:
                await ctx.send("🔊 Connecting to voice channel...")
                await ctx.author.voice.channel.connect()
                print(f"[INFO] Connected to {ctx.author.voice.channel}")
            else:
                return await ctx.send("❌ You're not in a voice channel.")

        await ctx.send(f"🔎 Searching for: `{query}`")
        print(f"[INFO] Searching YouTube for: {query}")
        player = await YTDLSource.create_source(query, loop=bot.loop)

        await queue.add(player)
        await ctx.send(f"✅ Added to queue: **{player.title}**")
        print(f"[INFO] Queued: {player.title}")

        if not ctx.voice_client.is_playing():
            print("[INFO] Starting playback loop...")
            bot.loop.create_task(queue.player_loop(ctx))
    except Exception as e:
        await ctx.send(f"⚠️ Failed to play `{query}`: {str(e)}")
        print(f"[ERROR] play() failed: {e}")


@bot.command()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏭ Skipped.")
    else:
        await ctx.send("Nothing is playing.")


@bot.command()
async def show_queue(ctx):
    if queue.current:
        msg = f"**Now Playing**: {queue.current.title}\n"
    else:
        msg = "Nothing playing.\n"
    if queue.queue.empty():
        msg += "_Queue is empty._"
    else:
        q = list(queue.queue._queue)
        msg += "**Up Next:**\n" + "\n".join([f"- {track.title}" for track in q])
    await ctx.send(msg)


@bot.command()
async def stop(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        queue.queue = asyncio.Queue()
        await ctx.send("Disconnected and cleared queue.")


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')


bot.run(TOKEN)
