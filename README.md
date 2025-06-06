# Discord Music Bot
# FULLY VIBECODED. NOT A SINGLE CHAR HANDTYPED!

A feature-rich Discord music bot built with discord.py, yt-dlp, and OpenAI that allows users to play music from YouTube, manage queues, and hear song announcements via Text-to-Speech.

## Features

- **YouTube Playback**: Play songs directly from YouTube using search queries or URLs.
- **Music Queue**: Manage upcoming songs in a queue.
- **Skip**: Skip the currently playing song.
- **Stop**: Disconnect the bot from the voice channel and clear the queue.
- **TTS Announcements**: Announces the currently playing song using OpenAI's Text-to-Speech before each track.
- **TTS Interruptions**: Inject custom TTS messages at any time, even if no music is playing.
- **Per-User TTS Voices**: Every user can choose their own OpenAI TTS voice with `!ttsvoice` and it will be remembered for all their TTS.
- **Pretty Embeds**: All bot responses use beautiful, modern Discord embeds for clarity and style.
- **Command List & Help**: Use `!commands` for a quick list, or `!help` for a detailed overview of all features.

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

**Note:** If you use a music command in the wrong channel, the bot will not reply at all—no error, no message, and no log. Only commands sent in the configured music commands channel will be processed.

- `!play [query]` — Play a song from YouTube via search or URL.
- `!skip` — Skip the current song.
- `!stop` — Stop playback and disconnect the bot.
- `!showqueue` — Display the current queue.
- `!tts [text]` — Speak a message in your chosen TTS voice in the voice channel (works any time, even if no music is playing).
- `!ttsvoice [voice]` — Set or show your personal TTS voice. Use without arguments to see your current voice and all available options.
- `!commands` — Show a pretty embed with all available commands and summaries.
- `!help` — Show a beautiful embed with detailed explanations of all bot features and usage.

## Per-User TTS Voices

Every user can select their own OpenAI TTS voice using `!ttsvoice <voice>`. The bot will remember your choice for all future TTS, even after restarts—your selection is stored persistently in the database.

## Seamless Music & TTS

- When you use `!tts` while music is playing, the music will pause, play your TTS, and then resume from the exact point it was paused (not from the start).
- This ensures smooth transitions and minimal interruption.

## Persistent Queue and Settings

- The music queue and all user settings (including TTS voices) are now fully persistent across bot restarts. The database is never reset on startup.

## Changelog

See [changelog.md](changelog.md) for a full history of updates and improvements.

## Notes

- If you use a music command in a channel other than the configured music commands channel, the bot will simply ignore it and do nothing (no error, no message, no log).


- Ensure the bot has permissions to connect and speak in voice channels.
- You must be in a voice channel to use music or TTS commands.
- TTS playback uses OpenAI's `tts-1` model and supports all available voices.
- All responses use beautiful, modern Discord embeds for a better experience.
