"""The retry and fallback paths only run when Gemini or Edge TTS misbehave, so fake both."""

import pytest
import podcastfy.client
from podcastfy.tts.providers.edge import EdgeTTS

import tldr_podcast


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(tldr_podcast.time, "sleep", calls.append)
    return calls


@pytest.fixture
def podcast(monkeypatch, tmp_path, sleeps):
    """Run make_podcast against a fake generate_podcast that fails `failures` times."""
    monkeypatch.setattr(tldr_podcast, "OUT_DIR", tmp_path)
    monkeypatch.setattr(tldr_podcast, "allow_audited_hub_prompts", lambda: None)
    monkeypatch.setattr(tldr_podcast, "resilient_turns", lambda: None)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    def run(failures):
        models = []

        def generate(llm_model_name, **_):
            models.append(llm_model_name)
            if len(models) <= failures:
                raise RuntimeError("429 You exceeded your current quota")
            audio = tmp_path / "raw.mp3"
            audio.write_bytes(b"mp3")
            return str(audio)

        monkeypatch.setattr(podcastfy.client, "generate_podcast", generate)
        return tldr_podcast.make_podcast("text", "2026-10-27"), models

    return run


def test_first_model_works(podcast, sleeps):
    mp3, models = podcast(failures=0)
    assert mp3.name == "tldr-2026-10-27.mp3" and mp3.read_bytes() == b"mp3"
    assert models == ["gemini-3.8-flash"]
    assert sleeps == []


def test_falls_back_to_older_model_without_waiting(podcast, sleeps):
    _, models = podcast(failures=1)
    assert models == ["gemini-3.8-flash", "gemini-3.5-flash"]
    assert sleeps == []


def test_waits_out_quota_when_both_models_fail(podcast, sleeps):
    # 2026-10-27: both models hit the per-minute quota seconds apart.
    _, models = podcast(failures=2)
    assert models == ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.8-flash"]
    assert sleeps == [90]


def test_gives_up_after_every_round(podcast, sleeps):
    with pytest.raises(RuntimeError, match="429"):
        podcast(failures=99)
    assert sleeps == [90, 180, 270]


@pytest.fixture
def tts(monkeypatch, sleeps):
    """Patch Edge TTS with a fake that fails for the given texts, then apply resilient_turns."""

    def setup(failing):
        voiced = []

        def generate_audio(self, text, voice, model, voice2=None):
            voiced.append(text)
            if failing(text):
                raise RuntimeError("No audio was received")
            return b"audio"

        monkeypatch.setattr(EdgeTTS, "generate_audio", generate_audio)
        tldr_podcast.resilient_turns()
        return voiced

    return setup


def test_tts_retries_then_strips_markup(tts):
    voiced = tts(failing=lambda text: "<" in text)
    assert EdgeTTS.generate_audio(None, "<b>Hi</b> there", "v", "m") == b"audio"
    assert voiced == ["<b>Hi</b> there", "<b>Hi</b> there", "Hi  there"]


def test_tts_acknowledges_when_nothing_works(tts):
    voiced = tts(failing=lambda text: text != "Mm-hmm.")
    assert EdgeTTS.generate_audio(None, "Hello", "v", "m") == b"audio"
    assert voiced[-1] == "Mm-hmm." and len(voiced) == 4


def test_tts_voices_wordless_turn_as_acknowledgement(tts):
    voiced = tts(failing=lambda text: False)
    EdgeTTS.generate_audio(None, "...", "v", "m")
    assert voiced == ["Mm-hmm."]
