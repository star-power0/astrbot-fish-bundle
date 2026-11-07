"""大肥鱼梗图插件：多源表情包图库（梗鲸 + AstrBot 社区包）。

数据源：
- 梗鲸 https://aigengtu.com/gallery-index.json —— 12 个 AI 娘化分类，2935+ 张，带台词/场景元数据
- AstrBot 社区表情包（GitHub）—— 每图预分类，语义匹配更准
图片全部走 CDN 热链，零本地存储。
- /梗图 [关键词|编号]  手动发一张
- LLM 工具 send_meme(query, as_sticker)  模型在接梗/怼人/表达情绪时自主发图
"""

import asyncio
import json
import os
import random
import re
import time
import urllib.parse
import urllib.request

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain

AIGENGTU_INDEX = "https://aigengtu.com/gallery-index.json"
AIGENGTU_IMG = "https://img.aigengtu.com/0_preview/meme/{}.webp"

# Index cache: building it needs ~11s of network calls (16 GitHub requests for
# the community packs alone). Persisting it turns every later start into a
# 0.1s file read; the TTL only decides when the background refresh re-fetches.
CACHE_TTL_SECONDS = 24 * 3600

# Community packs: every image already carries a semantic category.
# (repo, ref) -> GitHub raw base for the images.
GH_RAW = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"
PACKS = [
    ("anka-afk/blue-fat-fish-meme-pack", "v1.0.0"),
    ("anka-afk/deepseek-fanart-meme-pack", "v1.0.0"),
    ("anka-afk/astrbot-meme-pack-official-01", "main"),
    ("anka-afk/seio-stickers", "v2026.09.0"),
    ("liquidtoy001/astrbot-meme-pack-marisa", "v1.0.0"),
    ("momo-OwO-qwq/astrbot-meme-pack-kipfel", "master"),
    ("flybode/yctf-taffy-meme-pack", "main"),
    ("Shennoter/astrbot-meme-pack-steins-gate-0", "main"),
]

# ChineseBQB: 6246 Chinese stickers across 119 categories (cats, dogs, Altman,
# Kuan-chin Panda, SpongeBob, absurd memes...). A single GitHub Trees call
# returns every file path, so the whole library is indexable without any
# downloads — images stay on GitHub's CDN.
BQB_REPO = "zhaoolee/ChineseBQB"
BQB_REF = "master"
BQB_RAW = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"
BQB_IMAGE_EXT = ("jpg", "jpeg", "png", "gif", "webp")

# ChineseBQB folder prefix -> our semantic category (longest prefix wins).
BQB_CATEGORY_MAP = {
    "001Funny_": "baka",
    "002CuteGirl_": "affection",
    "003CuteBoy_": "affection",
    "004SmirkBoy_": "baka",
    "006Hamster_": "meow",
    "007Tiger_": "angry",
    "008HappyDuck_": "happy",
    "009KumamotoBear_": "confused",
    "010Cat_": "meow",
    "011Dog_": "meow",
    "012Parrot_": "confused",
    "013PigPecs_": "happy",
    "014Pig_": "happy",
    "015Golden_Curator_Panda": "baka",
    "017Playing_": "happy",
    "018WangEgg_": "meow",
    "020TATAN": "baka",
    "021TongfuInn_": "teasing",
    "022SuDaqiang_": "sigh",
    "023Emoji_": "happy",
    "024Programmer_": "work",
    "025SuperHeroes_": "surprised",
    "026Chicken_": "surprised",
    "027Turtle_": "sigh",
    "029Pigeon_": "reply",
    "030AntennaBaby_": "happy",
    "031Penguin_": "baka",
    "033Eat_": "food",
    "034WhiteVillain_": "confused",
    "035TomAndJerry_": "teasing",
    "036Pikachu_": "surprised",
    "038Jacky_": "teasing",
    "039YaoMing": "baka",
    "040HanazawaKana": "affection",
    "041ChenguoCui": "baka",
    "043Altman_": "surprised",
    "045MatchstickMen_": "confused",
    "046WhatToWear_": "confused",
    "047ShowSword": "angry",
    "048SpongeBob_": "happy",
    "049CatEveryday_": "meow",
    "051Call_": "reply",
    "052Squirtle_": "surprised",
    "053University": "work",
    "055AllHeart_": "affection",
    "056Doraemon_": "happy",
    "057HappyDuck": "happy",
    "059_Couple_Head": "affection",
    "060MurCat_": "meow",
    "061KeNan_": "confused",
    "062CaiXvKun_": "baka",
    "065TravelFrog_": "sigh",
    "067NegroCarryingACoffin": "sigh",
    "070JOJO": "surprised",
    "071": "affection",
    "072PaiYiPai_": "reply",
    "074BrotherGui_": "baka",
    "076Moe": "affection",
    "077TuHi_": "happy",
    "079mabaoguo_": "baka",
    "080GuiMie_": "angry",
    "082AttackOnTitan_": "surprised",
    "083ChineseNewYear_": "happy",
    "084Wuliuqi_": "teasing",
    "089TeaBoy_": "sigh",
    "090SailorMoon_": "affection",
    "091LetTheBulletsFly_": "teasing",
    "092LuoXiang_": "baka",
    "094TeacherWang_": "baka",
    "095GenShin_": "surprised",
    "096NationalDay_": "happy",
    "097Tu_": "angry",
    "098spyxfamily_": "affection",
    "100TheGegenerate_": "angry",
    "101ChainsawMan_": "surprised",
    "103EmpressesInThePalace_": "teasing",
    "105_BlackMythWuKong_": "surprised",
    "106_Frieren_": "affection",
    "107_FLittleBrother_": "surprised",
    "108_Pingu_": "confused",
    "109_Opossum_": "sigh",
    "110_AI_": "tech",
    "111_TheBoys_": "angry",
}

# Category keywords -> tokens used for scoring a query.
CATEGORY_HINTS = {
    "happy": "开心 高兴 得意 赢了 太好了 恭喜 笑 哈哈 好耶",
    "angry": "生气 恼火 怒 烦 滚 讨厌 抗议 骂 炸毛",
    "sad": "难过 委屈 哭 伤心 失落 emo 难受 破防",
    "sleep": "困 睡 累 打盹 下班 摸鱼 摆烂 躺平",
    "food": "吃 饿 饭 馋 白饭 投喂 好饿 干饭",
    "money": "钱 token 贵 穷 收费 打折 预算 白嫖 抠",
    "work": "工作 打工 加班 写代码 干活 忙 上班 搬砖",
    "tech": "技术 模型 开源 部署 api 服务器 版本 更新 代码",
    "confused": "不懂 疑惑 问号 什么 为啥 懵 没听懂",
    "affection": "喜欢 爱 贴贴 抱抱 亲亲 感谢 温柔 撒娇",
    "teasing": "菜 嘲讽 嘲笑 阴阳 挑衅 就这 看不起",
    "portrait": "自拍 人像 长相 好看 可爱 颜值",
    "greeting": "你好 在吗 早 晚安 打招呼 上线 来了",
    "shy": "害羞 脸红 不好意思 傲娇 害羞了",
    "surprised": "震惊 惊讶 卧槽 没想到 意外 傻了",
    "sigh": "无语 叹气 无奈 服了 没救了 算了",
    "baka": "笨蛋 傻 蠢 憨 弱智 离谱 离谱了",
    "fool": "自嘲 出丑 搞砸 丢人 尴尬 翻车",
    "meow": "猫 喵 萌 可爱 揉 撸",
    "givemoney": "打钱 红包 付费 转账 请客",
    "morning": "早安 早上 起床 睡醒",
    "reply": "等等 稍等 马上 回复 催",
    "see": "看看 偷看 关注 盯 监视",
    "color": "涩 色 暧昧 撩 害羞的话",
    "cpu": "卡住 脑子 转不动 加载 想不出来",
}

RECENT_LIMIT = 12
# How many distinct categories to avoid repeating before allowing a repeat.
BUCKET_MEMORY = 20
WEB_UA = {"User-Agent": "dafatyu-meme/1.1"}


class StickerSegment:
    """OneBot image segment; sub_type=1 renders it as a sticker in QQ.

    Not an AstrBot Image: AiocqhttpMessageEvent._from_segment_to_dict re-encodes
    every Image as base64 and drops sub_type. Any component exposing toDict()
    is passed through verbatim, so this keeps the sticker flag intact.
    """

    def __init__(self, url: str, sticker: bool = True):
        self.type = "image"
        self.data = {"file": url}
        if sticker:
            self.data["sub_type"] = 1
            self.data["summary"] = "[动画表情]"

    def toDict(self) -> dict:
        return {"type": self.type, "data": self.data}

    def __repr__(self) -> str:
        return "StickerSegment()"


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=WEB_UA)
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8-sig"))


@register(
    "astrbot_plugin_dafatyu_meme",
    "xiangguo",
    "1.2.0",
    "大肥鱼梗图：梗鲸 12 分类 + 8 个社区表情包 + ChineseBQB，共 9200+ 张，/梗图 手动发，LLM 可自主调 send_meme",
)
class DafatyuMemePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # (id, alt, haystack) — haystack holds alt + story + category hints for scoring
        self.records: list[tuple[str, str, str]] = []
        self.recent: list[str] = []
        # (source, label) -> records, used for source-fair sampling
        self._buckets: dict[str, list[tuple[str, str, str]]] = {}
        self._recent_buckets: list[str] = []
        self._loaded = False
        self._lock = asyncio.Lock()
        self._cache_dir = os.path.join("data", "plugin_data", "astrbot_plugin_dafatyu_meme")
        self._cache_file = os.path.join(self._cache_dir, "index_cache.json")
        # Build the index in the background so the first /梗图 or send_meme call
        # never waits for the ~11s network build.
        asyncio.create_task(self._warm_up())

    # ---------- index ----------

    async def _warm_up(self) -> None:
        """Build the index in the background right after the plugin loads.

        Without this the first /梗图 call pays the full ~11s build cost. Runs
        once at startup so no user ever waits for it.
        """
        try:
            await self._ensure_index()
        except Exception as e:
            logger.warning(f"[dafatyu_meme] 预热失败（首次调用时会重试）：{e}")

    async def _ensure_index(self) -> bool:
        if self._loaded or self.records:
            return bool(self.records)
        async with self._lock:
            if self.records:
                return True

            # 1) cached index first: turns an 11s build into a 0.1s read
            if self._load_cache():
                self._loaded = True
                logger.info(f"[dafatyu_meme] 索引来自缓存：{len(self.records)} 张")
                # refresh in the background if the snapshot is stale
                if self._cache_age() > CACHE_TTL_SECONDS:
                    asyncio.create_task(self._refresh_async())
                return True

            # 2) no usable cache: build from network (blocking, one time)
            await self._build_index()
            return bool(self.records)

    async def _refresh_async(self) -> None:
        """Rebuild from network without blocking, then swap the index in."""
        try:
            await self._build_index()
            logger.info(f"[dafatyu_meme] 后台刷新完成：{len(self.records)} 张")
        except Exception as e:
            logger.warning(f"[dafatyu_meme] 后台刷新失败，继续用旧索引：{e}")

    async def _build_index(self) -> None:
        loop = asyncio.get_running_loop()
        records: list[tuple[str, str, str]] = []
        aigengtu_ok = await loop.run_in_executor(None, lambda: self._load_aigengtu(records))
        packs = await loop.run_in_executor(None, lambda: self._load_packs(records))
        bqb = await loop.run_in_executor(None, lambda: self._load_bqb(records))
        if not records:
            return
        # swap only after a successful build so a failed refresh never empties
        # a working index
        self.records = records
        self._rebuild_buckets()
        self._loaded = True
        self._save_cache()
        logger.info(
            f"[dafatyu_meme] 索引构建完成：梗鲸={aigengtu_ok} 社区包={packs} "
            f"BQB={bqb} 合计={len(records)}"
        )

    def _load_cache(self) -> bool:
        """Read the persisted index; False when missing, corrupt, or empty."""
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
            rows = payload.get("records") or []
            if not rows:
                return False
            self.records = [tuple(r) for r in rows if len(r) == 3]
            if not self.records:
                return False
            self._rebuild_buckets()
            return True
        except FileNotFoundError:
            return False
        except Exception as e:
            logger.warning(f"[dafatyu_meme] 缓存读取失败，将重建：{e}")
            return False

    def _save_cache(self) -> None:
        """Persist the index so the next start does not pay the network cost."""
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            tmp = self._cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {"built_at": time.time(), "records": self.records},
                    f,
                    ensure_ascii=False,
                )
            os.replace(tmp, self._cache_file)
            logger.info(f"[dafatyu_meme] 索引已缓存：{len(self.records)} 张")
        except Exception as e:
            logger.warning(f"[dafatyu_meme] 缓存写入失败（不影响运行）：{e}")

    def _cache_age(self) -> float:
        try:
            with open(self._cache_file, "r", encoding="utf-8") as f:
                return time.time() - float(json.load(f).get("built_at", 0))
        except Exception:
            return float("inf")

    def _load_aigengtu(self, out: list[tuple[str, str, str]]) -> int:
        try:
            data = _fetch_json(AIGENGTU_INDEX)
        except Exception as e:
            logger.warning(f"[dafatyu_meme] 梗鲸索引拉取失败：{e}")
            return 0
        n = 0
        for cat, payload in data.get("gallery", {}).items():
            for img in payload.get("images", []):
                preview = img.get("preview", "")
                num = preview.rsplit("/", 1)[-1].split(".", 1)[0]
                if not num:
                    continue
                alt = img.get("alt", "")
                story = (img.get("story") or {}).get("zh", "")
                # category name is a strong signal ("Claude娘" -> claude)
                hay = f"{alt} {story} {cat}"
                out.append((f"gj{num}", f"{alt or cat}#{num}", hay))
                n += 1
        return n

    def _load_packs(self, out: list[tuple[str, str, str]]) -> int:
        n = 0
        for repo, ref in PACKS:
            try:
                manifest = _fetch_json(GH_RAW.format(repo=repo, ref=ref, path="manifest.json"))
                cats = manifest.get("categories", {})
                desc_by_cat = {c: (v or {}).get("description", "") for c, v in cats.items()}
                files = self._pack_files(repo, ref)
                for cat, name in files:
                    hint = CATEGORY_HINTS.get(cat, "")
                    hay = f"{cat} {hint} {desc_by_cat.get(cat, '')}"
                    # pack filenames contain spaces and CJK — must be percent-encoded
                    quoted = urllib.parse.quote(f"memes/{cat}/{name}")
                    url = GH_RAW.format(repo=repo, ref=ref, path=quoted)
                    out.append((url, f"{manifest.get('name', repo)}/{cat}", hay))
                    n += 1
            except Exception as e:
                logger.warning(f"[dafatyu_meme] 社区包 {repo} 失败：{e}")
        return n

    def _load_bqb(self, out: list[tuple[str, str, str]]) -> int:
        """Index ChineseBQB: one Trees call, images stay on GitHub's CDN."""
        url = f"https://api.github.com/repos/{BQB_REPO}/git/trees/{BQB_REF}?recursive=1"
        try:
            tree = _fetch_json(url).get("tree", [])
        except Exception as e:
            logger.warning(f"[dafatyu_meme] ChineseBQB tree 拉取失败：{e}")
            return 0

        # Longest prefix first so "010Cat_" wins before a shorter loose match.
        prefixes = sorted(BQB_CATEGORY_MAP.items(), key=lambda kv: -len(kv[0]))
        n = 0
        for node in tree:
            path = node.get("path", "")
            if node.get("type") != "blob" or "/" not in path:
                continue
            if path.lower().rsplit(".", 1)[-1] not in BQB_IMAGE_EXT:
                continue
            folder = path.split("/", 1)[0]
            cat = ""
            for pref, mapped in prefixes:
                if folder.startswith(pref):
                    cat = mapped
                    break
            if not cat:
                continue
            hint = CATEGORY_HINTS.get(cat, "")
            hay = f"{cat} {hint} {folder}"
            url = BQB_RAW.format(
                repo=BQB_REPO, ref=BQB_REF, path=urllib.parse.quote(path)
            )
            out.append((url, f"BQB/{folder.split('_', 1)[-1]}", hay))
            n += 1
        return n

    @staticmethod
    def _pack_files(repo: str, ref: str) -> list[tuple[str, str]]:
        """List memes/<category>/<file> via the GitHub tree API (one call per pack)."""
        url = f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"
        try:
            tree = _fetch_json(url).get("tree", [])
        except Exception as e:
            logger.warning(f"[dafatyu_meme] {repo} tree 拉取失败：{e}")
            return []
        out = []
        for node in tree:
            path = node.get("path", "")
            if node.get("type") != "blob" or not path.startswith("memes/"):
                continue
            parts = path.split("/")
            if len(parts) != 3:
                continue
            cat, name = parts[1], parts[2]
            if name.lower().rsplit(".", 1)[-1] not in ("png", "jpg", "jpeg", "webp", "gif"):
                continue
            out.append((cat, name))
        return out

    # ---------- selection ----------

    def pick_image(self, query: str = "") -> dict | None:
        """Public stable interface for other plugins.

        Returns {"url": str, "alt": str} or None. Other plugins may depend
        on this name/signature; internal refactors must not break it.
        """
        try:
            picked = self._pick(query)
            if not picked:
                return None
            rid, alt = picked
            return {"url": str(rid), "alt": str(alt)}
        except Exception:
            return None

    def _pick(self, query: str = "") -> tuple[str, str] | None:
        if not self.records:
            return None

        q = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]+", "", query or "")
        if q:
            grams = {q[i : i + 2] for i in range(len(q) - 1)} | ({q} if len(q) <= 8 else set())
            grams.discard("")

            def score(item: tuple[str, str, str]) -> int:
                hay = item[2]
                return sum(3 if g in hay else 0 for g in grams)

            ranked = sorted(self.records, key=score, reverse=True)
            pool = [r for r in ranked[:8] if score(r) > 0]
            if pool:
                return self._commit(self._choose(pool))
            # No semantic hit: fall through to balanced random picking.

        # Balanced sampling: pick a source/category first, then an image inside
        # it. The library is lopsided (DeepSeek娘 alone is ~60% of all images),
        # so a flat random.choice would keep returning the same source.
        bucket = self._balanced_bucket()
        pool = self._buckets.get(bucket) or self.records
        return self._commit(self._choose(pool))

    def _balanced_bucket(self) -> str:
        """Choose a category bucket that has not been used recently."""
        buckets = [b for b in self._buckets if b not in self._recent_buckets]
        if not buckets:
            self._recent_buckets.clear()
            buckets = list(self._buckets)
        chosen = random.choice(buckets)
        self._recent_buckets.append(chosen)
        del self._recent_buckets[:-BUCKET_MEMORY]
        return chosen

    def _choose(self, pool: list[tuple[str, str, str]]) -> tuple[str, str, str]:
        fresh = [r for r in pool if r[0] not in self.recent]
        return random.choice(fresh or pool)

    def _commit(self, chosen: tuple[str, str, str]) -> tuple[str, str]:
        self.recent.append(chosen[0])
        del self.recent[:-RECENT_LIMIT]
        return chosen[0], chosen[1]

    def _rebuild_buckets(self) -> None:
        """Group records by (source, label) so sampling can be source-fair."""
        buckets: dict[str, list[tuple[str, str, str]]] = {}
        for rec in self.records:
            rid, alt, _hay = rec
            if rid.startswith("gj"):
                key = f"gj:{alt.split('#')[0]}"
            elif rid.startswith("http") and "ChineseBQB" in rid:
                key = f"bqb:{alt}"
            else:
                key = f"pack:{alt}"
            buckets.setdefault(key, []).append(rec)
        self._buckets = buckets

    def _by_number(self, raw: str) -> tuple[str, str] | None:
        want = raw.strip().lstrip("0") or "0"
        for rid, alt, _hay in self.records:
            if rid.startswith("gj") and rid[2:].lstrip("0") == want:
                return rid, alt
        return None

    @staticmethod
    def _url(rid: str) -> str:
        return AIGENGTU_IMG.format(rid[2:]) if rid.startswith("gj") else rid

    def _image(self, rid: str, sticker: bool = True) -> StickerSegment:
        return StickerSegment(self._url(rid), sticker=sticker)

    # ---------- manual command ----------

    @filter.command("梗图", alias={"meme"})
    async def meme_command(self, event: AstrMessageEvent, keyword: str = ""):
        """发一张梗图。/梗图 随机；/梗图 关键词；/梗图 编号；/梗图 大图 关键词"""
        if not await self._ensure_index():
            yield event.plain_result("图库没拉到，稍后再试")
            return
        sticker = True
        words = keyword.split() if keyword else []
        if words and words[0] == "大图":
            sticker = False
            words = words[1:]
        query = " ".join(words)
        picked = None
        if query and query.isdigit():
            picked = self._by_number(query)
            if picked is None:
                yield event.plain_result(f"没有编号 {query} 的梗图")
                return
        if picked is None:
            picked = self._pick(query)
        if picked is None:
            yield event.plain_result("图库是空的，怪不了我")
            return
        rid, _alt = picked
        # event.send() goes straight to the adapter. The respond stage drops any
        # component whose exact type is not in its validator table, and its
        # serializer base64-encodes Image and drops sub_type -- both would lose
        # the sticker flag, so the command must bypass the result pipeline.
        await event.send(MessageChain(chain=[self._image(rid, sticker=sticker)]))

    # ---------- LLM tool ----------

    @filter.llm_tool(name="send_meme")
    async def send_meme(self, event: AstrMessageEvent, query: str = "", as_sticker: bool = True) -> str:
        """发一张梗图到当前会话，用于接梗、怼人、自嘲、表达情绪。看到气氛合适就主动发，别等人开口要。

        Args:
            query(string): 用中文描述想表达的情绪/场景，例如「被夸了嘴硬」「嫌对方菜」「气鼓鼓」「懒得理你」「得意」「饿了」
            as_sticker(boolean): 默认 true 发表情（小图表情样式，更自然）；false 发大图（图里有字要看清、或对方想看细节时）
        """
        if not await self._ensure_index():
            return "图库没加载出来，这次发不了图"
        picked = self._pick(query)
        if picked is None:
            return "图库是空的"
        rid, alt = picked
        try:
            await self.context.send_message(
                event.unified_msg_origin,
                MessageChain(chain=[self._image(rid, sticker=as_sticker)]),
            )
        except Exception as e:
            return f"发图失败: {e}"
        kind = "表情" if as_sticker else "大图"
        return f"已发出{kind}（{alt}）。可以在回复里自然提一句。"
