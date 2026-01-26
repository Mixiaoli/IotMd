from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from iotmd.ai import AiSummary, generate_network_advice, summarize_device
from iotmd.collectors import DeviceSnapshot
from iotmd.config import Inventory
from iotmd.topology import build_topology, render_mermaid


@dataclass(frozen=True)
class DocumentBundle:
    summary: str


def build_documents(inventory: Inventory, snapshots: list[DeviceSnapshot]) -> DocumentBundle:
    summaries = [
        summarize_device(
            snapshot,
            inventory.ai.api_base,
            inventory.ai.model,
            inventory.ai.enabled,
            inventory.ai.api_key,
        )
        for snapshot in snapshots
    ]

    topology_links = build_topology(snapshots)
    summary = _render_summary(inventory, summaries, snapshots, topology_links)

    return DocumentBundle(summary=summary)


def write_documents(bundle: DocumentBundle, output_dir: str | Path) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    (output_path / "summary.md").write_text(bundle.summary, encoding="utf-8")


def _render_overview(inventory: Inventory, summaries: list[AiSummary]) -> str:
    lines = [
        f"# {inventory.site} 运维文档总览",
        "",
        "## 负责人",
    ]
    for key, value in inventory.contacts.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## 设备摘要"])
    for summary in summaries:
        lines.append(f"- **{summary.device_name}**: {summary.summary}")

    return "\n".join(lines) + "\n"


def _render_topology(links: list) -> str:
    mermaid = render_mermaid(links)
    return "\n".join([
        "# 网络拓扑",
        "",
        "```mermaid",
        mermaid,
        "```",
        "",
    ])


def _render_device_details(
    snapshots: list[DeviceSnapshot], summaries: list[AiSummary]
) -> str:
    summary_map = {summary.device_name: summary.summary for summary in summaries}
    sections = ["# 设备详细信息", ""]

    for snapshot in snapshots:
        sections.extend(
            [
                f"## {snapshot.name} ({snapshot.vendor})",
                "",
                f"摘要: {summary_map.get(snapshot.name, '')}",
                "",
                "### 接口概览",
                "```",
                snapshot.interfaces.strip(),
                "```",
                "",
                "### 配置",
                "```",
                snapshot.config.strip(),
                "```",
                "",
                "### LLDP 邻居",
                "```",
                snapshot.lldp.strip(),
                "```",
                "",
            ]
        )

    return "\n".join(sections)


def _render_ip_allocation(
    inventory: Inventory, snapshots: list[DeviceSnapshot]
) -> str:
    rows = ["| 设备 | 接口 | IP |", "| --- | --- | --- |"]
    ip_pattern = re.compile(r"(\\d{1,3}(?:\\.\\d{1,3}){3}(?:/\\d{1,2})?)")
    for snapshot in snapshots:
        for line in snapshot.interfaces.splitlines():
            ips = ip_pattern.findall(line)
            if not ips:
                continue
            interface = line.strip().split()[0]
            for ip in ips:
                rows.append(f"| {snapshot.name} | {interface} | {ip} |")
    if len(rows) == 2:
        rows.append("| - | - | 未识别到 IP 信息 |")
    return "\n".join(
        [
            f"# {inventory.site} IP 地址分配表",
            "",
            *rows,
            "",
            "> 提示：接口输出未包含 IP 时，请补充设备 L3 接口信息。",
            "",
        ]
    )


def _render_device_inventory(
    inventory: Inventory, snapshots: list[DeviceSnapshot]
) -> str:
    rows = ["| 设备 | 厂商 | 管理地址 | 序列号 | 维保信息 |", "| --- | --- | --- | --- | --- |"]
    device_map = {device.name: device for device in inventory.devices}
    for snapshot in snapshots:
        device = device_map.get(snapshot.name)
        host = device.host if device else "-"
        rows.append(f"| {snapshot.name} | {snapshot.vendor} | {host} | 未采集 | 未采集 |")
    return "\n".join(
        [
            f"# {inventory.site} 设备清单",
            "",
            *rows,
            "",
            "> 序列号与维保信息需通过设备 SN/资产系统补充。",
            "",
        ]
    )


def _render_config_backup(snapshots: list[DeviceSnapshot]) -> str:
    sections = ["# 配置备份文档", ""]
    for snapshot in snapshots:
        sections.extend(
            [
                f"## {snapshot.name} ({snapshot.vendor})",
                "```",
                snapshot.config.strip(),
                "```",
                "",
            ]
        )
    return "\n".join(sections)


def _render_summary(
    inventory: Inventory,
    summaries: list[AiSummary],
    snapshots: list[DeviceSnapshot],
    topology_links: list,
) -> str:
    overview = _render_overview(inventory, summaries)
    topology = _render_topology(topology_links)
    devices = _render_device_details(snapshots, summaries)
    ip_allocation = _render_ip_allocation(inventory, snapshots)
    device_inventory = _render_device_inventory(inventory, snapshots)
    config_backup = _render_config_backup(snapshots)
    advice = generate_network_advice(snapshots, inventory.ai)

    return "\n".join(
        [
            overview,
            topology,
            ip_allocation,
            device_inventory,
            "# 安全与网络建议",
            "",
            advice,
            "",
            devices,
            config_backup,
        ]
    )
