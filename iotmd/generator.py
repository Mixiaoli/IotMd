from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from iotmd.ai import AiSummary, generate_network_advice, summarize_device
from iotmd.collectors import DeviceSnapshot
from iotmd.config import Inventory
from iotmd.topology import build_topology, render_mermaid


@dataclass(frozen=True)
class DocumentBundle:
    summary: str
    device_documents: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DeviceFacts:
    model: str = "未识别"
    serial_number: str = "未识别"
    software_version: str = "未识别"


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
    device_docs = _render_per_device_documents(inventory, snapshots, summaries)

    return DocumentBundle(summary=summary, device_documents=device_docs)


def write_documents(bundle: DocumentBundle, output_dir: str | Path) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    (output_path / "summary.md").write_text(bundle.summary, encoding="utf-8")
    for filename, content in bundle.device_documents.items():
        (output_path / filename).write_text(content, encoding="utf-8")


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

    if inventory.subnet_cidr and inventory.subnet_hosts:
        total = len(inventory.subnet_hosts)
        online = len([item for item in inventory.subnet_hosts if item.online])
        ssh_ok = len([item for item in inventory.subnet_hosts if item.ssh_open])
        lines.extend(
            [
                "",
                "## 网段扫描统计",
                f"- 网段: {inventory.subnet_cidr}",
                f"- 主机总数: {total}",
                f"- Ping 可达: {online}",
                f"- SSH 可达: {ssh_ok}",
            ]
        )

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
        facts = _extract_device_facts(snapshot)
        sections.extend(
            [
                f"## {snapshot.name} ({snapshot.vendor})",
                "",
                f"摘要: {summary_map.get(snapshot.name, '')}",
                "",
                f"型号: {facts.model}",
                f"SN: {facts.serial_number}",
                f"软件版本: {facts.software_version}",
                "",
                "### 版本信息原始输出",
                "```",
                snapshot.version.strip() or "未采集",
                "```",
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
    ip_pattern = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?)")
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
    inventory: Inventory, snapshots: list[DeviceSnapshot], summaries: list[AiSummary]
) -> str:
    rows = [
        "| 设备名称 | 设备厂商 | 设备型号 | 管理地址 | 管理方式 | 用户名 | SN | 软件版本 | 文档文件 | AI 优化建议 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    device_map = {device.name: device for device in inventory.devices}
    host_device_map = {device.host: device for device in inventory.devices}
    host_snapshot_map: dict[str, DeviceSnapshot] = {}
    for snapshot in snapshots:
        device = device_map.get(snapshot.name)
        if device:
            host_snapshot_map[device.host] = snapshot

    summary_map = {summary.device_name: summary.summary for summary in summaries}

    def _doc_filename(host: str) -> str:
        return f"device_{host.replace('.', '_')}.md"

    if inventory.subnet_hosts:
        used_hosts: set[str] = set()
        for host_item in inventory.subnet_hosts:
            host = host_item.host
            snapshot = host_snapshot_map.get(host)
            if snapshot:
                used_hosts.add(host)
                device = host_device_map.get(host)
                facts = _extract_device_facts(snapshot)
                advice = summary_map.get(snapshot.name, "-").replace("\n", " ")
                rows.append(
                    f"| {snapshot.name} | {snapshot.vendor} | {facts.model} | {host} | ssh | {device.username if device else '-'} | "
                    f"{facts.serial_number} | {facts.software_version} | {_doc_filename(host)} | {advice} | 已采集 |"
                )
            elif not host_item.online:
                rows.append(
                    f"| - | - | - | {host} | ping | - | - | - | - | - | {host_item.remark or '预留（Ping 不通）'} |"
                )
            elif not host_item.ssh_open:
                rows.append(
                    f"| - | - | - | {host} | ping | - | - | - | - | - | {host_item.remark or 'Ping 通但 SSH 不可达'} |"
                )
            else:
                rows.append(
                    f"| - | - | - | {host} | ssh | - | - | - | - | - | SSH 可达但采集失败（检查账号密码/命令权限） |"
                )

        for snapshot in snapshots:
            device = device_map.get(snapshot.name)
            if not device or device.host in used_hosts:
                continue
            facts = _extract_device_facts(snapshot)
            advice = summary_map.get(snapshot.name, "-").replace("\n", " ")
            rows.append(
                f"| {snapshot.name} | {snapshot.vendor} | {facts.model} | {device.host} | ssh | {device.username} | "
                f"{facts.serial_number} | {facts.software_version} | {_doc_filename(device.host)} | {advice} | 已采集 |"
            )
    else:
        for snapshot in snapshots:
            device = device_map.get(snapshot.name)
            facts = _extract_device_facts(snapshot)
            host = device.host if device else "-"
            username = device.username if device else "-"
            advice = summary_map.get(snapshot.name, "-").replace("\n", " ")
            rows.append(
                f"| {snapshot.name} | {snapshot.vendor} | {facts.model} | {host} | ssh | {username} | "
                f"{facts.serial_number} | {facts.software_version} | {(_doc_filename(host) if host != '-' else '-')} | {advice} | 已采集 |"
            )

    return "\n".join(
        [
            f"# {inventory.site} 设备资产清单（表格）",
            "",
            *rows,
            "",
            "> 说明：密码不写入文档，避免敏感信息泄漏。",
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
    device_inventory = _render_device_inventory(inventory, snapshots, summaries)
    config_backup = _render_config_backup(snapshots)
    advice = generate_network_advice(snapshots, inventory.ai)

    return "\n".join(
        [
            overview,
            topology,
            ip_allocation,
            device_inventory,
            "# 全网安全与网络优化建议",
            "",
            advice,
            "",
            devices,
            config_backup,
        ]
    )


def _render_per_device_documents(
    inventory: Inventory,
    snapshots: list[DeviceSnapshot],
    summaries: list[AiSummary],
) -> dict[str, str]:
    docs: dict[str, str] = {}
    summary_map = {summary.device_name: summary.summary for summary in summaries}
    device_map = {device.name: device for device in inventory.devices}
    for snapshot in snapshots:
        device = device_map.get(snapshot.name)
        host = device.host if device else snapshot.name
        filename = f"device_{host.replace('.', '_')}.md"
        facts = _extract_device_facts(snapshot)
        docs[filename] = "\n".join(
            [
                f"# 设备文档 - {snapshot.name}",
                "",
                f"- 管理IP: {host}",
                f"- 厂商: {snapshot.vendor}",
                f"- 型号: {facts.model}",
                f"- SN: {facts.serial_number}",
                f"- 软件版本: {facts.software_version}",
                "",
                "## AI 摘要",
                summary_map.get(snapshot.name, ""),
                "",
                "## 接口概览",
                "```",
                snapshot.interfaces.strip(),
                "```",
                "",
                "## LLDP 邻居",
                "```",
                snapshot.lldp.strip(),
                "```",
                "",
                "## 配置",
                "```",
                snapshot.config.strip(),
                "```",
                "",
            ]
        )
    return docs


def _extract_device_facts(snapshot: DeviceSnapshot) -> DeviceFacts:
    source = "\n".join([snapshot.version, snapshot.config])
    return DeviceFacts(
        model=_extract_with_patterns(
            source,
            [
                r"(?im)^\s*Device\s+name\s*:\s*(.+)$",
                r"(?im)^\s*Device\s+model\s*:\s*(.+)$",
                r"(?im)^\s*HUAWEI\s+([A-Z0-9-]+)\s+Routing\s+Switch\s+uptime",
                r"(?im)^\s*HUAWEI\s+(\S+)",
                r"(?im)^\s*Ruijie\s+(\S+)",
                r"(?im)^\s*(LS-\S+)",
                r"(?im)^\s*(S\d+\S*)",
                r"(?im)^\s*Model\s*:\s*(.+)$",
            ],
        ),
        serial_number=_extract_with_patterns(
            source,
            [
                r"(?im)^\s*ESN\s*:\s*(\S+)",
                r"(?im)^\s*SN\s*:\s*(\S+)",
                r"(?im)^\s*DEVICE_SERIAL_NUMBER\s*:\s*(\S+)",
                r"(?im)^\s*([A-Z0-9]{8,})\s+\d+\(Master\)\s*:",
                r"(?im)^\s*Serial(?:\s+Number)?\s*[:=]\s*(\S+)",
            ],
        ),
        software_version=_extract_with_patterns(
            source,
            [
                r"(?im)^\s*Comware\s+Software.*?Version\s+([^,\s]+,\s*Release\s+\S+)",
                r"(?im)^\s*VRP\s*\(R\)\s*software,\s*Version\s*(.+)$",
                r"(?im)^\s*VRP\s*\(R\)\s*software.*?Version\s*([^,\n]+(?:,[^\n]+)?)",
                r"(?im)^\s*Software\s+Version\s*[:=]\s*(.+)$",
                r"(?im)^\s*Version\s*[:=]\s*(.+)$",
                r"(?im)^\s*RGOS\s+version\s*[:=]\s*(.+)$",
            ],
        ),
    )


def _extract_with_patterns(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return "未识别"
