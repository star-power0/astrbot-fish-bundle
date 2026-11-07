import asyncio

from astrbot.api import logger
from astrbot.api.star import Context, Star, register

DEFAULTS = {
    "target_type": "private",   # private | group
    "target_id": "",            # QQ number (private) or group id (group)
    "interval_min": 30,
    "recall_after_s": 4,
    "probe_text": "·",
    "state_file": "/tmp/fish_probe_last",  # timestamp of last send attempt, read by qq-gate watchdog
}


@register(
    "astrbot_plugin_fish_probe",
    "xiangguo",
    "1.1.0",
    "心跳探针：定时向指定私聊/群发送一条消息并自动撤回，供 qq-gate watchdog 做消息管道存活检测",
)
class FishProbePlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = dict(DEFAULTS)
        if config:
            self.config.update(config)
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "[fish_probe] loaded | target=%s:%s interval=%smin",
            self.config.get("target_type"),
            self.config.get("target_id"),
            self.config.get("interval_min"),
        )

    def _cfg(self, key: str):
        return self.config.get(key, DEFAULTS.get(key))

    def _mark(self):
        try:
            import time

            with open(self._cfg("state_file"), "w") as f:
                f.write(str(int(time.time())))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[fish_probe] state write failed: %s", exc)

    def _find_bot(self):
        """Locate the aiocqhttp CQHttp instance across platform adapters.

        In AstrBot 4.29.x the platform inst IS the adapter (self.bot on it).
        """
        for inst in self.context.platform_manager.get_insts():
            bot = getattr(inst, "bot", None)
            if bot is not None:
                return bot
            adapter = getattr(inst, "adapter", None)
            bot = getattr(adapter, "bot", None)
            if bot is not None:
                return bot
        return None

    async def _loop(self):
        # settle: wait for platform adapters to come up
        await asyncio.sleep(90)
        while True:
            try:
                await self._probe()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[fish_probe] probe failed: %s", exc)
            await asyncio.sleep(int(self._cfg("interval_min")) * 60)

    async def _probe(self):
        bot = self._find_bot()
        if bot is None:
            logger.warning("[fish_probe] no aiocqhttp bot instance found")
            return
        tid = int(self._cfg("target_id"))
        self._mark()  # mark attempt time even if send fails
        if self._cfg("target_type") == "group":
            result = await bot.send_group_msg(group_id=tid, message=self._cfg("probe_text"))
        else:
            result = await bot.send_private_msg(user_id=tid, message=self._cfg("probe_text"))
        msg_id = None
        if isinstance(result, dict):
            msg_id = result.get("message_id") or (result.get("data") or {}).get("message_id")
        logger.info("[fish_probe] probe sent msg_id=%s", msg_id)
        if msg_id:
            await asyncio.sleep(int(self._cfg("recall_after_s")))
            try:
                await bot.delete_msg(message_id=int(msg_id))
                logger.info("[fish_probe] probe recalled")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[fish_probe] recall failed: %s", exc)

    async def terminate(self):
        if self._task:
            self._task.cancel()
