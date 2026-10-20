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
    skills = load_skills(["google", "tasks", "research", "admin"], db, cfg)
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
