# 大肥鱼梗图 (astrbot_plugin_dafatyu_meme)

给 AstrBot 接一个 **9210 张**的梗图/表情包图库。鱼可以自己判断气氛发图，也可以用命令手动要。

图片全部走 CDN 热链，**不占磁盘、不用下载、不建数据库**。

## 功能

- `/梗图` 命令：手动要一张，纯随机，只发图不带文字
- `send_meme` LLM 工具：模型在接梗、怼人、自嘲、表达情绪时**自主发图**，按关键词检索
- 两种发送形态：表情样式（QQ 小图）或普通大图
- 单一插件、零第三方依赖，只用 Python 标准库

## 用法

### 命令

| 命令 | 说明 |
|---|---|
| `/梗图` | 随机一张（表情样式） |
| `/梗图 得意` | 按关键词检索 |
| `/梗图 160` | 指定梗鲸编号 |
| `/梗图 大图 得意` | 发普通大图而不是表情 |
| `/meme` | 上表的别名 |

命令发完图**不附加任何文字**。只有出错时才回话（`没有编号 99999 的梗图`、`图库是空的`）。

### LLM 工具 `send_meme`

| 参数 | 类型 | 说明 |
|---|---|---|
| `query` | string | 中文描述想表达的情绪/场景，如「被夸了嘴硬」「嫌对方菜」「气鼓鼓」「饿了」 |
| `as_sticker` | boolean | `true`（默认）发表情样式；`false` 发大图 |

返回值形如 `已发出表情（DeepSeek娘/teasing）`，模型可以接着补一句话。

### 建议的人设片段

插件本身不写人设，但模型需要知道有这个工具才用得上。**光加「有这个工具」不够**——模型在不确定时会选保守（干脆不发）。要把「该发」写得比「少发」更明确：

```
【梗图】你有 send_meme 工具，这是你说话的另一种方式，不是装饰。
该发：对方夸你/说你可爱 → 嘴硬否认甩一张；说你菜/嘲讽/阴阳 → 怼回去甩一张；
对方翻车说蠢话 → 甩一张看戏；你自己得意被抓包 → 甩一张；
聊到吃饭睡觉加班没钱写代码 → 甩对口的。
不该发：认真求助 → 先办事别插科打诨；对方真难受或气氛僵 → 不发；群里没人理你 → 不主动发。
频率：每 3~5 条回复至少发一次，憋着不发才是错的。
query 填当时气氛（「被夸了嘴硬」「嫌对方菜」「看戏」），as_sticker 默认 true。
```

> 实测：只写「别每条都发，三五条里来一次就够」时，10 次发图里 10 次都是用户明确要求才发；改成上面这种「该发清单 + 憋着不发是错的」之后才出现自发行为。

## 图库来源

### 1. 梗鲸 aigengtu.com

索引 `https://aigengtu.com/gallery-index.json`，图直链 `img.aigengtu.com`（官方允许热链）。

| 分类 | 张数 |
|---|---|
| DeepSeek娘 | 2635 |
| AI娘化 | 97 |
| Claude娘 | 67 |
| GPT娘 | 62 |
| Gemini娘 | 36 |
| Kimi娘 | 17 |
| 通义千问娘 | 13 |
| 豆大妈 | 10 |
| Grok娘 | 8 |
| 智谱清言娘 | 4 |
| Stepfun娘 | 3 |
| MiMo娘 | 3 |

带 `alt`（台词）和 `story.zh`（使用场景）元数据，走关键词匹配。

### 2. AstrBot 社区表情包（GitHub）

来自 [astrbot-meme-pack-index](https://github.com/anka-afk/astrbot-meme-pack-index) 社区索引。这些包的每张图**已经按语义预分类**（`happy` / `angry` / `sleep` / `money` / `work` / `teasing` …），分类描述带「什么时候用」，匹配比关键词准。

| 包 | 张数 | 授权 |
|---|---|---|
| 官方表情包 1 号 | 398 | 见包内 LICENSE |
| Kipfel 表情包 | 285 | 见包内 LICENSE |
| AstrBot娘表情包 | 208 | 非商用 |
| DeepSeek 二创表情包 | 174 | 原素材许可未指定 |
| 魔理沙表情包 | 165 | 见包内 LICENSE |
| 蓝色大肥鱼表情包 | 157 | 见包内 LICENSE |
| 永雏塔菲表情包 | 81 | 见包内 LICENSE |
| 命运石之门 0 | 40 | 见包内 LICENSE |

合计 1508 张，图片走 `raw.githubusercontent.com` 直链。**版权归各原作者**，本插件只做检索转发，不重新分发。

### 3. ChineseBQB 中文表情包（GitHub）

来自 [zhaoolee/ChineseBQB](https://github.com/zhaoolee/ChineseBQB)，一个持续更新的中文表情包集合。索引走一次 Git Trees API，图片直链 `raw.githubusercontent.com`。

按文件夹前缀映射到语义分类，只收录有明确分类的 4746 张：

| 类别 | 例子 | 张数 |
|---|---|---|
| 动物 | 猫咪 176、狗 52、仓鼠、鹦鹉 | ~300 |
| 搞笑人物 | 金馆长熊猫 293、白色小人 839、马保国 | ~1200 |
| 动画角色 | 奥特曼 302、猫和老鼠 287、柯南 179、海绵宝宝 | ~900 |
| 真人梗 | 苏大强、张学友、姚明、黑人抬棺 | ~400 |
| 情绪 | 滑稽大佬 125、全是心心 72 | ~300 |
| 其他 | 原神、间谍过家家、芙莉莲、黑神话悟空 | ~1600 |

映射表 `BQB_CATEGORY_MAP` 只覆盖有语义价值的文件夹；`README/`、`斗图之王BQB`、`微信网友贡献表情包_暂存` 等未映射的目录不收录。

**均衡抽样**：图库 89% 是 DeepSeek 娘，纯随机必然扎堆。抽图时先随机选分类桶（2688 个），再从桶内选图，最近 20 个桶不重复 —— 实测 20 次抽到 20 个不同分类。

## 想要更多图库？

改 `main.py` 顶部的 `PACKS` 列表即可，格式是 `(GitHub 仓库, ref)`：

```python
PACKS = [
    ("anka-afk/blue-fat-fish-meme-pack", "v1.0.0"),
    # 加一行就多一个包
]
```

要求该仓库符合 [表情包格式规范](https://github.com/anka-afk/astrbot-meme-pack-index/blob/main/ASTRBOT_MEME_PACK_PROTOCOL_ZH.md)：根目录有 `manifest.json`，图片放 `memes/<分类>/<文件>`。

也可以在 [社区索引](https://github.com/anka-afk/astrbot-meme-pack-index) 里找现成的包。

### 加 ChineseBQB 分类

在 `main.py` 的 `BQB_CATEGORY_MAP` 里加一行，key 是文件夹前缀（不是全名），value 是语义分类：

```python
BQB_CATEGORY_MAP = {
    "010Cat_": "meow",
    "043Altman_": "surprised",
    # 加一行就多一类
}
```

value 必须落在 `CATEGORY_HINTS` 已有的分类里，否则图进去了但检索命中不了。加完清掉缓存 `index_cache.json` 让它重建。

## 实现要点

这里有三个坑，都是实际踩出来的，改代码前先看。

### 坑 1：AstrBot 的 `Image` 会丢掉表情标记

QQ 的「表情」和「图片」是两种消息。发成表情需要在 OneBot 段里带 `sub_type: 1`，但 AstrBot 的 `Image` 在序列化时会被强制转 base64 并丢掉 `sub_type`：

```python
# astrbot/core/platform/sources/aiocqhttp/aiocqhttp_message_event.py
if isinstance(segment, Image | Record):
    bs64 = await segment.convert_to_base64()
    return {"type": segment.type.lower(), "data": {"file": f"base64://{bs64}"}}
```

所以插件定义了 6 行的 `StickerSegment`，只提供 `toDict()`，走序列化器的最后一行 `return segment.toDict()` 原样透传：

```python
class StickerSegment:
    def __init__(self, url, sticker=True):
        self.type = "image"
        self.data = {"file": url}
        if sticker:
            self.data["sub_type"] = 1
            self.data["summary"] = "[动画表情]"
    def toDict(self):
        return {"type": self.type, "data": self.data}
```

`as_sticker=False` 时不带 `sub_type`，就是普通图片。

### 坑 2：respond stage 会静默丢掉自定义组件

**这是最坑的一个**：`yield event.chain_result([StickerSegment(...)])` 和 `yield MessageChain(...)` 都不会报错，但**图也不会发出去**，日志里只有一行 `Prepare to send`，看着像成功。

原因在 `astrbot/core/pipeline/respond/stage.py:45`，它用**精确类型**查表（`type(comp) in dict`，不是 `isinstance`）：

```python
_component_validators = {
    Comp.Plain: lambda comp: bool(comp.text and comp.text.strip()),
    Comp.Image: lambda comp: bool(comp.file),
    ...
}

async def _is_empty_message_chain(self, chain):
    for comp in chain:
        comp_type = type(comp)
        if comp_type in self._component_validators:   # StickerSegment 不在这里
            if self._component_validators[comp_type](comp):
                return False
    return True    # 全部被跳过 = 判定为空 = 整条丢弃
```

**解法**：命令里用 `await event.send(MessageChain(...))`，它直连适配器，绕开 respond stage：

```python
await event.send(MessageChain(chain=[self._image(rid, sticker=sticker)]))
```

另外注意 `event.chain()` **这个方法不存在**（会 `AttributeError`），正确的是 `event.chain_result()`——但它同样过 respond stage，所以命令里别用。

不 yield 任何东西也安全：`event.send()` 内部会设置 `self._has_send_oper = True`（`astr_message_event.py:600`），而 `process_stage/stage.py:66` 判断是否进 LLM 用的就是这个标志，所以不会触发模型补话。

### 坑 3：工具参数必须写在 docstring 的 `Args:` 段

AstrBot 从 docstring 的 `Args:` 段解析工具参数，不看 Python 类型注解。装饰器的 `desc=` 会被丢弃（`add_func` 用的是 `docstring.description`）：

```python
@filter.llm_tool(name="send_meme")
async def send_meme(self, event, query: str = "", as_sticker: bool = True) -> str:
    """发一张梗图到当前会话，用于接梗、怼人、自嘲、表达情绪。

        Args:
            query(string): 用中文描述想表达的情绪/场景
            as_sticker(boolean): 默认 true 发表情
        """
```

漏了 `Args:` 段，模型看到的就是一个零参数工具（日志会报 `_placeholder: 'no parameters'`），只能随机抽图且不爱调用。

### 检索

2 字滑窗匹配，命中权重 3；近 12 张去重。社区包的分类名和分类描述都拼进被检索的 haystack，所以「嫌他菜」能命中 `teasing` 分类下的图。

### 加载

插件加载后立即在后台建索引，用户永远不用等。

- **首次部署**：拉 3 个图源（梗鲸 1 次 HTTP + 8 个社区包 16 次 GitHub API + ChineseBQB 1 次 tree API），实测 11 秒，在后台跑
- **之后每次重启**：读本地缓存 `data/plugin_data/astrbot_plugin_dafatyu_meme/index_cache.json`，0.1 秒就绪
- **运行中**：全在内存，约 5.4 MB
- **缓存超 24 小时**：后台异步刷新，不阻塞当前请求；刷新失败继续用旧索引

加载失败会置 `_loaded = False`，下次调用重试。

## 安装

```bash
cd AstrBot/data/plugins
git clone <本仓库地址> astrbot_plugin_dafatyu_meme
# 重启 AstrBot
```

无第三方依赖，不需要 `pip install`。

### metadata.yaml

`name` 和 `desc` 都是必需字段（注意是 `desc` 不是 `description`）。缺 `name` 会报「插件元数据校验失败：缺少必需字段: name」，然后 fallback 到默认 metadata，插件页描述不显示。

## 已知限制

- 只能发图片消息或「表情样式图片」，**发不了 QQ 收藏表情本体**（`mface` 段）。收藏表情存在客户端本地库，需要 `emoji_id` + `emoji_package_id` + `key` 三件套，梗鲸和社区包的图都不在任何表情包里。NapCat 本身支持 mface 收发，是 AstrBot 组件层不透传。
- 社区包的图走 `raw.githubusercontent.com`，国内偶尔慢；必要时可换成 jsDelivr（`cdn.jsdelivr.net/gh/<repo>@<ref>/<path>`，实测可用）。
- 社区包的文件名可能带空格和中文（`0106_爱心 1.gif`），必须 `urllib.parse.quote()` 否则 `InvalidURL: URL can't contain control characters`。
- ChineseBQB 是网友贡献集合，**个别分类可能混入不适合的图**（政治、低俗）。发现后从 `BQB_CATEGORY_MAP` 删掉对应前缀，或加黑名单，再清缓存重建。
- 模型只在被唤醒时思考。群聊里没 @ 她就不会跑，所以「群里自己冒出来发图」这种能力不在插件范围内。

## 许可证

插件代码 MIT。图片版权归各来源作者所有，见上文各包 LICENSE。
