from __future__ import annotations

import json
from typing import Any

from ai_client import call_ai


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


def generate_ai_summary(
    payload: dict[str, Any],
    endpoint: str = "",
    model: str = "",
) -> str:
    prompt = build_prompt(payload)
    response, error = call_ai(
        prompt,
        endpoint=endpoint,
        model=model,
        system_prompt="你是擅长网络运维文档的助手。",
    )
    if error:
        return f"AI 摘要未生成：{error}"
    return response or "AI 摘要未生成：未返回内容。"
