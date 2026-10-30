"""Turn the latest TLDR Tech newsletter into a two-host podcast and post it to Discord.

Claude writes the dialogue in a cloud routine (docs/episode-session.md). When the routine
hasn't posted by the afternoon, GitHub Actions has Gemini write it instead
(gemini_writer.py). Either way this script does the rest: it fetches the edition, voices
the transcript and posts it.

Config comes from environment variables or a .env file next to this script:
  DISCORD_WEBHOOK_URL  needed by `post`
  HOST_VOICE           Edge TTS voice for the main host (Person1)
  COHOST_VOICE         Edge TTS voice for the co-host (Person2)

Usage:
  python tldr_podcast.py fetch               # save the latest edition to episodes/DATE/
  python tldr_podcast.py voice DATE          # episodes/DATE/transcript.txt -> tldr-DATE.mp3
  python tldr_podcast.py post DATE           # post it, then record DATE as posted
  python tldr_podcast.py post DATE --force   # post even if DATE was already posted

`fetch` ends with one line, `new DATE` or `posted DATE`.

The last posted edition lives in last_edition.txt on the editions-data branch, so the
cloud routine and the Actions fallback see each other's posts.
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import edge_tts
import feedparser
import imageio_ffmpeg
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
RSS_URL = "https://tldr.tech/api/rss/tech"
OUT_DIR = ROOT / "episodes"
DATA_BRANCH = "editions-data"
STATE_FILE = "last_edition.txt"
IDENTITY = ["-c", "user.name=TLDR Daily", "-c", "user.email=tldr-daily@users.noreply.github.com"]
DISCORD_MAX_BYTES = 10 * 1024 * 1024  # upload limit for servers without boosts

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


def git(*args, stdin=None):
    result = subprocess.run(["git", *args], cwd=ROOT, input=stdin, capture_output=True, text=True)
    if result.returncode:
        sys.exit(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def last_posted():
    # A failed fetch must stop the run: reading it as "nothing posted" would post twice.
    git("fetch", "-q", "origin", DATA_BRANCH)
    return git("show", f"FETCH_HEAD:{STATE_FILE}")


def record_posted(date):
    # Commit onto the data branch with plumbing, so the checkout is never switched. The
    # cloud git proxy allows pushing a branch but not deleting one, which this never does.
    # The parent is the FETCH_HEAD last_posted() just read, so a post from the other side
    # in between makes this push fail instead of overwriting it.
    blob = git("hash-object", "-w", "--stdin", stdin=f"{date}\n")
    tree = git("mktree", stdin=f"100644 blob {blob}\t{STATE_FILE}\n")
    commit = git(*IDENTITY, "commit-tree", tree, "-p", "FETCH_HEAD", "-m", f"Posted {date}")
    git("push", "-q", "origin", f"{commit}:refs/heads/{DATA_BRANCH}")


def fetch():
    url, title, date = latest_edition()
    stories = newsletter_stories(url)
    folder = OUT_DIR / date
    folder.mkdir(parents=True, exist_ok=True)
    edition = {"date": date, "title": title, "url": url, "stories": [t for t, _ in stories]}
    (folder / "edition.json").write_text(json.dumps(edition, indent=1), encoding="utf-8")
    text = "\n\n".join(f"{story_title}\n{body}" for story_title, body in stories)
    (folder / "newsletter.txt").write_text(f"{title}\n{url}\n\n{text}\n", encoding="utf-8")
    print(f"{len(stories)} stories in {folder}")
    print(f"{'posted' if last_posted() == date else 'new'} {date}")


def turns(transcript):
    for person, text in re.findall(r"<Person([12])>(.*?)</Person\1>", transcript, re.DOTALL):
        text = " ".join(re.sub(r"<[^>]+>", " ", text).split())
        # A turn with no words (Gemini sometimes writes "...") makes Edge TTS fail.
        if re.search(r"\w", text):
            yield person, text


def speak(text, voice, path):
    # Edge TTS fails a turn now and then for reasons we couldn't reproduce. Retry, then
    # strip anything but plain text. One bad turn is skipped rather than losing the episode.
    plain = re.sub(r"[^\w\s.,!?'-]", " ", text)
    for i, attempt in enumerate([text, text, plain]):
        try:
            asyncio.run(edge_tts.Communicate(attempt, voice).save(str(path)))
            return True
        except Exception as e:
            print(f"TTS attempt {i + 1} failed for {attempt[:60]!r}: {e}", file=sys.stderr)
            time.sleep(2)
    print(f"Skipping the turn {text[:60]!r}", file=sys.stderr)
    return False


def voice(date):
    folder = OUT_DIR / date
    transcript = (folder / "transcript.txt").read_text(encoding="utf-8")
    voices = {
        "1": os.environ.get("HOST_VOICE", "en-US-AvaMultilingualNeural"),
        "2": os.environ.get("COHOST_VOICE", "en-US-GuyNeural"),
    }
    lines = list(turns(transcript))
    if not lines:
        sys.exit("No <Person1>/<Person2> turns in the transcript")
    mp3 = folder / f"tldr-{date}.mp3"
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, (person, text) in enumerate(lines):
            part = Path(tmp) / f"{i:03}.mp3"
            if speak(text, voices[person], part):
                parts.append(part)
        playlist = Path(tmp) / "parts.txt"
        playlist.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        # Edge TTS returns every turn in the same format, so the parts join without re-encoding.
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", str(playlist), "-c", "copy", str(mp3)],
            check=True,
        )
    print(f"Voiced {len(parts)} of {len(lines)} turns into {mp3}")


def post(date, force):
    folder = OUT_DIR / date
    edition = json.loads((folder / "edition.json").read_text(encoding="utf-8"))
    mp3 = folder / f"tldr-{date}.mp3"
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        sys.exit("DISCORD_WEBHOOK_URL is not set")
    if mp3.stat().st_size > DISCORD_MAX_BYTES:
        sys.exit(f"{mp3.name} is over Discord's 10 MB limit")
    if last_posted() == date and not force:
        sys.exit(f"{date} was already posted")

    day = datetime.strptime(date, "%Y-%m-%d")
    headline = f"## {day:%A, %B} {day.day}, {day.year}"
    bullets = "\n\n".join(f"• {story_title}" for story_title in edition["stories"])
    summary = f"{headline}\n\n{bullets}"
    embed = {
        "title": f"TLDR Daily: {edition['title']}"[:256],
        "url": edition["url"],
        "description": summary[:4096],
        "color": 0x5B6B7A,
    }
    requests.post(webhook, json={"embeds": [embed]}, timeout=30).raise_for_status()

    with mp3.open("rb") as f:
        r = requests.post(webhook, files={"file": (mp3.name, f, "audio/mpeg")}, timeout=120)
    r.raise_for_status()
    print("Posted to Discord")
    record_posted(date)
    print(f"Recorded {date} on {DATA_BRANCH}")


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fetch")
    commands.add_parser("voice").add_argument("date")
    post_parser = commands.add_parser("post")
    post_parser.add_argument("date")
    post_parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.command == "fetch":
        fetch()
    elif args.command == "voice":
        voice(args.date)
    else:
        post(args.date, args.force)


if __name__ == "__main__":
    main()
