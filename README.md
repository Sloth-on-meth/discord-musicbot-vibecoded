# 🎶 Discord MusicBot (YouTube audio player)

#THIS IS 100% VIBECODED. LMAO. only gpt4, no typing

A simple Python Discord bot that joins voice channels and plays music using YouTube links or search queries. Uses `discord.py`, `yt-dlp`, and `ffmpeg`.

---

## ⚙️ Features

- `!play <query | YouTube URL>` – Searches and plays the first YouTube result
- `!skip` – Skips the current track
- `!queue` – Displays what's currently playing and queued
- `!stop` – Disconnects from voice and clears the queue
- Automatically joins the command issuer's voice channel
- Stream audio live via `yt-dlp` and `ffmpeg`
- Configurable via `config.json`

---

## 🚀 Getting Started

### 1. Install dependencies

```bash
sudo apt install ffmpeg
pip install -U discord.py yt-dlp
```

### 2. Create config.json
```
{
  "token": "YOUR_DISCORD_BOT_TOKEN"
}
```

### 3. run the bot
```
python3 music.py
```
