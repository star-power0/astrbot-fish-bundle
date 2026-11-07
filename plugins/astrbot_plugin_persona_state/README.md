# persona_state (astrbot_plugin_persona_state)

给**私聊**伴侣人格一套「她有自己的生活」的状态系统：心情、精力、睡眠、每日节目单、日记与梦、好感与纪念日、主动找你、亲密常驻许可。群聊一行代码都不碰。

对标 [astrbot_plugin_private_companion](https://github.com/menglimi/astrbot_plugin_private_companion) 的核心体验，但只做轻量实现（~1000 行、零依赖、无 WebUI），配置全在 AstrBot 插件配置页。

## 注入效果

每次私聊触发模型前，在系统提示末尾追加（≤240 字）：

```
# 此刻状态（只影响语气与生活感，不改事实与边界）
心情：有点心动，可以自然地黏一点；有点想你
睡眠：有点犯困，话更短更软
精力：有点累，话说短点
距你上一条消息 2 小时
她现在：刷短视频，还想把好笑的发给你
关系：好感 62（亲密档）
亲密：（由配置注入的许可文本，文案不公开）
```

## 模块一览

| 模块 | 机制 | 成本 |
|---|---|---|
| 心情 | 关键词打分（开心/心动），半衰期回落；道歉消气 | 0 token |
| 想念 | 随分开时长自动增长，回来缓解不归零 | 0 token |
| 精力 | 每轮 −3% 起、同段越说越贵；熬夜欠觉压精力上限 | 0 token |
| 睡眠 | 起床/睡觉时间（可配）；深夜被吵醒有起床气+睡眠债，整夜安静自动还清 | 0 token |
| 节目单 | 每天首次互动时 LLM 生成 5-8 项当日安排，注入「她现在：XXX」 | 1 次/天 |
| 日记+梦 | 每晚汇总当天对话，她的口吻写日记（≤120 字）+ 心情 + 1/4 概率做梦；`/她的日记` 查看 | 1 次/天 |
| 好感 | 0-100 分四档（认识/熟络/亲密/恋人），每日 +6 封顶，冷落超 24h 缓慢掉 | 0 token |
| 纪念日 | 生日/在一起的日子手动设；日记任务自动提取「第一次…」 | 随日记 |
| 主动消息 | 候选（久未联系/节目单想分享/话头没接完/深夜提醒）→ 频控（免打扰 01:00-08:00、每日上限 3、间隔 2h、睡觉不发）→ LLM 生成 → 发送 | ≤3 次/天 |
| 亲密许可 | **常驻人格级**（不分时段），mild/explicit 两级分档；注入文案由本机配置提供，仓库不含真实文案 | 0 token |

## 命令

- `/伴侣状态` — 查看全部数值
- `/刷新日程` — 重新生成她今天的节目单
- `/她的日记` — 看最近一篇日记（含梦）
- `/设置生日 06-01`、`/设置纪念日 在一起 2026-11-06`
- `/主动开关 on|off`、`/主动测试` — 主动消息控制

## 配置要点

- `persona_brief`：一句话角色简介（供节目单/日记参考），详细人设在 AstrBot 人格里
- `nsfw_mode`：`off` / `mild` / `explicit`；`nsfw_prompt` 填你自己的偏好文本（explicit 时原样注入）
- `task_provider_id`：后台任务用哪个模型，留空跟随会话当前模型
- `daily_task_token_limit`：后台任务每日 token 软限额（默认 20 万，超出停生成）

## 机制来源

- [dsh-identity](https://github.com/Anarrogantcat/dsh-identity) moodv2/pace：0 token 打分、半衰期、只注入语气
- [emotion-system](https://github.com/bvsden/emotion-system)：思念随时长增长
- [private_companion](https://github.com/menglimi/astrbot_plugin_private_companion)：节目单/日记/主动消息的功能模型（自研轻量实现）

## 已知边界

- 关键词打分读不懂反讽和长句（0 token 的代价）
- 主动消息只会发文本（表情包/语音后续再说）
- 时钟按北京时间（UTC+8）
- 数据全部本地 JSON：`data/plugin_data/astrbot_plugin_persona_state/`
