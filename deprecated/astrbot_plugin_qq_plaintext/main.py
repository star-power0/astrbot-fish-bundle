"""QQ 纯文本化插件：剥掉 LLM 回复里的 Markdown 标记。

QQ 客户端不渲染 Markdown，直接显示 `**加粗**`、反引号、代码围栏这些原始符号。
这个插件在消息发送前把 Plain 组件里的 Markdown 语法清洗掉，只留可读文本。

注意：只有在关闭流式输出（provider_settings.streaming_response=false）时，
OnDecoratingResultEvent 钩子才会被调用 —— 流式结果会在 result_decorate 阶段直接返回。
"""

import re

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.components import Plain

# ```lang\n...\n``` -> 代码正文，每行前面加缩进标记
FENCE_RE = re.compile(r"```[^\n]*\n?(.*?)```", re.S)
# `code` -> code
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
# **bold** / __bold__ -> bold
BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*|__([^_\n]+)__")
# *italic* -> italic（避免吃掉列表符号，要求前后不是空白）
ITALIC_RE = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")
# # 标题 -> 标题（去掉 #）
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
# - 列表 / * 列表 -> · 列表
BULLET_RE = re.compile(r"^(\s*)[-*+]\s+", re.M)
# > 引用 -> 去掉
QUOTE_RE = re.compile(r"^\s{0,3}>\s?", re.M)
# [text](url) -> text url
LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
# 表格分隔行：|---|---|  或  --- | ---  （保留换行，避免上下行粘连）
TABLE_SEP_RE = re.compile(r"^[ \t]*\|?[\s:|-]*\|[\s:|-]*\|?[ \t]*$\n?", re.M)
# 表格竖线 | a | b | -> a · b
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$", re.M)
# 连续 3 个以上空行 -> 2 个
BLANK_RE = re.compile(r"\n{3,}")


def _indent_code(body: str, max_lines: int = 20) -> str:
    """Render a code block as indented lines QQ can still read."""
    lines = body.rstrip("\n").split("\n")[:max_lines]
    return "\n".join("  " + ln if ln.strip() else "" for ln in lines)


def clean_markdown(text: str) -> str:
    if not text or not text.strip():
        return text

    # code fences first — their content must not be touched by other rules
    text = FENCE_RE.sub(lambda m: _indent_code(m.group(1)), text)

    text = LINK_RE.sub(lambda m: f"{m.group(1)} {m.group(2)}", text)

    # table separator lines must go before row conversion, else |---|---|
    # becomes "--- · ---" and can no longer be recognised
    text = TABLE_SEP_RE.sub("", text)
    text = TABLE_ROW_RE.sub(
        lambda m: " · ".join(c.strip() for c in m.group(1).split("|") if c.strip()),
        text,
    )

    text = INLINE_CODE_RE.sub(lambda m: m.group(1), text)
    text = BOLD_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = ITALIC_RE.sub(lambda m: m.group(1), text)
    text = HEADING_RE.sub("", text)
    text = BULLET_RE.sub(lambda m: m.group(1) + "· ", text)
    text = QUOTE_RE.sub("", text)

    text = BLANK_RE.sub("\n\n", text)
    return text.strip()


@register(
    "astrbot_plugin_qq_plaintext",
    "xiangguo",
    "1.0.0",
    "把 LLM 回复里的 Markdown 剥成 QQ 能看的纯文本",
)
class QQPlaintextPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.on_decorating_result()
    async def strip_markdown(self, event: AstrMessageEvent):
        result = event.get_result()
        if result is None or not result.chain:
            return
        for comp in result.chain:
            if isinstance(comp, Plain) and comp.text:
                cleaned = clean_markdown(comp.text)
                if cleaned != comp.text:
                    comp.text = cleaned
