"""The 'brain': talks to Claude, runs tools, and asks for approval when needed."""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from anthropic import AsyncAnthropic

from .skills.base import Skill, Tool, ToolContext

log = logging.getLogger(__name__)

MAX_STEPS = 15  # safety limit on tool calls per message


@dataclass
class AgentReply:
    text: str
    pending_ids: list[int] = field(default_factory=list)


class Agent:
    def __init__(self, config, db, skills: list[Skill], client=None):
        self.config = config
        self.db = db
        self.skills = skills
        self.client = client or AsyncAnthropic(api_key=config.anthropic_api_key)
        self.tools: dict[str, Tool] = {t.name: t for s in skills for t in s.tools}
        self.server_tools = [st for s in skills for st in s.server_tools()]

    # ------------------------------------------------------------------
    def system_prompt(self) -> list[dict]:
        """Stable instructions (cached together with the tools) + the current time.

        The time changes every minute, so it sits after the cache breakpoint:
        anything before the breakpoint must stay byte-identical between requests.
        """
        now = datetime.now(ZoneInfo(self.config.timezone))
        skill_text = "\n\n".join(
            f"## {s.name}\n{s.instructions}".strip() for s in self.skills if s.instructions
        )
        stable = f"""You are {self.config.assistant_name}, the personal assistant of {self.config.owner_name}.
You chat with them on Telegram, so keep answers short, friendly and easy to read on a phone.
Avoid markdown tables and headings; simple lists are fine.

Always interpret times in the user's timezone ({self.config.timezone}) unless told otherwise.
The current date and time is given at the end of these instructions.

Rules:
- Use your tools to get real information. Never invent emails, events or facts.
- Some actions (sending email, creating/deleting events, etc.) need the user's approval.
  When you call such a tool it is NOT executed yet: the user gets Approve/Reject buttons.
  Tell them briefly what you prepared and that it is waiting for their approval.
- If a request is ambiguous and the wrong guess would matter, ask one short question.
- If a tool fails because an account isn't connected, tell the user how to connect it.

{skill_text}

{self.config.extra_instructions}""".strip()
        return [
            {"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}},
            {"type": "text",
             "text": f"Current date and time: {now:%A %d %B %Y, %H:%M} ({self.config.timezone})."},
        ]

    def _all_tools(self) -> list[dict]:
        return [t.to_api() for t in self.tools.values()] + self.server_tools

    def _history_messages(self, chat_id: int) -> list[dict]:
        """Past text turns, merged so roles alternate (required by the API)."""
        msgs: list[dict] = []
        for row in self.db.history(chat_id, self.config.history_turns * 2):
            if msgs and msgs[-1]["role"] == row["role"]:
                msgs[-1]["content"] += "\n\n" + row["content"]
            else:
                msgs.append({"role": row["role"], "content": row["content"]})
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        return msgs

    # ------------------------------------------------------------------
    async def run_tool(self, tool: Tool, args: dict, chat_id: int) -> str:
        ctx = ToolContext(db=self.db, config=self.config, chat_id=chat_id)
        try:
            result = await asyncio.to_thread(tool.handler, args, ctx)
        except Exception as e:  # the model sees the error and can recover
            log.exception("Tool %s failed", tool.name)
            return f"ERROR: {type(e).__name__}: {e}"
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    async def handle(self, chat_id: int, user_text: str, remember: bool = True) -> AgentReply:
        messages = self._history_messages(chat_id) if remember else []
        if messages and messages[-1]["role"] == "user":
            messages[-1]["content"] += "\n\n" + user_text
        else:
            messages.append({"role": "user", "content": user_text})

        pending: list[int] = []
        final_text = ""
        system = self.system_prompt()  # build once: must stay identical within a turn
        for _ in range(MAX_STEPS):
            resp = await self.client.messages.create(
                model=self.config.model,
                max_tokens=4096,
                # Caches the growing conversation, so each step of the tool loop
                # re-reads the earlier steps at ~10% of the normal input price.
                cache_control={"type": "ephemeral"},
                system=system,
                tools=self._all_tools(),
                messages=messages,
            )
            if usage := getattr(resp, "usage", None):  # check cache hits in the Railway logs
                log.info("tokens: input=%s cache_read=%s cache_write=%s output=%s",
                         usage.input_tokens, usage.cache_read_input_tokens,
                         usage.cache_creation_input_tokens, usage.output_tokens)
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            if text:
                final_text = text

            if resp.stop_reason == "pause_turn":  # long web search: just continue
                messages.append({"role": "assistant", "content": resp.content})
                continue
            if resp.stop_reason != "tool_use":
                break

            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                tool = self.tools.get(block.name)
                if tool is None:
                    out = f"ERROR: unknown tool {block.name}"
                elif tool.needs_approval:
                    pid = self.db.execute(
                        "INSERT INTO pending_actions(chat_id, tool, args, summary) VALUES(?,?,?,?)",
                        (chat_id, tool.name, json.dumps(block.input), tool.summary(block.input)),
                    )
                    pending.append(pid)
                    out = (f"Not executed yet: queued as action #{pid}. The user now sees "
                           "Approve/Reject buttons. Do not say it is done.")
                else:
                    out = await self.run_tool(tool, block.input, chat_id)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
            messages.append({"role": "user", "content": results})
        else:
            final_text = final_text or "Sorry, that took too many steps. Could you break it down?"

        final_text = final_text or "Done."
        if remember:
            self.db.add_message(chat_id, "user", user_text)
            self.db.add_message(chat_id, "assistant", final_text)
        return AgentReply(final_text, pending)

    # ------------------------------------------------------------------
    async def resolve_action(self, action_id: int, approve: bool) -> str:
        rows = self.db.query("SELECT * FROM pending_actions WHERE id=?", (action_id,))
        if not rows:
            return "That action no longer exists."
        row = rows[0]
        if row["status"] != "pending":
            return f"Already {row['status']}."
        if not approve:
            self.db.execute("UPDATE pending_actions SET status='rejected' WHERE id=?", (action_id,))
            self.db.add_message(row["chat_id"], "assistant",
                                f"(Action #{action_id} '{row['tool']}' was rejected by the user.)")
            return "Rejected. Nothing was done."
        tool = self.tools.get(row["tool"])
        if tool is None:
            return "That tool is no longer available."
        result = await self.run_tool(tool, json.loads(row["args"]), row["chat_id"])
        status = "failed" if result.startswith("ERROR") else "done"
        self.db.execute("UPDATE pending_actions SET status=? WHERE id=?", (status, action_id))
        self.db.add_message(row["chat_id"], "assistant",
                            f"(Action #{action_id} '{row['tool']}' approved; result: {result[:500]})")
        return ("Done ✅" if status == "done" else "It failed ❌") + f"\n{result[:1000]}"
