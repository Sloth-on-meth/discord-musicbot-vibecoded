# 🎶 Discord MusicBot with TTS Announcements

A Python-powered Discord bot that streams audio from YouTube into voice channels and announces the currently playing track using OpenAI's Text-to-Speech (TTS).

### 🚀 Features

!play <query or YouTube URL> — Play a song (searches YouTube if not a URL)

!skip — Skip the current song

!queue — Show current and upcoming songs

!stop — Disconnect and clear the queue

🎙 Announces songs using realistic OpenAI TTS voices

### 🔊 Streams audio via yt-dlp and ffmpeg

⚙️ Requirements

Install system dependencies:

sudo apt install ffmpeg

Install Python packages:

pip install -U discord.py yt-dlp openai httpx

### 📁 Setup

Create a config.json file:
```
{
  "token": "YOUR_DISCORD_BOT_TOKEN",
  "openai_api_key": "YOUR_OPENAI_API_KEY"
}
```
Run the bot:
```
python3 music.py
```
🧪 Commands

!play hello          # searches YouTube
!play <youtube_url>  # direct link
!skip                # skip current track
!queue               # show queue
!stop                # stop and leave

🧠 How it Works

yt-dlp fetches audio streams from YouTube

ffmpeg transcodes live to Discord-compatible PCM

OpenAI TTS generates mp3 intro clips like: “Now playing Never Gonna Give You Up, requested by Sam.”

🔐 Legal & Notes

This bot is for educational/personal use only.
Using YouTube content in public servers may violate TOS.
OpenAI API usage is billable — keep an eye on usage.

✨ Attribution

This bot was 100% written by ChatGPT via prompts.
I typed nothing but vibes. 😎
