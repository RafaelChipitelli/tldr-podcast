"""Fallback dialogue writer: Gemini through Podcastfy writes episodes/DATE/transcript.txt.

Claude writes the episode in the cloud routine (docs/episode-session.md). This runs only
from the GitHub Actions fallback, when the routine hasn't posted by the afternoon. It needs
GEMINI_API_KEY (and optionally GEMINI_MODEL) and requirements-gemini.txt.

Usage:
  python gemini_writer.py DATE    # after `python tldr_podcast.py fetch`
"""

import os
import shutil
import sys
import time

from tldr_podcast import OUT_DIR

# Podcastfy pulls its prompts from LangChain Hub, which langsmith now blocks by default.
# These pinned commits were audited on 2026-10-25: plain ChatPromptTemplates, no models,
# URLs or headers. Only these exact identifiers are allowed through.
AUDITED_PROMPTS = {
    "souzatharsis/podcastfy_multimodal_cleanmarkup:b2365f11",
    "souzatharsis/podcastfy_longform:acfdbc91",
    "souzatharsis/podcastfy_longform_clean:8c110a0b",
    "souzatharsis/podcast_rewriter:8ee296fb",
}


def allow_audited_hub_prompts():
    from langsmith import Client
    from podcastfy import content_generator

    def pull(identifier, **_):
        if identifier not in AUDITED_PROMPTS:
            sys.exit(f"Refusing unaudited hub prompt {identifier}")
        return Client().pull_prompt(identifier, dangerously_pull_public_prompt=True)

    content_generator.hub.pull = pull


def write_transcript(date):
    from podcastfy.client import generate_podcast

    allow_audited_hub_prompts()
    folder = OUT_DIR / date
    text = (folder / "newsletter.txt").read_text(encoding="utf-8")
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
            "Never mention sponsors, links or reading times. "
            "End with: That's it for today. See you tomorrow!"
        ),
        "text_to_speech": {"output_directories": {"transcripts": str(folder / "gemini")}},
    }
    # Free-tier Gemini models fail in more ways than we can list (429, 503, 504 seen so
    # far), sometimes for hours, so any failure falls back to an older model. The per-minute
    # quota can hit both models back to back, so rounds are spaced a few minutes apart.
    models = list(dict.fromkeys([os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"), "gemini-3.5-flash"]))
    attempts = [(round_, model) for round_ in range(4) for model in models]
    for i, (round_, model) in enumerate(attempts):
        if i and model == models[0]:
            print(f"All models failed, waiting {90 * round_}s before round {round_ + 1}", file=sys.stderr)
            time.sleep(90 * round_)
        try:
            transcript = generate_podcast(
                text=text,
                transcript_only=True,
                conversation_config=conversation_config,
                llm_model_name=model,
            )
            break
        except Exception as e:
            if i == len(attempts) - 1:
                raise
            print(f"{model} failed ({str(e)[:80]}), trying again", file=sys.stderr)
    if not transcript:
        sys.exit("Podcastfy returned no transcript")
    shutil.copy(transcript, folder / "transcript.txt")
    print(f"Wrote {folder / 'transcript.txt'} with {model}")


if __name__ == "__main__":
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is not set")
    write_transcript(sys.argv[1])
