# 全局规则层（astrbot_plugin_global_rules）

把**跨人格通用**的行为准则注入每一次 LLM 请求，弥补 AstrBot 单层人格模型的空缺。

## 为什么需要

AstrBot 的人格模型是单层的：一个会话绑定一个人格，人格提示词通过 `persona.py` 追加进 `system_prompt`。

```
conversations.persona_id → 选定人格 → req.system_prompt += "<persona_instructions>..."
```

没有「基础人格 + 角色人格」的继承概念。如果你有 5 个人格，想让它们都遵守“不要乱改 GitHub 仓库”“不要每句话都搜索”，就得在 5 份人格里各写一遍——改一次要改五处，还容易漏。

本插件在 `on_llm_request` 里追加一段独立规则块，**所有人格自动继承**。

## 工作原理

钩子时序（AstrBot 4.29.4）：

```
astr_main_agent/builder.py:99   await persona.apply_persona(...)   # 人格写入 system_prompt
astr_main_agent/builder.py:175  await call_event_hook(OnLLMRequestEvent)   # ← 本插件
```

因为在内置人格注入**之后**触发，规则会排在人格提示词后面。逻辑上就是「人格是角色，规则是底线」，冲突时规则优先。

带 `[全局规则]` 标记做幂等：同一请求重复触发不会叠加。

## 配置

| 键 | 值 | 说明 |
|---|---|---|
| `enabled` | bool | 总开关 |
| `scope` | `all` / `group` / `private` | 生效范围 |
| `rules` | text | 规则全文，留空用内置默认 |

`scope` 的用处：只服务群聊的人格不必背负私聊规则，反之亦然。

## 内置默认规则覆盖什么

- **工具使用**：按需调用，搜索额度有限只搜实时信息，写操作先确认
- **话题边界**：不编造事实与引用，未经证实的消息不传
- **表达**：不假装做过没做的事，演戏不牺牲准确性

## 与人格的关系

| 位置 | 内容 | 作用 |
|---|---|---|
| 人格提示词 | 大肥鱼是谁、什么性格、怎么说话 | 角色 |
| 全局规则 | 什么不能做、什么时候该停 | 底线 |

两者不重复：人格写「我是谁」，规则写「我不能做什么」。所以人格里不需要再重复工具纪律或话题回避。

## 局限

- 规则是**软约束**，靠模型自觉遵守，不是硬拦截
- 想硬拦截（比如政治话题直接不回）需要另写消息层过滤器，本插件不做
- 模型上下文有限，规则太长会挤占空间，建议控制在 500 字以内

## 安装

```bash
cp -r astrbot_plugin_global_rules /path/to/AstrBot/data/plugins/
systemctl restart astrbot
```

日志出现 `[global_rules] 已启用，作用域=all，规则 XXX 字` 即生效。
