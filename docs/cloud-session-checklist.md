# Running the episode session in the cloud: checklist

Goal (Rafael, 30/10/2026): Claude writes each weekday's episode instead of Gemini, in an
Anthropic cloud routine on Rafael's subscription, the way the newsletter moved on
30/10/2026. The routine clones the repo and follows `docs/episode-session.md`. GitHub
Actions stays as an automatic fallback in the afternoon (UTC), with Gemini.

## The cloud environment (Rafael, on claude.ai/code)

One environment for tldr-podcast. Claude cannot type keys.

- [ ] Network access: **Full** (tldr.tech, Edge TTS's speech service, PyPI, Discord).
- [ ] Environment variable, `.env` style: `DISCORD_WEBHOOK_URL` (the same webhook as the
      Actions secret).
- [ ] Setup script: none. `pip install` is the runbook's step 0, and ffmpeg comes from the
      `imageio-ffmpeg` wheel, so the image needs no apt package.

## The routine (Rafael)

- [ ] Create a routine on `RafaelChipitelli/tldr-podcast`, in that environment, no
      connectors, prompt: `Run docs/episode-session.md.`
- [ ] Cron, in UTC: `15 12 * * 1-5` (weekdays 12:15 UTC: 23:15 AEDT, 22:15 AEST).
      TLDR's 30/10/2026 edition reached the RSS feed between 10:30 and 10:33 UTC, 06:30
      New York time, and the 29/10 one was there by 11:19 UTC. New York leaves daylight
      saving on 01/11/2026, which moves the edition to about 11:30 UTC; 12:15 clears both,
      so **this cron never needs changing**, for New York's or Sydney's daylight saving.
      An edition later than that: the routine prints `posted` with yesterday's date and
      stops, and the Actions fallback posts it from 15:05 UTC.
- [ ] Run it once by hand as a dry run first: `Run docs/episode-session.md as a dry run.`
      It stops after the MP3 and posts nothing.

## Code (Claude, PR #8)

- [x] `tldr_podcast.py fetch | voice | post`, with no Gemini in the main path.
- [x] The last posted edition lives on the `editions-data` branch (seeded with
      `2026-10-29`); the routine and the fallback both read it before posting.
- [x] `podcast.yml` is the fallback: hourly from 15:05 UTC on weekdays, Gemini writes the
      transcript only when the latest edition isn't recorded as posted.
- [x] Dry run on PC, 30/10/2026: transcript of 1,176 words, 59 of 59 turns voiced, a
      7.7 minute, 2.7 MB MP3. Voicing took about 6 minutes.
