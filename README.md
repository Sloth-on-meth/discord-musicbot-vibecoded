# Discord Music Bot
# FULLY VIBECODED. NOT A SINGLE CHAR HANDTYPED!

A feature-rich Discord music bot built with discord.py, yt-dlp, and OpenAI that allows users to play music from YouTube, manage queues, and hear song announcements via Text-to-Speech.

## Features

- **YouTube Playback**: Play songs directly from YouTube using search queries or URLs.
- **Music Queue**: Manage upcoming songs in a queue.
- **Skip**: Skip the currently playing song.
- **Stop**: Disconnect the bot from the voice channel and clear the queue.
- **TTS Announcements**: Announces the currently playing song using OpenAI's Text-to-Speech before each track.
- **TTS Interruptions**: Inject custom TTS messages during playback and resume at the correct timestamp.

## Setup

To set up and run this bot, follow these steps:

### Prerequisites

- **Python**: Python 3.8 or higher. [Download Python](https://www.python.org/downloads/)
- **FFmpeg**: Install ffmpeg and ensure it is accessible in your system's PATH. [Download FFmpeg](https://ffmpeg.org/download.html)

### Install Dependencies

Save the bot code as `bot.py` and run:

```bash
pip install discord.py yt-dlp openai PyNaCl
```

### Configuration

Create a `config.json` file in the same directory as your bot script with the following content:

```json
{
  "token": "YOUR_DISCORD_BOT_TOKEN",
  "openai_api_key": "YOUR_OPENAI_API_KEY",
  "musicbot_log_channel": YOUR_LOG_CHANNEL_ID
}
```

- Replace values with your actual Discord Bot token, OpenAI API key, and the numeric channel ID where logs should be sent.

### Running the Bot

```bash
python bot.py
```

The bot will come online and respond to commands in your Discord server.

## Commands

- `!play [query]` — Play a song from YouTube via search or URL.
- `!skip` — Skip the current song.
- `!stop` — Stop playback and disconnect the bot.
- `!showqueue` — Display the current queue.
- `!tittiestts [text]` — Interrupt playback with a TTS message and resume from where it left off.

## Notes

- Ensure the bot has permissions to connect and speak in voice channels.
- You must be in a voice channel to use `!play`, `!tittiestts`, or `!stop`.
- TTS playback uses OpenAI's `tts-1` model and `alloy` voice.
