"""Turn the latest TLDR Tech newsletter into a two-host podcast and post it to Discord.

Config comes from environment variables or a .env file next to this script:
  GEMINI_API_KEY       required, writes the script (Gemini free tier is enough)
  GEMINI_MODEL         optional, defaults to gemini-3.8-flash
  DISCORD_WEBHOOK_URL  optional, posts the MP3 to that channel
  HOST_VOICE           Edge TTS voice for the main host (Person1)
  COHOST_VOICE         Edge TTS voice for the co-host (Person2)

Usage:
  python tldr_podcast.py              # generate the latest edition locally, no posting
  python tldr_podcast.py --post       # generate and post to Discord, skipped if already posted
  python tldr_podcast.py --force      # regenerate even if already posted
  python tldr_podcast.py --dry-run    # only print the cleaned newsletter text
"""

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
RSS_URL = "https://tldr.tech/api/rss/tech"
STATE_FILE = ROOT / "last_edition.txt"
OUT_DIR = ROOT / "episodes"
DISCORD_MAX_BYTES = 10 * 1024 * 1024  # upload limit for servers without boosts

# Podcastfy pulls its prompts from LangChain Hub, which langsmith now blocks by default.
# These pinned commits were audited on 2026-10-25: plain ChatPromptTemplates, no models,
# URLs or headers. Only these exact identifiers are allowed through.
AUDITED_PROMPTS = {
    "souzatharsis/podcastfy_multimodal_cleanmarkup:b2365f11",
    "souzatharsis/podcastfy_longform:acfdbc91",
    "souzatharsis/podcastfy_longform_clean:8c110a0b",
    "souzatharsis/podcast_rewriter:8ee296fb",
}

load_dotenv(ROOT / ".env")


def latest_edition():
    feed = feedparser.parse(RSS_URL)
    if not feed.entries:
        sys.exit(f"No entries in {RSS_URL}")
    entry = feed.entries[0]
    return entry.link, entry.title, entry.link.rstrip("/").rsplit("/", 1)[-1]


def newsletter_stories(url):
    html = requests.get(url, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")
    stories = []
    for article in soup.select("article"):
        title_tag = article.find("h3")
        body_tag = article.find("div", class_="newsletter-html")
        if not title_tag or not body_tag:
            continue
        title = title_tag.get_text(" ", strip=True)
        if "(Sponsor)" in title:
            continue
        title = re.sub(r"\s*\(\d+ minute read\)|\s*\(GitHub Repo\)", "", title)
        stories.append((title, body_tag.get_text(" ", strip=True)))
    if not stories:
        sys.exit(f"No stories found at {url}; the page layout may have changed")
    return stories


def allow_audited_hub_prompts():
    from langsmith import Client
    from podcastfy import content_generator

    def pull(identifier, **_):
        if identifier not in AUDITED_PROMPTS:
            sys.exit(f"Refusing unaudited hub prompt {identifier}")
        return Client().pull_prompt(identifier, dangerously_pull_public_prompt=True)

    content_generator.hub.pull = pull


def voice_wordless_turns():
    # Edge TTS returns no audio for a turn with no words (Gemini sometimes writes a
    # silent reaction like "..."), which kills the whole episode. Turns must keep
    # alternating, so the turn is voiced as a short acknowledgement instead of dropped.
    from podcastfy.tts.providers.edge import EdgeTTS

    generate_audio = EdgeTTS.generate_audio

    def generate(self, text, voice, model, voice2=None):
        if not re.search(r"\w", text):
            text = "Mm-hmm."
        return generate_audio(self, text, voice, model, voice2)

    EdgeTTS.generate_audio = generate


def make_podcast(text, date):
    from podcastfy.client import generate_podcast

    allow_audited_hub_prompts()
    voice_wordless_turns()

    conversation_config = {
        "podcast_name": "TLDR Daily",
        "podcast_tagline": f"Tech news for {date}",
        "output_language": "English",
        "conversation_style": ["calm", "conversational", "informative"],
        "roles_person1": "main host who walks through each story",
        "roles_person2": "co-host who asks questions and adds context",
        "dialogue_structure": ["Introduction", "Story by story", "Wrap-up"],
        "engagement_techniques": ["questions", "analogies"],
        "creativity": 0.6,
        "user_instructions": (
            "Cover every story in the newsletter, one at a time. "
            "Person1 does most of the talking and explains each story; "
            "Person2 keeps to short questions and reactions. "
            "Never mention sponsors, links or reading times."
        ),
        "text_to_speech": {
            "default_tts_model": "edge",
            "edge": {
                "default_voices": {
                    "question": os.environ.get("HOST_VOICE", "en-US-AvaMultilingualNeural"),
                    "answer": os.environ.get("COHOST_VOICE", "en-US-GuyNeural"),
                }
            },
            "output_directories": {
                "transcripts": str(OUT_DIR / "transcripts"),
                "audio": str(OUT_DIR),
            },
            "temp_audio_dir": str(OUT_DIR / "tmp") + os.sep,
            "ending_message": "That's it for today. See you tomorrow!",
        },
    }
    audio = generate_podcast(
        text=text,
        tts_model="edge",
        conversation_config=conversation_config,
        llm_model_name=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
    )
    if not audio:
        sys.exit("Podcastfy returned no audio file")
    final = OUT_DIR / f"tldr-{date}.mp3"
    os.replace(audio, final)
    return final


def post_to_discord(mp3, title, url, date, stories):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("DISCORD_WEBHOOK_URL not set, skipping Discord")
        return
    if mp3.stat().st_size > DISCORD_MAX_BYTES:
        sys.exit(f"{mp3.name} is over Discord's 10 MB limit")

    day = datetime.strptime(date, "%Y-%m-%d")
    headline = f"## {day:%A, %B} {day.day}, {day.year}"
    bullets = "\n\n".join(f"• {story_title}" for story_title, _ in stories)
    summary = f"{headline}\n\n{bullets}"
    embed = {
        "title": f"TLDR Daily: {title}"[:256],
        "url": url,
        "description": summary[:4096],
        "color": 0x5B6B7A,
    }
    requests.post(webhook, json={"embeds": [embed]}, timeout=30).raise_for_status()

    with mp3.open("rb") as f:
        r = requests.post(webhook, files={"file": (mp3.name, f, "audio/mpeg")}, timeout=120)
    r.raise_for_status()
    print("Posted to Discord")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--post", action="store_true", help="post to Discord (off by default)")
    args = parser.parse_args()

    url, title, date = latest_edition()
    stories = newsletter_stories(url)
    text = "\n\n".join(f"{story_title}\n{body}" for story_title, body in stories)
    if args.dry_run:
        print(f"{title}\n{url}\n\n{text}")
        return
    if not args.force and STATE_FILE.exists() and STATE_FILE.read_text().strip() == date:
        print(f"{datetime.now():%Y-%m-%d %H:%M} {date} already done")
        return
    print(f"{datetime.now():%Y-%m-%d %H:%M} found edition {date}")
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is not set")

    OUT_DIR.mkdir(exist_ok=True)
    mp3 = make_podcast(text, date)
    print(f"Saved {mp3}")
    if args.post:
        post_to_discord(mp3, title, url, date, stories)
        STATE_FILE.write_text(date)


if __name__ == "__main__":
    main()
