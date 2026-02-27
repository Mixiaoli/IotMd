from __future__ import annotations

import importlib
import importlib.util
import os
from dataclasses import dataclass
from typing import Iterable

if importlib.util.find_spec("requests") is not None:
    requests = importlib.import_module("requests")
    RequestException = importlib.import_module("requests.exceptions").RequestException
else:
    requests = None
    RequestException = Exception

from iotmd.collectors import DeviceSnapshot
from iotmd.config import AiConfig


def _requests_post(*args, **kwargs):
    if requests is None:
        raise RequestException("requests is not installed")
    return requests.post(*args, **kwargs)


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

    try:
        response = _requests_post(
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
    except RequestException:
        return AiSummary(device_name=snapshot.name, summary=_fallback_summary(snapshot))


def build_ai_question(
    label: str,
    api_base: str,
    model: str,
    api_key: str | None,
) -> str:
    resolved_key = resolve_api_key(api_key)
    if not resolved_key:
        return label

    try:
        response = _requests_post(
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
    except RequestException:
        return label


def _fallback_summary(snapshot: DeviceSnapshot) -> str:
    return (
        f"设备 {snapshot.name} ({snapshot.vendor}) 已采集配置与接口信息。"
        " 如果需要更完整的描述，请启用 AI 总结。"
    )


def _build_prompt(snapshot: DeviceSnapshot) -> str:
    return (
        "请根据以下信息，生成用于运维文档的设备摘要，包含：\n"
        "1) 设备角色与用途 2) 接口/链路概览 3) 关键风险与安全建议\n"
        f"设备名称: {snapshot.name}\n"
        f"厂商: {snapshot.vendor}\n"
        "接口概览: \n"
        f"{snapshot.interfaces}\n"
        "配置片段: \n"
        f"{snapshot.config[:2000]}\n"
    )


def generate_network_advice(
    snapshots: Iterable[DeviceSnapshot],
    ai: AiConfig,
) -> str:
    resolved_key = resolve_api_key(ai.api_key)
    if not resolved_key:
        return _fallback_network_advice()

    prompt = _build_network_advice_prompt(snapshots)
    try:
        response = _requests_post(
            ai.api_base,
            headers={"Authorization": f"Bearer {resolved_key}"},
            json={
                "model": ai.model,
                "input": {
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "你是网络安全与运维专家，请输出可执行的安全建议与优化建议。"
                                "尽量结合现有配置与接口信息。"
                            ),
                        },
                        {"role": "user", "content": prompt},
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
        return content or _fallback_network_advice()
    except RequestException:
        return _fallback_network_advice()


def resolve_api_key(api_key: str | None) -> str | None:
    return api_key or os.environ.get("DASHSCOPE_API_KEY")


def _resolve_api_key(api_key: str | None) -> str | None:
    return resolve_api_key(api_key)


def answer_query(
    query: str,
    snapshots: Iterable[DeviceSnapshot],
    ai: AiConfig,
) -> str:
    resolved_key = resolve_api_key(ai.api_key)
    if not resolved_key:
        return _fallback_answer(query, snapshots)

    prompt = _build_query_prompt(query, snapshots)
    try:
        response = _requests_post(
            ai.api_base,
            headers={"Authorization": f"Bearer {resolved_key}"},
            json={
                "model": ai.model,
                "input": {
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "你是网络运维助手。需要基于设备配置、LLDP、接口摘要回答问题。"
                                "如果缺少数据，明确说明缺口并给出可执行的排查步骤。"
                                "输出结构化要点，尽量中文。"
                                "当用户请求诊断或优化时，给出根因、影响范围、建议。"
                            ),
                        },
                        {"role": "user", "content": prompt},
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
        return content or _fallback_answer(query, snapshots)
    except RequestException:
        return _fallback_answer(query, snapshots)


def _build_query_prompt(query: str, snapshots: Iterable[DeviceSnapshot]) -> str:
    parts = [
        "用户问题:",
        query,
        "",
        "已采集设备信息:",
    ]
    for snapshot in snapshots:
        parts.append(f"设备: {snapshot.name} ({snapshot.vendor})")
        if snapshot.interfaces.strip():
            parts.append("接口概览:")
            parts.append(snapshot.interfaces.strip())
        if snapshot.lldp.strip():
            parts.append("LLDP 邻居:")
            parts.append(snapshot.lldp.strip())
        if snapshot.config.strip():
            parts.append("配置片段:")
            parts.append(snapshot.config[:1500])
        parts.append("")
    return "\n".join(parts)


def _fallback_answer(query: str, snapshots: Iterable[DeviceSnapshot]) -> str:
    snapshot_list = list(snapshots)
    if not snapshot_list:
        lowered = query.lower()
        if lowered in {"hi", "hello", "你好", "您好"}:
            return (
                "你好，我在。即使暂未采集交换机数据，也可以先回答通用运维问题。"
                "如果你想结合现网信息分析，可以输入“加载设备”重新采集。"
            )
        return (
            "当前还没有设备快照，我可以先给你通用排查建议。"
            "如果你希望基于交换机配置做精准分析，请输入“加载设备”重新采集。"
        )
    lowered = query.lower()
    if "cpu" in lowered or "利用率" in query:
        return (
            "暂未接入实时性能监控数据，无法直接给出 CPU 曲线。"
            "建议：启用 SNMP/Telemetry，并采集 CPU/内存/接口错误计数。"
        )
    if "中断" in query or "故障" in query:
        return (
            "未检测到日志或告警数据来源，无法量化中断时长。"
            "建议：接入 syslog/告警平台，并关联接口 flap 与错误计数。"
        )
    if "qos" in lowered or "qos" in query:
        return (
            "已采集配置片段，但未识别到 QoS 模板与策略数据。"
            "建议：导出 QoS 配置并标记关键业务流量，再生成优化建议。"
        )
    if "vlan" in lowered or "vlan" in query:
        return (
            "建议排查：VLAN 100 是否在上联/接入口放行；"
            "网关 SVI 是否启用；DHCP/ACL 是否阻断；确认链路 Trunk 允许 VLAN 100。"
        )
    if "环路" in query or "stp" in lowered:
        return (
            "建议查看 STP 状态与 MAC 地址漂移记录，定位异常端口并临时 shutdown。"
            "如可用，开启 BPDU Guard 与环路保护。"
        )
    return "需要更完整的监控/日志数据才能回答该问题。"


def _build_network_advice_prompt(snapshots: Iterable[DeviceSnapshot]) -> str:
    parts = [
        "请输出该网络的安全建议与优化建议，包含：",
        "- 安全基线（弱口令、ACL、管理面访问）",
        "- 稳定性（链路冗余、STP/BPDU Guard）",
        "- 可观测性（日志、告警、监控）",
        "- 性能与容量（QoS、带宽）",
        "",
        "已采集设备信息:",
    ]
    for snapshot in snapshots:
        parts.append(f"设备: {snapshot.name} ({snapshot.vendor})")
        if snapshot.interfaces.strip():
            parts.append("接口概览:")
            parts.append(snapshot.interfaces.strip())
        if snapshot.lldp.strip():
            parts.append("LLDP 邻居:")
            parts.append(snapshot.lldp.strip())
        if snapshot.config.strip():
            parts.append("配置片段:")
            parts.append(snapshot.config[:1200])
        parts.append("")
    return "\n".join(parts)


def _fallback_network_advice() -> str:
    return (
        "安全建议: 启用强口令与分级账号、限制管理面访问、开启日志审计与告警。"
        "网络建议: 检查链路冗余与 STP 保护，关键链路启用 BPDU Guard，"
        "为办公网/访客网配置 QoS 与访问控制，接入 SNMP/Telemetry 进行可观测性建设。"
    )
