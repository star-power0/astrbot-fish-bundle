"""Markdown 双端清洗：发送端 + 存储端。

AstrBot 一轮回复产生两份独立副本：

    发送  ← resp.completion_text（agent_sub_stages/internal.py:336）
    存库  ← run_context.messages（internal.py:308 _save_to_history）

只清洗一份不够：历史里留着 **加粗**，模型下一轮读到就照着学。

三个清洗点
----------
1. on_llm_response  → 改 completion_text（非流式发送用）
2. on_agent_done    → 改 run_context.messages[-1]（存库用）
3. 运行时接管 AiocqhttpMessageEvent.send → 流式的每个分片都过这里

第 3 点是关键：QQ 的流式按句号切分后逐段 send()，分片在 on_llm_response
之前就发出去了，钩子拦不住。而所有分片最终都经过 send()，在那里清洗才不漏。

时序参考 tool_loop_agent_runner.py:201：
    self.run_context.messages.append(Message(role="assistant", content=parts))
    await self.agent_hooks.on_agent_done(self.run_context, llm_resp)
"""

import re

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

# Set once so a plugin reload doesn't stack wrappers.
_SEND_PATCHED = False

FENCE_RE = re.compile(r"```(?:[a-zA-Z0-9+\-]*\s+)?([\s\S]*?)```")
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
IMG_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
BOLD_RE = re.compile(r"\*\*(.*?)\*\*|__(.*?)__", re.S)
ITALIC_STAR_RE = re.compile(r"(?<!\*)\*(?!\s)(.*?)(?<!\s)\*(?!\*)")
ITALIC_UNDER_RE = re.compile(r"(?<!\w)_(?!\s)(.*?)(?<!\s)_(?!\w)")
STRIKE_RE = re.compile(r"~~(.*?)~~")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)", re.MULTILINE)
QUOTE_RE = re.compile(r"^(?:>\s*)+(.*)", re.MULTILINE)
BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)", re.MULTILINE)


def strip_markdown(text: str) -> str:
    if not text:
        return text
    text = FENCE_RE.sub(r"\1", text)
    text = INLINE_CODE_RE.sub(r"\1", text)
    text = IMG_RE.sub(r"\1", text)
    text = LINK_RE.sub(r"\1", text)
    text = BOLD_RE.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(2), text)
    text = ITALIC_STAR_RE.sub(r"\1", text)
    text = ITALIC_UNDER_RE.sub(r"\1", text)
    text = STRIKE_RE.sub(r"\1", text)
    text = HEADING_RE.sub(r"\2", text)
    text = QUOTE_RE.sub(r"\1", text)
    text = BULLET_RE.sub(r"\1", text)
    return text


def _install_send_cleaner() -> None:
    """Clean Markdown at the adapter's send() choke point.

    QQ streaming splits the reply at sentence marks and calls send() per piece,
    which happens before on_llm_response fires. Patching send() is the only way
    to catch streamed chunks. Runtime patch only -- AstrBot's files are untouched.
    """
    global _SEND_PATCHED
    if _SEND_PATCHED:
        return
    try:
        from astrbot.api.message_components import Plain
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
            AiocqhttpMessageEvent,
        )

        original_send = AiocqhttpMessageEvent.send

        async def cleaned_send(self, message):
            chain = getattr(message, "chain", None)
            if chain:
                for comp in chain:
                    if isinstance(comp, Plain) and comp.text:
                        cleaned = strip_markdown(comp.text)
                        if cleaned != comp.text:
                            comp.text = cleaned
            return await original_send(self, message)

        AiocqhttpMessageEvent.send = cleaned_send
        _SEND_PATCHED = True
        logger.info("[history_cleaner] 已在 send() 出口装 Markdown 清洗（覆盖流式分片）")
    except Exception as e:
        logger.warning(f"[history_cleaner] send() 清洗安装失败：{e}")


@register(
    "astrbot_plugin_history_cleaner",
    "xiangguo",
    "1.0.0",
    "同步清洗对话历史里的 Markdown，防止模型照着旧格式自我强化",
)
class HistoryCleanerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        _install_send_cleaner()

    @filter.on_llm_response()
    async def clean_completion_text(self, event: AstrMessageEvent, resp, *args, **kwargs):
        """Clean the copy that gets sent to the user.

        AstrBot keeps two copies of one reply: resp.completion_text is what goes
        out to QQ (internal.py:336), run_context.messages[-1] is what gets stored
        as memory. They are separate objects, so both paths need cleaning.
        """
        text = getattr(resp, "completion_text", None)
        if not isinstance(text, str) or not text:
            return
        cleaned = strip_markdown(text)
        if cleaned != text:
            resp.completion_text = cleaned

    @filter.on_agent_done()
    async def clean_saved_message(self, event: AstrMessageEvent, run_context, resp, *args, **kwargs):
        messages = getattr(run_context, "messages", None) or []
        if not messages:
            return
        last = messages[-1]
        if getattr(last, "role", None) != "assistant":
            return

        content = getattr(last, "content", None)
        touched = 0

        # content may be a plain string or a list of TextPart / ThinkPart objects
        if isinstance(content, str):
            cleaned = strip_markdown(content)
            if cleaned != content:
                last.content = cleaned
                touched += 1
        elif isinstance(content, list):
            for part in content:
                # TextPart has type="text"; ThinkPart (type="think") must stay untouched
                if getattr(part, "type", None) != "text":
                    continue
                text = getattr(part, "text", None)
                if not isinstance(text, str):
                    continue
                cleaned = strip_markdown(text)
                if cleaned != text:
                    part.text = cleaned
                    touched += 1

        if touched:
            logger.debug(f"[history_cleaner] cleaned {touched} text part(s) before save")
