# TLDR Daily Podcast

Turns the latest [TLDR Tech](https://tldr.tech/tech) newsletter into a two-host podcast and posts it to Discord.

- Script: [Podcastfy](https://github.com/souzatharsis/podcastfy) with Gemini
- Voices: Edge TTS (Ava hosts, Guy co-hosts)
- Discord: an embed with the date and headlines, then the MP3

GitHub Actions checks the RSS feed every hour and only generates when a new edition is out (weekdays).

## Secrets

- `GEMINI_API_KEY`: free key from https://aistudio.google.com/apikey
- `DISCORD_WEBHOOK_URL`: channel settings > Integrations > Webhooks

## Run locally

```bash
pip install -r requirements.txt
python tldr_podcast.py --dry-run   # print the cleaned newsletter
python tldr_podcast.py             # generate the MP3 in episodes/, no posting
python tldr_podcast.py --post      # generate and post
```

Locally, the secrets go in a `.env` file next to the script.
