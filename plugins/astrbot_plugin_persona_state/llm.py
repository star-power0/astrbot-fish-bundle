"""Thin wrapper for background LLM calls (plan / diary / proactive).

Resolves the provider once per call: task_provider_id from config, else the
session's current provider. All failures raise — callers decide fallback.
"""

import json


async def call_llm(context, prompt, cfg=None, umo=None):
    """Run one background text task. Returns the reply text (str).

    Raises RuntimeError when no provider is available or the call fails.
    """
    cfg = cfg or {}
    provider = None
    task_id = str(cfg.get("task_provider_id") or "").strip()
    if task_id:
        try:
            provider = context.get_provider_by_id(task_id)
        except Exception:
            provider = None
    if provider is None:
        getter = getattr(context, "get_using_provider_async", None)
        if getter is not None:
            provider = await getter(umo)
        else:
            provider = context.get_using_provider(umo)
    if provider is None:
        raise RuntimeError("没有可用的文本 Provider")

    result = await provider.text_chat(
        prompt=prompt,
        session_id=None,
        system_prompt="你是角色扮演辅助器：只输出被要求的格式，不解释。",
    )
    text = getattr(result, "completion_text", None) or str(result)
    return text


def estimate_tokens(text):
    """Rough cost estimate for the daily soft limit (~4 chars/token CJK)."""
    return max(1, len(str(text or "")) // 4)


def extract_json(text):
    """Best-effort first {...} JSON blob; raises ValueError when absent."""
    import re

    m = re.search(r"\{.*\}", str(text or ""), re.S)
    if not m:
        raise ValueError("no json in reply")
    return json.loads(m.group(0))
