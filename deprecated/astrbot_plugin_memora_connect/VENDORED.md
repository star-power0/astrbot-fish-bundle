# Vendored snapshot

- Upstream: https://github.com/qa296/astrbot_plugin_memora_connect
- Version: v0.5.4
- Author: qa296
- Vendored: 2026-11-05
- License: upstream 未附许可证（仓库 license 为 null）。此处仅作个人部署快照归档，版权归原作者。

本目录是从 `/opt/fish/AstrBot/data/plugins/astrbot_plugin_memora_connect` 复制的部署版本，已移除 `.git` 与 `__pycache__`。升级请以上游仓库为准。

## Local patch

`core/memory_system.py::get_llm_provider` 增加了四级回退：精确 ID → 名称匹配 → 当前/默认对话模型 → 第一个可用聊天提供商。
原因：上游只认精确 provider ID，AstrBot 换模型后 ID 变化会让记忆形成静默停摆。
配置 `llm_provider` 留空即自动跟随当前对话模型。上游升级会覆盖此补丁，升级后需重新应用。
