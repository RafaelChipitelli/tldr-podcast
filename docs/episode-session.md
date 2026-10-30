# The episode session

The runbook for the scheduled Claude session that makes each weekday's TLDR Daily episode
(Rafael, 30/10/2026). Code does the mechanical work: it fetches the edition, voices the
transcript with Edge TTS and posts to Discord. The session does the part Gemini used to do:
it writes the two-host dialogue. If the session posts nothing, GitHub Actions has Gemini
write the episode in the afternoon (`.github/workflows/podcast.yml`).

It runs in an Anthropic cloud session (a routine, or a session Rafael starts from the
phone), in the repo root of the clone. `DISCORD_WEBHOOK_URL` comes from the environment.
`D` below is the edition's date, as `fetch` prints it.

If Rafael asks for a **dry run**, do steps 0 to 3 and stop: nothing is posted.

## Never

- Never post any other way than step 4, and never pass `--force`.
- Never print or post the webhook URL.
- Never commit, push, switch branches or edit code or docs; the one push allowed is the one
  `post` makes to the `editions-data` branch. If the code is in the way, stop and say so in
  the summary; the Actions fallback will post in the afternoon.
- Never say a fact, number or name that is not in that story's text in `newsletter.txt`.

## 0. Set up

    python -m pip install -q -r requirements.txt

`python -m pip`, because in the cloud a bare `pip` installs into another Python. ffmpeg
comes with it (`imageio-ffmpeg`), so nothing else is installed.

## 1. Should it run?

    python tldr_podcast.py fetch

It saves the latest edition to `episodes/D/` and ends with one line. `posted D` means the
latest edition is already out (TLDR hasn't published a new one yet, or it was posted
already): stop there with a one-line summary. `new D` means go on.

## 2. Write the transcript: `episodes/D/transcript.txt`

Read `episodes/D/newsletter.txt` in full: the edition's title and link, then each story's
headline and text. Write the episode as a conversation between two hosts:

- **Person1 is Ava, the main host.** She walks through every story, one at a time, in the
  newsletter's order, and does most of the talking.
- **Person2 is Guy, the co-host.** He keeps to short questions and reactions that move the
  story along or add context the text supports.
- Calm, conversational and informative, like two people who read the news before work. An
  analogy now and then when it makes a story clearer.
- Open with `Welcome to TLDR Daily - Tech news for <Month day>.` and a one-line preview of
  the top stories. Close with a short wrap-up and `That's it for today. See you tomorrow!`
- Cover every story. Say what happened, then why it matters, with the numbers and names
  the text gives. No sponsors, links, reading times or "GitHub repo".
- Write for the ear: no markdown, emoji, bullet points, URLs or stage directions. Say
  symbols as words ("percent", "dollars"); "US$2" is "two US dollars". Model and product
  names as they are written are fine.
- Each turn is one to four sentences. The length follows the newsletter: about one and a
  half times its word count (`wc -w episodes/D/newsletter.txt`). Never pad to reach a
  number; covering every story clearly matters more. 1,176 words made 7.7 minutes.

The file holds only the turns, one per line, alternating and starting with Person1:

```
<Person1>Welcome to TLDR Daily - Tech news for October 29. ...</Person1>
<Person2>Where do we start?</Person2>
<Person1>...</Person1>
```

Then read it once against `newsletter.txt`, as a fact-checker would: every number, name,
date and claim must be in that story's text. Fix or remove what isn't. Never add a fact to
fix one.

## 3. Voice it

    python tldr_podcast.py voice D

It voices each turn with Edge TTS (Ava for Person1, Guy for Person2) and joins them into
`episodes/D/tldr-D.mp3`, and prints how many turns it voiced. A turn Edge TTS refuses three
times is skipped with a warning; if more than two are skipped, find what they share (an
odd character, a very long turn), fix the transcript and run this step again.

## 4. Post

    python tldr_podcast.py post D

It posts the embed (date and headlines) and the MP3 to Discord, then records `D` as posted
on the `editions-data` branch so the Actions fallback doesn't post it again. It refuses if
`D` was posted in the meantime: that is a stop, not an error to work around. If the post
went out but recording failed, say so in the summary: the fallback would post it again.

## 5. Summary

End with three lines: the edition date and how many stories, the episode's length (word
count and MP3 size), and anything that went wrong on the way.
