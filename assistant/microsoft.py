"""Connect a Microsoft account (OneDrive) with the device-code login.

/connect_onedrive -> the bot shows a short code -> you open microsoft.com/devicelogin,
type the code and sign in -> the bot notices by itself. No addresses to copy.
"""
import asyncio
import time

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = "Files.Read User.Read offline_access"
TOKEN_KEY = "microsoft_token"


def _login(config) -> str:
    return f"https://login.microsoftonline.com/{config.ms_tenant}/oauth2/v2.0"


async def start(config) -> dict:
    if not config.ms_client_id:
        raise RuntimeError("MS_CLIENT_ID is not set (see README).")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{_login(config)}/devicecode",
                              data={"client_id": config.ms_client_id, "scope": SCOPES})
    if r.status_code != 200:
        raise RuntimeError(f"Microsoft said {r.status_code}: {r.text[:300]}")
    return r.json()  # user_code, verification_uri, device_code, interval, expires_in


def _save(db, t: dict) -> None:
    db.set(TOKEN_KEY, {"access_token": t["access_token"], "refresh_token": t["refresh_token"],
                       "expires_at": time.time() + int(t.get("expires_in", 3600))})


async def wait_for_login(db, config, flow: dict) -> None:
    """Poll until the user has signed in (or the code expires)."""
    deadline = time.time() + int(flow.get("expires_in", 900))
    interval = int(flow.get("interval", 5))
    async with httpx.AsyncClient(timeout=30) as client:
        while time.time() < deadline:
            await asyncio.sleep(interval)
            r = await client.post(f"{_login(config)}/token", data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": config.ms_client_id, "device_code": flow["device_code"]})
            body = r.json()
            if r.status_code == 200:
                _save(db, body)
                return
            error = body.get("error")
            if error == "slow_down":
                interval += 5
            elif error != "authorization_pending":
                raise RuntimeError(body.get("error_description", error or r.text)[:300])
    raise RuntimeError("the code expired. Send /connect_onedrive to get a new one.")


def _access_token(db, config) -> str:
    token = db.get(TOKEN_KEY)
    if not token:
        raise RuntimeError("OneDrive is not connected. Ask the user to send /connect_onedrive.")
    if token["expires_at"] < time.time() + 60:
        r = httpx.post(f"{_login(config)}/token", timeout=30, data={
            "grant_type": "refresh_token", "client_id": config.ms_client_id,
            "refresh_token": token["refresh_token"], "scope": SCOPES})
        if r.status_code != 200:
            raise RuntimeError("OneDrive login expired. Ask the user to send /connect_onedrive.")
        _save(db, r.json())
        token = db.get(TOKEN_KEY)
    return token["access_token"]


def graph(db, config, path: str, params: dict | None = None, raw: bool = False):
    r = httpx.get(f"{GRAPH}{path}", params=params, follow_redirects=True, timeout=60,
                  headers={"Authorization": f"Bearer {_access_token(db, config)}"})
    if r.status_code != 200:
        raise RuntimeError(f"OneDrive said {r.status_code}: {r.text[:200]}")
    return r.content if raw else r.json()
