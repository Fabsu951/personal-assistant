"""Connect a Google account from inside Telegram (no local scripts needed).

Flow: /connect_google -> bot sends a link -> you approve in the browser ->
the browser ends on a 'localhost' page that doesn't load (that's expected) ->
copy that page's full address and paste it into Telegram.
"""
import json
from urllib.parse import parse_qs, urlparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
]
REDIRECT_URI = "http://localhost"
TOKEN_KEY = "google_token"

_flows: dict[int, Flow] = {}  # chat_id -> flow waiting for the pasted URL


def _client_config(config) -> dict:
    return {
        "installed": {
            "client_id": config.google_client_id,
            "client_secret": config.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI],
        }
    }


def start(config, chat_id: int) -> str:
    if not (config.google_client_id and config.google_client_secret):
        raise RuntimeError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set.")
    flow = Flow.from_client_config(_client_config(config), scopes=SCOPES,
                                   redirect_uri=REDIRECT_URI)
    url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    _flows[chat_id] = flow
    return url


def is_waiting(chat_id: int) -> bool:
    return chat_id in _flows


def finish(db, chat_id: int, pasted: str) -> None:
    flow = _flows.get(chat_id)
    if flow is None:
        raise RuntimeError("No connection in progress. Send /connect_google first.")
    code = parse_qs(urlparse(pasted.strip()).query).get("code", [None])[0]
    if not code:
        raise RuntimeError("I couldn't find a code in that address. Copy the whole URL.")
    flow.fetch_token(code=code)
    db.set(TOKEN_KEY, json.loads(flow.credentials.to_json()))
    _flows.pop(chat_id, None)


def get_credentials(db) -> Credentials:
    info = db.get(TOKEN_KEY)
    if not info:
        raise RuntimeError("Google is not connected. Ask the user to send /connect_google.")
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        db.set(TOKEN_KEY, json.loads(creds.to_json()))
    return creds
