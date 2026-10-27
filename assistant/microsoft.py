"""Connect a Microsoft account (Outlook mail, calendar, OneDrive) with the device-code login.

/connect_microsoft -> the bot shows a short code -> you open microsoft.com/devicelogin,
type the code and sign in -> the bot notices by itself. No addresses to copy.
"""
import asyncio
import time

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = "Files.Read Mail.ReadWrite Mail.Send Calendars.ReadWrite User.Read offline_access"
OLD_SCOPES = "Files.Read User.Read offline_access"  # logins made before Outlook was added
RECONNECT = "Ask the user to send /connect_microsoft."
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


def _save(db, t: dict, old_refresh: str = "") -> None:
    scope = t.get("scope") or SCOPES
    if "offline_access" not in scope:  # Microsoft leaves it out of the granted list
        scope += " offline_access"
    db.set(TOKEN_KEY, {"access_token": t["access_token"],
                       "refresh_token": t.get("refresh_token") or old_refresh,
                       "expires_at": time.time() + int(t.get("expires_in", 3600)), "scope": scope})


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
    raise RuntimeError("the code expired. Send /connect_microsoft to get a new one.")


def _access_token(db, config) -> str:
    token = db.get(TOKEN_KEY)
    if not token:
        raise RuntimeError(f"Microsoft (Outlook/OneDrive) is not connected. {RECONNECT}")
    if token["expires_at"] < time.time() + 60:
        r = httpx.post(f"{_login(config)}/token", timeout=30, data={
            "grant_type": "refresh_token", "client_id": config.ms_client_id,
            # refresh with what was granted; asking for more here would be refused
            "refresh_token": token["refresh_token"], "scope": token.get("scope") or OLD_SCOPES})
        if r.status_code != 200:
            raise RuntimeError(f"The Microsoft login has expired. {RECONNECT}")
        _save(db, r.json(), token["refresh_token"])
        token = db.get(TOKEN_KEY)
    return token["access_token"]


def graph(db, config, path: str, params: dict | None = None, raw: bool = False,
          method: str = "GET", body: dict | None = None, headers: dict | None = None):
    r = httpx.request(method, f"{GRAPH}{path}", params=params, json=body, follow_redirects=True,
                      timeout=60, headers={"Authorization": f"Bearer {_access_token(db, config)}",
                                           **(headers or {})})
    if r.status_code in (401, 403):
        raise RuntimeError(f"Microsoft denied access ({r.status_code}). If this is mail or calendar, "
                           f"the login may predate that permission. {RECONNECT}")
    if r.status_code >= 300:
        raise RuntimeError(f"Microsoft said {r.status_code}: {r.text[:200]}")
    if raw:
        return r.content
    return r.json() if r.content else {}
