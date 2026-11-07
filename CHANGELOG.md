# Changelog

## [1.4.0] - 2026-11-07

### Added
- fish_voice v1.0.0 自研极简语音：`/语音` 命令 + `send_voice` 工具（LLM 在合适时机自主开口，如被要求听声音、道晚安、安慰），MiMo TTS voicedesign 音色驱动（音色描述走本机配置），wav→silk 复用 AstrBot 内置 pysilk 编码，NapCat 直发免 ffmpeg，仅私聊

## [1.3.0] - 2026-11-07

### Added
- fish_draw v1.0.0 自研极简生图：`/生图` 命令 + `generate_image` 工具（聊天中自主生图，LLM 先翻译意图为画面描述），OpenAI Images 兼容 API 接自建网关（gpt-image-2，分组 142），仅私聊；替代曾短暂上线的第三方手办工坊 Pro（功能过重已删）
- persona_state 亲密许可文案配置化（nsfw_mild_text / nsfw_explicit_text），真实文案走本机配置，仓库默认中性占位

### Changed
- memora_connect 移入 deprecated/（已被 LivingMemory 取代）；README 记忆行改指 LivingMemory 上游
- FISH-SYSTEM.md 人设细节脱敏为抽象描述（配合开源）；插件总览补生图插件

### Fixed
- wake_prefix 被回写为 [] 导致群聊斜杠命令静默失效（WebUI 保存回写坑，重启日志有 wake_window WARN 可探测）
- WebUI「嵌入」tab 不显示向量模型：provider 条目缺 provider_type 字段（前端 getProviderType 依赖它），补 "embedding"

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的格式。

## [1.2.1] - 2026-11-07

### Added

- **persona_state**：节目单随对话约定重排（PLAN_RE 触发 ≤3 次/天，参考昨天+今天对话）；主动消息可带表情（`<表情:情绪>` 意图 → meme 公共契约选图 → 图先文字后）；`set_anniversary` LLM 工具（对话中自然确立纪念日，默默登记不入戏）；`/伴侣状态` emoji 面板（进度条+白话状态）
### Changed

- **命令体系三层模型固化**：会话类型 = AstrBot 原生声明式装饰器 `@filter.event_message_type(...)`（persona_state 全系仅私聊、wake_window 仅群聊，手写 gate 全删）；触发来源 = 剧情内 LLM 工具 / 上帝视角斜杠 / 纯自动引擎三分类
- global_rules 加 `exclude_personas` 豁免机制；沉浸式人格删除全部出戏条款（承认AI/不编造/钱与见面）
- 人格遵循问题定案：deepseek-v4.1-flash 对 system 遵循极差 → **begin_dialogs 历史化人设**（林娟 6 轮展示式开场：表面陌生学长学妹，秘密只有她藏）；加人设 SOP = 加「发生过的事」不加「要求」
- admins_id 加丞相 QQ；私有仓库敏感信息清理（QQ 号/群号/中转域名脱敏）
- FISH-SYSTEM.md 全面重写（人格系统/命令体系/架构规则/坑清单/已证伪假设）
### Fixed

- bond_init 之前被 AstrBot 回写成 85（恋人档），与「还没在一起」设定冲突 → utf-8-sig 读写+重启复查修复
- persona_state 重构残留（_private_only 死引用、sleep_phase 缺导入）导致 /伴侣状态 报错
- fish-qq 旧平台残留（umo_aliases/umo_senders/provider_stats 三表）清零

## [1.2.0] - 2026-11-06

### Added

- **astrbot_plugin_persona_state 1.0.0**（新增）
  - 私聊伴侣状态注入：开心/心动/想念 + 精力 + 时间流逝，只对私聊生效，群聊不碰
  - 打分纯本地正则（0 token），半衰期衰减；思念不靠关键词、随分开时长自动增长（emotion-system 思路）
  - 工具续答同 message_id 去重，不重复扣精力；注入 ≤160 字（可配）
  - 复合心情：开心低 + 想念高 → 「委屈」
  - 机制来源：dsh-identity moodv2/pace + emotion-system；调研结论：astrbot_plugin_private_companion 功能最全但 #555（AstrBot 4.29.4 WebUI 404）与 #409（与记忆插件 tool_calls 400）未修复，暂不装，修复后可替换本插件

### Added（同日第二次，persona_state v2.0.0）

- **astrbot_plugin_persona_state 2.0.0**：从状态注入升级为「她有自己的生活」
  - 新增：每日节目单（LLM 生成，注入「她现在：XXX」）、日记+梦境（每晚汇总对话，她的口吻）、好感 0-100 四档+纪念日（手动+日记自动提取「第一次…」）、主动消息（候选评分+免打扰/每日上限/最小间隔/睡觉不发）、睡眠作息（起床/睡觉时间、被吵醒起床气、睡眠债）
  - 亲密常驻许可（不分时段）：mild/explicit 两级分档，是否发生由模型按对话情境自然判断；注入文案由本机配置提供，仓库不含真实文案
  - 后台任务走 `task_provider_id`（空=跟随会话模型），每日 token 软限额默认 20 万
  - 架构：state.py（纯状态）/ jobs.py（纯任务逻辑）/ llm.py（Provider 封装）/ main.py（接线）；38 项本地单测 + VPS 端到端（模拟 LLM/发送）全过

## [1.1.0] - 2026-11-06

### Added

- **astrbot_plugin_dafatyu_meme 1.2.0**
  - 图库从 4463 张扩到 9210 张：新增 ChineseBQB 4746 张，覆盖动物、搞笑人物、动画角色、真人梗、情绪五大类
  - 均衡抽样：先随机选分类桶（2688 个）再桶内选图，最近 20 个桶不重复。修掉了「随机抽必然扎堆 DeepSeek 娘」的问题，实测 20 次抽到 20 个不同分类
  - 索引缓存 + 启动预热：插件加载后后台建索引，之后每次重启读本地缓存 0.1 秒就绪，24 小时 TTL 后台异步刷新
  - 日志统一走 `logger`，不再用 `print`
- **astrbot_plugin_global_rules 1.0.0**（新增）
  - `on_llm_request` 注入跨人格规则层，追加在人设提示词之后
  - 工具使用节制（搜索额度有限，常识问题不搜）、不主动操作外部系统、不编造事实
  - `exclude_tools_for_default` 配置项：按人格剔除工具，默认对 `default` 人格禁用 `send_meme`
- **LivingMemory 2.9.1** 替换 memora 作为记忆系统
  - 向量召回（BAAI/bge-m3 1024 维）+ BM25 混合检索 + FTS5
  - `memory_scope_mode: legacy` 保持按会话隔离，`use_persona_filtering: true` 加人格维度
  - 群聊全量捕获进缓冲区，10 轮触发一次总结写入记忆库

### Changed

- 人格重构为两层：`default` 是 243 字的中性兜底人格（非机器人腔），`大肥鱼` 是 1038 字的群聊人格，绑定目标群聊会话
- `personas.tools` 全部置 `NULL`（全工具开放），改用 `global_rules` 插件按人格剔除，避免以后加新工具还要改人格配置
- memora 插件与数据已删除（不留备用）

### Fixed

- 嵌入模型 `无效的嵌入向量维度: 0`：provider source 需要显式 `embedding_dimensions: 1024`
- bge-m3 拒绝 `dimensions` 参数（HTTP 400）：`embedding_dimensions_mode` 必须设 `never`。**之前只看初始化日志就宣称「完全打通」，实际每次嵌入调用都在失败** —— 教训是初始化成功不等于调用成功
- 模型广场分组无法单独隐藏：加 `model_quality_hidden_groups` 设置项，前后端联动

### Known issues

- ChineseBQB 是网友贡献集合，个别分类可能混入不适合的图（政治、低俗），发现后从 `BQB_CATEGORY_MAP` 剔除
- QQ/NapCat 登录态丢失后需手动扫码，掉线时 `send_meme` 无法端到端验证
- LivingMemory 尚未经真实流量验证（0 条记忆）

## [1.0.0] - 2026-11-05

首次归档。以下插件均在 AstrBot 4.29.4 + NapCat 4.18.42 上实测运行。

### Added

- **astrbot_plugin_dafatyu_meme 1.1.0**
  - 图库 4463 张：梗鲸 12 分类 2955 张 + 8 个 AstrBot 社区表情包 1508 张
  - `/梗图 [关键词]` 命令，支持表情 / 大图两种发送模式
  - `send_meme` LLM 工具，`as_sticker` 参数控制发的是表情还是图片
  - 社区包文件名自动 URL 编码，兼容带空格的中文文件名
- **astrbot_plugin_history_cleaner 1.0.0**
  - `on_llm_response`：清洗即将发送的 `resp.completion_text`
  - `on_agent_done`：清洗 `run_context.messages[-1]` 里的 TextPart（ThinkPart 不碰）
  - `send()` 出口 monkey-patch：覆盖流式输出的逐段发送
- **astrbot_plugin_wake_window 1.0.0**
  - 被 @ 后默认 30 秒内同群免 @，滑动窗口续期，按群独立
  - `/时间窗`、`/时间窗 60`、`/时间窗关闭` 命令
  - 纯表情包消息空组件兜底：运行时包装 `WakingCheckStage.process`，不改 AstrBot 源码
  - 唤醒阶段剥离命令前的 `/`，保证 `wake_prefix=""` 时命令仍能命中 handler
- **astrbot_plugin_memora_connect v0.5.4**（第三方，qa296）
  - 长期记忆 + 知识图谱，无向量模式（`recall_mode: simple`）
  - 按群隔离、图谱联想召回、90 天遗忘阈值、最多注入 5 条
  - 代码快照收录，来源与版本见插件目录下 `VENDORED.md`
- **configs/**：`memora_connect` 与 `wake_window` 的运行配置快照
- **docs/FISH-SYSTEM.md**：架构、全部插件、关键配置、四个坑、记忆系统、运维手册
- **astrbot_plugin_qq_plaintext 1.0.0** 归档到 `deprecated/`
- **astrbot_plugin_markdown_killer 0.0.7**（第三方，AlanBacker）归档到 `deprecated/`

### Fixed

- memora 记忆形成停摆：`llm_provider` 用了 schema 默认值 `openai`，AstrBot 里不存在这个 ID，日志报 `无法找到配置的LLM提供商`、`LLM: 未连接`。改为完整 ID `star（ds鲸鱼专用）/deepseek-v4.1-flash` 后恢复。
- memora 换模型会再次失效：给 `get_llm_provider` 加四级回退（精确 ID → 名称 → 当前默认模型 → 第一个可用），并把 `llm_provider` 设为空表示自动跟随。已用 `__bogus_provider__` 实测回退成功。
- 表情包图片发不出去：`respond` stage 用 `type(comp) in dict` 精确匹配组件，自定义段被判为空消息后**静默丢弃**。改走 `await event.send(MessageChain(...))` 直连适配器。
- `send_meme` 工具参数不生效：AstrBot 只从 docstring 的 `Args:` 段解析参数，装饰器里的 `desc=` 会被丢弃。
- Markdown 清洗只生效一半：发送用的 `resp.completion_text` 和存库用的 `run_context.messages` 是两份独立副本，只清一份会导致历史里残留 `**`，模型每轮照学。改为三处同时清洗。
- 拦消息挡不住 LLM：只调 `event.stop_event()` 时 `process_stage` 仍会继续调用模型；必须同时 `event.set_result(MessageEventResult())`。
- 纯表情包（mface）消息触发 `messages[0]` IndexError：适配器把 mface 段整个丢掉，消息零组件；插件侧加空消息兜底。
- `wake_prefix` 改为 `[""]` 后所有 `/命令` 失效：AstrBot 不再自动剥斜杠，`CommandFilter` 匹配不到。在 `waking_check` 包装层提前剥离。
- `/时间窗40` 不生效：命令匹配要求 `命令名 + 空格 + 参数`，必须写 `/时间窗 40`。

### Changed

- 输出切回流式（`streaming_response: true`），`segmented_reply` 关闭；Markdown 清洗改由 `send()` 出口兜住流式分片。
- 图库从 2635 张扩到 4463 张。

### Known issues

- 免 @ 时间窗的计时存在内存里，AstrBot 重启后清零（可接受）。
- 发不了 QQ 收藏表情本体（mface），需要 `emoji_id + emoji_package_id + key` 三件套。
- memora 记忆按群隔离，不含人格维度；同群换人格会共用记忆。
