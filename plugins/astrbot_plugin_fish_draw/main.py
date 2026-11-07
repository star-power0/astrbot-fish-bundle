import base64
import json
import os
import time

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain

DATA_SUB = "astrbot_plugin_fish_draw"
DEFAULTS = {
    "enabled": True,
    "base_url": "api.starroute.me",
    "api_key": "",
    "model": "gpt-image-2",
    "size": "1024x1024",
    "timeout": 120,
    "tool_cooldown": 60,       # per-user LLM-tool cooldown, seconds
}

GEN_USAGE = "用法：/生图 <描述>，例如 /生图 一只戴墨镜的鲸鱼"


@register(
    "astrbot_plugin_fish_draw",
    "xiangguo",
    "1.0.0",
    "极简生图：/生图 命令 + generate_image 工具，OpenAI Images 兼容 API，仅私聊",
)
class FishDrawPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = dict(DEFAULTS)
        if config:
            self.config.update(config)
        self._last_tool_call: dict[str, float] = {}
        logger.info(
            "[fish_draw] loaded | model=%s base=%s | cooldown=%ss",
            self.config.get("model"),
            self.config.get("base_url"),
            self.config.get("tool_cooldown"),
        )

    def _cfg(self, key: str):
        return self.config.get(key, DEFAULTS.get(key))

    def _data_dir(self) -> str:
        return os.path.join("data", "plugin_data", DATA_SUB)

    async def _generate(self, prompt: str) -> str:
        """Call Images API, save the returned image, return a local file path."""
        base = str(self._cfg("base_url") or "").rstrip("/")
        if not base.startswith("http"):
            base = "https://" + base
        url = f"{base}/v1/images/generations"
        body = {
            "model": self._cfg("model"),
            "prompt": prompt,
            "size": self._cfg("size"),
            "n": 1,
        }
        headers = {
            "Authorization": f"Bearer {self._cfg('api_key')}",
            "Content-Type": "application/json",
        }
        timeout_s = int(self._cfg("timeout") or 120)
        t0 = time.time()
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_s),
            ) as resp:
                text = await resp.text()
                if resp.status != 200:
                    logger.warning("[fish_draw] HTTP %s: %s", resp.status, text[:300])
                    raise RuntimeError(f"接口返回 {resp.status}")
                data = json.loads(text)
        items = data.get("data") or []
        if not items:
            raise RuntimeError("接口没有返回图片")
        item = items[0]
        os.makedirs(self._data_dir(), exist_ok=True)
        path = os.path.join(self._data_dir(), f"gen_{int(time.time())}.png")
        if item.get("b64_json"):
            with open(path, "wb") as f:
                f.write(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    item["url"], timeout=aiohttp.ClientTimeout(total=timeout_s)
                ) as r:
                    if r.status != 200:
                        raise RuntimeError(f"图片下载失败 {r.status}")
                    with open(path, "wb") as f:
                        f.write(await r.read())
        else:
            raise RuntimeError("返回里既没有 b64_json 也没有 url")
        logger.info("[fish_draw] generated in %.1fs -> %s", time.time() - t0, path)
        return path

    @staticmethod
    def _image(path: str) -> Image:
        return Image.fromFileSystem(path)

    # ---------- manual command, private chat only ----------

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("生图", alias={"画图"})
    async def draw_command(self, event: AstrMessageEvent, prompt: str = ""):
        """/生图 <描述>"""
        if not prompt.strip():
            yield event.plain_result(GEN_USAGE)
            return
        try:
            path = await self._generate(prompt.strip())
        except Exception as e:
            yield event.plain_result(f"失败：{e}")
            return
        yield event.chain([self._image(path)])

    # ---------- LLM tool, private chat only ----------

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.llm_tool(name="generate_image")
    async def generate_image(self, event: AstrMessageEvent, prompt: str = "") -> str:
        """生成一张图片并发送。当对方想看画、照片、插图，或让你「画一张/拍一张/看看你长什么样」时调用。

        你要先把对方的意图翻译成一段独立的画面描述再传 prompt：
        - 对方说「你的样子 / 你在干嘛 / 拍一张现在的你」→ 结合你的人设形象（外表、穿着）和此刻正在做的事，写成第三人称画面描述
        - 对方描述一个场景 → 忠实扩写，补上风格、光线、构图细节
        - prompt 必须独立完整，不出现「我」「你」这类代词

        Args:
            prompt(string): 完整画面描述，例如「傍晚的画室里，一个扎马尾的美术生伏在画板前，暖黄灯光，动漫风格」
        """
        if not prompt.strip():
            return "描述太空了，画不了"
        sender = str(event.get_sender_id())
        cooldown = int(self._cfg("tool_cooldown") or 0)
        if cooldown > 0:
            wait = cooldown - (time.time() - self._last_tool_call.get(sender, 0))
            if wait > 0:
                return f"刚画过一张，休息 {int(wait)} 秒再画。"
        try:
            path = await self._generate(prompt.strip())
        except Exception as e:
            return f"画失败了：{e}"
        self._last_tool_call[sender] = time.time()
        try:
            await self.context.send_message(
                event.unified_msg_origin,
                MessageChain(chain=[self._image(path)]),
            )
        except Exception as e:
            return f"画好了但发送失败: {e}"
        return "图片已发送。可以在回复里自然提一句。"
