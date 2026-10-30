# TLDR Daily Podcast

Turns the latest [TLDR Tech](https://tldr.tech/tech) newsletter into a two-host podcast and posts it to Discord.

- Script: Claude, in an Anthropic cloud routine that follows [docs/episode-session.md](docs/episode-session.md)
- Voices: Edge TTS (Ava hosts, Guy co-hosts)
- Discord: an embed with the date and headlines, then the MP3

If the routine hasn't posted by the afternoon (UTC), the GitHub Actions workflow has Gemini
write the episode through [Podcastfy](https://github.com/souzatharsis/podcastfy) instead.
The last posted edition lives on the `editions-data` branch, so the two never post the same
edition. Setup: [docs/cloud-session-checklist.md](docs/cloud-session-checklist.md).

## Secrets

- `DISCORD_WEBHOOK_URL`: channel settings > Integrations > Webhooks (cloud environment and Actions)
- `GEMINI_API_KEY`: free key from https://aistudio.google.com/apikey (Actions only)

## Run locally

```bash
pip install -r requirements.txt
python tldr_podcast.py fetch              # save the latest edition to episodes/DATE/
python tldr_podcast.py voice DATE         # episodes/DATE/transcript.txt -> MP3
python tldr_podcast.py post DATE          # post and record it on editions-data
```

The fallback writer needs `pip install -r requirements-gemini.txt`, then
`python gemini_writer.py DATE` writes the transcript. Locally, the secrets go in a `.env`
file next to the script.
