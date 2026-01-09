from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def call_ai(
    prompt: str,
    endpoint: str = "",
    model: str = "",
    system_prompt: str = "你是擅长网络运维文档的助手。",
) -> tuple[str | None, str | None]:
    resolved_endpoint = endpoint or os.environ.get("AI_ENDPOINT", "")
    resolved_model = model or os.environ.get("AI_MODEL", "")
    if not resolved_endpoint or not resolved_model:
        return None, "缺少 AI_ENDPOINT 或 AI_MODEL 配置。"

    request_payload = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
    }
    request = Request(
        resolved_endpoint,
        data=json.dumps(request_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except (HTTPError, URLError) as exc:
        return None, f"请求失败（{exc}）。"

    try:
        data: dict[str, Any] = json.loads(body)
        content = data["choices"][0]["message"]["content"].strip()
        return content, None
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        return None, f"响应解析失败（{exc}）。"
