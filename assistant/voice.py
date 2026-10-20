"""Voice messages -> text.

Claude can't listen to audio, so a speech-to-text API transcribes the voice
message first and the text then goes to the assistant like a typed message.
"""
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
