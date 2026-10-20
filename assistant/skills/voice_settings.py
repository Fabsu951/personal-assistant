"""Lets the assistant change how it sounds (voice, tone, when to speak)."""
from .. import voice
from .base import Skill, Tool, schema


def voice_settings(a, ctx):
    if a.get("voice"):
        ctx.db.set("tts_voice", a["voice"])
    if a.get("style"):
        ctx.db.set("tts_style", a["style"])
    if a.get("replies"):
        ctx.db.set("voice_replies", a["replies"])
    return {"voice": ctx.db.get("tts_voice", ctx.config.tts_voice),
            "style": ctx.db.get("tts_style", ctx.config.tts_style),
            "replies": ctx.db.get("voice_replies", ctx.config.voice_replies)}


class VoiceSkill(Skill):
    def __init__(self):
        super().__init__(
            name="Voice",
            description="Spoken replies: voice, tone and when to speak.",
            instructions=(
                "Your spoken replies use text-to-speech that you CAN adjust with "
                "voice_settings: 'style' is an instruction for tone, emotion and pace (write it "
                "in English, e.g. 'Very cheerful and energetic, smiling, upbeat pace'), 'voice' "
                "picks the speaker, 'replies' sets when you speak (auto = answer voice with "
                "voice, always, off). When the user asks for a different sound, change it and "
                "tell them the next spoken reply will sound like that."
            ),
            tools=[
                Tool("voice_settings", "Change or show how spoken replies sound.",
                     schema({"voice": {"type": "string", "enum": list(voice.VOICES),
                                       "description": "onyx/ash/echo = deeper male-sounding, "
                                                      "nova/coral/shimmer = brighter female-sounding"},
                             "style": {"type": "string",
                                       "description": "Tone instruction for the speech engine"},
                             "replies": {"type": "string", "enum": list(voice.MODES)}}),
                     voice_settings),
            ],
        )
