"""Global persona rules: injected into every persona's system prompt.

AstrBot has a single-layer persona model -- a conversation binds exactly one
persona, and that persona's prompt is appended to system_prompt in
`astr_main_agent/persona.py`. There is no "base persona + layer" concept, so
cross-cutting rules (tool discipline, topic avoidance) would have to be
duplicated into every persona.

This plugin fills that gap: `on_llm_request` fires *after* the persona is
applied (builder.py: persona.py:99 -> hook at builder.py:175), so appending
here puts the rules above every persona without touching AstrBot sources.

Scope targeting: rules can be limited to group chats, private chats, or both,
so a persona used only in groups does not carry private-chat rules.
"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register

# Marker so a re-fired hook (retries, multi-provider fallback) never stacks
# duplicate blocks into the same request.
_MARKER = "[全局规则]"

DEFAULT_RULES = """\
[全局规则]
以下是所有场景通用的行为准则，优先级高于任何人格设定中与之冲突的部分。

【工具使用】
- 只在确实需要时才调用工具。没有明确需求时，用已有知识直接回答。
- 网络搜索额度有限：仅在问题涉及实时信息、最新事件、未收录的具体数据时才搜索。
  常识性问题、闲聊、情绪回应一律不搜。
- 不主动操作外部系统（代码仓库、服务器、账号）。涉及写操作必须先向用户确认。

【话题边界】
- 不传播未经证实的消息，不编造事实、数据或引用来源。

【表达】
- 不假装做过没做过的事（没查就说没查，不确定就说不确定）。
- 保持人格设定的语气，但不要为了"演得像人"而牺牲准确性。
"""

DEFAULT_CONFIG = {
    "enabled": True,
    # "all" | "group" | "private"
    "scope": "all",
    "rules": DEFAULT_RULES,
    # personas listed here skip rule injection entirely (immersive RP
    # personas find "don't pretend / admit being an AI" rules mood-breaking)
    "exclude_personas": "",
}


@register(
    "astrbot_plugin_global_rules",
    "xiangguo",
    "1.0.0",
    "全局规则层：把跨人格通用的行为准则注入每次请求，弥补 AstrBot 单层人格模型的空缺",
)
class GlobalRulesPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or DEFAULT_CONFIG

        self.enabled = bool(self.config.get("enabled", True))
        self.scope = str(self.config.get("scope", "all")).lower()
        # A config object created from the schema may hold an empty string for
        # "use built-in defaults"; treat blank as unset so the defaults apply.
        self.rules = str(self.config.get("rules") or DEFAULT_RULES).strip()

        # Personas that must not see the character-flavoured meme tool. A generic
        # fallback persona sending AI-waifu stickers reads wrong, while every
        # other tool (search, memory) is genuinely useful there.
        raw_exclude = self.config.get("exclude_tools_for_default", "")
        if isinstance(raw_exclude, list):
            names = [str(x).strip() for x in raw_exclude if str(x).strip()]
        else:
            names = [x.strip() for x in str(raw_exclude).split(",") if x.strip()]
        self.exclude_for_default = names

        # personas that never get the rule block (comma-separated names)
        raw_skip = self.config.get("exclude_personas", "")
        if isinstance(raw_skip, list):
            self.exclude_personas = {str(x).strip() for x in raw_skip if str(x).strip()}
        else:
            self.exclude_personas = {x.strip() for x in str(raw_skip).split(",") if x.strip()}

        if self.scope not in {"all", "group", "private"}:
            logger.warning(f"[global_rules] scope 配置无效 ({self.scope!r})，回退到 all")
            self.scope = "all"

        logger.info(
            f"[global_rules] 已启用，作用域={self.scope}，规则 {len(self.rules)} 字"
        )

    def _should_apply(self, event: AstrMessageEvent) -> bool:
        """True when this conversation falls inside the configured scope."""
        if not self.enabled or not self.rules:
            return False
        if self.scope == "all":
            return True
        if self.scope == "group":
            return not event.is_private_chat()
        return event.is_private_chat()

    @filter.on_llm_request()
    async def inject_global_rules(
        self, event: AstrMessageEvent, req: ProviderRequest
    ) -> None:
        """Append the global rule block after the persona prompt.

        The hook runs after persona injection, so `req.system_prompt` already
        holds `...<persona_instructions>...</persona_instructions>`. Appending
        afterwards means the model reads persona voice first, then the rules
        that take precedence over it.
        """
        if not self._should_apply(event):
            return

        persona_id = str(event.get_extra("_trace_persona_id") or "")
        if persona_id in self.exclude_personas:
            logger.debug(f"[global_rules] persona={persona_id} 在豁免名单，跳过注入")
            return

        self._apply_tool_policy(event, req)

        current = req.system_prompt or ""
        if _MARKER in current:
            # Already injected for this request (hook re-fired), do not stack.
            return

        req.system_prompt = f"{current}\n\n{self.rules}"
        logger.debug(
            f"[global_rules] 已注入 {len(self.rules)} 字规则 "
            f"(scope={self.scope}, private={event.is_private_chat()})"
        )

    def _apply_tool_policy(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        """Drop tools a persona must not use, by name.

        Runs in on_llm_request, i.e. after apply_persona() has merged the
        persona toolset into req.func_tool, so the set is already populated.
        Exclusion (not allowlisting) means newly installed plugins are picked
        up automatically by every persona.
        """
        if not self.exclude_for_default:
            return

        persona_id = str(event.get_extra("_trace_persona_id") or "")
        if persona_id != "default":
            return

        toolset = getattr(req, "func_tool", None)
        if toolset is None:
            return
        for name in self.exclude_for_default:
            toolset.remove_tool(name)
        logger.debug(
            f"[global_rules] persona=default 已移除工具 {self.exclude_for_default}"
        )
