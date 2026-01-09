from __future__ import annotations

import os
from dataclasses import dataclass

import requests

from iotmd.collectors import DeviceSnapshot


@dataclass(frozen=True)
class AiSummary:
    device_name: str
    summary: str


def summarize_device(
    snapshot: DeviceSnapshot,
    api_base: str,
    model: str,
    enabled: bool,
) -> AiSummary:
    if not enabled:
        return AiSummary(device_name=snapshot.name, summary=_fallback_summary(snapshot))

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return AiSummary(device_name=snapshot.name, summary=_fallback_summary(snapshot))

    response = requests.post(
        f"{api_base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是网络运维文档助手，请用简洁中文总结设备角色。",
                },
                {
                    "role": "user",
                    "content": _build_prompt(snapshot),
                },
            ],
            "temperature": 0.2,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"].strip()
    return AiSummary(device_name=snapshot.name, summary=content)


def _fallback_summary(snapshot: DeviceSnapshot) -> str:
    return (
        f"设备 {snapshot.name} ({snapshot.vendor}) 已采集配置与接口信息。"
        " 如果需要更完整的描述，请启用 AI 总结。"
    )


def _build_prompt(snapshot: DeviceSnapshot) -> str:
    return (
        "请根据以下信息，生成一段用于运维文档的设备摘要：\n"
        f"设备名称: {snapshot.name}\n"
        f"厂商: {snapshot.vendor}\n"
        "接口概览: \n"
        f"{snapshot.interfaces}\n"
        "配置片段: \n"
        f"{snapshot.config[:2000]}\n"
    )
