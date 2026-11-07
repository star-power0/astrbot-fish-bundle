"""Pure state engine for persona_state: mood / energy / sleep / bond / plan.

Stdlib only — no AstrBot imports — so the logic is unit-testable outside
AstrBot. main.py handles all AstrBot wiring; jobs.py holds prompt/decision
logic for background LLM tasks.

Design sources:
- dsh-identity moodv2/pace: keyword-scored emotions (0 token), half-life
  decay to baseline, tone-only injection (never changes facts).
- emotion-system: longing grows with time apart, relieved (not erased) on
  contact.
- private_companion (feature model only): daily plan, diary+dream, bond
  levels, proactive candidates — reimplemented lightweight, JSON-backed.
"""

import json
import os
import re
import time

# ---- baselines / rates -------------------------------------------------
BASE_JOY = 0.35
BASE_LOVE = 0.30
BASE_MISS = 0.30
JOY_HALF_H = 12.0
LOVE_HALF_H = 24.0
MISS_GROWTH_PER_H = 0.05
MISS_RELIEF_FLOOR = 0.25
MISS_RELIEF_KEEP = 0.4

BASE_INTIMACY = 0.35
INTIMACY_HALF_H = 48.0     # intimacy is slow: builds over days, fades slowly
INTIMACY_DAILY_CAP = 0.3   # max intimacy gain per day from keywords

ENERGY_RECOVER_PER_MIN = 0.02
ENERGY_COST_BASE = 0.03
ENERGY_COST_STEP = 0.025
ENERGY_COST_CAP = 0.15
SEGMENT_GAP_S = 300

FULL_AT = 0.55
LOW_AT = 0.30

# bond: 0-100, gains capped per day, slow decay when neglected
BOND_TALK = 0.2            # per interaction
BOND_SWEET = 0.5           # per sweet-keyword hit
BOND_DAILY_CAP = 6.0
BOND_DECAY_PER_DAY = 2.0   # when silent > 24h
BOND_MIN = 0.0
BOND_MAX = 100.0

BOND_LEVELS = [(80, "恋人"), (55, "亲密"), (30, "熟络"), (0, "认识")]

MARKER = "[persona_state]"

# (pattern, joy, love, intimacy) — scored against the user's message only
SIGS = [
    (r"(哈+|哈哈|笑死|好耶|太棒|厉害|牛|强|优秀|可爱|谢谢|辛苦|晚安|早安)", 0.10, 0.02, 0.0),
    (r"(喜欢|爱你|想你|抱抱|贴贴|亲亲|宝贝|老婆|亲爱的|想你啦)", 0.08, 0.16, 0.06),
    (r"(亲|摸|抱|靠|蹭|腿|腰|嘴唇|吻|脱|床)", 0.02, 0.06, 0.08),
    (r"(滚|讨厌|烦死了|笨|蠢|闭嘴|别理我|不理你|哼)", -0.12, -0.05, -0.03),
    (r"(难过|委屈|伤心|emo|不开心|好累)", -0.06, 0.02, 0.0),
]
APOLOGY_RE = re.compile(r"(对不起|抱歉|不好意思|我的错|是我不好|怪我)")
APOLOGY_JOY_RECOVER = 0.7

NSFW_LEVELS = {"off": 0, "mild": 1, "explicit": 2}


def _clamp01(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, n))


def _clampf(n, lo, hi):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return lo
    return min(hi, max(lo, n))


def beijing_now(now=None):
    """Bot serves a China-based user; use UTC+8 regardless of server TZ."""
    return time.gmtime((now if now is not None else time.time()) + 8 * 3600)


def beijing_date_str(now=None):
    return time.strftime("%Y-%m-%d", beijing_now(now))


def beijing_hm(now=None):
    return time.strftime("%H:%M", beijing_now(now))


def beijing_hour(now=None):
    return beijing_now(now).tm_hour


BOND_INIT_DEFAULT = 85.0  # matches a "we're already together" persona


def fresh_session(now=None, bond_init=BOND_INIT_DEFAULT):
    now = now if now is not None else time.time()
    return {
        # mood
        "joy": BASE_JOY,
        "love": BASE_LOVE,
        "miss_value": BASE_MISS,
        "miss_since": now,
        # body / energy
        "energy": 0.85,
        "energy_at": now,
        "streak": 0,
        "sleep_debt": 0,
        # relationship
        "bond": float(bond_init),
        "intimacy": BASE_INTIMACY,
        "intimacy_gain_today": 0.0,
        "intimacy_gain_day": "",
        "bond_gain_today": 0.0,
        "bond_gain_day": "",
        # activity
        "last_user_at": now,
        "last_msg_id": "",
        "persona_id": "",      # cached from on_llm_request for background jobs
        # life
        "plan": None,          # {"date","items":[{"start","end","title","note"}]}
        "daily_log": {},       # {"YYYY-MM-DD": [{"t","u"}]} keep 2 days
        # proactive
        "pro": {
            "last_sent": 0,
            "today": "",
            "count": 0,
            "open_thread": None,  # {"text","at"} — she asked, user hasn't replied
            "plan_regen_day": "",
            "plan_regen_count": 0,
        },
        "updated_at": now,
    }


def apply_bond_init(state, bond_init=BOND_INIT_DEFAULT):
    """One-shot migration: raise existing sessions to the configured start.

    Persona says the two already know each other, so a stored bond from the
    old 20-point default must not keep the model in "stranger" mode. Marks
    each session so lowering bond_init later doesn't re-apply.
    """
    try:
        target = float(bond_init)
    except (TypeError, ValueError):
        target = BOND_INIT_DEFAULT
    for sess in state.get("sessions", {}).values():
        if not isinstance(sess, dict):
            continue
        pro = sess.setdefault("pro", {})
        if pro.get("bond_init_applied"):
            continue
        if target > float(sess.get("bond", 0)):
            sess["bond"] = target
        pro["bond_init_applied"] = True
    return state


def _merge_fresh(sess):
    """Fill any missing keys so an old state.json keeps working after upgrades."""
    base = fresh_session()
    for k, v in base.items():
        if k not in sess:
            sess[k] = v
        elif isinstance(v, dict) and isinstance(sess[k], dict):
            for k2, v2 in v.items():
                sess[k].setdefault(k2, v2)
    return sess


# ---- persistence -------------------------------------------------------

def load_state(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("sessions"), dict):
            return {"sessions": {}}
        for sess in data["sessions"].values():
            if isinstance(sess, dict):
                _merge_fresh(sess)
        return data
    except (OSError, ValueError):
        return {"sessions": {}}


def save_state(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, path)


# ---- derived values ----------------------------------------------------

def derived_miss(sess, now=None):
    now = now if now is not None else time.time()
    hours = max(0.0, (now - float(sess.get("miss_since", now))) / 3600.0)
    return _clamp01(float(sess.get("miss_value", BASE_MISS)) + MISS_GROWTH_PER_H * hours)


def sleep_phase(sess, now=None, wake_hour=8, sleep_hour=23):
    """awake / sleepy / asleep — from Beijing clock + sleep debt."""
    h = beijing_hour(now)
    debt = int(sess.get("sleep_debt", 0))
    if sleep_hour <= h or h < wake_hour - 1:
        return "asleep"
    if h < wake_hour + 1 or h >= sleep_hour - 1 or debt >= 2:
        return "sleepy"
    return "awake"


def bond_level(bond):
    for floor, name in BOND_LEVELS:
        if bond >= floor:
            return name
    return "认识"


def current_plan_item(sess, now=None):
    """The plan item covering now, or None. Items are 'HH:MM' strings."""
    plan = sess.get("plan") or {}
    if not isinstance(plan, dict) or plan.get("date") != beijing_date_str(now):
        return None
    hm = beijing_hm(now)
    cur = None
    for item in plan.get("items", []):
        if str(item.get("start", "")) <= hm:
            cur = item
    return cur


def append_daily_log(sess, text, now=None):
    """Keep the last 2 days of user lines for the nightly diary job."""
    now = now if now is not None else time.time()
    d = beijing_date_str(now)
    log = sess.setdefault("daily_log", {})
    log.setdefault(d, [])
    u = str(text or "").strip()
    if u:
        log[d].append({"t": int(now), "u": u[:80]})
        log[d] = log[d][-60:]
    yday = time.strftime("%Y-%m-%d", time.gmtime(now + 8 * 3600 - 86400))
    for k in list(log.keys()):
        if k not in (d, yday):
            del log[k]


# ---- decay -------------------------------------------------------------

def decay_session(sess, now=None, wake_hour=8, sleep_hour=23):
    """In-place decay toward baselines + energy recovery. Mutates sess."""
    now = now if now is not None else time.time()
    hours = max(0.0, (now - float(sess.get("updated_at", now))) / 3600.0)
    if hours > 0:
        k_joy = 0.5 ** (hours / JOY_HALF_H)
        k_love = 0.5 ** (hours / LOVE_HALF_H)
        sess["joy"] = _clamp01(BASE_JOY + (float(sess.get("joy", BASE_JOY)) - BASE_JOY) * k_joy)
        sess["love"] = _clamp01(BASE_LOVE + (float(sess.get("love", BASE_LOVE)) - BASE_LOVE) * k_love)
        k_int = 0.5 ** (hours / INTIMACY_HALF_H)
        sess["intimacy"] = _clamp01(BASE_INTIMACY + (float(sess.get("intimacy", BASE_INTIMACY)) - BASE_INTIMACY) * k_int)

    mins = max(0.0, (now - float(sess.get("energy_at", now))) / 60.0)
    energy = _clamp01(float(sess.get("energy", 0.85)) + mins * ENERGY_RECOVER_PER_MIN)
    # sleep debt caps how high energy can climb
    if int(sess.get("sleep_debt", 0)) >= 2:
        energy = min(energy, FULL_AT - 0.1)
    sess["energy"] = energy
    sess["energy_at"] = now
    if mins > SEGMENT_GAP_S / 60.0:
        sess["streak"] = 0

    # bond decays only when neglected for a full day
    silent_h = max(0.0, (now - float(sess.get("last_user_at", now))) / 3600.0)
    if silent_h > 24:
        days = silent_h / 24.0
        sess["bond"] = _clampf(float(sess.get("bond", 20)) - BOND_DECAY_PER_DAY * days, BOND_MIN, BOND_MAX)

    # reset per-day gain counters on a new Beijing day
    today = beijing_date_str(now)
    if sess.get("intimacy_gain_day") != today:
        sess["intimacy_gain_today"] = 0.0
        sess["intimacy_gain_day"] = today
    if sess.get("bond_gain_day") != today:
        sess["bond_gain_today"] = 0.0
        sess["bond_gain_day"] = today

    # a full night of silence clears sleep debt
    if sleep_phase(sess, now, wake_hour, sleep_hour) == "asleep" and silent_h > 6:
        sess["sleep_debt"] = 0

    sess["updated_at"] = now
    return sess


# ---- events ------------------------------------------------------------

def observe_user_message(sess, text, now=None, wake_hour=8, sleep_hour=23):
    """Score one incoming user message; relieve longing; grow bond/intimacy."""
    now = now if now is not None else time.time()
    text = str(text or "")

    grown = derived_miss(sess, now)
    sess["miss_value"] = _clamp01(MISS_RELIEF_FLOOR + (grown - MISS_RELIEF_FLOOR) * MISS_RELIEF_KEEP)
    sess["miss_since"] = now

    sweet = 0
    intimate = 0
    for pattern, joy_d, love_d, int_d in SIGS:
        if re.search(pattern, text):
            sess["joy"] = _clamp01(float(sess.get("joy", BASE_JOY)) + joy_d)
            sess["love"] = _clamp01(float(sess.get("love", BASE_LOVE)) + love_d)
            if int_d > 0:
                intimate += 1
            if love_d >= 0.06:
                sweet += 1
    if APOLOGY_RE.search(text):
        joy = float(sess.get("joy", BASE_JOY))
        if joy < BASE_JOY:
            sess["joy"] = _clamp01(BASE_JOY + (joy - BASE_JOY) * APOLOGY_JOY_RECOVER)

    today = beijing_date_str(now)
    if sess.get("intimacy_gain_day") != today:
        sess["intimacy_gain_today"] = 0.0
        sess["intimacy_gain_day"] = today
    if sess.get("bond_gain_day") != today:
        sess["bond_gain_today"] = 0.0
        sess["bond_gain_day"] = today

    int_gain = min(0.1 * intimate, max(0.0, INTIMACY_DAILY_CAP - float(sess.get("intimacy_gain_today", 0))))
    sess["intimacy"] = _clamp01(float(sess.get("intimacy", BASE_INTIMACY)) + int_gain)
    sess["intimacy_gain_today"] = float(sess.get("intimacy_gain_today", 0)) + int_gain

    bond_gain = min(BOND_TALK + BOND_SWEET * sweet, max(0.0, BOND_DAILY_CAP - float(sess.get("bond_gain_today", 0))))
    sess["bond"] = _clampf(float(sess.get("bond", 20)) + bond_gain, BOND_MIN, BOND_MAX)
    sess["bond_gain_today"] = float(sess.get("bond_gain_today", 0)) + bond_gain

    # being woken up during asleep hours builds sleep debt and kills energy
    if sleep_phase(sess, now, wake_hour, sleep_hour) == "asleep":
        sess["sleep_debt"] = int(sess.get("sleep_debt", 0)) + 1
        sess["energy"] = min(float(sess.get("energy", 0.85)), LOW_AT)

    sess["last_user_at"] = now
    sess["updated_at"] = now
    return sess


def count_reply_cost(sess, now=None):
    now = now if now is not None else time.time()
    cost = min(ENERGY_COST_CAP, ENERGY_COST_BASE + ENERGY_COST_STEP * int(sess.get("streak", 0)))
    sess["energy"] = _clamp01(float(sess.get("energy", 0.85)) - cost)
    sess["streak"] = int(sess.get("streak", 0)) + 1
    sess["energy_at"] = now
    sess["updated_at"] = now
    return sess


# ---- composition -------------------------------------------------------

def _gap_phrase(seconds):
    if seconds < 120:
        return ""
    if seconds < 3600:
        return f"距你上一条消息 {int(seconds // 60)} 分钟"
    if seconds < 86400:
        return f"距你上一条消息 {int(seconds // 3600)} 小时"
    return f"你有 {int(seconds // 86400)} 天没找我了"


def compose_block(sess, now=None, max_chars=240, nsfw_mode="off", nsfw_prompt="",
                  wake_hour=8, sleep_hour=23, nsfw_mild_text="", nsfw_explicit_text=""):
    """Build the injected block: tone + life + relationship + standing consent.

    The NSFW line is a *standing permission in the persona* (not a
    time-windowed injection): always present when enabled, letting the model
    decide in-conversation when intimacy is appropriate.
    """
    now = now if now is not None else time.time()
    lines = ["# 此刻状态（只影响语气与生活感，不改事实与边界）"]

    joy = _clamp01(sess.get("joy", BASE_JOY))
    love = _clamp01(sess.get("love", BASE_LOVE))
    miss = derived_miss(sess, now)

    mood = []
    if joy <= 0.22 and miss >= 0.55:
        mood.append("有点委屈：想你，但也带点小情绪，别撒娇过头")
    else:
        if joy >= 0.6:
            mood.append("心情很好，语气轻快")
        elif joy <= 0.18:
            mood.append("有点低落，别硬撑着活跃")
        if love >= 0.45:
            mood.append("有点心动，可以自然地黏一点")
        if miss >= 0.85:
            mood.append("很想你")
        elif miss >= 0.6:
            mood.append("有点想你")
    if mood:
        lines.append("心情：" + "；".join(mood))

    phase = sleep_phase(sess, now, wake_hour, sleep_hour)
    energy = _clamp01(sess.get("energy", 0.85))
    if phase == "asleep":
        lines.append("睡眠：被你吵醒了，声音迷糊带点起床气，说完还想睡")
    elif phase == "sleepy":
        lines.append("睡眠：有点犯困，话更短更软")
    if energy < LOW_AT:
        lines.append("精力：很累，能一句说完就一句")
    elif energy < FULL_AT:
        lines.append("精力：有点累，话说短点")

    gap = _gap_phrase(now - float(sess.get("last_user_at", now)))
    if gap:
        lines.append(gap)

    # her life: current plan item
    item = current_plan_item(sess, now)
    if item:
        tail = f"，还想{item['note']}" if item.get("note") else ""
        lines.append(f"她现在：{item.get('title', '忙着')}{tail}")

    # relationship
    bond = float(sess.get("bond", 20))
    lines.append(f"关系：好感 {bond:.0f}（{bond_level(bond)}档）")

    # standing consent — persona-level, always injected when enabled
    level = NSFW_LEVELS.get(str(nsfw_mode or "off").lower(), 0)
    if level == 1:
        # Consent wording comes from config so the public repo stays neutral.
        lines.append(str(nsfw_mild_text or "").strip() or "(mild consent text)")
    elif level >= 2:
        lines.append(str(nsfw_explicit_text or "").strip() or "(explicit consent text)")
        extra = str(nsfw_prompt or "").strip()
        if extra:
            lines.append(extra)

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text
