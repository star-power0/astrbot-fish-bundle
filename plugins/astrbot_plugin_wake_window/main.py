"""群聊免@时间窗。

被 @ 之后的一段时间内（默认 30 秒），同一群里继续说话不用再 @；超时自动收回，
恢复成「必须 @」的状态。

工作原理
--------
AstrBot 的 waking_check 阶段在插件之前执行，没被唤醒的消息根本到不了插件层。
所以需要把 wake_prefix 配成 [""]（空字符串）—— 空串的 startswith 恒为 True，
所有消息都能通过唤醒检查进入插件，再由本插件决定「回」还是「拦」。

  @ 消息        → 记录「本群最后唤醒时间」，放行
  时间窗内消息   → 放行（续命，滑动窗口）
  时间窗外消息   → event.stop_event() 拦掉，不产生回复也不烧 token

⚠️ 前置条件：cmd_config.json 里 "wake_prefix" 必须是 [""]。插件启动时会检查并告警。

空消息兜底
----------
AstrBot 的 aiocqhttp 适配器会把 mface（表情包）消息段整个丢掉：

    elif t == "mface":
        continue

所以一条纯表情包消息解析完是「零个组件 + 空字符串」。wake_prefix 为空串时
waking_check 会走进 startswith("") 分支，然后 messages[0] 直接 IndexError，
整条管线报 "Pipeline task failed"。

本插件在加载时给 WakingCheckStage.process 包一层：消息没有组件就直接丢弃，
不进入唤醒判断。这样纯表情包消息只会被安静忽略，不会崩。不改 AstrBot 源码。
"""

import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.components import At
from astrbot.core.message.message_event_result import MessageEventResult

# How long a window stays open after the last wake, in seconds.
DEFAULT_WINDOW_SECONDS = 30

# Set once so a reload doesn't stack wrappers on top of each other.
_GUARD_INSTALLED = False


def _install_empty_message_guard() -> None:
    """Stop waking_check from indexing messages[0] on a component-less message."""
    global _GUARD_INSTALLED
    if _GUARD_INSTALLED:
        return
    try:
        from astrbot.core.pipeline.waking_check.stage import WakingCheckStage

        original = WakingCheckStage.process

        async def guarded_process(self, event):
            # A sticker-only message loses every segment in the adapter and
            # arrives with an empty component list. Nothing to wake for anyway.
            if not event.get_messages():
                event.set_result(MessageEventResult())
                event.stop_event()
                return

            # Handler activation happens inside this stage, BEFORE the plugin
            # layer ever runs. So the leading "/" has to go now, not in gate():
            # CommandFilter requires message_str.startswith("时间窗 "), and with
            # wake_prefix=[""] AstrBot no longer strips the slash. Doing it here
            # is what actually lets /时间窗, /记忆, /梗图 reach their handlers.
            text = (event.message_str or "").lstrip()
            if text.startswith("/"):
                body = text[1:].strip()
                if _is_command_text(body):
                    event.message_str = body
                    logger.info(f"[wake_window] 唤醒前剥斜杠 {text!r} -> {body!r}")

            return await original(self, event)

        WakingCheckStage.process = guarded_process
        _GUARD_INSTALLED = True
        logger.info("[wake_window] 已装空消息兜底 + 命令斜杠预处理")
    except Exception as e:
        logger.warning(f"[wake_window] 唤醒阶段兜底安装失败：{e}")


_COMMAND_NAMES: set[str] | None = None
_COMMAND_NAMES_AT = 0.0


def _registered_command_names() -> set[str]:
    """Collect every command name AstrBot has a handler for, cached 60s."""
    global _COMMAND_NAMES, _COMMAND_NAMES_AT
    now = time.monotonic()
    if _COMMAND_NAMES is not None and (now - _COMMAND_NAMES_AT) < 60:
        return _COMMAND_NAMES
    names: set[str] = set()
    try:
        from astrbot.core.star.filter.command import CommandFilter
        from astrbot.core.star.star_handler import EventType, star_handlers_registry

        for handler in star_handlers_registry.get_handlers_by_event_type(
            EventType.AdapterMessageEvent, only_activated=False
        ):
            for flt in getattr(handler, "event_filters", []) or []:
                if isinstance(flt, CommandFilter):
                    try:
                        names.update(flt.get_complete_command_names())
                    except Exception:
                        pass
    except Exception as e:
        logger.debug(f"[wake_window] 命令表读取失败：{e}")
    _COMMAND_NAMES = names
    _COMMAND_NAMES_AT = now
    return names


def _is_command_text(body: str) -> bool:
    """True when ``body`` would be claimed by one of AstrBot's commands."""
    names = _registered_command_names()
    if not names:
        return False
    # longest first so "时间窗关闭" wins before "时间窗"
    for name in sorted(names, key=len, reverse=True):
        if body == name or body.startswith(name + " "):
            return True
    return False



@register(
    "astrbot_plugin_wake_window",
    "xiangguo",
    "1.0.0",
    "群聊免@时间窗：被@后一段时间内不用再@",
)
class WakeWindowPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or {}
        # group scope id -> last wake timestamp
        self._last_wake: dict[str, float] = {}
        # cache of AstrBot command names (refreshed every 60s)
        self._cmd_cache: set[str] | None = None
        self._cmd_cache_at = 0.0

        window = self.config.get("window_seconds", DEFAULT_WINDOW_SECONDS)
        try:
            self.window = max(1, int(window))
        except (TypeError, ValueError):
            self.window = DEFAULT_WINDOW_SECONDS
            logger.warning(
                f"[wake_window] window_seconds 配置无效 ({window!r})，回退到 {DEFAULT_WINDOW_SECONDS}s"
            )

        logger.info(f"[wake_window] 时间窗 {self.window} 秒")
        self._check_config()
        _install_empty_message_guard()

    # ---------- helpers ----------

    @staticmethod
    def _is_at_me(event: AstrMessageEvent) -> bool:
        """True when this message @s the bot itself."""
        self_id = str(event.get_self_id())
        for seg in event.get_messages():
            if isinstance(seg, At) and str(seg.qq) == self_id:
                return True
        return False

    @staticmethod
    def _scope(event: AstrMessageEvent) -> str:
        """Per-group key; private chats get their own bucket too."""
        group = event.get_group_id()
        if group:
            return f"group:{group}"
        return f"private:{event.get_sender_id()}"

    def _check_config(self) -> None:
        """Warn when wake_prefix prevents group messages from reaching this plugin.

        self.config is the plugin-scoped config (only window_seconds); the global
        config with wake_prefix has to come from context.get_config().
        """
        try:
            cfg = self.context.get_config()
            prefixes = cfg.get("wake_prefix", [])
        except Exception as e:
            logger.debug(f"[wake_window] 读取全局配置失败：{e}")
            return
        if prefixes != [""]:
            logger.warning(
                '[wake_window] wake_prefix 不是 [""]（当前 %r），时间窗不会生效。'
                "请在 配置文件 → 平台与消息 → 唤醒词 中留空。",
                prefixes,
            )
        else:
            logger.info('[wake_window] wake_prefix 已留空，所有群消息都会经过时间窗判断')

    # ---------- main hook ----------

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def gate(self, event: AstrMessageEvent):
        """放行时间窗内的消息，拦掉时间窗外的群聊消息。"""
        # Private chats always get through -- no gating needed there.
        if event.is_private_chat():
            return

        # Commands must always reach their handlers.
        #
        # With wake_prefix=[""] AstrBot no longer strips the leading "/", so
        # CommandFilter (which requires message_str.startswith("时间窗 ")) would
        # never match "/时间窗 40" and every command would silently fall through
        # to the LLM. Strip the slash ourselves, but only for commands AstrBot
        # actually knows -- otherwise /签到 /充值 from other bots would be
        # answered by the fish as if they were chat.
        text = (event.message_str or "").lstrip()
        body = text[1:].strip() if text.startswith("/") else text
        if _is_command_text(body):
            event.message_str = body
            return

        scope = self._scope(event)
        now = time.monotonic()

        # An explicit @ always opens (or refreshes) the window.
        if self._is_at_me(event):
            self._last_wake[scope] = now
            return

        last = self._last_wake.get(scope)
        if last is not None and (now - last) <= self.window:
            # Slide the window forward while the conversation keeps going.
            self._last_wake[scope] = now
            return

        # Outside the window: this group message is not for us.
        #
        # stop_event() alone does NOT stop the LLM call. process_stage/stage.py
        # gates on:
        #     if (event.get_result() and not event.is_stopped()) or not event.get_result():
        # so an event with no result AND no send still reaches the model. Setting
        # an empty result makes the first half False, and stop_event() is kept so
        # later handlers are skipped too.
        self._last_wake.pop(scope, None)
        event.set_result(MessageEventResult())
        event.stop_event()

    # ---------- commands ----------

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("时间窗")
    async def window_status(self, event: AstrMessageEvent, action: str = ""):
        """查看或调整免@时间窗。/时间窗 查看；/时间窗 60 设为60秒"""
        if action.isdigit() and int(action) > 0:
            self.window = int(action)
            self._persist_window(self.window)
            yield event.plain_result(f"时间窗改为 {self.window} 秒")
            return

        scope = self._scope(event)
        last = self._last_wake.get(scope)
        if last is None:
            remain = 0
        else:
            remain = max(0, int(self.window - (time.monotonic() - last)))
        tail = f"，本群剩余 {remain} 秒" if remain else "，本群当前未开启"
        yield event.plain_result(f"免@时间窗 {self.window} 秒{tail}")

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.command("时间窗关闭")
    async def window_close(self, event: AstrMessageEvent):
        """立刻收回本群的免@时间窗"""
        scope = self._scope(event)
        self._last_wake.pop(scope, None)
        yield event.plain_result("本群时间窗已关闭，之后需要重新 @")

    # ---------- internals ----------

    def _is_known_command(self, event: AstrMessageEvent, body: str) -> bool:
        """Ask AstrBot's own command filters whether they claim this text.

        Name matching against the registry is unreliable (command groups expand
        to "记忆 状态" style names, and the registry is empty before plugins
        load). Running the real filters is exact by construction.
        """
        try:
            from astrbot.core.star.filter.command import CommandFilter
            from astrbot.core.star.filter.command_group import CommandGroupFilter
            from astrbot.core.star.star_handler import EventType, star_handlers_registry
        except Exception as e:
            logger.debug(f"[wake_window] 无法导入命令过滤器：{e}")
            return False

        cfg = None
        try:
            cfg = self.context.get_config()
        except Exception:
            pass

        original = event.message_str
        event.message_str = body
        try:
            handlers = star_handlers_registry.get_handlers_by_event_type(
                EventType.AdapterMessageEvent, only_activated=False
            )
            for handler in handlers:
                for flt in getattr(handler, "event_filters", []) or []:
                    if not isinstance(flt, (CommandFilter, CommandGroupFilter)):
                        continue
                    try:
                        if flt.filter(event, cfg):
                            return True
                    except Exception:
                        continue
        finally:
            event.message_str = original
        return False

    def _matches_registered_command(self, body: str) -> bool:
        """Deprecated name-based check, kept for the unit test harness."""
        names = self._registered_commands()
        if not names:
            return False
        for name in names:
            if body == name or body.startswith(name + " "):
                return True
        return False

    def _registered_commands(self) -> set[str]:
        """Collect command names from the handler registry, cached for a minute."""
        now = time.monotonic()
        if self._cmd_cache is not None and (now - self._cmd_cache_at) < 60:
            return self._cmd_cache
        names: set[str] = set()
        try:
            from astrbot.core.star.filter.command import CommandFilter
            from astrbot.core.star.star_handler import EventType, star_handlers_registry

            for handler in star_handlers_registry.get_handlers_by_event_type(
                EventType.AdapterMessageEvent
            ):
                for flt in getattr(handler, "event_filters", []) or []:
                    if isinstance(flt, CommandFilter):
                        try:
                            names.update(flt.get_complete_command_names())
                        except Exception:
                            pass
        except Exception as e:
            logger.debug(f"[wake_window] 读取命令表失败：{e}")
        self._cmd_cache = names
        self._cmd_cache_at = now
        return names

    def _persist_window(self, seconds: int) -> None:
        """Write the new value into this plugin's own config file so it survives restarts."""
        cfg = self.config
        if cfg is None:
            return
        try:
            cfg["window_seconds"] = seconds
            save = getattr(cfg, "save_config", None)
            if save:
                save()
        except Exception as e:
            logger.debug(f"[wake_window] 保存配置失败（不影响当前运行）：{e}")
