from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def build_prompt(payload: dict[str, Any]) -> str:
    company = payload.get("company", "未知公司")
    region = payload.get("region", "未指定区域")
    devices = payload.get("devices", [])
    links = payload.get("topology", {}).get("links", [])
    device_names = [device.get("name", "") for device in devices if device.get("name")]
    return (
        "你是运维文档助手，请根据以下网络拓扑 JSON 提供简明摘要。"
        "要求：中文，100-200 字，包含设备概况、链路数量、关键风险提示。\n"
        f"公司：{company}\n"
        f"区域：{region}\n"
        f"设备数量：{len(devices)}\n"
        f"链路数量：{len(links)}\n"
        f"设备名称：{', '.join(device_names)}\n"
        f"拓扑数据：{json.dumps(payload, ensure_ascii=False)}"
    )


def build_request_payload(prompt: str, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是擅长网络运维文档的助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
    }


def generate_ai_summary(
    payload: dict[str, Any],
    endpoint: str = "",
    model: str = "",
) -> str:
    resolved_endpoint = endpoint or os.environ.get("AI_ENDPOINT", "")
    resolved_model = model or os.environ.get("AI_MODEL", "")
    if not resolved_endpoint or not resolved_model:
        return "AI 摘要未生成：缺少 AI_ENDPOINT 或 AI_MODEL 配置。"

    prompt = build_prompt(payload)
    request_payload = build_request_payload(prompt, resolved_model)
    request = Request(
        resolved_endpoint,
        data=json.dumps(request_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except (HTTPError, URLError) as exc:
        return f"AI 摘要未生成：请求失败（{exc}）。"

    try:
        data = json.loads(body)
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        return f"AI 摘要未生成：响应解析失败（{exc}）。"
