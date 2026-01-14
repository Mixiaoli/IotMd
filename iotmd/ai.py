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
    api_key: str | None = None,
) -> AiSummary:
    if not enabled:
        return AiSummary(device_name=snapshot.name, summary=_fallback_summary(snapshot))

    resolved_key = _resolve_api_key(api_key)
    if not resolved_key:
        return AiSummary(device_name=snapshot.name, summary=_fallback_summary(snapshot))

    response = requests.post(
        api_base,
        headers={"Authorization": f"Bearer {resolved_key}"},
        json={
            "model": model,
            "input": {
                "messages": [
                    {
                        "role": "system",
                        "content": "你是网络运维文档助手，请用简洁中文总结设备角色。",
                    },
                    {
                        "role": "user",
                        "content": _build_prompt(snapshot),
                    },
                ]
            },
            "parameters": {"temperature": 0.2},
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    output = data.get("output", {})
    content = output.get("text")
    if not content:
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    content = str(content).strip()
    return AiSummary(device_name=snapshot.name, summary=content)


def build_ai_question(
    label: str,
    api_base: str,
    model: str,
    api_key: str | None,
) -> str:
    resolved_key = resolve_api_key(api_key)
    if not resolved_key:
        return label

    response = requests.post(
        api_base,
        headers={"Authorization": f"Bearer {resolved_key}"},
        json={
            "model": model,
            "input": {
                "messages": [
                    {
                        "role": "system",
                        "content": "你是网络运维助手，请把字段转成友好且简洁的问题。",
                    },
                    {
                        "role": "user",
                        "content": f"字段: {label}",
                    },
                ]
            },
            "parameters": {"temperature": 0.2},
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    output = data.get("output", {})
    content = output.get("text")
    if not content:
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    content = str(content).strip()
    return content or label


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


def resolve_api_key(api_key: str | None) -> str | None:
    return api_key or os.environ.get("DASHSCOPE_API_KEY")


def _resolve_api_key(api_key: str | None) -> str | None:
    return resolve_api_key(api_key)
