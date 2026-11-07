import base64
import json
import os
import time

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Record
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.utils.tencent_record_helper import wav_to_tencent_silk

DATA_SUB = "astrbot_plugin_fish_voice"
DEFAULTS = {
    "enabled": True,
    "api_base": "https://api.xiaomimimo.com",
    "api_key": "",
    "model": "mimo-v2.5-tts-voicedesign",
    "voice_desc": "",
    "voice_map": "{}",         # per-persona voice desc: {"人格名": "音色描述"}
    "group_whitelist": "",     # comma-separated group ids allowed to use voice; empty = private only
    "timeout": 60,
    "tool_cooldown": 60,       # per-user LLM-tool cooldown, seconds
}

VOICE_USAGE = "用法：/语音 <要说的话>（仅私聊或已开通的群）"
GROUP_CLOSED = "这个群没开通语音。"


@register(
    "astrbot_plugin_fish_voice",
    "xiangguo",
    "1.2.0",
    "极简语音：/语音 命令 + send_voice 工具，MiMo TTS voicedesign，人格级音色映射，私聊+群白名单",
)
class FishVoicePlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = dict(DEFAULTS)
        if config:
            self.config.update(config)
        self._last_tool_call: dict[str, float] = {}
        logger.info(
            "[fish_voice] loaded | model=%s | voice_desc=%d chars | voice_map=%d personas | group_whitelist=%s | cooldown=%ss",
            self.config.get("model"),
            len(str(self.config.get("voice_desc") or "")),
            len(self._voice_map()),
            self._group_whitelist() or "(private only)",
            self.config.get("tool_cooldown"),
        )

    def _cfg(self, key: str):
        return self.config.get(key, DEFAULTS.get(key))

    def _voice_map(self) -> dict:
        """Parse persona->voice-desc mapping from config (JSON string)."""
        raw = self.config.get("voice_map") or "{}"
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return dict(data) if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _group_whitelist(self) -> list:
        raw = str(self.config.get("group_whitelist") or "")
        return [g.strip() for g in raw.split(",") if g.strip()]

    def _allowed(self, event: AstrMessageEvent) -> bool:
        """Private chat always allowed; group chat only for whitelisted groups."""
        parts = str(event.unified_msg_origin).split(":")
        if len(parts) >= 3 and parts[1] == "GroupMessage":
            return parts[2] in self._group_whitelist()
        return True

    async def _voice_for(self, event: AstrMessageEvent) -> str:
        """Pick voice desc for the current conversation's persona; fallback to default."""
        try:
            cm = self.context.conversation_manager
            cid = await cm.get_curr_conversation_id(event.unified_msg_origin)
            if cid:
                conv = await cm.get_conversation(event.unified_msg_origin, cid)
                pid = conv.persona_id if conv else None
                if pid:
                    desc = self._voice_map().get(pid)
                    if desc:
                        return str(desc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[fish_voice] persona resolve failed: %s", exc)
        return str(self._cfg("voice_desc") or "")

    def _data_dir(self) -> str:
        return os.path.join("data", "plugin_data", DATA_SUB)

    async def _synthesize(self, text: str, voice_desc: str) -> str:
        """Call MiMo TTS (voicedesign), convert wav to Tencent silk, return silk path."""
        desc = str(voice_desc or "").strip()
        if not desc:
            raise RuntimeError("未配置音色描述")
        base = str(self._cfg("api_base") or "").rstrip("/")
        url = f"{base}/v1/chat/completions"
        body = {
            "model": self._cfg("model"),
            "messages": [
                {"role": "user", "content": desc},
                {"role": "assistant", "content": text},
            ],
            "audio": {"format": "wav"},
        }
        headers = {
            "api-key": self._cfg("api_key"),
            "Content-Type": "application/json",
        }
        timeout_s = int(self._cfg("timeout") or 60)
        t0 = time.time()
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_s),
            ) as resp:
                raw = await resp.text()
                if resp.status != 200:
                    logger.warning("[fish_voice] HTTP %s: %s", resp.status, raw[:300])
                    raise RuntimeError(f"接口返回 {resp.status}")
                data = json.loads(raw)
        audio = (data.get("choices") or [{}])[0].get("message", {}).get("audio") or {}
        b64 = audio.get("data")
        if not b64:
            raise RuntimeError("接口没有返回音频")
        os.makedirs(self._data_dir(), exist_ok=True)
        wav_path = os.path.join(self._data_dir(), f"voice_{int(time.time())}.wav")
        with open(wav_path, "wb") as f:
            f.write(base64.b64decode(b64))
        silk_path = wav_path.replace(".wav", ".silk")
        duration = await wav_to_tencent_silk(wav_path, silk_path)
        os.remove(wav_path)
        logger.info(
            "[fish_voice] synthesized in %.1fs -> %s (%.1fs audio)",
            time.time() - t0, silk_path, duration or 0,
        )
        return silk_path

    # ---------- manual command ----------

    @filter.event_message_type(filter.EventMessageType.ALL)
    @filter.command("语音", alias={"说"})
    async def voice_command(self, event: AstrMessageEvent, text: str = ""):
        """/语音 <要说的话>"""
        if not self._allowed(event):
            yield event.plain_result(GROUP_CLOSED)
            return
        if not text.strip():
            yield event.plain_result(VOICE_USAGE)
            return
        try:
            path = await self._synthesize(text.strip(), await self._voice_for(event))
        except Exception as e:
            yield event.plain_result(f"失败：{e}")
            return
        yield event.chain_result([Record.fromFileSystem(path)])

    # ---------- LLM tool ----------

    @filter.event_message_type(filter.EventMessageType.ALL)
    @filter.llm_tool(name="send_voice")
    async def send_voice(self, event: AstrMessageEvent, text: str = "") -> str:
        """用一条语音消息把想说的话说出来。当对方想听你的声音——让你「发语音 / 念出来 / 说给我听」时必须调用；道晚安、哄人、安慰人这种特别适合用声音传达的时刻，也可以主动调用。在群聊里仅在对方明确要求你发语音时才调用，不要自主发。平时普通聊天不要调用，一次回复最多调用一次。

        Args:
            text(string): 语音里要说的话。根据当前对话情境用你自己的口吻自然生成，一两句话，口语化；不要包含 emoji、表情符号或括号里的动作描写
        """
        if not self._allowed(event):
            return "（这个群没开通语音，无法发送，自然带过即可）"
        if not text.strip():
            return "不知道该说什么，先不发了"
        voice_desc = await self._voice_for(event)
        if not voice_desc.strip():
            return "（这个人还没配置声音，发不了语音，自然带过即可）"
        sender = str(event.get_sender_id())
        cooldown = int(self._cfg("tool_cooldown") or 0)
        if cooldown > 0:
            wait = cooldown - (time.time() - self._last_tool_call.get(sender, 0))
            if wait > 0:
                return f"刚发过一条语音，歇 {int(wait)} 秒再说。"
        try:
            path = await self._synthesize(text.strip(), voice_desc)
        except Exception as e:
            return f"语音生成失败：{e}"
        self._last_tool_call[sender] = time.time()
        try:
            await self.context.send_message(
                event.unified_msg_origin,
                MessageChain(chain=[Record.fromFileSystem(path)]),
            )
        except Exception as e:
            return f"语音生成好了但发送失败: {e}"
        return "语音已发送。可以在回复里自然带一句，不要重复语音的内容。"
