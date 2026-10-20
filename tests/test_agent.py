"""Offline tests: a fake Claude drives the agent loop, no API keys needed."""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

from assistant.agent import Agent
from assistant.config import Config
from assistant.db import DB
from assistant.skills import load_skills
from assistant.skills.tasks import due_reminders


def text(t):
    return NS(type="text", text=t)


def tool_use(id, name, inp):
    return NS(type="tool_use", id=id, name=name, input=inp)


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = self

    async def create(self, **kw):
        self.calls.append(kw)
        content, stop = self.script.pop(0)
        return NS(content=content, stop_reason=stop)


def make(tmp_path, script):
    cfg = Config()
    cfg.data_dir = tmp_path
    db = DB(tmp_path / "t.db")
    skills = load_skills(["google", "tasks", "research", "admin", "fitness"], db, cfg)
    client = FakeClient(script)
    return Agent(cfg, db, skills, client=client), db, client


def test_tool_runs_and_history_saved(tmp_path):
    agent, db, client = make(tmp_path, [
        ([tool_use("t1", "task_add", {"title": "Renew passport"})], "tool_use"),
        ([text("Added it!")], "end_turn"),
    ])
    reply = asyncio.run(agent.handle(1, "add renew passport"))
    assert reply.text == "Added it!"
    assert db.query("SELECT title FROM tasks")[0]["title"] == "Renew passport"
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert "Task #1 added" in tool_result["content"]
    assert [m["role"] for m in db.history(1, 10)] == ["user", "assistant"]
    # tools sent to the API include web search + all client tools
    names = [t["name"] for t in client.calls[0]["tools"]]
    assert "web_search" in names and "gmail_send" in names


def test_approval_flow(tmp_path):
    email = {"to": "a@b.com", "subject": "Hi", "body": "Hello"}
    agent, db, _ = make(tmp_path, [
        ([tool_use("t1", "gmail_send", email)], "tool_use"),
        ([text("Drafted, waiting for approval.")], "end_turn"),
    ])
    reply = asyncio.run(agent.handle(1, "email a@b.com"))
    assert reply.pending_ids == [1]
    row = db.query("SELECT * FROM pending_actions")[0]
    assert row["status"] == "pending" and "a@b.com" in row["summary"]
    # Reject -> nothing executed
    assert "Rejected" in asyncio.run(agent.resolve_action(1, approve=False))
    assert "Already" in asyncio.run(agent.resolve_action(1, approve=True))


def test_approve_runs_tool(tmp_path):
    agent, db, _ = make(tmp_path, [])
    sent = {}
    agent.tools["gmail_send"].handler = lambda a, c: sent.update(a) or "Email sent."
    pid = db.execute("INSERT INTO pending_actions(chat_id, tool, args, summary) VALUES(1,'gmail_send','{\"to\":\"x\"}','s')")
    out = asyncio.run(agent.resolve_action(pid, approve=True))
    assert out.startswith("Done") and sent == {"to": "x"}


def test_tool_error_is_reported_not_crash(tmp_path):
    agent, db, client = make(tmp_path, [
        ([tool_use("t1", "gmail_search", {"query": "x"})], "tool_use"),
        ([text("Google isn't connected yet.")], "end_turn"),
    ])
    reply = asyncio.run(agent.handle(1, "emails?"))
    assert "connected" in reply.text
    assert "ERROR" in client.calls[1]["messages"][-1]["content"][0]["content"]


def test_reminders_due(tmp_path):
    agent, db, client = make(tmp_path, [])
    past = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat()
    db.execute("INSERT INTO reminders(chat_id, text, due_at) VALUES(1,'call mom',?)", (past,))
    assert [r["text"] for r in due_reminders(db)] == ["call mom"]
    assert due_reminders(db) == []


def test_history_alternates(tmp_path):
    agent, db, _ = make(tmp_path, [])
    db.add_message(1, "assistant", "(approved)")
    db.add_message(1, "user", "a")
    db.add_message(1, "assistant", "b")
    db.add_message(1, "assistant", "(action done)")
    msgs = agent._history_messages(1)
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_expenses(tmp_path):
    agent, db, _ = make(tmp_path, [])
    from assistant.skills.base import ToolContext
    ctx = ToolContext(db=db, config=agent.config, chat_id=1)
    agent.tools["expense_add"].handler({"amount": 250, "category": "food"}, ctx)
    s = agent.tools["expense_summary"].handler({}, ctx)
    assert s["totals_by_category"][0]["total"] == 250


def test_prompt_caching(tmp_path):
    agent, db, client = make(tmp_path, [([text("Hi")], "end_turn")])
    asyncio.run(agent.handle(1, "hello"))
    call = client.calls[0]
    assert call["cache_control"] == {"type": "ephemeral"}
    stable, now = call["system"]
    assert stable["cache_control"] == {"type": "ephemeral"}
    # the time changes every minute, so it must not be inside the cached block
    assert "Current date and time" not in stable["text"] and "Current date and time" in now["text"]
    assert "cache_control" not in now


def test_system_prompt_identical_within_turn(tmp_path):
    agent, db, client = make(tmp_path, [
        ([tool_use("t1", "task_list", {})], "tool_use"),
        ([text("Nothing to do.")], "end_turn"),
    ])
    asyncio.run(agent.handle(1, "tasks?"))
    assert client.calls[0]["system"] == client.calls[1]["system"]


class FakeCalendar:
    """Just enough of the Google Calendar client for calendar_list_events."""
    def __init__(self, calendars, events):
        self.calendars, self.events_by_cal, self.inserted = calendars, events, None

    def calendarList(self):
        return NS(list=lambda pageToken=None: NS(execute=lambda: {"items": self.calendars}))

    def events(self):
        def list_(calendarId, **kw):
            if calendarId not in self.events_by_cal:
                raise RuntimeError("forbidden")
            return NS(execute=lambda: {"items": self.events_by_cal[calendarId]})

        def insert(calendarId, body, sendUpdates):
            self.inserted = calendarId
            return NS(execute=lambda: {"htmlLink": "link"})
        return NS(list=list_, insert=insert)


def test_calendar_reads_all_calendars(tmp_path, monkeypatch):
    from assistant.skills import google_workspace as gw
    from assistant.skills.base import ToolContext
    agent, db, _ = make(tmp_path, [])
    cal = FakeCalendar(
        [{"id": "me@x.com", "summary": "me@x.com", "primary": True},
         {"id": "fam123", "summary": "Familj"},
         {"id": "broken", "summary": "Broken"}],
        {"me@x.com": [{"id": "a", "summary": "Gym",
                       "start": {"dateTime": "2026-10-21T18:00:00+08:00"},
                       "end": {"dateTime": "2026-10-21T19:00:00+08:00"}}],
         "fam123": [{"id": "b", "summary": "Dinner with mom",
                     "start": {"dateTime": "2026-10-21T10:00:00Z"},
                     "end": {"dateTime": "2026-10-21T11:00:00Z"}},
                    {"id": "c", "summary": "Birthday", "start": {"date": "2026-10-21"},
                     "end": {"date": "2026-10-22"}}]})
    monkeypatch.setattr(gw, "_svc", lambda ctx, name, version: cal)
    ctx = ToolContext(db=db, config=agent.config, chat_id=1)
    out = gw.calendar_list_events({"start": "2026-10-21", "end": "2026-10-22"}, ctx)
    assert [e.get("title") for e in out[:3]] == ["Birthday", "Gym", "Dinner with mom"]
    assert out[2]["calendar"] == "Familj" and out[2]["calendar_id"] == "fam123"
    assert "Broken" in out[3]["note"]
    gw.calendar_create_event({"title": "Picnic", "start": "2026-10-25T12:00", "calendar": "familj"}, ctx)
    assert cal.inserted == "fam123"


def test_fitness(tmp_path):
    from assistant.skills.base import ToolContext
    agent, db, _ = make(tmp_path, [])
    ctx = ToolContext(db=db, config=agent.config, chat_id=1)
    t = agent.tools
    t["program_set"].handler({"program": "Mon: legs. Thu: upper body."}, ctx)
    assert "legs" in t["program_get"].handler({}, ctx)["program"]
    t["workout_log"].handler({"kind": "legs", "date": "2000-01-01", "exercises": [
        {"exercise": "Squat", "sets": 3, "reps": 5, "weight_kg": 100}]}, ctx)
    t["workout_log"].handler({"kind": "legs", "exercises": [
        {"exercise": "squat", "sets": 3, "reps": 5, "weight_kg": 102.5}]}, ctx)
    assert [r["weight_kg"] for r in t["exercise_progress"].handler({"exercise": "squat"}, ctx)] == [100, 102.5]
    recent = t["workout_history"].handler({"days": 7}, ctx)
    assert len(recent) == 1 and recent[0]["exercises"][0]["weight_kg"] == 102.5


def test_voice_needs_key():
    import pytest
    from assistant import voice
    cfg = Config()
    cfg.openai_api_key = ""
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        asyncio.run(voice.transcribe(cfg, b"audio"))


def test_voice_transcribes(monkeypatch):
    import httpx
    from assistant import voice
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"text": " hej Ragnar "})

    real = httpx.AsyncClient
    monkeypatch.setattr(voice.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    cfg = Config()
    cfg.openai_api_key = "sk-test"
    assert asyncio.run(voice.transcribe(cfg, b"audio")) == "hej Ragnar"
    assert seen["auth"] == "Bearer sk-test"


def test_blank_settings_use_defaults(monkeypatch):
    for name in ["MODEL", "TIMEZONE", "HISTORY_TURNS", "DATA_DIR", "ENABLED_SKILLS", "OWNER_TELEGRAM_ID"]:
        monkeypatch.setenv(name, "")
    cfg = Config()
    assert cfg.model and cfg.timezone == "Asia/Taipei" and cfg.history_turns == 20
    assert "google" in cfg.enabled_skills and cfg.owner_id == 0 and str(cfg.data_dir) == "data"


def test_body_status(tmp_path):
    from assistant.skills.base import ToolContext
    agent, db, _ = make(tmp_path, [])
    ctx = ToolContext(db=db, config=agent.config, chat_id=1)
    agent.tools["status_log"].handler({"sleep_hours": 6, "injuries": "left knee aches"}, ctx)
    agent.tools["status_log"].handler({"weight_kg": 80.5, "energy": 8}, ctx)
    rows = agent.tools["status_history"].handler({"days": 3}, ctx)
    assert rows[0]["injuries"] == "left knee aches" and "weight_kg" not in rows[0]
    assert rows[1]["weight_kg"] == 80.5


def test_strava(tmp_path, monkeypatch):
    import httpx
    from assistant import strava
    agent, db, _ = make(tmp_path, [])
    cfg = agent.config
    cfg.strava_client_id, cfg.strava_client_secret = "123", "secret"
    assert "state=strava" in strava.start(cfg)
    assert strava.is_strava_redirect("http://localhost/?state=strava&code=abc&scope=read")
    assert not strava.is_strava_redirect("http://localhost/?code=abc&scope=https://www.googleapis.com/x")

    calls = []

    def fake_post(url, data, timeout):
        calls.append(data["grant_type"])
        return httpx.Response(200, json={"access_token": f"tok{len(calls)}", "refresh_token": "r",
                                         "expires_at": 0 if len(calls) == 1 else 9999999999})

    def fake_get(url, headers, params, timeout):
        assert headers["Authorization"] == "Bearer tok2"  # expired token was refreshed first
        return httpx.Response(200, json=[{"name": "Morning run", "sport_type": "Run",
                                          "start_date_local": "2026-10-19T07:00:00Z",
                                          "moving_time": 1800, "distance": 6000,
                                          "average_heartrate": 150}])

    monkeypatch.setattr(strava.httpx, "post", fake_post)
    monkeypatch.setattr(strava.httpx, "get", fake_get)
    strava.finish(db, cfg, "http://localhost/?state=strava&code=abc")
    run = strava.activities(db, cfg, 7)[0]
    assert calls == ["authorization_code", "refresh_token"]
    assert run["distance_km"] == 6.0 and run["pace_min_per_km"] == "5:00" and run["moving_min"] == 30
    assert db.get("strava_token")["access_token"] == "tok2"


def test_strava_not_connected(tmp_path):
    agent, db, client = make(tmp_path, [
        ([tool_use("t1", "strava_activities", {})], "tool_use"),
        ([text("Strava isn't connected.")], "end_turn"),
    ])
    asyncio.run(agent.handle(1, "runs?"))
    assert "connect_strava" in client.calls[1]["messages"][-1]["content"][0]["content"]
