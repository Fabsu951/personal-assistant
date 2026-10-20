"""Connect Strava from inside Telegram (same copy-the-localhost-address trick as Google).

Garmin, Apple Watch, Polar, Coros etc. can all sync to Strava, so this is the
one connection that brings in workouts from a watch.
"""
import time
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
API = "https://www.strava.com/api/v3"
REDIRECT_URI = "http://localhost"
STATE = "strava"  # Strava echoes this back, so the bot can tell it apart from Google
TOKEN_KEY = "strava_token"


def start(config) -> str:
    if not (config.strava_client_id and config.strava_client_secret):
        raise RuntimeError("STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET are not set (see README).")
    return AUTH_URL + "?" + urlencode({
        "client_id": config.strava_client_id, "redirect_uri": REDIRECT_URI,
        "response_type": "code", "approval_prompt": "auto",
        "scope": "read,activity:read_all", "state": STATE,
    })


def is_strava_redirect(pasted: str) -> bool:
    return parse_qs(urlparse(pasted.strip()).query).get("state") == [STATE]


def _token_request(config, **data) -> dict:
    r = httpx.post(TOKEN_URL, data={"client_id": config.strava_client_id,
                                    "client_secret": config.strava_client_secret, **data},
                   timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Strava said {r.status_code}: {r.text[:200]}")
    t = r.json()
    return {"access_token": t["access_token"], "refresh_token": t["refresh_token"],
            "expires_at": t["expires_at"]}


def finish(db, config, pasted: str) -> None:
    code = parse_qs(urlparse(pasted.strip()).query).get("code", [None])[0]
    if not code:
        raise RuntimeError("I couldn't find a code in that address. Copy the whole URL.")
    db.set(TOKEN_KEY, _token_request(config, code=code, grant_type="authorization_code"))


def _access_token(db, config) -> str:
    token = db.get(TOKEN_KEY)
    if not token:
        raise RuntimeError("Strava is not connected. Ask the user to send /connect_strava.")
    if token["expires_at"] < time.time() + 60:  # access tokens only live 6 hours
        token = _token_request(config, refresh_token=token["refresh_token"],
                               grant_type="refresh_token")
        db.set(TOKEN_KEY, token)
    return token["access_token"]


def activities(db, config, days: int) -> list[dict]:
    r = httpx.get(f"{API}/athlete/activities",
                  headers={"Authorization": f"Bearer {_access_token(db, config)}"},
                  params={"after": int(time.time() - days * 86400), "per_page": 100},
                  timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Strava said {r.status_code}: {r.text[:200]}")
    out = []
    for a in r.json():
        item = {"name": a.get("name"), "type": a.get("sport_type") or a.get("type"),
                "start": a.get("start_date_local"),
                "moving_min": round(a.get("moving_time", 0) / 60),
                "distance_km": round(a.get("distance", 0) / 1000, 2)}
        if a.get("distance") and a.get("moving_time"):
            sec = round(a["moving_time"] / (a["distance"] / 1000))
            item["pace_min_per_km"] = f"{sec // 60}:{sec % 60:02d}"
        for key in ("average_heartrate", "max_heartrate", "total_elevation_gain", "suffer_score"):
            if a.get(key) is not None:
                item[key] = a[key]
        out.append(item)
    return out
