
Discord Music Bot

A feature-rich Discord music bot built with discord.py, yt-dlp, and openai that allows users to play music from YouTube, manage queues, get autoplay recommendations, and hear fun facts via Text-to-Speech.

Features

- **YouTube Playback**: Play songs directly from YouTube using search queries or URLs.
- **Music Queue**: Manage upcoming songs in a queue.
- **Skip**: Skip the currently playing song.
- **Stop**: Disconnect the bot from the voice channel and clear the queue.
- **Autoplay Recommendations**: Automatically add recommended songs to the queue when it's empty (toggleable).
- **TTS Announcements**: Announces the currently playing song and a random fun fact using OpenAI's Text-to-Speech.

Setup

To set up and run this bot, follow these steps:

**Prerequisites**:

- **Python**: Ensure you have Python 3.8 or higher installed. You can download it from python.org.
- **FFmpeg**: Install ffmpeg and make sure it's accessible in your system's PATH. You can find download instructions for your operating system on the ffmpeg website.

**Install Dependencies**:

Save the provided code as a Python file (e.g., `bot.py`). Open your terminal or command prompt, navigate to the directory where you saved the file, and run the following command to install the required libraries:

```bash
pip install discord.py yt-dlp openai PyNaCl
```

`PyNaCl` is necessary for voice functionality in `discord.py`.

**Create config.json**:

In the same directory as your bot script, create a file named `config.json`. This file will store your sensitive keys. Add the following structure to the file, replacing the placeholder values with your actual keys:

```json
{
  "token": "YOUR_DISCORD_BOT_TOKEN",
  "openai_api_key": "YOUR_OPENAI_API_KEY"
}
```

- **Discord Bot Token**: Obtain your bot token from the Discord Developer Portal. Create a new application, go to the "Bot" tab, and reveal the token. Keep this token secret!
- **OpenAI API Key**: Get your API key from the OpenAI API website. You'll need an OpenAI account. Keep this key secret!

**Run the Bot**:

After installing dependencies and creating the `config.json` file, you can run the bot using your terminal:

```bash
python bot.py
```

The bot should come online in your Discord server. Check the terminal output for confirmation (e.g., "Logged in as YourBotName").

Usage

The bot uses Discord slash commands. Type `/` in your Discord server's chat and select your bot to see the available commands.

- `/play [query]`: Use this command to play a song. You can paste a YouTube video URL or type a search query (e.g., `/play never gonna give you up` or `/play https://www.youtube.com/watch?v=dQw4w9WgXcQ`).
- `/skip`: Skips the song currently being played and moves to the next one in the queue.
- `/queue`: Displays the current song and lists the songs that are waiting in the queue.
- `/stop`: Disconnects the bot from the voice channel it's currently in and clears the entire music queue.
- `/autoplay`: Toggles the autoplay feature. When enabled, the bot will fetch and add recommended songs to the queue automatically once the current queue is empty, based on the last played song.

Notes

- Ensure the bot has the necessary permissions to join voice channels, speak, and send messages in the channels you intend to use it in.
- The quality of recommendations and facts depends on the respective APIs (YouTube and OpenAI).
```
