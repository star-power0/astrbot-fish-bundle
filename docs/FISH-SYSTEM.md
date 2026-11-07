# 养鱼系统现状 · 2026-11-07

丞相的 QQ 养鱼栈完整说明。改任何东西之前先看这份。

---

## 一、架构

```
QQ 群 / 私聊
    ↓
NapCat（LinuxQQ 注入，OneBot 11 协议端）
    ↓ 反向 WebSocket 127.0.0.1:6199
AstrBot 4.29.4（fish 系统用户）
    ↓
自家 sub2api 中转（域名见私密备忘，模型 deepseek-v4.1-flash）
```

**位置**：全部在 VPS `/opt/fish/`
**后台**：后台域名（见私密备忘，用户 astrbot）
**systemd**：`astrbot.service` + `fish-napcat.service`
**插件归档**：本仓库（GitHub 开源归档，2026-11-07 公开）

---

## 二、插件总览（6 个启用中）

| 插件 | 版本 | 作用 |
|---|---|---|
| `astrbot_plugin_persona_state` | 2.0.0 | **私聊伴侣状态+生活系统**（自研，详见第四节） |
| `astrbot_plugin_dafatyu_meme` | 1.2.0 | 梗图 9210 张（梗鲸+8 社区包+ChineseBQB），`/梗图` + `send_meme` 工具，对外暴露 `pick_image()` 公共契约 |
| `astrbot_plugin_history_cleaner` | 1.0.0 | Markdown 三处清洗（发送+send 出口+存库） |
| `astrbot_plugin_wake_window` | 1.0.0 | 群聊免 @ 时间窗（40 秒，命令仅群聊） |
| `astrbot_plugin_shoubanhua` | 2.9.5 | 生图（OpenAI Images 兼容，接自建网关 gpt-image-2）；`#文生图` 等命令；**群黑名单禁用，仅私聊** |
| `astrbot_plugin_global_rules` | 1.0.0 | 跨人格规则层，**支持人格豁免**（exclude_personas） |

记忆：**LivingMemory 2.9.1**（插件市场装，不收录本仓库）——向量(bge-m3)+BM25 混合检索。
已停用/删除：memora_connect（被 LivingMemory 取代，仓库移入 deprecated/）、qq_plaintext、markdown_killer。

---

## 三、人格系统（核心概念，先读这节）

### 3.1 三个会话、三套人格

| 会话 | 人格 | 说明 |
|---|---|---|
| 群聊 | `大肥鱼`（1038 字） | 活泼群友，吃 global_rules 约束 |
| 私聊 | `林娟` | 私聊伴侣人格（设定细节不公开），**豁免全局规则** |
| 兜底 | `default`（243 字） | 中性群友腔，禁 send_meme |

绑定**没有聊天命令**（4.29.4 无 /persona），改 `data_v4.db` 的 `conversations` 表：**`user_id` 列是会话键**（如 `大肥鱼:FriendMessage:QQ号`），`inner_conversation_id` 是数字 id，`conversation_id` 是 uuid——别搞混。

### 3.2 主链人格解析链路（排查必读）

`apply_persona` 读 `req.conversation.persona_id` → `persona_manager.resolve_selected_persona`，优先级：

1. preferences 表（sp，scope=umo，key=`session_service_config`）强制人格（`[%None]`=显式禁用）
2. conversations.persona_id
3. 全局默认人格

**坑**：`personas_v3` 构建时解析失败的行**静默跳过**（只有一行 error 日志）。直接 SQL INSERT 人格要保证字段格式与现有人格一致（tools=NULL 而不是字符串 "null"）。

### 3.3 人设遵循问题（最重要的经验）

**deepseek-v4.1-flash（推理模型）对 system prompt 遵循极差**。症状：人设组装正确（钩子日志可证），模型却自称 AI 助手。群聊之所以正常，是几百轮历史撑的，不是 system 起作用。

**正解：begin_dialogs 历史化人设**。personas 表 `begin_dialogs` 字段（JSON 数组，偶数条 user/assistant 交替），AstrBot 每轮注入 `req.contexts[:0]`，永不被滚动截断。把 system 人设的核心「翻译成历史对话」——模型对历史的遵循远强于 system。

**写法原则（丞相定稿）**：
- 只放**身份事实**（名字/学校/关系），别放剧情态度——剧情钉子会把角色锁死在开场状态
- 用「展示」不用「告知」：性格通过她的说话方式呈现，不是声明
- 当前会话 6 轮展示式开场（内容结构不公开，属私密人设）

**加人设 SOP**：加「发生过的事」不加「要求」——性格=system 写一句+聊天里演一次；事实=聊天里说让 LivingMemory 存；禁令=system 严禁+首次违规当场纠正；出戏=/reset（begin_dialogs 自动重建骨架，进度/记忆无损）。

### 3.4 私聊伴侣人格（设定不公开）

具体人设、剧情与称呼属私密内容，不在本仓库公开。可复用的技术要点：
- 关系阶段挂好感档（四档阈值驱动），不跳档
- 称呼由配置（user_name）驱动
- 亲密许可为常驻人格级行，mild/explicit 两级，注入文案由本机配置提供（仓库不含真实文案）

### 3.5 沉浸式人格红线

**严禁**在人设/system 注入「承认是 AI」「不编造」这类条款——丞相明令禁止（出戏）。global_rules 用 `exclude_personas` 豁免林娟。给沉浸式人格加规则只能写进她自己的人设。

---

## 四、persona_state v2.1（私聊伴侣引擎）

架构：`state.py`（纯状态）/ `jobs.py`（纯任务逻辑）/ `llm.py`（provider 封装）/ `main.py`（接线）。本地单测 53 项 + VPS 端到端。

### 4.1 功能

| 类别 | 内容 |
|---|---|
| 状态引擎（0 token） | 心情（关键词打分+半衰期）、想念（随分开时长增长）、精力（每轮消耗）、睡眠作息（8-23 点，被吵醒有起床气+睡眠债） |
| 生活（LLM 后台） | 每日节目单（每天首次互动生成）、日记+梦（每晚，自动提取纪念日）、主动消息（候选评分→频控→发送） |
| 亲密 | 常驻许可（explicit）+尺度随好感档联动，**不分时段** |
| 关系 | 好感 0-100 四档（bond_init=35 起步）、生日/纪念日、`set_anniversary` LLM 工具（对话中默默登记） |

### 4.2 关键配置（`data/config/astrbot_plugin_persona_state_config.json`）

**这个文件带 UTF-8 BOM，脚本读写必须 `encoding="utf-8-sig"`**，改完必须重启并复查（AstrBot 重启时会按 schema 回写）。

网页搜索已启用（cmd_config provider_settings：`web_search=true` + `websearch_provider=tavily` + 完整 key）——林娟遇实时信息先搜后答，回复里绝不提搜索痕迹。

终态：bond_init=35 · user_name=(已配置) · nsfw_mode=(已配置) · apply_personas=林娟 · sticker_enabled=true · 作息 8-23 · 主动每日 3 条/间隔 2h/免打扰 01:00-08:00 · token 软限额 20 万/天。

### 4.3 节目单是活的

消息命中约会类表达（`jobs.PLAN_RE`）触发当日节目单重排（≤3 次/天，0 token 触发）；生成时参考**昨天+今天**两天对话（昨晚的约定今天生效）。

---

### 4.5 生图（手办工坊 Pro）

- 接口：`openai_image`（/v1/images/generations），base_url 指向自建网关，模型 `gpt-image-2`
- 分组 142「少限制」在用；分组 140（luluai 上游）被 Cloudflare 1010 拦，不可用
- `group_blacklist` 禁了真人群 —— 生图仅私聊可用
- 配置文件：`data/config/astrbot_plugin_shoubanhua_config.json`（插件自带体系，不走 AstrBot provider）

## 五、命令体系（三层模型，已固化）

每个能力两个属性：**会话类型 × 触发来源**。以后加东西按矩阵归类，照抄模板。

### 5.1 会话类型 = AstrBot 原生声明式装饰器（别手写 gate！）

```python
@filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)  # 仅私聊
@filter.command("xxx")
```

群聊用 `GROUP_MESSAGE`，全场景不加。手写 `is_private_chat` gate 已全部移除——**声明式是框架层拦截，忘写检查这种 bug 从根上不存在**。

### 5.2 触发来源

| 来源 | 机制 | 例子 |
|---|---|---|
| 手动斜杠 | 上帝视角能力，绝不能被对话触发 | 伴侣状态/她的日记/设置生日/主动开关 |
| LLM 工具 | 剧情内合理，她自主调用，用户不可见 | send_meme、set_anniversary |
| 纯自动 | 后台引擎，无触发概念 | 心情/好感/节目单/日记撰写/主动消息 |

**llm_tool 坑**：参数类型必须写进 docstring `Args:` 段且 `name (str): desc` 格式，裸中文描述→「缺少类型注释」→整个插件加载失败。

### 5.3 当前命令

私聊专属：`/伴侣状态`（emoji 面板）`/刷新日程` `/她的日记` `/设置生日` `/设置纪念日` `/主动开关` `/主动测试`；另有 `#` 前缀生图命令（手办工坊，如 `#文生图 <描述>`）
群聊专属：`/时间窗` `/时间窗关闭`（40 秒）
全场景：`/梗图`
斜杠命令不进 LLM 历史、不进记忆缓冲、不占反思轮数（CommandFilter 拦截，不触发 LLM）。

---

## 六、架构规则（评审后固化，改架构前必读）

1. **钩子层协作是默认耦合方式**：LivingMemory/global_rules/persona_state 互不认识，各自往 system_prompt 追加，宿主拼接。拔掉任何一个其余照常。
2. **跨插件依赖全系统只允许一条**：persona_state → dafatyu_meme 的 `pick_image()` 公共契约（docstring 注明内部重构不得破坏）+ `sticker_enabled` 开关 + 启动依赖自检日志。**不许再加第二条摸私有方法的线**。
3. **数据隔离**：各管各的 plugin_data 目录。
4. **插件增减不影响系统**：新插件用钩子层接入即可；删插件不影响其余（persona_state 的跨插件调用有开关+静默降级）。
5. **人格隔离**：apply_personas 白名单——状态系统只跑白名单人格的私聊；别人加 bot 私聊零影响。LivingMemory 会话隔离（use_session_filtering=true）同理不可关。
6. **敏感信息不入库**：key/IP/token/QQ 号不进本仓库（文档里一律脱敏）。

---

## 七、记忆系统（LivingMemory 2.9.1）

- **10 轮一结算**：缓冲攒满 10 轮真实对话 → LLM 反思总结 → 写入向量库。reset 丢的是未结算部分；已结算记忆、好感、人设骨架全保留。
- **会话隔离**：记忆归属 session_id+persona_id。**私聊里 /lmem search 搜不到群聊记忆**（设计如此）——跨会话查询去对应会话里搜，或将来给 search 打 --all patch。
- 想让她记住某件事：聊天里说「记住：…」（memorize 工具，单条直写），别指望自然凑 10 轮。
- 嵌入：BAAI/bge-m3（自家中转 relay-embedding），**`embedding_dimensions_mode: never`**（bge-m3 不接受 dimensions 参数，发了 400）——当初「初始化成功但全部调用失败」的教训：初始化日志不等于调用成功。

---

## 八、坑清单（历史踩坑，新会话必读）

### 8.1 AstrBot 本体

1. **wake_prefix 空串**才让插件接管；AstrBot 不再自动剥 `/`，wake_window 在 waking_check 预剥
2. **Markdown 双副本**：resp.completion_text（发送）与 run_context.messages[-1]（存库）要都洗，ThinkPart 不能碰
3. **自定义消息段被 respond stage 静默丢弃**（type 精确匹配）——用 `await event.send(MessageChain(...))` 直连
4. **QQ 表情 vs 图片**：StickerSegment 自定义段透传；mface 发不了
5. **插件配置文件带 BOM**：读写用 `utf-8-sig`；AstrBot 重启会按 schema 回写，改完必须重启+复查
6. **WebUI 密码字段截断坑**：配置页 password 输入框显示掩码，页面一旦保存，掩码（如 `tvly-dev` 8 个字符）会被当真值写回 cmd_config.json——完整的 API key 就这么坏的。**修复 = 从 `cmd_config.json.bak_*` 备份提取原值写回**；改 cmd_config 前先扫备份找原始值
6. **`__init__(self, context, config=None)`** 才有 config；Plain/Image 从 `astrbot.api.message_components` 导入；多文件插件 `from .x` 失败要 fallback `from x`
7. **`/persona` 等人格命令不存在**（4.29.4 内置命令只有 help/sid/name/reset/stop/new/stats/provider/set/unset）；人格绑定改 conversations 表
8. `text_chat` 无 max_tokens 参数（走 kwargs）；后台 LLM 用 `await context.get_using_provider_async(umo)`
9. 拦消息要 `set_result(MessageEventResult())` + `stop_event()` 双管齐下

### 8.2 模型侧

10. **deepseek-v4.1-flash system 遵循差** → begin_dialogs 历史化（见 3.3）
11. bge-m3 拒绝 dimensions 参数 → `embedding_dimensions_mode: never`
12. 推理模型 think 是英文不代表人格丢失；判断人格是否生效要看请求组装日志（钩子里打印 `<persona_instructions>` 存在性）

### 8.3 已证伪的假设（别再走弯路）

- 「工具续答丢 system prompt」→ 证伪：关掉工具单轮直出照样翻脸，根因是 10
- 「历史污染是主因」→ 部分对：/reset 有效但根因还是 10，begin_dialogs 才是治本
- 「AstrBot 日志说人格加载成功 = 注入成功」→ 证伪：注入要以钩子层实测为准

---

## 九、运维速查

```bash
systemctl status astrbot fish-napcat          # 服务
journalctl -u astrbot.service -f              # 日志
journalctl -u astrbot.service --since '30 min ago' | grep -iE 'error|traceback'
systemctl restart astrbot.service             # 改配置后重启
# 数据库：没装 sqlite3 CLI，用 python -c + sqlite3
# NapCat WebUI：http://<VPS_IP>:6099/webui/（token 见私密备忘）
```

数据库速查：
```python
# 人格与绑定
sqlite3.connect('/opt/fish/AstrBot/data/data_v4.db')
#   personas: persona_id / system_prompt / begin_dialogs / tools
#   conversations: user_id 列=会话键 / persona_id
# 记忆
#   plugin_data/astrbot_plugin_livingmemory/{livingmemory,conversations}.db
```

---

## 十、已知限制与待办

- [ ] LivingMemory recall 工具续答行为未深究（memorize 已恢复；recall 恢复后若出戏再关）
- [ ] 林娟会调 send_meme 发「大肥鱼鲸娘」表情——图库与人设违和；方案：global_rules 人格级工具排除（未做）
- [ ] lmem search 无跨会话参数；需要时给第三方源码打 --all patch（记入 bundle）
- [ ] private_companion #555/#409 修复后可评估替换 persona_state（数据不冲突）
- [ ] 换服务器后：ffmpeg + 视频解析
- [ ] 群聊主动回复开关仍关（22 人真人群）
- [ ] 私聊尚未长期实测：观察 3-7 天（日记/纪念日/主动消息质量），稳定后定版
