"""The web server next to the bot: the hands-free voice page, the Teams endpoint,
private download links for documents, and the Teams app package.

Telegram opens /talk inside the app. The page listens, sends what you said to
/api/talk, plays Ragnar's spoken reply straight away and starts listening again.
Every request is checked: only the owner gets an answer.
"""
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qsl, quote

from aiohttp import web

from . import voice

log = logging.getLogger(__name__)

PAGE = Path(__file__).with_name("static") / "talk.html"
PRIVACY = Path(__file__).parent.parent / "docs" / "privacy.html"
FILE_DAYS = 7  # download links for documents stop working after this
MAX_AUDIO = 15 * 1024 * 1024
KEY_DAYS = 30
EXTENSIONS = {"webm": "webm", "mp4": "mp4", "ogg": "ogg", "mpeg": "mp3", "wav": "wav"}


def check_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> int | None:
    """Telegram signs the Mini App's initData with the bot token. Returns the user id if valid."""
    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received = fields.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not received or not hmac.compare_digest(expected, received):
        return None
    if time.time() - int(fields.get("auth_date", 0)) > max_age:
        return None
    return json.loads(fields.get("user", "{}")).get("id")


def _sign(bot_token: str, owner_id: int, expires: int) -> str:
    return hmac.new(bot_token.encode(), f"talk:{owner_id}:{expires}".encode(),
                    hashlib.sha256).hexdigest()[:32]


def make_key(bot_token: str, owner_id: int) -> str:
    """Link key for opening the page in a normal browser instead of inside Telegram."""
    expires = int(time.time()) + KEY_DAYS * 86400
    return f"{expires}.{_sign(bot_token, owner_id, expires)}"


def check_key(key: str, bot_token: str, owner_id: int) -> bool:
    expires, _, sig = key.partition(".")
    if not expires.isdigit() or int(expires) < time.time():
        return False
    return hmac.compare_digest(sig, _sign(bot_token, owner_id, int(expires)))


class WebApp:
    def __init__(self, bot):
        self.bot = bot  # the assistant's Bot (main.py): agent, db, config, approvals
        self.config = bot.config
        self.app = web.Application(client_max_size=MAX_AUDIO)
        self.app.add_routes([web.get("/", self.page), web.get("/talk", self.page),
                             web.post("/api/talk", self.talk),
                             web.post("/api/messages", self.teams_message),
                             web.get("/files/{token}/{name}", self.download),
                             web.get("/teams/app.zip", self.teams_package),
                             web.get("/privacy", self.privacy)])
        self.runner: web.AppRunner | None = None

    def authorized(self, request) -> bool:
        if init_data := request.headers.get("X-Init-Data"):  # opened inside Telegram
            owner = self.config.owner_id
            return bool(owner) and check_init_data(init_data, self.config.telegram_token) == owner
        secret = self.bot.link_secret()  # a signed link, e.g. from /talk in Teams or a browser
        return bool(secret) and check_key(request.headers.get("X-Key", ""), secret, self.bot.home_chat)

    # ------------------------------------------------------- documents
    def file_link(self, name: str, data: bytes) -> str:
        """A private, expiring link to a document (Teams bots can't attach files directly)."""
        token = secrets.token_urlsafe(24)
        self.bot.db.execute("DELETE FROM kv WHERE key LIKE 'file:%' AND json_extract(value, '$.expires') < ?",
                            (time.time(),))  # old links
        self.bot.db.set(f"file:{token}", {"name": name, "data": base64.b64encode(data).decode(),
                                          "expires": time.time() + FILE_DAYS * 86400})
        return f"{self.config.web_url}/files/{token}/{quote(name)}"

    async def download(self, request):
        key = f"file:{request.match_info['token']}"
        f = self.bot.db.get(key)
        if not f or f["expires"] < time.time():
            return web.Response(status=404, text="This link has expired.")
        return web.Response(body=base64.b64decode(f["data"]), headers={
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(f['name'])}"})

    # ----------------------------------------------------------- Teams
    async def teams_message(self, request):
        if not self.bot.teams:
            return web.Response(status=404)
        return await self.bot.teams.handle(request)

    async def teams_package(self, request):
        from . import teams
        try:
            data = teams.app_package(self.config)
        except RuntimeError as e:
            return web.Response(status=404, text=str(e))
        return web.Response(body=data, headers={
            "Content-Type": "application/zip",
            "Content-Disposition": f"attachment; filename={self.config.assistant_name}-teams.zip"})

    async def privacy(self, request):
        if PRIVACY.exists():
            return web.FileResponse(PRIVACY)
        return web.Response(text="This assistant is private to its owner. No data is shared or sold.")

    async def page(self, request):
        return web.FileResponse(PAGE, headers={"Cache-Control": "no-cache"})

    async def talk(self, request):
        if not self.authorized(request):
            return web.json_response({"error": "Not allowed. Open this page from Telegram or "
                                               "the /talk link."}, status=403)
        audio = await request.read()
        if not audio:
            return web.json_response({"error": "No audio received."}, status=400)
        kind = request.content_type.split("/")[-1]
        t0 = time.monotonic()
        try:
            heard = await voice.transcribe(self.config, audio, f"talk.{EXTENSIONS.get(kind, 'webm')}")
        except Exception as e:
            log.exception("Transcription failed")
            return web.json_response({"error": f"I couldn't listen: {e}"}, status=502)
        if not heard:
            return web.json_response({"heard": "", "reply": "", "audio": None})
        t1 = time.monotonic()
        chat_id = self.bot.home_chat  # the same memory as the chat apps
        try:
            reply = await self.bot.agent.handle(chat_id, heard, spoken=True)
        except Exception as e:
            log.exception("Agent error")
            return web.json_response({"heard": heard, "error": f"Something went wrong: {e}"},
                                     status=500)
        t2 = time.monotonic()
        if reply.files or reply.pending_ids:  # documents and approval buttons go to the chat app
            try:
                await self.bot.deliver(reply, text=False)
            except Exception:
                log.exception("Could not send files/approvals to the chat app")
        audio_b64 = None
        try:
            mp3 = await voice.speak(self.config, reply.text, voice=self.bot.db.get("tts_voice"),
                                    style=self.bot.db.get("tts_style"), fmt="mp3")
            audio_b64 = base64.b64encode(mp3).decode()
        except Exception:
            log.exception("Text-to-speech failed")
        log.info("timing (web): listening %.1fs, thinking %.1fs, speech %.1fs",
                 t1 - t0, t2 - t1, time.monotonic() - t2)
        return web.json_response({"heard": heard, "reply": reply.text, "audio": audio_b64,
                                  "pending": len(reply.pending_ids), "files": len(reply.files)})

    async def start(self) -> None:
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, "0.0.0.0", self.config.port).start()
        log.info("Voice page listening on port %s (%s)", self.config.port, self.config.web_url or "no public URL")

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()
