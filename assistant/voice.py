"""Voice in and out.

Claude can't listen or speak, so OpenAI's speech-to-text turns voice messages
into text for the assistant, and text-to-speech reads its replies aloud.
"""
import re

import httpx

API_URL = "https://api.openai.com/v1/audio/transcriptions"


async def transcribe(config, audio: bytes, filename: str = "voice.ogg") -> str:
    if not config.openai_api_key:
        raise RuntimeError("voice messages need the OPENAI_API_KEY setting (see README).")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            API_URL,
            headers={"Authorization": f"Bearer {config.openai_api_key}"},
            data={"model": config.transcribe_model},
            files={"file": (filename, audio)},
        )
    if r.status_code != 200:
        raise RuntimeError(f"transcription service said {r.status_code}: {r.text[:200]}")
    return r.json().get("text", "").strip()


SPEECH_URL = "https://api.openai.com/v1/audio/speech"
MODES = ("auto", "always", "off")  # auto = answer voice with voice


def wants_voice(mode: str, spoken: bool) -> bool:
    return mode == "always" or (mode == "auto" and spoken)


def for_speech(text: str) -> str:
    """Drop what sounds bad read aloud (links, markdown symbols)."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_`#>]", "", text)
    return text.strip()[:4000]  # the API takes at most 4096 characters


async def speak(config, text: str) -> bytes:
    """Text -> an OGG/Opus voice message that Telegram plays inline."""
    if not config.openai_api_key:
        raise RuntimeError("voice replies need the OPENAI_API_KEY setting (see README).")
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            SPEECH_URL,
            headers={"Authorization": f"Bearer {config.openai_api_key}"},
            json={"model": config.tts_model, "voice": config.tts_voice,
                  "input": for_speech(text), "response_format": "opus",
                  "instructions": "Speak naturally and warmly, at a relaxed pace, "
                                  "in the language of the text."},
        )
    if r.status_code != 200:
        raise RuntimeError(f"speech service said {r.status_code}: {r.text[:200]}")
    return r.content
