# 对话历史 Markdown 清洗 (astrbot_plugin_history_cleaner)

把 LLM 回复里的 Markdown 剥成纯文本，**发送端和存储端同时清洗**。

QQ 客户端不渲染 Markdown，`**加粗**`、反引号、代码围栏、`# 标题`、`- 列表` 这些会原样显示成一堆符号。

## 为什么需要两个钩子

AstrBot 一轮回复会产生**两份独立的副本**：

| 副本 | 来源 | 用途 |
|---|---|---|
| `resp.completion_text` | `agent_sub_stages/internal.py:336` | **发送**给用户 |
| `run_context.messages[-1]` | `internal.py:308` `_save_to_history()` | **存进数据库**，成为下一轮的「记忆」 |

**只清洗发送端是不够的。** 历史里留着 `**加粗**`，模型下一轮读到就会照着这个格式继续写，形成自我强化 —— 你会发现改人设、加规则都压不住。

本插件两个钩子各管一份：

```python
@filter.on_llm_response()   # 改 completion_text（发送用）
@filter.on_agent_done()     # 改 run_context.messages[-1]（存库用）
```

`on_agent_done` 的时机恰好卡在 `tool_loop_agent_runner.py:201` 的 append 之后、落库之前。

## 清洗规则

| 输入 | 输出 |
|---|---|
| `**粗体**` / `__粗体__` | 粗体 |
| `` `代码` `` | 代码 |
| ```` ```python ... ``` ```` | 去掉围栏，保留内容 |
| `# 标题` | 标题 |
| `- 列表` / `* 列表` | 列表（去符号） |
| `> 引用` | 引用 |
| `~~删除线~~` | 删除线 |
| `[文字](url)` | 文字 |
| `![图](url)` | 图 |

## 安全边界

**只处理 `role == "assistant"` 的消息，且只处理 `TextPart`。**

```python
if getattr(part, "type", None) != "text":
    continue        # ThinkPart（type="think"）不碰
```

- **模型的思考过程（ThinkPart）不动** —— 里面带 `**` 是正常的，改了会破坏推理
- **用户发的消息不动** —— 群友说 `**真的假的**` 原样保留

## 测试

```
SENT   -> '重点：看 main.py:42\n第一\n第二\ncode()'    ✅ 发出去的
STORED -> '重点：看 main.py:42\n第一\n第二\ncode()'    ✅ 存进库的
THINK  -> 'use **bold**' (unchanged)                  ✅ 思考内容不动
USER   -> unchanged OK                                ✅ 用户消息不动
```

## 和流式输出的关系

两个钩子在流式和非流式下都能工作，**不需要关闭流式**。

参考：之前用社区的 `markdown_killer`（只改 `completion_text`）时，历史一直是脏的，才写了这个插件补齐另一半。

## 许可证

MIT
