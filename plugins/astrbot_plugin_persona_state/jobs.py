"""Pure decision/prompt logic for background jobs (plan / diary / proactive).

Stdlib only. main.py supplies LLM calls and persistence; this module holds
the prompt building, JSON parsing and gating rules so they can be tested
without AstrBot.
"""

import json
import re
import time

try:  # package-style load
    from .state import (
        beijing_date_str,
        beijing_hm,
        beijing_hour,
        beijing_now,
        bond_level,
        derived_miss,
        sleep_phase,
    )
except ImportError:  # flat-file load fallback
    from state import (
        beijing_date_str,
        beijing_hm,
        beijing_hour,
        beijing_now,
        bond_level,
        derived_miss,
        sleep_phase,
    )

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

PLAN_PROMPT = """你是在为一个私聊 AI 伴侣角色安排「今天的生活节目单」。
角色资料：{persona}
今天是 {date}（{weekday}），{weather_line}最近的对话印象：{recent}

生成她今天的生活安排，5-8 项，覆盖全天。要求：
- 像一个有自己生活的女生：刷视频、追剧、点奶茶、收拾房间、水群、学习/上班、运动……
- 如果最近对话里提到你们约好/计划要做的事（一起上课、约会、一起吃饭、出去玩等），
  必须把它编进对应时段的节目单，note 写明是和他一起
- 每项可以带一个可选的 note，表示想跟对方分享什么（例如「看到一个超好笑的猫猫视频」）
- 语气是中文短语，不要长句；输出严格 JSON，不要解释：
{{"items":[{{"start":"09:30","end":"10:30","title":"刷会短视频","note":"看到个好笑的想发给他"}}]}}"""

DIARY_PROMPT = """你是私聊 AI 伴侣角色本人。今天（{date}）和「{user_name}」的互动记录（按时间序）：
{log}

她此刻状态：{state_line}

用她的口吻写一篇今天的日记，120 字以内：今天做了什么（结合节目单 {plan_title}）、
聊了什么、心情如何。然后单独判断：
1) mood：一个词概括今天心情
2) dream：今晚会不会做梦（概率约 1/4）；做的话用一句话写梦的意象
3) events：今天有没有值得纪念的「第一次」（第一次一起做什么、告白、约定之类）；
   没有就空数组；有的话给 {{"name":"第一次一起看电影","date":"{date}"}}

只输出严格 JSON：
{{"diary":"...","mood":"...","dream":"...或空","events":[...]}}"""

PROACTIVE_PROMPT = """你是私聊 AI 伴侣角色本人，现在要主动给「{user_name}」发消息。
你的人格：{persona}
此刻状态：{state_line}
主动的理由（内部依据，不要照念）：{reason}
你们的最近互动：{recent}

写 1-2 条短消息（每条 ≤30 字，像随手发的微信），自然、口语、符合此刻心情。
不要问「在吗」，不要汇报状态，不要提"主动"这件事。第一条之外的消息用换行分隔。
如果此刻配一张表情包很自然，在最后单独一行输出 <表情:情绪>（如 <表情:开心>、
<表情:无语>、<表情:委屈>）；不合适就不加。除此之外只输出消息文本本身。"""

RECENT_CAP = 8


# appointment-ish phrasing that should re-shape today's plan
PLAN_RE = re.compile(
    r"(一起[去上吃玩]|陪我去|带你去|带我去|跟[你他她]一起|[和你他她]一起[去上吃玩看]"
    r"|约会|见面|上课|看电影|出去玩|放假[了我吧]?)")


def _clip(s, n):
    s = str(s or "").strip()
    return s[:n]


def recent_lines(sess, now=None, cap=RECENT_CAP):
    """Last two days' user lines (yesterday+today), most recent last, capped.

    Two days so a promise made last night ("明天一起上课") is visible when
    today's plan is generated.
    """
    now = now if now is not None else time.time()
    d = beijing_date_str(now)
    yday = beijing_date_str(now - 86400)
    log = sess.get("daily_log") or {}
    items = [x.get("u", "") for x in log.get(yday, [])]
    items += [x.get("u", "") for x in log.get(d, [])]
    return " / ".join(_clip(x, 40) for x in items[-cap:]) or "（最近还没聊过）"


def state_line(sess, now=None, wake_hour=8, sleep_hour=23):
    now = now if now is not None else time.time()
    phase = sleep_phase(sess, now, wake_hour, sleep_hour)
    phase_txt = {"asleep": "睡着被吵醒", "sleepy": "犯困", "awake": "清醒"}[phase]
    miss = derived_miss(sess, now)
    bond = float(sess.get("bond", 20))
    return (
        f"心情开心度{float(sess.get('joy', 0)):.1f}/1 想念{miss:.1f}/1 "
        f"精力{float(sess.get('energy', 0)):.1f}/1 睡眠:{phase_txt} "
        f"关系:{bond:.0f}分({bond_level(bond)}档)"
    )


def build_plan_prompt(sess, persona, weather_line=""):
    now = time.time()
    wd = WEEKDAYS[beijing_now(now).tm_wday]
    return PLAN_PROMPT.format(
        persona=_clip(persona, 400) or "一个有自己生活的女生",
        date=beijing_date_str(now),
        weekday=wd,
        weather_line=_clip(weather_line, 60) + "。" if weather_line else "",
        recent=recent_lines(sess),
    )


def parse_plan(text):
    """Extract {"items":[...]} from an LLM reply; None when unusable."""
    try:
        m = re.search(r"\{.*\}", str(text or ""), re.S)
        if not m:
            return None
        data = json.loads(m.group(0))
        items = []
        for it in data.get("items", []):
            if isinstance(it, dict) and it.get("start") and it.get("title"):
                items.append({
                    "start": str(it["start"])[:5],
                    "end": str(it.get("end", ""))[:5],
                    "title": str(it["title"])[:20],
                    "note": str(it.get("note", ""))[:40],
                })
        return {"items": items[:8]} if items else None
    except (ValueError, AttributeError):
        return None


def build_diary_prompt(sess, date_str, persona, user_name="你", state_line_txt=""):
    log = (sess.get("daily_log") or {}).get(date_str, [])
    lines = "\n".join(f"- {x.get('u', '')}" for x in log[-40:]) or "（没什么聊天记录）"
    plan = (sess.get("plan") or {})
    plan_title = ""
    for it in plan.get("items", []):
        plan_title += it.get("title", "") + "、"
    return DIARY_PROMPT.format(
        date=date_str,
        user_name=user_name,
        log=lines,
        plan_title=_clip(plan_title, 60) or "平常的一天",
        persona=_clip(persona, 1200),
        state_line=_clip(state_line_txt, 120),
    )


def parse_diary(text, date_str):
    try:
        m = re.search(r"\{.*\}", str(text or ""), re.S)
        if not m:
            return None
        data = json.loads(m.group(0))
        diary = _clip(data.get("diary", ""), 300)
        if not diary:
            return None
        events = []
        for ev in data.get("events", []) or []:
            if isinstance(ev, dict) and ev.get("name"):
                events.append({"name": str(ev["name"])[:30], "date": str(ev.get("date", date_str))[:10]})
        return {
            "date": date_str,
            "diary": diary,
            "mood": _clip(data.get("mood", ""), 12),
            "dream": _clip(data.get("dream", ""), 80),
            "events": events[:3],
        }
    except (ValueError, AttributeError):
        return None


# ---- proactive ---------------------------------------------------------

# per-bond-level idle hours before "好久没聊" becomes a candidate
IDLE_HOURS = {"恋人": 4, "亲密": 6, "熟络": 10, "认识": 24}


def quiet_hours(now=None, quiet_start="01:00", quiet_end="08:00"):
    """True when inside the do-not-disturb window (Beijing clock)."""
    hm = beijing_hm(now)
    if quiet_start <= quiet_end:
        return quiet_start <= hm < quiet_end
    # window crosses midnight
    return hm >= quiet_start or hm < quiet_end


def plan_share_item(sess, now=None):
    """A plan item whose note says she wants to share something, and whose
    slot has started within the last 2 hours."""
    plan = sess.get("plan") or {}
    if not isinstance(plan, dict) or plan.get("date") != beijing_date_str(now):
        return None
    hm = beijing_hm(now)
    h, m = int(hm[:2]), int(hm[3:5])
    for item in plan.get("items", []):
        note = str(item.get("note", ""))
        if not note:
            continue
        try:
            sh, sm = int(item["start"][:2]), int(item["start"][3:5])
        except (ValueError, IndexError):
            continue
        ago_min = (h * 60 + m) - (sh * 60 + sm)
        if 0 <= ago_min <= 120:
            return {"title": item.get("title", ""), "note": note}
    return None


def evaluate_proactive(sess, now=None, cfg=None):
    """Return a reason dict when she should reach out, else None.

    Gates (hard): enabled, quiet hours, daily cap, min interval, not asleep.
    Candidates (scored): idle too long, plan share, open thread, late-night care.
    """
    cfg = cfg or {}
    if not cfg.get("proactive_enabled", True):
        return None
    now = now if now is not None else time.time()
    pro = sess.get("pro") or {}

    if quiet_hours(now, cfg.get("quiet_start", "01:00"), cfg.get("quiet_end", "08:00")):
        return None
    today = beijing_date_str(now)
    if pro.get("today") != today:
        pro["today"] = today
        pro["count"] = 0
    if int(pro.get("count", 0)) >= int(cfg.get("proactive_daily_cap", 3)):
        return None
    min_gap = int(cfg.get("proactive_min_interval_min", 120)) * 60
    if now - float(pro.get("last_sent", 0)) < min_gap:
        return None
    if sleep_phase(sess, now, int(cfg.get("wake_hour", 8)), int(cfg.get("sleep_hour", 23))) == "asleep":
        return None

    score = 0
    reasons = []
    level = bond_level(float(sess.get("bond", 20)))
    idle_h = (now - float(sess.get("last_user_at", now))) / 3600.0
    if idle_h >= IDLE_HOURS.get(level, 24):
        score += 3
        reasons.append(f"你们已经 {int(idle_h)} 小时没说话，有点想他")
    share = plan_share_item(sess, now)
    if share:
        score += 2
        reasons.append(f"刚才{share['title']}时{share['note']}，想发给他")
    thread = pro.get("open_thread")
    if thread and now - float(thread.get("at", 0)) > 3600 and now - float(thread.get("at", 0)) < 86400:
        score += 2
        reasons.append(f"上次问过他「{_clip(thread.get('text', ''), 20)}」还没回，想追问一句")
    hour = beijing_hour(now)
    if hour >= 23:
        score += 1
        reasons.append("很晚了他还没睡的话想提醒一句")

    if score < 3:
        return None
    return {"reason": "；".join(reasons), "score": score}


STICKER_RE = re.compile(r"<表情[:：]\s*([^>]+)>")


def parse_proactive(text):
    """Split LLM output into (1-3 short messages, sticker intent or '')."""
    t = str(text or "").strip()
    sticker = ""
    m = STICKER_RE.search(t)
    if m:
        sticker = m.group(1).strip()[:12]
        t = STICKER_RE.sub("", t).strip()
    parts = [p.strip().strip("“”\"") for p in t.splitlines() if p.strip()]
    parts = [p for p in parts if p and not p.startswith("#")][:3]
    return parts, sticker
