# 群聊免@时间窗 (astrbot_plugin_wake_window)

被 **@** 之后的一段时间内（默认 **30 秒**），同一群里继续说话不用再 @。超时自动收回，恢复成必须 @ 的状态。

## 效果

```
你 @她         → 开窗，她回复
你继续说        → 窗内，她回复，且计时重置（滑动窗口）
继续聊          → 一直续命
停 30 秒        → 窗口关闭
再说一句        → 不理（回到必须 @）
```

**滑动窗口**：不是「@ 之后固定 30 秒」，而是「每说一句重新计时」。连续聊 10 分钟都不用重复 @，只要不中断超过 30 秒。

**按群独立**：A 群 @ 过后，B 群不会跟着免 @。私聊完全不受影响。

## 命令

| 命令 | 作用 |
|---|---|
| `/时间窗` | 查看当前秒数和本群剩余时间 |
| `/时间窗 60` | 改成 60 秒并写入配置（支持任意正整数） |
| `/时间窗关闭` | 立刻收回本群的窗口 |

## 配置

WebUI 插件配置里可调 `window_seconds`，默认 `30`。

也可以在聊天里用 `/时间窗 <秒数>` 直接改，会持久化到配置文件。

## 前置条件（必须）

**`cmd_config.json` 里的 `wake_prefix` 必须是 `[""]`。**

原因：AstrBot 的 `waking_check` 阶段在插件之前执行，没被唤醒的消息根本到不了插件层。空字符串的 `startswith` 恒为 `True`，所以所有消息都能通过唤醒检查进入插件，再由本插件决定「回」还是「拦」。

```json
{
  "wake_prefix": [""]
}
```

配错了插件启动时会打 WARN：

```
[wake_window] wake_prefix 不是 [""]（当前 ['/']），时间窗不会生效。
```

## 空消息兜底（插件自动装）

AstrBot 的 aiocqhttp 适配器会把**表情包（mface）消息段整个丢掉**：

```python
# aiocqhttp_platform_adapter.py
elif t == "mface":
    continue
```

所以一条纯表情包消息解析完是「**零个组件 + 空字符串**」。`wake_prefix` 为空串时，
`waking_check/stage.py:121` 会走进 `startswith("")` 分支，然后 `messages[0]` 直接：

```
IndexError: list index out of range
Pipeline task failed.
```

本插件在加载时给 `WakingCheckStage.process` 包一层（**运行时接管，不改 AstrBot 源码**）：

```python
async def guarded_process(self, event):
    if not event.get_messages():
        event.set_result(MessageEventResult())
        event.stop_event()
        return
    return await original(self, event)
```

纯表情包消息被安静丢弃，不崩溃、不回复。**AstrBot 升级后插件重新加载会自动重装，不用管。**

## 工作原理

```
群消息到达
    ↓
waking_check（wake_prefix=[""] 让全部通过）
    ↓
本插件 gate()
    ├── 私聊？              → 直接放行
    ├── @ 了机器人？        → 记录时间戳，放行
    ├── 在时间窗内？        → 刷新时间戳，放行
    └── 窗外               → event.stop_event() 拦掉
```

被拦掉的消息**不产生回复、不烧 token**。

状态存在内存 dict 里（`{group_id: 最后唤醒时间}`），**重启后清空** —— 重启后需要重新 @ 一次。

## 测试

内部单测覆盖 10 个场景，全部通过：

```
1. @她        -> 放行
2. 窗内不@     -> 放行
3. 再一条      -> 放行（滑动续命）
4. 超时后      -> 拦截
5. A群@过后B群 -> 拦截（群隔离）
6. A群继续     -> 放行
7. 私聊不@     -> 放行（私聊豁免）
8. /时间窗 60  -> 改为 60 秒
9. /时间窗关闭  -> 立刻收回
10. 关掉后     -> 拦截
```

## 已知限制

- 状态不持久化，重启后时间窗归零
- 只对群聊生效；私聊本来就不需要 @
- 需要配合 `wake_prefix=[""]`，这会让所有群消息都进入插件层（但被拦掉的不消耗资源）

## 许可证

MIT
