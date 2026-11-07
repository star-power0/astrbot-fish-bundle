"""astrbot_plugin_persona_state — private-chat companion with a life of her own.

Injects a small state block (mood / energy / sleep / plan / relationship /
standing consent) into private-chat system prompts, runs her daily life
(schedule, diary+dream, anniversaries) and lets her reach out first with
rate-limited proactive messages. Group chats are never touched.

Layout: state.py (pure state), jobs.py (pure job logic), llm.py (provider
wrapper), main.py (AstrBot wiring). v2.0.0.
"""

import asyncio
import json
import os
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Image, Plain
from astrbot.core.message.message_event_result import MessageChain

try:  # package-style load (AstrBot normal case)
    from . import jobs, llm
    from .state import (
        MARKER,
        append_daily_log,
        beijing_date_str,
        compose_block,
        count_reply_cost,
        decay_session,
        derived_miss,
        fresh_session,
        load_state,
        observe_user_message,
        save_state,
        apply_bond_init,
        bond_level,
        sleep_phase,
    )
except ImportError:  # flat-file load fallback
    import jobs
    import llm
    from state import (
        MARKER,
        append_daily_log,
        beijing_date_str,
        compose_block,
        count_reply_cost,
        decay_session,
        derived_miss,
        fresh_session,
        load_state,
        observe_user_message,
        save_state,
        apply_bond_init,
        bond_level,
        sleep_phase,
    )

DATA_SUB = "astrbot_plugin_persona_state"
DEFAULTS = {
    "enabled": True,
    "inject_chars": 240,
    "wake_hour": 8,
    "sleep_hour": 23,
    "nsfw_mode": "off",
    "nsfw_prompt": "",
    "nsfw_mild_text": "",      # consent line injected at mild level (config-driven)
    "nsfw_explicit_text": "",  # consent line injected at explicit level (config-driven)
    "persona_brief": "",
    "user_name": "你",
    "user_birthday": "",       # "MM-DD"
    "anniversary_date": "",    # "YYYY-MM-DD"
    "sticker_enabled": True,   # proactive messages may attach a meme image
    "bond_init": 85,           # starting bond: 85=恋人, 55=亲密, 30=熟络, 20=认识
    "apply_personas": "",      # empty = every private chat; else comma-separated persona ids
    "proactive_enabled": True,
    "proactive_daily_cap": 3,
    "proactive_min_interval_min": 120,
    "quiet_start": "01:00",
    "quiet_end": "08:00",
    "task_provider_id": "",
    "daily_task_token_limit": 200000,
}


@register(
    "astrbot_plugin_persona_state",
    "xiangguo",
    "2.0.0",
    "私聊伴侣状态+生活：心情/精力/睡眠/节目单/日记梦境/好感纪念日/主动消息/关系分级，0 token 打分",
)
class PersonaStatePlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = dict(DEFAULTS)
        if config:
            self.config.update({k: v for k, v in config.items() if v not in (None, "")})
        self.data_dir = os.path.join("data", "plugin_data", DATA_SUB)
        self.state_path = os.path.join(self.data_dir, "state.json")
        self.diary_dir = os.path.join(self.data_dir, "diary")
        self.events_path = os.path.join(self.data_dir, "events.json")
        raw_ap = self.config.get("apply_personas", "")
        if isinstance(raw_ap, list):
            self.apply_personas = {str(x).strip() for x in raw_ap if str(x).strip()}
        else:
            self.apply_personas = {x.strip() for x in str(raw_ap).split(",") if x.strip()}
        self._state = load_state(self.state_path)
        apply_bond_init(self._state, self._cfg("bond_init"))
        self._events = self._load_events()
        self._task = None
        self._task_tokens_today = {"day": "", "n": 0}
        self._diary_done_day = {}
        self._plan_gen_locks = {}

    # ---------- helpers ----------

    def _cfg(self, key):
        return self.config.get(key, DEFAULTS.get(key))

    def _session(self, sid: str) -> dict:
        sessions = self._state.setdefault("sessions", {})
        sess = sessions.get(sid)
        if not isinstance(sess, dict):
            sess = fresh_session(bond_init=self._cfg("bond_init"))
            sessions[sid] = sess
        return sess

    def _private_sessions(self):
        return {k: v for k, v in self._state.get("sessions", {}).items()
                if ":FriendMessage:" in k}

    def _load_events(self):
        try:
            with open(self.events_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"custom": [], "auto": []}

    def _save_events(self):
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            tmp = self.events_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._events, f, ensure_ascii=False)
            os.replace(tmp, self.events_path)
        except OSError as e:
            logger.warning(f"[persona_state] events save failed: {e}")

    def _tokens_left(self):
        today = beijing_date_str()
        if self._task_tokens_today["day"] != today:
            self._task_tokens_today = {"day": today, "n": 0}
        return int(self._cfg("daily_task_token_limit")) - self._task_tokens_today["n"]

    def _charge(self, n):
        self._task_tokens_today["n"] += int(n)

    async def _llm(self, prompt, umo=None):
        """One background task with token accounting; raises on failure."""
        self._charge(llm.estimate_tokens(prompt) + 200)
        text = await llm.call_llm(self.context, prompt, self.config, umo)
        self._charge(llm.estimate_tokens(text))
        return text

    def _persona_prompt(self, sess):
        """Full persona text for background jobs (falls back to the brief).

        persona_id is cached from on_llm_request; the prompt comes from the
        public persona_manager, so diary/proactive tasks always speak in the
        persona's own voice without keeping a second copy in config.
        """
        pid = str(sess.get("persona_id") or "")
        try:
            persona = self.context.persona_manager.get_persona_v3_by_id(pid or None)
            if persona and persona.get("prompt"):
                return str(persona["prompt"])[:1500]
        except Exception:
            pass
        return str(self._cfg("persona_brief") or "")

    def _special_today(self, sess):
        """Anniversary/birthday line for today, or ''."""
        today = beijing_date_str()
        md = today[5:]
        out = []
        bday = str(self._cfg("user_birthday") or "").strip()
        if bday and bday == md:
            out.append("今天是用户的生日")
        ann = str(self._cfg("anniversary_date") or "").strip()
        if ann and ann <= today:
            try:
                days = (time.mktime(time.strptime(today, "%Y-%m-%d"))
                        - time.mktime(time.strptime(ann, "%Y-%m-%d"))) // 86400
                out.append(f"你们在一起第 {int(days)} 天（{ann} 起）")
            except ValueError:
                pass
        for ev in (self._events.get("custom") or []) + (self._events.get("auto") or []):
            if str(ev.get("date", ""))[5:] == md:
                out.append(f"今天是「{ev.get('name')}」的日子")
        return "；".join(out[:2])

    # ---------- hooks ----------

    @filter.on_llm_request()
    async def inject_state(self, event: AstrMessageEvent, req, **kwargs):
        if not self._cfg("enabled"):
            return

        persona_id = ""
        try:
            persona_id = str(event.get_extra("_trace_persona_id") or "")
        except Exception:
            persona_id = ""
        if self.apply_personas and persona_id not in self.apply_personas:
            return  # not a companion persona: no injection, no state growth

        sid = str(event.unified_msg_origin or "private")
        sess = self._session(sid)
        if persona_id:
            sess["persona_id"] = persona_id
        now = time.time()
        decay_session(sess, now, int(self._cfg("wake_hour")), int(self._cfg("sleep_hour")))

        msg_id = ""
        try:
            msg_id = str(event.message_obj.message_id or "")
        except Exception:
            msg_id = ""
        if msg_id and msg_id != sess.get("last_msg_id"):
            sess["last_msg_id"] = msg_id
            observe_user_message(sess, event.message_str, now,
                                 int(self._cfg("wake_hour")), int(self._cfg("sleep_hour")))
            count_reply_cost(sess, now)
            append_daily_log(sess, event.message_str, now)
            self._clear_thread_if_answered(sess, event.message_str)
            asyncio.create_task(self._maybe_gen_plan(sid, sess))
            # plans are alive: appointments in chat re-shape today's schedule
            self._maybe_regen_plan_on_appointment(sid, sess, now, event.message_str)

        try:
            block = compose_block(
                sess, now, int(self._cfg("inject_chars") or 240),
                nsfw_mode=self._cfg("nsfw_mode"), nsfw_prompt=self._cfg("nsfw_prompt"),
                nsfw_mild_text=self._cfg("nsfw_mild_text"),
                nsfw_explicit_text=self._cfg("nsfw_explicit_text"),
                wake_hour=int(self._cfg("wake_hour")), sleep_hour=int(self._cfg("sleep_hour")),
            )
            special = self._special_today(sess)
            if special:
                block = f"{block}\n日子：{special}"
        except Exception as e:
            logger.warning(f"[persona_state] compose failed: {e}")
            return
        if block and MARKER not in (req.system_prompt or ""):
            current = req.system_prompt or ""
            req.system_prompt = f"{current}\n\n{block}" if current else block

        try:
            save_state(self.state_path, self._state)
        except Exception as e:
            logger.warning(f"[persona_state] save failed: {e}")

    @filter.on_llm_response()
    async def on_resp(self, event: AstrMessageEvent, resp, **kwargs):
        """Catch open questions from her replies so proactive can follow up."""
        sid = str(event.unified_msg_origin or "")
        sess = self._session(sid)
        text = str(getattr(resp, "completion_text", "") or "")
        pro = sess.setdefault("pro", {})
        # he replied after her open thread -> resolved
        if pro.get("open_thread"):
            pro["open_thread"] = None
        if text.rstrip().endswith(("？", "?")) and len(text) < 60:
            pro["open_thread"] = {"text": text.strip()[-40:], "at": time.time()}

    def _clear_thread_if_answered(self, sess, text):
        pro = sess.get("pro") or {}
        if pro.get("open_thread") and str(text or "").strip():
            pro["open_thread"] = None

    # ---------- in-story capabilities ----------

    @filter.llm_tool("set_anniversary")
    async def set_anniversary(self, event: AstrMessageEvent, name: str, date: str):
        """当聊天中自然确立了值得纪念的具体日子时，默默登记它（例如第一次见面、在一起的日子、说好的约定）。不要主动询问对方纪念日，也不要在回复中提到你登记了什么。

        Args:
            name (str): 纪念日名称，简短，如「在一起」「第一次一起吃饭」
            date (str): 发生日期，格式 YYYY-MM-DD
        """
        try:
            if not event.is_private_chat():
                return ""
            pid = str(event.get_extra("_trace_persona_id") or "")
            if self.apply_personas and pid not in self.apply_personas:
                return ""
        except Exception:
            return ""
        name = str(name or "").strip()[:20]
        date = str(date or "").strip()
        import re as _re
        if not name:
            return "需要纪念日名称"
        if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            return "日期格式需要是 YYYY-MM-DD"
        existing = self._events.setdefault("custom", [])
        if any(e.get("name") == name for e in existing):
            return f"「{name}」已经记着了"
        existing.append({"name": name, "date": date})
        self._save_events()
        logger.info(f"[persona_state] 纪念日登记（对话内）：{name} {date}")
        return "好的"

    # ---------- background life ----------

    @filter.on_astrbot_loaded()
    async def on_loaded(self):
        # dependency self-check: one info line so decoupling is observable
        try:
            if not self._cfg("sticker_enabled"):
                logger.info("[persona_state] 依赖自检：表情功能已由配置关闭")
            else:
                meta = self.context.get_registered_star("astrbot_plugin_dafatyu_meme")
                ok = meta is not None and hasattr(getattr(meta, "star_cls", None), "pick_image")
                logger.info("[persona_state] 依赖自检：表情图源 "
                            + ("可用" if ok else "未找到（主动消息将退化为纯文本）"))
        except Exception:
            pass
        self._task = asyncio.create_task(self._life_loop())

    async def terminate(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._task = None

    async def _life_loop(self):
        """Minute tick: diary at night, proactive candidates."""
        while True:
            try:
                await asyncio.sleep(60)
                await self._tick()
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"[persona_state] life loop: {e}")

    async def _tick(self):
        now = time.time()
        for sid, sess in list(self._private_sessions().items()):
            if self.apply_personas and str(sess.get("persona_id") or "") not in self.apply_personas:
                continue  # a plain private chat: no life of her own
            decay_session(sess, now, int(self._cfg("wake_hour")), int(self._cfg("sleep_hour")))
            await self._maybe_write_diary(sid, sess)
            await self._maybe_proactive(sid, sess)
            save_state(self.state_path, self._state)

    def _maybe_regen_plan_on_appointment(self, sid, sess, now, text, daily_cap=3):
        """Re-shape today's plan when the chat mentions doing things together."""
        try:
            if not jobs.PLAN_RE.search(str(text or "")):
                return
        except Exception:
            return
        pro = sess.setdefault("pro", {})
        today = beijing_date_str(now)
        if pro.get("plan_regen_day") != today:
            pro["plan_regen_day"] = today
            pro["plan_regen_count"] = 0
        if int(pro.get("plan_regen_count", 0)) >= daily_cap:
            return
        pro["plan_regen_count"] = int(pro.get("plan_regen_count", 0)) + 1
        asyncio.create_task(self._regen_plan_now(sid, sess))

    async def _regen_plan_now(self, sid, sess):
        sess["plan"] = None
        await self._maybe_gen_plan(sid, sess)

    async def _maybe_gen_plan(self, sid, sess):
        """Generate today's plan once per day (async, non-blocking)."""
        today = beijing_date_str()
        plan = sess.get("plan") or {}
        if isinstance(plan, dict) and plan.get("date") == today:
            return
        if self._tokens_left() < 2000:
            return
        lock = self._plan_gen_locks.setdefault(sid, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            plan = sess.get("plan") or {}
            if isinstance(plan, dict) and plan.get("date") == today:
                return
            try:
                text = await self._llm(jobs.build_plan_prompt(sess, self._cfg("persona_brief")), sid)
                parsed = jobs.parse_plan(text)
                if parsed:
                    parsed["date"] = today
                    sess["plan"] = parsed
                    logger.info(f"[persona_state] plan generated: {len(parsed['items'])} items")
                    save_state(self.state_path, self._state)
            except Exception as e:
                logger.warning(f"[persona_state] plan gen failed: {e}")

    async def _maybe_write_diary(self, sid, sess):
        """Nightly: write yesterday's diary once per day."""
        yesterday = beijing_date_str(time.time() - 86400)
        if self._diary_done_day.get(sid) == yesterday:
            return
        if not (sess.get("daily_log") or {}).get(yesterday):
            self._diary_done_day[sid] = yesterday  # nothing to write
            return
        if self._tokens_left() < 2000:
            return
        try:
            text = await self._llm(
                jobs.build_diary_prompt(
                    sess, yesterday, self._persona_prompt(sess),
                    self._cfg("user_name"),
                    jobs.state_line(sess, time.time(),
                                    int(self._cfg("wake_hour")), int(self._cfg("sleep_hour"))),
                ), sid)
            parsed = jobs.parse_diary(text, yesterday)
            self._diary_done_day[sid] = yesterday
            if parsed:
                os.makedirs(self.diary_dir, exist_ok=True)
                path = os.path.join(self.diary_dir, f"{yesterday}.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(parsed, f, ensure_ascii=False)
                for ev in parsed.get("events", []):
                    names = {x.get("name") for x in self._events.setdefault("auto", [])}
                    if ev["name"] not in names:
                        self._events["auto"].append(ev)
                self._save_events()
                logger.info(f"[persona_state] diary written for {yesterday}")
        except Exception as e:
            logger.warning(f"[persona_state] diary failed: {e}")

    async def _maybe_proactive(self, sid, sess):
        reason = jobs.evaluate_proactive(sess, time.time(), {
            "proactive_enabled": self._cfg("proactive_enabled"),
            "quiet_start": self._cfg("quiet_start"),
            "quiet_end": self._cfg("quiet_end"),
            "proactive_daily_cap": self._cfg("proactive_daily_cap"),
            "proactive_min_interval_min": self._cfg("proactive_min_interval_min"),
            "wake_hour": self._cfg("wake_hour"),
            "sleep_hour": self._cfg("sleep_hour"),
        })
        if not reason or self._tokens_left() < 1000:
            return
        try:
            text = await self._llm(
                jobs.PROACTIVE_PROMPT.format(
                    user_name=self._cfg("user_name"),
                    persona=self._persona_prompt(sess) or "一个有自己生活的女生",
                    state_line=jobs.state_line(sess, time.time()),
                    reason=reason["reason"],
                    recent=jobs.recent_lines(sess),
                ), sid)
            parts, sticker = jobs.parse_proactive(text)
            if not parts and not sticker:
                return
            sent = await self._send_proactive(sid, parts, sticker)
            if sent:
                pro = sess.setdefault("pro", {})
                pro["last_sent"] = time.time()
                pro["count"] = int(pro.get("count", 0)) + 1
                logger.info(f"[persona_state] proactive sent (score={reason['score']}): {parts[0][:30]}")
        except Exception as e:
            logger.warning(f"[persona_state] proactive failed: {e}")

    # ---------- proactive sending ----------

    def _meme_url(self, query):
        """Pick a sticker via the meme plugin's public contract.

        Returns '' when the config switch is off or the plugin is absent —
        callers then fall back to plain text, so this dependency stays
        optional and one-directional.
        """
        if not self._cfg("sticker_enabled"):
            return ""
        try:
            meta = self.context.get_registered_star("astrbot_plugin_dafatyu_meme")
            inst = getattr(meta, "star_cls", None) if meta else None
            if inst is None or not hasattr(inst, "pick_image"):
                return ""
            picked = inst.pick_image(str(query)[:16])
            return str(picked.get("url", "")) if picked else ""
        except Exception as e:
            logger.warning(f"[persona_state] sticker pick failed: {e}")
            return ""

    async def _send_proactive(self, sid, parts, sticker=""):
        """Send like a person: sticker first, then each line, 1.2s apart."""
        try:
            chains = []
            if sticker:
                url = self._meme_url(sticker)
                if url:
                    chains.append(MessageChain(chain=[Image.fromURL(url)]))
            for p in parts[:2]:
                chains.append(MessageChain(chain=[Plain(p)]))
            ok = True
            for i, ch in enumerate(chains):
                if i:
                    await asyncio.sleep(1.2)
                ok = await self.context.send_message(sid, ch) and ok
            return ok
        except Exception as e:
            logger.warning(f"[persona_state] proactive send failed: {e}")
            return False

    # ---------- commands ----------


    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("伴侣状态")
    async def cmd_state(self, event: AstrMessageEvent):
        """查看当前私聊状态数值（调试用）。"""
        sid = str(event.unified_msg_origin or "private")
        sess = self._session(sid)
        decay_session(sess)
        now = time.time()
        pro = sess.get("pro") or {}
        joy = _clamp01(sess.get("joy", 0))
        love = _clamp01(sess.get("love", 0))
        miss = derived_miss(sess, now)
        energy = _clamp01(sess.get("energy", 0))
        bond = float(sess.get("bond", 0))
        phase = sleep_phase(sess, now, int(self._cfg("wake_hour")), int(self._cfg("sleep_hour")))
        plan_ok = (sess.get("plan") or {}).get("date") == beijing_date_str()
        gap = max(0, now - float(sess.get("last_user_at", now)))

        lines = ["💗 林娟 · 此刻", ""]
        lines.append(f"😊 心情 {_bar(joy)} {_joy_word(joy)}")
        lines.append(f"💗 心动 {_bar(love)} {_love_word(love)}")
        lines.append(f"🌙 想念 {_bar(miss)} {_miss_word(miss)}")
        lines.append(f"⚡ 精力 {_bar(energy)} {_energy_word(energy)}")
        lines.append(f"💞 好感 {bond:.0f}/100 · {_bond_word(bond)}")
        lines.append(f"😴 状态 {_sleep_word(phase)}")
        if int(sess.get("sleep_debt", 0)):
            lines.append(f"   （欠觉 {int(sess['sleep_debt'])} 场，被你吵醒的）")
        if gap >= 120:
            h, m = int(gap // 3600), int(gap // 60) % 60
            lines.append(f"⏳ 你们有 {'%d 小时 %d 分钟' % (h, m) if h else f'{m} 分钟'}没说话了")
        lines.append("")
        lines.append(f"📋 节目单：{'✅ 已排好（/刷新日程 可重排）' if plan_ok else '⬜ 未生成'}")
        lines.append(f"💌 今日主动找你：{pro.get('count', 0)} 次")
        lines.append(f"🧵 没接完的话头：{'有' if pro.get('open_thread') else '无'}")
        lines.append(f"🎭 人格：{sess.get('persona_id') or '未记录'}"
                     f"{'✓' if not self.apply_personas or str(sess.get('persona_id') or '') in self.apply_personas else '（状态系统未启用）'}")
        yield event.plain_result("\n".join(lines))


def _clamp01(n):
    try:
        return min(1.0, max(0.0, float(n)))
    except (TypeError, ValueError):
        return 0.0


def _bar(v, n=5):
    v = _clamp01(v)
    return "▓" * round(v * n) + "░" * (n - round(v * n))


def _joy_word(v):
    if v < 0.2: return "有点低落"
    if v < 0.5: return "平静"
    if v < 0.7: return "心情不错"
    return "很开心"


def _love_word(v):
    if v < 0.4: return "平静"
    if v < 0.55: return "有点在意"
    return "心动加速"


def _miss_word(v):
    if v < 0.4: return "还好"
    if v < 0.6: return "有点想"
    if v < 0.85: return "挺想的"
    return "很想很想"


def _energy_word(v):
    if v < 0.3: return "很累"
    if v < 0.55: return "有点累"
    if v < 0.8: return "正常"
    return "满状态"


def _bond_word(b):
    for floor, name in [(80, "恋人"), (55, "亲密"), (30, "熟络"), (0, "认识")]:
        if b >= floor:
            return name
    return "认识"


def _sleep_word(phase):
    return {"awake": "清醒中", "sleepy": "有点犯困", "asleep": "已入睡"}.get(phase, phase)


    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("刷新日程")
    async def cmd_refresh_plan(self, event: AstrMessageEvent):
        """重新生成她今天的节目单。"""
        sid = str(event.unified_msg_origin or "")
        sess = self._session(sid)
        sess["plan"] = None
        yield event.plain_result("好，她在重新想今天干什么……")
        await self._maybe_gen_plan(sid, sess)
        plan = sess.get("plan") or {}
        items = plan.get("items", [])
        if items:
            lines = [f"{it['start']} {it['title']}" + (f"（{it['note']}）" if it.get("note") else "") for it in items]
            yield event.plain_result("她今天的安排：\n" + "\n".join(lines))
        else:
            yield event.plain_result("她今天想随性一点，没排计划")

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("她的日记")
    async def cmd_diary(self, event: AstrMessageEvent):
        """看她最近一篇日记。"""
        try:
            files = sorted(os.listdir(self.diary_dir)) if os.path.isdir(self.diary_dir) else []
            if not files:
                yield event.plain_result("她还没写过日记")
                return
            with open(os.path.join(self.diary_dir, files[-1]), "r", encoding="utf-8") as f:
                d = json.load(f)
            text = f"【{d.get('date')}】{d.get('mood', '')}\n{d.get('diary', '')}"
            if d.get("dream"):
                text += f"\n昨晚的梦：{d['dream']}"
            yield event.plain_result(text)
        except Exception as e:
            yield event.plain_result(f"失败：{e}")

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("设置生日")
    async def cmd_birthday(self, event: AstrMessageEvent, date: str = ""):
        """设置用户生日 MM-DD。"""
        if not _valid_md(date):
            yield event.plain_result("格式：/设置生日 06-01")
            return
        self.config["user_birthday"] = date
        yield event.plain_result(f"已记住你的生日：{date}")

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("设置纪念日")
    async def cmd_anniversary(self, event: AstrMessageEvent, name: str = "", date: str = ""):
        """添加纪念日，如 /设置纪念日 在一起 2026-11-06"""
        if not name or not _valid_date(date):
            yield event.plain_result("格式：/设置纪念日 名称 YYYY-MM-DD")
            return
        self._events.setdefault("custom", []).append({"name": name[:20], "date": date})
        self._save_events()
        yield event.plain_result(f"已记住纪念日「{name}」：{date}")

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("主动开关")
    async def cmd_proactive(self, event: AstrMessageEvent, flag: str = ""):
        """开/关主动消息：/主动开关 on|off"""
        flag = str(flag).lower()
        if flag in ("on", "off"):
            self.config["proactive_enabled"] = flag == "on"
        state = "开" if self._cfg("proactive_enabled") else "关"
        yield event.plain_result(
            f"主动消息：{state}"
            f"（每日上限 {self._cfg('proactive_daily_cap')}，免打扰 {self._cfg('quiet_start')}-{self._cfg('quiet_end')}）"
        )

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("主动测试")
    async def cmd_proactive_test(self, event: AstrMessageEvent):
        """立刻触发一次主动消息（不计频控）。"""
        sid = str(event.unified_msg_origin or "")
        sess = self._session(sid)
        yield event.plain_result("测试中……")
        try:
            text = await self._llm(
                jobs.PROACTIVE_PROMPT.format(
                    user_name=self._cfg("user_name"),
                    persona=self._persona_prompt(sess) or "一个有自己生活的女生",
                    state_line=jobs.state_line(sess, time.time()),
                    reason="用户要求测试主动消息，随便找件事分享",
                    recent=jobs.recent_lines(sess),
                ), sid)
            parts, sticker = jobs.parse_proactive(text)
            if parts or sticker:
                await self._send_proactive(sid, parts, sticker)
                yield event.plain_result("已发送（见上方她的消息）")
            else:
                yield event.plain_result("失败：模型没输出可用内容")
        except Exception as e:
            yield event.plain_result(f"失败：{e}")


def _valid_md(s):
    import re
    return bool(re.fullmatch(r"\d{2}-\d{2}", str(s or "").strip()))


def _valid_date(s):
    import re
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s or "").strip()))
