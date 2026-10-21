"""Microsoft OneDrive: search, list recent and read files."""
from .. import microsoft
from ..extract import can_read, text_from_file
from .base import Skill, Tool, schema

MAX_TEXT = 12000
MAX_DOWNLOAD = 20 * 1024 * 1024
FIELDS = "id,name,size,lastModifiedDateTime,webUrl,file,folder,parentReference"


def _item(i: dict) -> dict:
    return {"id": i["id"], "name": i.get("name"),
            "type": "folder" if "folder" in i else "file",
            "folder": (i.get("parentReference") or {}).get("path", "").replace("/drive/root:", "") or "/",
            "modified": i.get("lastModifiedDateTime"), "size_kb": round(i.get("size", 0) / 1024),
            "link": i.get("webUrl")}


def onedrive_search(a, ctx):
    q = a["query"].replace("'", "''")
    res = microsoft.graph(ctx.db, ctx.config, f"/me/drive/root/search(q='{q}')",
                          {"$top": 20, "$select": FIELDS})
    return [_item(i) for i in res.get("value", [])] or "No files found."


def onedrive_recent(a, ctx):
    res = microsoft.graph(ctx.db, ctx.config, "/me/drive/recent", {"$top": 20})
    return [_item(i.get("remoteItem", i) | {"id": i["id"]}) for i in res.get("value", [])] \
        or "No recent files."


def onedrive_list(a, ctx):
    path = a.get("folder", "").strip("/")
    where = f"/me/drive/root:/{path}:/children" if path else "/me/drive/root/children"
    res = microsoft.graph(ctx.db, ctx.config, where, {"$top": 100, "$select": FIELDS})
    return [_item(i) for i in res.get("value", [])] or "That folder is empty."


def onedrive_read(a, ctx):
    meta = microsoft.graph(ctx.db, ctx.config, f"/me/drive/items/{a['file_id']}", {"$select": FIELDS})
    if "folder" in meta:
        return "That's a folder; use onedrive_list."
    if not can_read(meta["name"]):
        return {**_item(meta), "note": "Can't read this file type as text; share the link instead."}
    if meta.get("size", 0) > MAX_DOWNLOAD:
        return {**_item(meta), "note": "Too big to read here; share the link instead."}
    data = microsoft.graph(ctx.db, ctx.config, f"/me/drive/items/{meta['id']}/content", raw=True)
    text = text_from_file(meta["name"], data)
    return {**_item(meta), "content": text[:MAX_TEXT],
            "truncated": len(text) > MAX_TEXT}


class OneDriveSkill(Skill):
    def __init__(self):
        super().__init__(
            name="OneDrive (Microsoft)",
            description="Search, browse and read files in your OneDrive.",
            instructions=(
                "OneDrive is separate from Google Drive: when the user says OneDrive (or a file "
                "isn't in Google Drive) use onedrive_search / onedrive_recent / onedrive_list, "
                "then onedrive_read to get the text of Word, Excel, PowerPoint, PDF and text "
                "files. Access is read-only. Give the file link when it helps."
            ),
            tools=[
                Tool("onedrive_search", "Search OneDrive files by name or content.",
                     schema({"query": {"type": "string"}}, ["query"]), onedrive_search),
                Tool("onedrive_recent", "Recently used OneDrive files.", schema({}), onedrive_recent),
                Tool("onedrive_list", "List a OneDrive folder (default: the top level).",
                     schema({"folder": {"type": "string", "description": "e.g. 'Documents/School'"}}),
                     onedrive_list),
                Tool("onedrive_read", "Read the text of a OneDrive file.",
                     schema({"file_id": {"type": "string"}}, ["file_id"]), onedrive_read),
            ],
        )
