# 大肥鱼 AstrBot 插件集

跑在 AstrBot 4.29.4 上的 QQ 机器人插件集合。解决四件事：发梗图、把 Markdown 洗成 QQ 能看的纯文本、群聊里被 @ 之后一段时间内免 @ 继续聊天、给所有人格加一层通用行为规则。

## 插件

| 插件 | 版本 | 状态 | 来源 | 作用 |
|---|---|---|---|---|
| [`astrbot_plugin_persona_state`](plugins/astrbot_plugin_persona_state) | 2.0.0 | 启用 | 自研 | 私聊伴侣状态+生活：心情/精力/睡眠/节目单/日记梦/好感纪念日/主动消息/亲密许可，0 token 打分 |
| [`astrbot_plugin_dafatyu_meme`](plugins/astrbot_plugin_dafatyu_meme) | 1.2.0 | 启用 | 自研 | 9210 张梗图（梗鲸 12 分类 + 8 个社区包 + ChineseBQB），`/梗图` 命令 + `send_meme` 工具，均衡抽样 |
| [`astrbot_plugin_global_rules`](plugins/astrbot_plugin_global_rules) | 1.0.0 | 启用 | 自研 | `on_llm_request` 注入跨人格规则层；按人格剔除工具（默认对 `default` 禁 `send_meme`） |
| [`astrbot_plugin_history_cleaner`](plugins/astrbot_plugin_history_cleaner) | 1.0.0 | 启用 | 自研 | 三处 Markdown 清洗：发送端、`send()` 出口（覆盖流式分片）、存库端 |
| [`astrbot_plugin_wake_window`](plugins/astrbot_plugin_wake_window) | 1.0.0 | 启用 | 自研 | 被 @ 后 N 秒内同群免 @，滑动续期，按群独立，命令可调时长 |
| [`astrbot_plugin_memora_connect`](plugins/astrbot_plugin_memora_connect) | v0.5.4 | 已停用 | 第三方 [qa296](https://github.com/qa296/astrbot_plugin_memora_connect) | 长期记忆（知识图谱，无向量）。已被 LivingMemory 取代，代码留档 |
| [`astrbot_plugin_qq_plaintext`](deprecated/astrbot_plugin_qq_plaintext) | 1.0.0 | 已停用 | 自研 | 初版 Markdown 清洗，只改发送端，已被 history_cleaner 取代 |
| [`astrbot_plugin_markdown_killer`](deprecated/astrbot_plugin_markdown_killer) | 0.0.7 | 已停用 | 第三方 [AlanBacker](https://github.com/AlanBacker/astrbot_plugin_markdown_killer) | 社区 Markdown 清洗，覆盖不到存库端，已被 history_cleaner 取代 |

记忆系统现用 **LivingMemory 2.9.1**（插件市场安装，向量召回 + BM25 混合检索），不收录在本仓库。

`astrbot_plugin_memora_connect` 以代码快照方式收录（上游未附许可证，仅作个人部署归档），来源与版本见 [VENDORED.md](plugins/astrbot_plugin_memora_connect/VENDORED.md)。

## 安装

```bash
git clone https://github.com/star-power0/astrbot-fish-bundle.git
cp -r astrbot-fish-bundle/plugins/astrbot_plugin_* /path/to/AstrBot/data/plugins/
systemctl restart astrbot
```

`deprecated/` 目录只做归档，**不要部署**（会和 history_cleaner 重复清洗）。

## 前置条件

`astrbot_plugin_wake_window` 要求 `data/cmd_config.json` 里：

```json
"wake_prefix": [""]
```

空字符串让所有群消息通过 AstrBot 的唤醒检查、进入插件层，再由时间窗决定放不放行。若保持默认的 `"/"`，没带唤醒词的消息根本到不了插件，时间窗不会生效。

副作用：`wake_prefix` 留空后 AstrBot 不再自动剥掉命令前的 `/`，本插件在 `waking_check` 阶段做了预处理，所以 `/时间窗`、`/记忆`、`/梗图` 仍然可用。

## 目录结构

```
plugins/                 插件源码（4 个自研启用中 + 1 个第三方留档）
deprecated/              历史版本，仅归档
configs/                 运行配置快照（脱敏，无凭据）
docs/FISH-SYSTEM.md      完整系统说明：架构、配置、坑、备忘、运维
CHANGELOG.md             版本与修复记录
```

## 兼容性

- AstrBot 4.29.4（2026-11 实测）
- Python 3.10+
- OneBot 11 协议端：NapCat 4.18.42

## 许可

MIT
